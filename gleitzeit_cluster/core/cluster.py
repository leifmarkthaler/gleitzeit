"""
Main cluster orchestration for Gleitzeit Cluster
"""

from typing import Any, Dict, List, Optional
from .workflow import Workflow, WorkflowStatus, WorkflowResult, WorkflowErrorStrategy
from .task import Task, TaskType
from .node import ExecutorNode
from .service_manager import ServiceManager
from .error_handling import (
    RetryManager, RetryConfig, GleitzeitLogger, 
    ErrorCategorizer, ErrorCategory, ErrorSeverity,
    CircuitBreaker
)
from .errors import (
    GleitzeitError, ErrorCode, 
    RedisConnectionError, OllamaModelNotFoundError,
    WorkflowNotFoundError
)
from ..execution.task_executor import TaskExecutor
from ..execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy
from ..storage.redis_client import RedisClient
from ..communication.socketio_client import ClusterSocketClient
from ..communication.socketio_server import SocketIOServer


class GleitzeitCluster:
    """
    Main cluster interface for Gleitzeit distributed workflow orchestration.
    
    This is a minimal working example that demonstrates the API design.
    In the full implementation, this would coordinate with Redis, Socket.IO,
    and the distributed scheduler/executor components.
    """
    
    def __init__(
        self, 
        redis_url: str = "redis://localhost:6379", 
        socketio_url: str = "http://localhost:8000",
        ollama_url: str = "http://localhost:11434",
        ollama_endpoints: Optional[List[EndpointConfig]] = None,
        ollama_strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED,
        enable_real_execution: bool = True,
        enable_redis: bool = True,
        enable_socketio: bool = True,
        auto_start_socketio_server: bool = True,
        socketio_host: str = "0.0.0.0",
        socketio_port: int = 8000,
        auto_start_services: bool = True,
        auto_start_redis: bool = True,
        auto_start_executors: bool = True,
        min_executors: int = 1
    ):
        """Initialize cluster connection"""
        self.redis_url = redis_url
        self.socketio_url = socketio_url
        self.enable_redis = enable_redis
        self.enable_socketio = enable_socketio
        self.auto_start_socketio_server = auto_start_socketio_server
        self.socketio_host = socketio_host
        self.socketio_port = socketio_port
        
        # Auto-start configuration
        self.auto_start_services = auto_start_services
        self.auto_start_redis = auto_start_redis
        self.auto_start_executors = auto_start_executors
        self.min_executors = min_executors
        
        # Service manager for auto-starting services
        self.service_manager = ServiceManager() if auto_start_services else None
        
        # Local fallback storage
        self._workflows: Dict[str, Workflow] = {}
        self._nodes: Dict[str, ExecutorNode] = {}
        self._is_started = False
        
        # Error handling and reliability components
        self.logger = GleitzeitLogger("GleitzeitCluster")
        self.retry_manager = RetryManager(self.logger)
        self.circuit_breakers = {
            'redis': CircuitBreaker(failure_threshold=5, recovery_timeout=30),
            'ollama': CircuitBreaker(failure_threshold=3, recovery_timeout=60),
            'socketio': CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        }
        
        # Retry configurations for different operations
        self.retry_configs = {
            'redis': RetryConfig(max_attempts=3, base_delay=1.0, max_delay=30.0),
            'ollama': RetryConfig(max_attempts=2, base_delay=2.0, max_delay=60.0),
            'socketio': RetryConfig(max_attempts=3, base_delay=1.0, max_delay=15.0),
            'task_execution': RetryConfig(max_attempts=3, base_delay=2.0, max_delay=120.0)
        }
        
        # Initialize Redis client with error handling
        if enable_redis:
            self.redis_client = RedisClient(redis_url=redis_url)
        else:
            self.redis_client = None
        
        # Initialize Socket.IO server (if auto-start enabled)
        if enable_socketio and auto_start_socketio_server:
            self.socketio_server = SocketIOServer(
                host=socketio_host,
                port=socketio_port,
                redis_url=redis_url
            )
        else:
            self.socketio_server = None
        
        # Initialize Socket.IO client
        if enable_socketio:
            self.socketio_client = ClusterSocketClient(
                server_url=socketio_url,
                auth_token="demo_token"  # TODO: Proper authentication
            )
        else:
            self.socketio_client = None
        
        # Initialize task executor for real execution
        self.enable_real_execution = enable_real_execution
        if enable_real_execution:
            self.task_executor = TaskExecutor(
                ollama_url=ollama_url,
                ollama_endpoints=ollama_endpoints,
                ollama_strategy=ollama_strategy
            )
        else:
            self.task_executor = None
    
    async def start(self) -> None:
        """Start cluster components with comprehensive error handling"""
        self.logger.logger.info("Starting Gleitzeit Cluster")
        self.logger.logger.info(f"Redis: {self.redis_url}")
        self.logger.logger.info(f"Socket.IO: {self.socketio_url}")
        
        # Auto-start services if enabled
        if self.service_manager:
            self.logger.logger.info("Auto-start services enabled")
            try:
                service_results = await self._start_services_with_retry()
                if service_results.get("services_started"):
                    self.logger.logger.info(f"Started services: {', '.join(service_results['services_started'])}")
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {"component": "service_manager"})
                self.logger.log_error(error_info)
        
        # Connect to Redis with retry and circuit breaker
        if self.redis_client:
            await self._connect_redis_with_retry()
        
        # Start Socket.IO server with error handling
        if self.socketio_server:
            await self._start_socketio_server_with_retry()
        
        # Connect to Socket.IO client with error handling
        if self.socketio_client:
            await self._connect_socketio_client_with_retry()
        
        # Start task executor if enabled
        if self.task_executor:
            try:
                await self.task_executor.start()
                if self.task_executor._multi_endpoint_mode:
                    healthy = len(self.task_executor.ollama_manager.get_healthy_endpoints())
                    total = len(self.task_executor.ollama_manager.endpoints)
                    self.logger.logger.info(f"Ollama: {healthy}/{total} endpoints healthy")
                else:
                    self.logger.logger.info(f"Ollama: {self.task_executor.ollama_client.base_url}")
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {"component": "task_executor"})
                self.logger.log_error(error_info)
                self.logger.logger.warning("Task executor failed to start, continuing without it")
                self.task_executor = None
            
        # Check for resumable workflows after startup
        await self._check_resumable_workflows()
        
        self._is_started = True
        self.logger.logger.info("Gleitzeit Cluster started successfully")
    
    async def _start_services_with_retry(self):
        """Start services with retry logic"""
        async def start_services():
            return await self.service_manager.ensure_services_running(
                redis_url=self.redis_url,
                socketio_url=self.socketio_url,
                auto_start_redis=self.auto_start_redis and self.enable_redis,
                auto_start_executor=self.auto_start_executors and self.enable_socketio,
                min_executors=self.min_executors
            )
        
        return await self.retry_manager.execute_with_retry(
            start_services,
            self.retry_configs['redis'],
            service_name="service_manager",
            context={"operation": "start_services"}
        )
    
    async def _connect_redis_with_retry(self):
        """Connect to Redis with circuit breaker and retry logic"""
        circuit_breaker = self.circuit_breakers['redis']
        
        if not circuit_breaker.can_execute():
            self.logger.logger.warning("Redis circuit breaker is open, skipping connection")
            self.redis_client = None
            return
        
        async def connect_redis():
            await self.redis_client.connect()
            return True
        
        try:
            await self.retry_manager.execute_with_retry(
                connect_redis,
                self.retry_configs['redis'],
                service_name="redis",
                context={"operation": "connect", "url": self.redis_url}
            )
            circuit_breaker.record_success()
            self.logger.logger.info("Redis: Connected successfully")
            
        except Exception as e:
            circuit_breaker.record_failure()
            error_info = ErrorCategorizer.categorize_error(e, {
                "component": "redis",
                "operation": "connect", 
                "url": self.redis_url
            })
            self.logger.log_error(error_info)
            self.logger.logger.warning("Redis: Connection failed, falling back to local storage")
            self.redis_client = None
    
    async def _start_socketio_server_with_retry(self):
        """Start Socket.IO server with retry logic"""
        async def start_server():
            await self.socketio_server.start()
            # Give server a moment to start
            import asyncio
            await asyncio.sleep(0.5)
            return True
        
        try:
            await self.retry_manager.execute_with_retry(
                start_server,
                self.retry_configs['socketio'],
                service_name="socketio_server",
                context={"operation": "start_server", "host": self.socketio_host, "port": self.socketio_port}
            )
            self.circuit_breakers['socketio'].record_success()
            self.logger.logger.info(f"Socket.IO Server: Started on {self.socketio_host}:{self.socketio_port}")
            
        except Exception as e:
            self.circuit_breakers['socketio'].record_failure()
            error_info = ErrorCategorizer.categorize_error(e, {
                "component": "socketio_server",
                "operation": "start",
                "host": self.socketio_host,
                "port": self.socketio_port
            })
            self.logger.log_error(error_info)
            self.socketio_server = None
    
    async def _connect_socketio_client_with_retry(self):
        """Connect Socket.IO client with retry logic"""
        circuit_breaker = self.circuit_breakers['socketio']
        
        if not circuit_breaker.can_execute():
            self.logger.logger.warning("Socket.IO circuit breaker is open, skipping client connection")
            self.socketio_client = None
            return
        
        async def connect_client():
            connected = await self.socketio_client.connect()
            if not connected:
                raise Exception("Socket.IO client connection failed")
            return connected
        
        try:
            await self.retry_manager.execute_with_retry(
                connect_client,
                self.retry_configs['socketio'],
                service_name="socketio_client",
                context={"operation": "connect", "url": self.socketio_url}
            )
            circuit_breaker.record_success()
            self.logger.logger.info("Socket.IO Client: Connected successfully")
            
        except Exception as e:
            circuit_breaker.record_failure()
            error_info = ErrorCategorizer.categorize_error(e, {
                "component": "socketio_client",
                "operation": "connect",
                "url": self.socketio_url
            })
            self.logger.log_error(error_info)
            self.socketio_client = None
    
    async def stop(self) -> None:
        """Stop cluster components with error handling"""
        self.logger.logger.info("Stopping Gleitzeit Cluster")
        
        # Stop task executor if enabled
        if self.task_executor:
            try:
                await self.task_executor.stop()
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {"component": "task_executor", "operation": "stop"})
                self.logger.log_error(error_info)
        
        # Disconnect from Socket.IO client if connected
        if self.socketio_client:
            try:
                await self.socketio_client.disconnect()
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {"component": "socketio_client", "operation": "disconnect"})
                self.logger.log_error(error_info)
        
        # Stop Socket.IO server if started
        if self.socketio_server:
            try:
                await self.socketio_server.stop()
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {"component": "socketio_server", "operation": "stop"})
                self.logger.log_error(error_info)
        
        # Disconnect from Redis if connected
        if self.redis_client:
            try:
                await self.redis_client.disconnect()
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {"component": "redis", "operation": "disconnect"})
                self.logger.log_error(error_info)
        
        # Stop managed services
        if self.service_manager:
            try:
                self.service_manager.stop_managed_services()
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {"component": "service_manager", "operation": "stop"})
                self.logger.log_error(error_info)
            
        self._is_started = False
        self.logger.logger.info("Gleitzeit Cluster stopped")
    
    async def _check_resumable_workflows(self):
        """Check for workflows that can be resumed after cluster restart"""
        if not self.redis_client:
            return
            
        try:
            resumable = await self.redis_client.get_resumable_workflows()
            
            if resumable:
                self.logger.logger.info(f"Found {len(resumable)} resumable workflows:")
                for workflow in resumable:
                    progress = f"{workflow['completed_tasks']}/{workflow['total_tasks']}"
                    self.logger.logger.info(f"  - {workflow['name']} ({workflow['id'][:8]}...): {progress} tasks")
                    
                self.logger.logger.info("💡 Use 'gleitzeit resume' to continue interrupted workflows")
                
                # TODO: Implement automatic resumption logic
                # For now, just log the information for user awareness
                
        except Exception as e:
            error_info = ErrorCategorizer.categorize_error(e, {
                "component": "workflow_recovery",
                "operation": "check_resumable"
            })
            self.logger.log_error(error_info)
    
    def create_workflow(self, name: str, description: Optional[str] = None) -> Workflow:
        """Create a new workflow"""
        workflow = Workflow(name=name, description=description)
        self._workflows[workflow.id] = workflow
        return workflow
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow for execution"""
        if not self._is_started:
            raise RuntimeError("Cluster not started. Call await cluster.start() first.")
            
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = workflow.created_at
        
        # Store in Redis if available
        if self.redis_client:
            try:
                await self.redis_client.store_workflow(workflow)
                self.logger.logger.info(f"Submitted workflow to Redis: {workflow.name} ({len(workflow.tasks)} tasks)")
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {
                    "component": "redis",
                    "operation": "store_workflow",
                    "workflow_id": workflow.id
                })
                self.logger.log_error(error_info)
                self.logger.logger.warning(f"Fallback to local storage: {workflow.name}")
                self._workflows[workflow.id] = workflow
        else:
            # Fallback to local storage
            self._workflows[workflow.id] = workflow
            self.logger.logger.info(f"Submitted workflow (local): {workflow.name} ({len(workflow.tasks)} tasks)")
        
        # Submit via Socket.IO if available
        if self.socketio_client and self.socketio_client.is_connected:
            try:
                await self.socketio_client.submit_workflow(workflow)
                self.logger.logger.info(f"Workflow submitted via Socket.IO: {workflow.name}")
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {
                    "component": "socketio_client",
                    "operation": "submit_workflow",
                    "workflow_id": workflow.id
                })
                self.logger.log_error(error_info)
        
        return workflow.id
    
    async def execute_workflow(self, workflow: Workflow) -> WorkflowResult:
        """Execute workflow and return results"""
        workflow_id = await self.submit_workflow(workflow)
        
        # In full implementation:
        # - Wait for workflow completion via Redis/Socket.IO events
        # - Handle real-time progress updates
        # - Return actual execution results
        
        self.logger.logger.info(f"Executing workflow: {workflow.name}")
        
        # Execute tasks in dependency order
        executed_tasks = set()
        failed_tasks = set()
        
        while len(executed_tasks) + len(failed_tasks) < len(workflow.tasks):
            # Find tasks that can be executed (dependencies satisfied)
            ready_tasks = []
            for task_id, task in workflow.tasks.items():
                if task_id in executed_tasks or task_id in failed_tasks:
                    continue
                    
                # Check if all dependencies are satisfied
                dependencies_satisfied = all(
                    dep_id in executed_tasks for dep_id in task.dependencies
                )
                
                if dependencies_satisfied:
                    ready_tasks.append((task_id, task))
            
            if not ready_tasks:
                # No more tasks can be executed (circular dependency or all failed)
                remaining_tasks = set(workflow.tasks.keys()) - executed_tasks - failed_tasks
                for task_id in remaining_tasks:
                    workflow.mark_task_failed(task_id, "Dependencies not satisfied or circular dependency")
                    failed_tasks.add(task_id)
                break
            
            # Execute ready tasks
            for task_id, task in ready_tasks:
                self.logger.logger.info(f"Processing task: {task.name}")
                
                # Execute task with retry logic
                async def execute_task_with_retry():
                    if self.task_executor and self.enable_real_execution:
                        # Real execution using TaskExecutor (already has retry logic)
                        result = await self.task_executor.execute_task(task)
                        workflow.mark_task_completed(task_id, result)
                        
                        # Store result in Redis if available
                        if self.redis_client:
                            try:
                                await self.redis_client.store_workflow_result(workflow.id, task_id, result)
                                await self.redis_client.complete_task(task_id, result=result)
                            except Exception as e:
                                error_info = ErrorCategorizer.categorize_error(e, {
                                    "component": "redis", 
                                    "operation": "store_result",
                                    "task_id": task_id,
                                    "workflow_id": workflow.id
                                })
                                self.logger.log_error(error_info)
                        
                        self.logger.logger.info(f"Completed task: {task.name}")
                        return result
                    else:
                        # Fallback to mock execution
                        mock_result = f"Mock result for {task.name}"
                        workflow.mark_task_completed(task_id, mock_result)
                        
                        # Store mock result in Redis if available
                        if self.redis_client:
                            try:
                                await self.redis_client.store_workflow_result(workflow.id, task_id, mock_result)
                                await self.redis_client.complete_task(task_id, result=mock_result)
                            except Exception as e:
                                error_info = ErrorCategorizer.categorize_error(e, {
                                    "component": "redis", 
                                    "operation": "store_result",
                                    "task_id": task_id,
                                    "workflow_id": workflow.id
                                })
                                self.logger.log_error(error_info)
                        
                        self.logger.logger.info(f"Completed task (mock): {task.name}")
                        return mock_result
                
                try:
                    # Execute with retry logic for non-executor tasks
                    if not (self.task_executor and self.enable_real_execution):
                        await self.retry_manager.execute_with_retry(
                            execute_task_with_retry,
                            self.retry_configs['task_execution'],
                            service_name="workflow_task",
                            context={
                                "task_id": task_id,
                                "task_name": task.name,
                                "workflow_id": workflow.id
                            }
                        )
                    else:
                        # TaskExecutor already has its own retry logic
                        await execute_task_with_retry()
                    
                    executed_tasks.add(task_id)
                    
                except Exception as e:
                    error_info = ErrorCategorizer.categorize_error(e, {
                        "component": "task_execution",
                        "task_id": task_id,
                        "task_name": task.name,
                        "workflow_id": workflow.id
                    })
                    self.logger.log_error(error_info)
                    
                    error_msg = str(e)
                    workflow.mark_task_failed(task_id, error_msg)
                    failed_tasks.add(task_id)
                    
                    # Store error in Redis if available
                    if self.redis_client:
                        try:
                            await self.redis_client.store_workflow_error(workflow.id, task_id, error_msg)
                            await self.redis_client.complete_task(task_id, error=error_msg)
                        except Exception as redis_error:
                            redis_error_info = ErrorCategorizer.categorize_error(redis_error, {
                                "component": "redis",
                                "operation": "store_error",
                                "task_id": task_id,
                                "workflow_id": workflow.id
                            })
                            self.logger.log_error(redis_error_info)
                    
                    self.logger.logger.error(f"Failed task: {task.name} - {error_msg}")
                    
                    # Handle error strategy
                    if workflow.error_strategy == WorkflowErrorStrategy.STOP_ON_FIRST_ERROR:
                        self.logger.logger.warning("Stopping workflow due to task failure")
                        workflow.status = WorkflowStatus.FAILED
                        
                        # Update workflow status in Redis
                        if self.redis_client:
                            try:
                                await self.redis_client.update_workflow_status(
                                    workflow.id, 
                                    WorkflowStatus.FAILED,
                                    completed_tasks=len(executed_tasks),
                                    failed_tasks=len(failed_tasks)
                                )
                            except Exception as redis_error:
                                redis_error_info = ErrorCategorizer.categorize_error(redis_error, {
                                    "component": "redis",
                                    "operation": "update_workflow_status",
                                    "workflow_id": workflow.id
                                })
                                self.logger.log_error(redis_error_info)
                        
                        return workflow.to_result()
        
        # Set final workflow status
        if failed_tasks:
            workflow.status = WorkflowStatus.FAILED if workflow.error_strategy == WorkflowErrorStrategy.STOP_ON_FIRST_ERROR else WorkflowStatus.COMPLETED
        else:
            workflow.status = WorkflowStatus.COMPLETED
        
        # Update final workflow status in Redis
        if self.redis_client:
            try:
                await self.redis_client.update_workflow_status(
                    workflow.id,
                    workflow.status,
                    completed_tasks=len(executed_tasks),
                    failed_tasks=len(failed_tasks)
                )
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {
                    "component": "redis",
                    "operation": "final_status_update",
                    "workflow_id": workflow.id
                })
                self.logger.log_error(error_info)
            
        return workflow.to_result()
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow status and progress"""
        # Try Redis first
        if self.redis_client:
            try:
                redis_data = await self.redis_client.get_workflow(workflow_id)
                if redis_data:
                    # Get results and errors from Redis
                    results = await self.redis_client.get_workflow_results(workflow_id)
                    errors = await self.redis_client.get_workflow_errors(workflow_id)
                    
                    return {
                        "workflow_id": workflow_id,
                        "name": redis_data.get("name"),
                        "status": redis_data.get("status"),
                        "total_tasks": int(redis_data.get("total_tasks", 0)),
                        "completed_tasks": int(redis_data.get("completed_tasks", 0)),
                        "failed_tasks": int(redis_data.get("failed_tasks", 0)),
                        "results": results,
                        "errors": errors
                    }
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {
                    "component": "redis",
                    "operation": "get_workflow",
                    "workflow_id": workflow_id
                })
                self.logger.log_error(error_info)
        
        # Fallback to local storage
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return None
            
        return workflow.get_progress()
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow"""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False
            
        workflow.status = WorkflowStatus.CANCELLED
        
        # In full implementation:
        # - Cancel running tasks via Socket.IO
        # - Update Redis state
        # - Clean up resources
        
        self.logger.logger.info(f"Cancelled workflow: {workflow.name}")
        return True
    
    async def list_workflows(self) -> List[Dict[str, Any]]:
        """List all workflows with their status"""
        return [workflow.get_progress() for workflow in self._workflows.values()]
    
    async def register_node(self, node: ExecutorNode) -> None:
        """Register an executor node"""
        self._nodes[node.id] = node
        self.logger.logger.info(f"Registered executor node: {node.name}")
    
    async def list_nodes(self) -> List[Dict[str, Any]]:
        """List all executor nodes"""
        return [node.to_dict() for node in self._nodes.values()]
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume a specific workflow by restoring its incomplete tasks to the queue"""
        if not self._is_started:
            raise RuntimeError("Cluster not started. Call await cluster.start() first.")
        
        if not self.redis_client:
            raise RuntimeError("Redis connection required for workflow resumption")
        
        try:
            # Check if workflow exists and is resumable
            workflow_data = await self.redis_client.get_workflow(workflow_id)
            if not workflow_data:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found", context={
                    "workflow_id": workflow_id,
                    "operation": "resume"
                })
            
            status = workflow_data.get('status')
            if status not in ['running', 'pending']:
                raise GleitzeitError(
                    ErrorCode.WORKFLOW_VALIDATION_FAILED,
                    context={
                        "workflow_id": workflow_id,
                        "current_status": status,
                        "expected_status": "running or pending",
                        "operation": "resume"
                    }
                )
            
            # Get incomplete tasks details before resuming
            incomplete_tasks = await self.redis_client.get_incomplete_tasks(workflow_id)
            resumable_tasks = [t for t in incomplete_tasks if t['can_resume']]
            blocked_tasks = [t for t in incomplete_tasks if not t['can_resume']]
            
            self.logger.logger.info(f"Resuming workflow: {workflow_data.get('name')} ({workflow_id[:8]}...)")
            self.logger.logger.info(f"Found {len(resumable_tasks)} resumable tasks, {len(blocked_tasks)} blocked tasks")
            
            # Restore tasks to queue
            restore_result = await self.redis_client.restore_workflow_tasks(workflow_id)
            
            if restore_result['restored_tasks'] > 0:
                self.logger.logger.info(f"✅ Restored {restore_result['restored_tasks']} tasks to execution queue")
            
            if blocked_tasks:
                self.logger.logger.warning(f"⚠️  {len(blocked_tasks)} tasks still blocked by dependencies:")
                for task in blocked_tasks:
                    deps = ', '.join(task['dependencies']) if task['dependencies'] else 'none'
                    self.logger.logger.warning(f"  - {task['name']} (depends on: {deps})")
            
            return {
                "workflow_id": workflow_id,
                "workflow_name": workflow_data.get('name'),
                "status": "resumed",
                "total_tasks": int(workflow_data.get('total_tasks', 0)),
                "completed_tasks": int(workflow_data.get('completed_tasks', 0)),
                "incomplete_tasks": len(incomplete_tasks),
                "restored_tasks": restore_result['restored_tasks'],
                "blocked_tasks": len(blocked_tasks),
                "ready_for_execution": restore_result['ready_for_execution']
            }
            
        except Exception as e:
            error_info = ErrorCategorizer.categorize_error(e, {
                "component": "workflow_recovery",
                "operation": "resume_workflow",
                "workflow_id": workflow_id
            })
            self.logger.log_error(error_info)
            raise
    
    # Convenience methods for common workflow patterns
    
    async def analyze_text(self, prompt: str, model: str = "llama3") -> str:
        """Quick text analysis"""
        workflow = self.create_workflow("text_analysis")
        workflow.add_text_task("analyze", prompt, model)
        
        result = await self.execute_workflow(workflow)
        return result.results.get(list(workflow.tasks.keys())[0], "No result")
    
    async def analyze_image(self, prompt: str, image_path: str, model: str = "llava") -> str:
        """Quick image analysis"""
        workflow = self.create_workflow("image_analysis")  
        workflow.add_vision_task("analyze", prompt, image_path, model)
        
        result = await self.execute_workflow(workflow)
        return result.results.get(list(workflow.tasks.keys())[0], "No result")
    
    async def batch_analyze_images(self, prompt: str, image_paths: List[str], model: str = "llava") -> Dict[str, str]:
        """Batch image analysis"""
        workflow = self.create_workflow("batch_image_analysis")
        
        task_ids = []
        for i, image_path in enumerate(image_paths):
            task = workflow.add_vision_task(f"analyze_image_{i}", prompt, image_path, model)
            task_ids.append(task.id)
        
        result = await self.execute_workflow(workflow)
        
        # Map results back to image paths
        results = {}
        for i, task_id in enumerate(task_ids):
            results[image_paths[i]] = result.results.get(task_id, "No result")
            
        return results
    
    # Task executor management methods
    
    async def get_available_models(self) -> Dict[str, Any]:
        """Get available Ollama models"""
        if not self.task_executor:
            return {"error": "Real execution not enabled"}
        return await self.task_executor.get_available_models()
    
    async def pull_model(self, model_name: str) -> bool:
        """Pull a model from Ollama"""
        if not self.task_executor:
            return False
        return await self.task_executor.pull_model(model_name)
    
    def register_python_function(self, name: str, func) -> None:
        """Register a Python function for execution"""
        if self.task_executor:
            self.task_executor.register_python_function(name, func)
    
    def register_python_functions(self, functions: Dict[str, Any]) -> None:
        """Register multiple Python functions"""
        if self.task_executor:
            self.task_executor.register_python_functions(functions)
    
    async def get_cluster_stats(self) -> Dict[str, Any]:
        """Get cluster statistics"""
        stats = {
            "is_started": self._is_started,
            "workflows": len(self._workflows),
            "nodes": len(self._nodes),
            "real_execution_enabled": self.enable_real_execution,
            "redis_enabled": self.redis_client is not None
        }
        
        # Add Redis stats if available
        if self.redis_client:
            try:
                redis_stats = await self.redis_client.get_cluster_stats()
                stats["redis_stats"] = redis_stats
                
                # Get Redis health
                redis_health = await self.redis_client.health_check()
                stats["redis_health"] = redis_health
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, {
                    "component": "redis",
                    "operation": "get_stats"
                })
                self.logger.log_error(error_info)
                stats["redis_error"] = str(e)
        
        if self.task_executor:
            stats["executor_stats"] = self.task_executor.get_executor_stats()
        
        return stats
    
    def __str__(self) -> str:
        return f"GleitzeitCluster(workflows={len(self._workflows)}, nodes={len(self._nodes)})"