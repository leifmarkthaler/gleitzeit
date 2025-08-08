"""
Main cluster orchestration for Gleitzeit Cluster
"""

from typing import Any, Dict, List, Optional
from .workflow import Workflow, WorkflowStatus, WorkflowResult, WorkflowErrorStrategy
from .task import Task, TaskType
from .node import ExecutorNode
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
        socketio_port: int = 8000
    ):
        """Initialize cluster connection"""
        self.redis_url = redis_url
        self.socketio_url = socketio_url
        self.enable_redis = enable_redis
        self.enable_socketio = enable_socketio
        self.auto_start_socketio_server = auto_start_socketio_server
        self.socketio_host = socketio_host
        self.socketio_port = socketio_port
        
        # Local fallback storage
        self._workflows: Dict[str, Workflow] = {}
        self._nodes: Dict[str, ExecutorNode] = {}
        self._is_started = False
        
        # Initialize Redis client
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
        """Start cluster components"""
        print(f"🚀 Starting Gleitzeit Cluster")
        print(f"   Redis: {self.redis_url}")
        print(f"   Socket.IO: {self.socketio_url}")
        
        # Connect to Redis if enabled
        if self.redis_client:
            try:
                await self.redis_client.connect()
                print(f"   Redis: ✅ Connected")
            except Exception as e:
                print(f"   Redis: ⚠️  Connection failed - {e}")
                print(f"   Redis: Falling back to local storage")
                self.redis_client = None
        
        # Start Socket.IO server if enabled
        if self.socketio_server:
            try:
                await self.socketio_server.start()
                print(f"   Socket.IO Server: ✅ Started on {self.socketio_host}:{self.socketio_port}")
                
                # Give server a moment to start
                import asyncio
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"   Socket.IO Server: ⚠️  Failed to start - {e}")
                self.socketio_server = None
        
        # Connect to Socket.IO if enabled
        if self.socketio_client:
            try:
                connected = await self.socketio_client.connect()
                if connected:
                    print(f"   Socket.IO Client: ✅ Connected")
                else:
                    print(f"   Socket.IO Client: ⚠️  Connection failed")
                    self.socketio_client = None
            except Exception as e:
                print(f"   Socket.IO Client: ⚠️  Connection failed - {e}")
                self.socketio_client = None
        
        # Start task executor if enabled
        if self.task_executor:
            await self.task_executor.start()
            if self.task_executor._multi_endpoint_mode:
                healthy = len(self.task_executor.ollama_manager.get_healthy_endpoints())
                total = len(self.task_executor.ollama_manager.endpoints)
                print(f"   Ollama: {healthy}/{total} endpoints healthy")
            else:
                print(f"   Ollama: {self.task_executor.ollama_client.base_url}")
            
        self._is_started = True
    
    async def stop(self) -> None:
        """Stop cluster components"""
        print("🛑 Stopping Gleitzeit Cluster")
        
        # Stop task executor if enabled
        if self.task_executor:
            await self.task_executor.stop()
        
        # Disconnect from Socket.IO client if connected
        if self.socketio_client:
            await self.socketio_client.disconnect()
        
        # Stop Socket.IO server if started
        if self.socketio_server:
            await self.socketio_server.stop()
        
        # Disconnect from Redis if connected
        if self.redis_client:
            await self.redis_client.disconnect()
            
        self._is_started = False
    
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
                print(f"📋 Submitted workflow to Redis: {workflow.name} ({len(workflow.tasks)} tasks)")
            except Exception as e:
                print(f"⚠️  Redis storage failed: {e}")
                print(f"📋 Fallback to local storage: {workflow.name}")
                self._workflows[workflow.id] = workflow
        else:
            # Fallback to local storage
            self._workflows[workflow.id] = workflow
            print(f"📋 Submitted workflow (local): {workflow.name} ({len(workflow.tasks)} tasks)")
        
        # Submit via Socket.IO if available
        if self.socketio_client and self.socketio_client.is_connected:
            try:
                await self.socketio_client.submit_workflow(workflow)
                print(f"📡 Workflow submitted via Socket.IO: {workflow.name}")
            except Exception as e:
                print(f"⚠️  Socket.IO submission failed: {e}")
        
        return workflow.id
    
    async def execute_workflow(self, workflow: Workflow) -> WorkflowResult:
        """Execute workflow and return results"""
        workflow_id = await self.submit_workflow(workflow)
        
        # In full implementation:
        # - Wait for workflow completion via Redis/Socket.IO events
        # - Handle real-time progress updates
        # - Return actual execution results
        
        print(f"⚡ Executing workflow: {workflow.name}")
        
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
                print(f"   🔄 Processing task: {task.name}")
                
                try:
                    if self.task_executor and self.enable_real_execution:
                        # Real execution using TaskExecutor
                        result = await self.task_executor.execute_task(task)
                        workflow.mark_task_completed(task_id, result)
                        
                        # Store result in Redis if available
                        if self.redis_client:
                            try:
                                await self.redis_client.store_workflow_result(workflow.id, task_id, result)
                                await self.redis_client.complete_task(task_id, result=result)
                            except Exception as e:
                                print(f"⚠️  Redis result storage failed: {e}")
                        
                        print(f"   ✅ Completed task: {task.name}")
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
                                print(f"⚠️  Redis result storage failed: {e}")
                        
                        print(f"   ✅ Completed task (mock): {task.name}")
                    
                    executed_tasks.add(task_id)
                    
                except Exception as e:
                    error_msg = str(e)
                    workflow.mark_task_failed(task_id, error_msg)
                    failed_tasks.add(task_id)
                    
                    # Store error in Redis if available
                    if self.redis_client:
                        try:
                            await self.redis_client.store_workflow_error(workflow.id, task_id, error_msg)
                            await self.redis_client.complete_task(task_id, error=error_msg)
                        except Exception as redis_error:
                            print(f"⚠️  Redis error storage failed: {redis_error}")
                    
                    print(f"   ❌ Failed task: {task.name} - {error_msg}")
                    
                    # Handle error strategy
                    if workflow.error_strategy == WorkflowErrorStrategy.STOP_ON_FIRST_ERROR:
                        print(f"   🛑 Stopping workflow due to task failure")
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
                                print(f"⚠️  Redis workflow status update failed: {redis_error}")
                        
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
                print(f"⚠️  Redis final status update failed: {e}")
            
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
                print(f"⚠️  Redis retrieval failed: {e}")
        
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
        
        print(f"🚫 Cancelled workflow: {workflow.name}")
        return True
    
    async def list_workflows(self) -> List[Dict[str, Any]]:
        """List all workflows with their status"""
        return [workflow.get_progress() for workflow in self._workflows.values()]
    
    async def register_node(self, node: ExecutorNode) -> None:
        """Register an executor node"""
        self._nodes[node.id] = node
        print(f"🏗️  Registered executor node: {node.name}")
    
    async def list_nodes(self) -> List[Dict[str, Any]]:
        """List all executor nodes"""
        return [node.to_dict() for node in self._nodes.values()]
    
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
                stats["redis_error"] = str(e)
        
        if self.task_executor:
            stats["executor_stats"] = self.task_executor.get_executor_stats()
        
        return stats
    
    def __str__(self) -> str:
        return f"GleitzeitCluster(workflows={len(self._workflows)}, nodes={len(self._nodes)})"