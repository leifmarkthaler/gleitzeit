"""
Gleitzeit Cluster Client

Client-only version of GleitzeitCluster that connects to the central Socket.IO service
instead of creating its own server.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from .workflow import Workflow, WorkflowStatus, WorkflowResult
from .task import Task, TaskType
from .errors import GleitzeitError, ErrorCode
from .error_handling import GleitzeitLogger, RetryManager, RetryConfig, ErrorCategorizer, CircuitBreaker
from ..storage.redis_client import RedisClient
from ..communication.socketio_client import ClusterSocketClient
from ..communication.service_discovery import get_socketio_url
from ..execution.task_executor import TaskExecutor

logger = logging.getLogger(__name__)

class GleitzeitClusterClient:
    """
    Cluster client that connects to central Socket.IO service
    
    This is a lightweight client that doesn't create its own server,
    but connects to the central Gleitzeit Socket.IO service for coordination.
    """
    
    def __init__(
        self,
        # Connection configuration
        redis_url: str = "redis://localhost:6379",
        socketio_url: str = None,  # Will be auto-discovered if not provided
        
        # Feature toggles
        enable_redis: bool = True,
        enable_real_execution: bool = False,
        
        # Execution configuration
        ollama_url: str = "http://localhost:11434",
        auto_recovery: bool = True
    ):
        """
        Initialize cluster client
        
        Args:
            redis_url: Redis URL for persistence
            socketio_url: Socket.IO service URL (auto-discovered if None)
            enable_redis: Enable Redis integration
            enable_real_execution: Enable real task execution
            ollama_url: Ollama URL for LLM tasks
            auto_recovery: Enable automatic error recovery
        """
        self.redis_url = redis_url
        self.socketio_url = socketio_url or get_socketio_url()
        self.enable_redis = enable_redis
        self.enable_real_execution = enable_real_execution
        self.ollama_url = ollama_url
        self.auto_recovery = auto_recovery
        
        # State management
        self._workflows: Dict[str, Workflow] = {}
        self._is_started = False
        
        # Error handling
        self.logger = GleitzeitLogger("GleitzeitClusterClient")
        self.retry_manager = RetryManager(self.logger)
        self.circuit_breakers = {
            'redis': CircuitBreaker(failure_threshold=5, recovery_timeout=30),
            'socketio': CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        }
        
        # Retry configurations
        self.retry_configs = {
            'redis': RetryConfig(max_attempts=3, base_delay=1.0, max_delay=30.0),
            'socketio': RetryConfig(max_attempts=3, base_delay=1.0, max_delay=15.0),
            'task_execution': RetryConfig(max_attempts=3, base_delay=2.0, max_delay=120.0)
        }
        
        # Initialize components
        if enable_redis:
            self.redis_client = RedisClient(redis_url=redis_url)
        else:
            self.redis_client = None
        
        # Socket.IO client (connects to central service)
        self.socketio_client = ClusterSocketClient(
            server_url=self.socketio_url,
            auth_token="demo_token"  # TODO: Proper authentication
        )
        
        # Task executor
        if enable_real_execution:
            self.task_executor = TaskExecutor(ollama_url=ollama_url)
        else:
            self.task_executor = None
        
        self.logger.logger.info(f"GleitzeitClusterClient initialized")
        self.logger.logger.info(f"  Socket.IO URL: {self.socketio_url}")
        self.logger.logger.info(f"  Redis: {'enabled' if enable_redis else 'disabled'}")
        self.logger.logger.info(f"  Real execution: {'enabled' if enable_real_execution else 'disabled'}")
    
    async def start(self) -> None:
        """Start cluster client components"""
        if self._is_started:
            self.logger.logger.warning("Cluster client is already started")
            return
        
        self.logger.logger.info("Starting Gleitzeit Cluster Client")
        
        # Connect to Redis
        if self.redis_client:
            await self._connect_redis_with_retry()
        
        # Connect to central Socket.IO service
        await self._connect_socketio_with_retry()
        
        # Start task executor if enabled
        if self.task_executor:
            try:
                await self.task_executor.start()
                self.logger.logger.info("Task executor started")
            except Exception as e:
                self.logger.logger.warning(f"Task executor failed to start: {e}")
                self.task_executor = None
        
        self._is_started = True
        self.logger.logger.info("✅ Gleitzeit Cluster Client started successfully")
    
    async def stop(self) -> None:
        """Stop cluster client components"""
        if not self._is_started:
            return
        
        self.logger.logger.info("Stopping Gleitzeit Cluster Client")
        
        # Stop task executor
        if self.task_executor:
            try:
                await self.task_executor.stop()
            except Exception as e:
                self.logger.logger.warning(f"Error stopping task executor: {e}")
        
        # Disconnect Socket.IO client
        if self.socketio_client:
            try:
                await self.socketio_client.disconnect()
            except Exception as e:
                self.logger.logger.warning(f"Error disconnecting Socket.IO client: {e}")
        
        # Disconnect Redis
        if self.redis_client:
            try:
                await self.redis_client.disconnect()
            except Exception as e:
                self.logger.logger.warning(f"Error disconnecting Redis: {e}")
        
        self._is_started = False
        self.logger.logger.info("✅ Gleitzeit Cluster Client stopped")
    
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
            self.logger.logger.info("✅ Redis connected")
            
        except Exception as e:
            circuit_breaker.record_failure()
            error_info = ErrorCategorizer.categorize_error(e, {
                "component": "redis",
                "operation": "connect",
                "url": self.redis_url
            })
            self.logger.log_error(error_info)
            self.logger.logger.warning("Redis connection failed, falling back to local storage")
            self.redis_client = None
    
    async def _connect_socketio_with_retry(self):
        """Connect to Socket.IO service with retry logic"""
        async def connect_socketio():
            await self.socketio_client.connect()
            return True
        
        try:
            await self.retry_manager.execute_with_retry(
                connect_socketio,
                self.retry_configs['socketio'],
                service_name="socketio_client",
                context={"operation": "connect", "url": self.socketio_url}
            )
            self.logger.logger.info("✅ Socket.IO connected")
            
        except Exception as e:
            error_info = ErrorCategorizer.categorize_error(e, {
                "component": "socketio_client",
                "operation": "connect",
                "url": self.socketio_url
            })
            self.logger.log_error(error_info)
            self.logger.logger.error("Socket.IO connection failed - cluster functionality will be limited")
            raise
    
    # === Workflow Management ===
    # (Same as original GleitzeitCluster)
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow for execution"""
        # Implementation same as original cluster
        self.logger.logger.info(f"Submitting workflow: {workflow.name}")
        
        # Store workflow
        workflow_id = workflow.id
        self._workflows[workflow_id] = workflow
        
        # Store in Redis if available
        if self.redis_client:
            try:
                await self.redis_client.store_workflow(workflow)
                self.logger.logger.info(f"Workflow stored in Redis: {workflow_id}")
            except Exception as e:
                self.logger.logger.warning(f"Failed to store workflow in Redis: {e}")
        
        # Submit via Socket.IO if connected
        if self.socketio_client and self.socketio_client.connected:
            try:
                await self.socketio_client.sio.emit(
                    'workflow:submit',
                    {
                        'workflow_id': workflow_id,
                        'workflow_data': workflow.to_dict()
                    },
                    namespace='/cluster'
                )
                self.logger.logger.info(f"Workflow submitted via Socket.IO: {workflow_id}")
            except Exception as e:
                self.logger.logger.warning(f"Failed to submit workflow via Socket.IO: {e}")
        
        return workflow_id
    
    async def get_workflow_status(self, workflow_id: str) -> WorkflowStatus:
        """Get workflow status"""
        if workflow_id in self._workflows:
            return self._workflows[workflow_id].status
        
        # Try Redis
        if self.redis_client:
            try:
                workflow_data = await self.redis_client.get_workflow_status(workflow_id)
                if workflow_data:
                    return WorkflowStatus(workflow_data.get('status', 'unknown'))
            except Exception as e:
                self.logger.logger.warning(f"Failed to get workflow status from Redis: {e}")
        
        return WorkflowStatus.UNKNOWN
    
    async def get_workflow_result(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow execution result"""
        if self.redis_client:
            try:
                return await self.redis_client.get_workflow_results(workflow_id)
            except Exception as e:
                self.logger.logger.warning(f"Failed to get workflow result from Redis: {e}")
        return None
    
    async def wait_for_workflow_completion(self, workflow_id: str, timeout: float = 60.0) -> Dict[str, Any]:
        """Wait for workflow completion using Socket.IO events (no polling!)"""
        import asyncio
        
        completion_future = asyncio.Future()
        
        async def handle_workflow_completed(data):
            """Handle workflow:completed event"""
            if data.get('workflow_id') == workflow_id:
                completion_future.set_result({
                    'status': 'completed',
                    'workflow_id': workflow_id,
                    'data': data
                })
        
        async def handle_workflow_failed(data):
            """Handle workflow:failed event (if it exists)"""
            if data.get('workflow_id') == workflow_id:
                completion_future.set_result({
                    'status': 'failed', 
                    'workflow_id': workflow_id,
                    'data': data
                })
        
        # Subscribe to workflow completion events
        if self.socketio_client:
            self.socketio_client.sio.on('workflow:completed', handle_workflow_completed)
            self.socketio_client.sio.on('workflow:failed', handle_workflow_failed)
        
        try:
            # Check if already completed (race condition protection)
            current_status = await self.get_workflow_status(workflow_id)
            if current_status.value in ['completed', 'failed']:
                result = await self.get_workflow_result(workflow_id)
                return {
                    'status': current_status.value,
                    'workflow_id': workflow_id,
                    'result': result
                }
            
            # Wait for completion event with timeout
            try:
                result = await asyncio.wait_for(completion_future, timeout=timeout)
                # Get the actual result data
                workflow_result = await self.get_workflow_result(workflow_id)
                result['result'] = workflow_result
                return result
                
            except asyncio.TimeoutError:
                return {
                    'status': 'timeout',
                    'workflow_id': workflow_id,
                    'timeout': timeout
                }
        
        finally:
            # Cleanup event handlers
            if self.socketio_client:
                # Note: python-socketio doesn't have easy event unsubscription
                # This is acceptable since cluster client is short-lived in CLI
                pass
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task status and result"""
        if self.redis_client:
            try:
                return await self.redis_client.get_task_result(task_id)
            except Exception as e:
                self.logger.logger.warning(f"Failed to get task status from Redis: {e}")
        return None
    
    def __str__(self) -> str:
        return f"GleitzeitClusterClient(socketio={self.socketio_url}, workflows={len(self._workflows)})"