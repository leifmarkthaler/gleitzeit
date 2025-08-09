"""
External Service Node - Allows external services to register as task executors
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

import socketio

from .task import Task, TaskType, TaskStatus
from .error_handling import GleitzeitLogger
from .errors import ErrorCode, GleitzeitError


logger = logging.getLogger(__name__)


class ExternalServiceCapability(Enum):
    """Standard external service capabilities"""
    ML_TRAINING = "ml_training"
    ML_INFERENCE = "ml_inference"
    DATA_PROCESSING = "data_processing"
    API_INTEGRATION = "api_integration"
    DATABASE_OPERATIONS = "database_operations"
    FILE_PROCESSING = "file_processing"
    WEBHOOK_HANDLING = "webhook_handling"
    CUSTOM_PROCESSING = "custom_processing"


class ExternalServiceNode:
    """
    External service that registers with Gleitzeit cluster as a task executor
    
    This allows external services (ML systems, APIs, databases, etc.) to:
    1. Register as available task executors
    2. Receive task assignments via Socket.IO
    3. Report progress and completion back to cluster
    4. Integrate seamlessly with workflow dependencies
    """
    
    def __init__(
        self,
        service_name: str,
        service_id: Optional[str] = None,
        cluster_url: str = "http://localhost:8000",
        capabilities: List[ExternalServiceCapability] = None,
        max_concurrent_tasks: int = 10,
        heartbeat_interval: int = 30,
        auth_token: Optional[str] = None
    ):
        """
        Initialize external service node
        
        Args:
            service_name: Human-readable service name
            service_id: Unique service identifier (auto-generated if None)
            cluster_url: Gleitzeit cluster Socket.IO URL
            capabilities: List of task types this service can handle
            max_concurrent_tasks: Maximum concurrent task limit
            heartbeat_interval: Heartbeat interval in seconds
            auth_token: Authentication token for cluster connection
        """
        self.service_name = service_name
        self.service_id = service_id or f"external_{service_name}_{uuid.uuid4().hex[:8]}"
        self.cluster_url = cluster_url
        self.capabilities = capabilities or []
        self.max_concurrent_tasks = max_concurrent_tasks
        self.heartbeat_interval = heartbeat_interval
        self.auth_token = auth_token or "demo_token"
        
        # Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=10,
            reconnection_delay=2,
            reconnection_delay_max=30
        )
        
        # State tracking
        self.running = False
        self.connected = False
        self.registered = False
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.task_handlers: Dict[str, Callable] = {}
        
        # Metrics
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.start_time = time.time()
        
        # Logging
        self.logger = GleitzeitLogger(f"ExternalService:{service_name}")
        
        # Setup event handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        # Connection events
        self.sio.on('connect', namespace='/cluster')(self.handle_connect)
        self.sio.on('disconnect', namespace='/cluster')(self.handle_disconnect)
        
        # Authentication
        self.sio.on('authenticated', namespace='/cluster')(self.handle_authenticated)
        self.sio.on('authentication_failed', namespace='/cluster')(self.handle_auth_failed)
        
        # Task assignment
        self.sio.on('task:assign', namespace='/cluster')(self.handle_task_assign)
        self.sio.on('task:cancel', namespace='/cluster')(self.handle_task_cancel)
        
        # Cluster events
        self.sio.on('cluster:shutdown', namespace='/cluster')(self.handle_cluster_shutdown)
    
    def register_task_handler(self, task_type: str, handler: Callable):
        """
        Register a handler function for specific task type
        
        Args:
            task_type: The task type to handle (e.g., "ml_training", "data_processing")
            handler: Async function that takes (task_data: Dict) -> Any
        """
        self.task_handlers[task_type] = handler
        self.logger.logger.info(f"Registered handler for task type: {task_type}")
    
    async def start(self):
        """Start external service node"""
        self.logger.logger.info(f"🚀 Starting external service: {self.service_name}")
        print(f"🚀 Starting external service: {self.service_name}")
        print(f"   Service ID: {self.service_id}")
        print(f"   Cluster: {self.cluster_url}")
        print(f"   Capabilities: {[cap.value for cap in self.capabilities]}")
        
        self.running = True
        self.start_time = time.time()
        
        try:
            # Connect to cluster
            await self.sio.connect(self.cluster_url, namespaces=['/cluster'])
            
            # Start heartbeat loop
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            # Keep running
            await heartbeat_task
            
        except Exception as e:
            self.logger.logger.error(f"❌ Failed to start external service: {e}")
            raise
    
    async def stop(self):
        """Stop external service node"""
        self.logger.logger.info(f"🛑 Stopping external service: {self.service_name}")
        print(f"🛑 Stopping external service: {self.service_name}")
        
        self.running = False
        
        # Cancel active tasks
        for task_id, task_coroutine in self.active_tasks.items():
            if not task_coroutine.done():
                self.logger.logger.info(f"⚠️  Cancelling active task: {task_id}")
                task_coroutine.cancel()
        
        # Wait for tasks to complete
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks.values(), return_exceptions=True)
        
        # Disconnect from cluster
        if self.connected:
            await self.sio.disconnect()
        
        print("✅ External service stopped")
    
    # ========================
    # Connection Handlers
    # ========================
    
    async def handle_connect(self):
        """Handle connection to cluster"""
        self.logger.logger.info(f"🔌 Connected to cluster: {self.cluster_url}")
        print(f"🔌 Connected to cluster: {self.cluster_url}")
        self.connected = True
        
        # Authenticate with cluster
        await self.sio.emit('authenticate', {
            'client_type': 'external_service',
            'token': self.auth_token,
            'service_name': self.service_name
        }, namespace='/cluster')
    
    async def handle_disconnect(self):
        """Handle disconnection from cluster"""
        self.logger.logger.warning(f"❌ Disconnected from cluster")
        print(f"❌ Disconnected from cluster")
        self.connected = False
        self.registered = False
    
    async def handle_authenticated(self, data):
        """Handle successful authentication"""
        if data.get('success'):
            self.logger.logger.info("✅ Authenticated with cluster")
            print("✅ Authenticated with cluster")
            
            # Register as external service node
            await self.register_with_cluster()
        else:
            self.logger.logger.error("❌ Authentication failed")
            print("❌ Authentication failed")
    
    async def handle_auth_failed(self, data):
        """Handle authentication failure"""
        error_msg = data.get('error', 'Unknown authentication error')
        self.logger.logger.error(f"❌ Authentication failed: {error_msg}")
        print(f"❌ Authentication failed: {error_msg}")
    
    async def register_with_cluster(self):
        """Register this external service with the cluster"""
        self.logger.logger.info(f"📋 Registering external service with cluster...")
        print(f"📋 Registering external service with cluster...")
        
        # Prepare capability task types
        task_types = []
        for cap in self.capabilities:
            if cap == ExternalServiceCapability.ML_TRAINING:
                task_types.extend(["external_ml", "ml_training"])
            elif cap == ExternalServiceCapability.ML_INFERENCE:
                task_types.extend(["external_ml", "ml_inference"])
            elif cap == ExternalServiceCapability.DATA_PROCESSING:
                task_types.extend(["external_processing", "data_processing"])
            elif cap == ExternalServiceCapability.API_INTEGRATION:
                task_types.extend(["external_api", "api_integration"])
            elif cap == ExternalServiceCapability.DATABASE_OPERATIONS:
                task_types.extend(["external_database", "database_operations"])
            elif cap == ExternalServiceCapability.WEBHOOK_HANDLING:
                task_types.extend(["external_webhook", "webhook_handling"])
            else:
                task_types.extend(["external_custom", cap.value])
        
        # Send registration
        await self.sio.emit('node:register', {
            'node_id': self.service_id,
            'name': self.service_name,
            'node_type': 'external_service',
            'capabilities': {
                'task_types': task_types,
                'max_concurrent_tasks': self.max_concurrent_tasks,
                'external_service': True,
                'service_capabilities': [cap.value for cap in self.capabilities]
            }
        }, namespace='/cluster')
        
        self.registered = True
        self.logger.logger.info("✅ Successfully registered with cluster")
        print("✅ Successfully registered with cluster")
        print(f"   Ready to execute external tasks!")
    
    # ========================
    # Task Handlers
    # ========================
    
    async def handle_task_assign(self, data):
        """Handle task assignment from cluster"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        task_type = data.get('task_type')
        external_task_type = data.get('external_task_type')
        
        self.logger.logger.info(f"📋 Received task assignment: {task_id}")
        print(f"📋 Received external task: {task_id} (type: {external_task_type or task_type})")
        
        # Check capacity
        if len(self.active_tasks) >= self.max_concurrent_tasks:
            self.logger.logger.warning(f"⚠️  At capacity, rejecting task: {task_id}")
            await self.report_task_failed(task_id, workflow_id, "Service at capacity")
            return
        
        # Find appropriate task handler
        handler = self._find_task_handler(task_type, external_task_type)
        if not handler:
            error_msg = f"No handler registered for task type: {external_task_type or task_type}"
            self.logger.logger.error(f"❌ {error_msg}")
            await self.report_task_failed(task_id, workflow_id, error_msg)
            return
        
        # Accept task
        await self.sio.emit('task:accepted', {
            'task_id': task_id,
            'workflow_id': workflow_id,
            'node_id': self.service_id
        }, namespace='/cluster')
        
        # Execute task asynchronously
        task_coroutine = asyncio.create_task(
            self.execute_external_task(task_id, workflow_id, data, handler)
        )
        self.active_tasks[task_id] = task_coroutine
    
    async def handle_task_cancel(self, data):
        """Handle task cancellation"""
        task_id = data.get('task_id')
        
        self.logger.logger.info(f"❌ Task cancellation requested: {task_id}")
        print(f"❌ Task cancellation requested: {task_id}")
        
        if task_id in self.active_tasks:
            task_coroutine = self.active_tasks[task_id]
            if not task_coroutine.done():
                task_coroutine.cancel()
            del self.active_tasks[task_id]
    
    def _find_task_handler(self, task_type: str, external_task_type: str) -> Optional[Callable]:
        """Find appropriate task handler"""
        # Try external_task_type first (more specific)
        if external_task_type and external_task_type in self.task_handlers:
            return self.task_handlers[external_task_type]
        
        # Try general task_type
        if task_type in self.task_handlers:
            return self.task_handlers[task_type]
        
        # Try capability-based matching
        for cap in self.capabilities:
            if cap.value in self.task_handlers:
                return self.task_handlers[cap.value]
        
        return None
    
    async def execute_external_task(self, task_id: str, workflow_id: str, task_data: Dict, handler: Callable):
        """Execute external task using registered handler"""
        start_time = time.time()
        
        try:
            self.logger.logger.info(f"⚡ Executing external task: {task_id}")
            print(f"⚡ Executing external task: {task_id}")
            
            # Report progress
            await self.report_task_progress(task_id, workflow_id, 0, "Starting external task execution")
            
            # Execute task using handler
            result = await handler(task_data)
            
            # Report completion
            execution_time = time.time() - start_time
            self.tasks_completed += 1
            self.logger.logger.info(f"✅ External task completed: {task_id} (took {execution_time:.2f}s)")
            print(f"✅ External task completed: {task_id} (took {execution_time:.2f}s)")
            
            await self.report_task_completed(task_id, workflow_id, result)
            
        except asyncio.CancelledError:
            self.logger.logger.info(f"❌ External task cancelled: {task_id}")
            print(f"❌ External task cancelled: {task_id}")
            await self.report_task_failed(task_id, workflow_id, "Task cancelled")
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.tasks_failed += 1
            self.logger.logger.error(f"❌ External task failed: {task_id} - {e}")
            print(f"❌ External task failed: {task_id} - {e}")
            await self.report_task_failed(task_id, workflow_id, str(e))
            
        finally:
            # Clean up
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
    
    async def report_task_progress(self, task_id: str, workflow_id: str, progress: int, message: str):
        """Report task progress to cluster"""
        if self.connected:
            await self.sio.emit('task:progress', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'progress': progress,
                'message': message,
                'node_id': self.service_id,
                'service_name': self.service_name,
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
    
    async def report_task_completed(self, task_id: str, workflow_id: str, result: Any):
        """Report task completion to cluster"""
        if self.connected:
            await self.sio.emit('task:completed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'result': result,
                'node_id': self.service_id,
                'service_name': self.service_name,
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
    
    async def report_task_failed(self, task_id: str, workflow_id: str, error: str):
        """Report task failure to cluster"""
        if self.connected:
            await self.sio.emit('task:failed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'error': error,
                'node_id': self.service_id,
                'service_name': self.service_name,
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
    
    # ========================
    # Background Tasks
    # ========================
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to cluster"""
        while self.running:
            if self.connected and self.registered:
                await self.send_heartbeat()
            
            await asyncio.sleep(self.heartbeat_interval)
    
    async def send_heartbeat(self):
        """Send heartbeat with service status"""
        try:
            uptime_seconds = time.time() - self.start_time
            
            await self.sio.emit('node:heartbeat', {
                'node_id': self.service_id,
                'service_name': self.service_name,
                'status': 'ready',
                'node_type': 'external_service',
                'active_tasks': len(self.active_tasks),
                'max_tasks': self.max_concurrent_tasks,
                'tasks_completed': self.tasks_completed,
                'tasks_failed': self.tasks_failed,
                'uptime_seconds': uptime_seconds,
                'capabilities': [cap.value for cap in self.capabilities],
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
            
        except Exception as e:
            self.logger.logger.error(f"❌ Failed to send heartbeat: {e}")
    
    async def handle_cluster_shutdown(self, data):
        """Handle cluster shutdown notification"""
        self.logger.logger.info("🛑 Cluster shutdown requested")
        print("🛑 Cluster shutdown requested")
        await self.stop()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current service status"""
        return {
            'service_name': self.service_name,
            'service_id': self.service_id,
            'connected': self.connected,
            'registered': self.registered,
            'active_tasks': len(self.active_tasks),
            'max_concurrent_tasks': self.max_concurrent_tasks,
            'tasks_completed': self.tasks_completed,
            'tasks_failed': self.tasks_failed,
            'uptime_seconds': time.time() - self.start_time,
            'capabilities': [cap.value for cap in self.capabilities]
        }