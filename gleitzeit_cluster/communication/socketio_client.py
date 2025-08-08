"""
Socket.IO client for cluster components
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

import socketio

from ..core.workflow import Workflow, WorkflowStatus
from ..core.task import Task, TaskStatus
from ..core.node import ExecutorNode
from ..core.error_handling import RetryManager, RetryConfig, GleitzeitLogger


logger = logging.getLogger(__name__)


class ClientType(Enum):
    """Types of Socket.IO clients"""
    CLUSTER = "cluster"
    EXECUTOR = "executor"
    DASHBOARD = "dashboard"


class SocketIOClient:
    """
    Base Socket.IO client for Gleitzeit cluster components
    
    Provides real-time communication with the cluster coordinator
    for workflow submission, task execution, and monitoring.
    """
    
    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        client_type: ClientType = ClientType.CLUSTER,
        client_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        reconnection: bool = True,
        reconnection_attempts: int = 5,
        reconnection_delay: int = 2
    ):
        """
        Initialize Socket.IO client
        
        Args:
            server_url: Socket.IO server URL
            client_type: Type of client (cluster/executor/dashboard)
            client_id: Unique client identifier
            auth_token: Authentication token
            reconnection: Enable automatic reconnection
            reconnection_attempts: Maximum reconnection attempts
            reconnection_delay: Delay between reconnection attempts
        """
        self.server_url = server_url
        self.client_type = client_type
        self.client_id = client_id or str(uuid.uuid4())
        self.auth_token = auth_token
        
        # Initialize Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=reconnection,
            reconnection_attempts=reconnection_attempts,
            reconnection_delay=reconnection_delay,
            logger=logger,
            engineio_logger=False
        )
        
        # Connection state
        self._connected = False
        self._authenticated = False
        
        # Event callbacks
        self._event_callbacks: Dict[str, List[Callable]] = {}
        
        # Error handling and retry
        self.logger = GleitzeitLogger(f"SocketIOClient_{client_type.value}")
        self.retry_manager = RetryManager(self.logger)
        self.reconnection_attempts = reconnection_attempts
        self.reconnection_delay = reconnection_delay
        
        # Setup base handlers
        self._setup_base_handlers()
    
    def _setup_base_handlers(self):
        """Setup base event handlers"""
        
        @self.sio.on('connect', namespace='/cluster')
        async def on_connect():
            logger.info(f"Connected to server: {self.server_url}")
            self._connected = True
            
            # Send authentication
            if self.auth_token:
                await self.authenticate()
            
            # Trigger connected callback
            await self._trigger_callbacks('connected', {})
        
        @self.sio.on('disconnect', namespace='/cluster')
        async def on_disconnect():
            logger.info("Disconnected from server")
            self._connected = False
            self._authenticated = False
            
            # Trigger disconnected callback
            await self._trigger_callbacks('disconnected', {})
        
        @self.sio.on('authenticated', namespace='/cluster')
        async def on_authenticated(data):
            if data.get('success'):
                logger.info("Authentication successful")
                self._authenticated = True
                await self._trigger_callbacks('authenticated', data)
            else:
                logger.error("Authentication failed")
                self._authenticated = False
        
        @self.sio.on('error', namespace='/cluster')
        async def on_error(data):
            logger.error(f"Server error: {data}")
            await self._trigger_callbacks('error', data)
    
    async def connect(self) -> bool:
        """Connect to Socket.IO server with retry logic"""
        retry_config = RetryConfig(
            max_attempts=self.reconnection_attempts,
            base_delay=self.reconnection_delay,
            max_delay=30.0
        )
        
        async def _connect():
            await self.sio.connect(
                self.server_url,
                namespaces=['/cluster']
            )
            
            # Wait for connection
            for _ in range(10):
                if self._connected:
                    return True
                await asyncio.sleep(0.5)
            
            raise Exception("Connection timeout - did not receive connected event")
        
        try:
            return await self.retry_manager.execute_with_retry(
                _connect,
                retry_config,
                service_name="socketio_connection",
                context={"server_url": self.server_url, "client_type": self.client_type.value}
            )
        except Exception as e:
            self.logger.logger.error(f"Failed to connect after {self.reconnection_attempts} attempts: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from server"""
        if self._connected:
            await self.sio.disconnect()
            self._connected = False
    
    async def authenticate(self) -> bool:
        """Authenticate with server"""
        await self.emit('authenticate', {
            'token': self.auth_token,
            'client_type': self.client_type.value,
            'client_id': self.client_id
        })
        
        # Wait for authentication response
        for _ in range(10):
            if self._authenticated:
                return True
            await asyncio.sleep(0.5)
        
        return False
    
    async def emit(self, event: str, data: Dict[str, Any]) -> None:
        """Emit event to server with retry logic"""
        if not self._connected:
            logger.warning(f"Not connected, cannot emit {event}")
            return
        
        retry_config = RetryConfig(
            max_attempts=3,
            base_delay=0.5,
            max_delay=5.0
        )
        
        async def _emit():
            await self.sio.emit(event, data, namespace='/cluster')
        
        try:
            await self.retry_manager.execute_with_retry(
                _emit,
                retry_config,
                service_name="socketio_emit",
                context={"event": event, "client_type": self.client_type.value}
            )
        except Exception as e:
            self.logger.logger.error(f"Failed to emit event {event}: {e}")
    
    def on(self, event: str, callback: Callable):
        """Register event handler"""
        if event not in self._event_callbacks:
            self._event_callbacks[event] = []
            
            # Register with Socket.IO
            @self.sio.on(event, namespace='/cluster')
            async def handler(data):
                await self._trigger_callbacks(event, data)
        
        self._event_callbacks[event].append(callback)
    
    async def _trigger_callbacks(self, event: str, data: Any):
        """Trigger registered callbacks for event"""
        if event in self._event_callbacks:
            for callback in self._event_callbacks[event]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as e:
                    logger.error(f"Callback error for {event}: {e}")
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected"""
        return self._connected
    
    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated"""
        return self._authenticated


class ClusterSocketClient(SocketIOClient):
    """
    Socket.IO client for cluster manager
    
    Handles workflow submission and monitoring
    """
    
    def __init__(self, **kwargs):
        super().__init__(client_type=ClientType.CLUSTER, **kwargs)
        self._setup_cluster_handlers()
    
    def _setup_cluster_handlers(self):
        """Setup cluster-specific handlers"""
        
        # Workflow events
        self.on('workflow:started', self._handle_workflow_started)
        self.on('workflow:completed', self._handle_workflow_completed)
        self.on('workflow:progress', self._handle_workflow_progress)
        
        # Task events
        self.on('task:completed', self._handle_task_completed)
        self.on('task:failed', self._handle_task_failed)
        self.on('task:progress', self._handle_task_progress)
    
    async def submit_workflow(self, workflow: Workflow) -> None:
        """Submit workflow for execution"""
        
        # Prepare workflow data
        tasks_data = []
        for task in workflow.tasks.values():
            tasks_data.append({
                'task_id': task.id,
                'task_type': task.task_type.value,
                'priority': task.priority.value,
                'parameters': task.parameters.model_dump(),
                'dependencies': task.dependencies,
                'timeout': task.timeout_seconds
            })
        
        workflow_data = {
            'workflow_id': workflow.id,
            'name': workflow.name,
            'tasks': tasks_data,
            'metadata': workflow.metadata
        }
        
        await self.emit('workflow:submit', workflow_data)
        logger.info(f"Submitted workflow {workflow.id} via Socket.IO")
    
    async def cancel_workflow(self, workflow_id: str) -> None:
        """Cancel workflow execution"""
        await self.emit('workflow:cancel', {'workflow_id': workflow_id})
        logger.info(f"Cancelled workflow {workflow_id}")
    
    async def get_workflow_status(self, workflow_id: str) -> None:
        """Request workflow status"""
        await self.emit('workflow:status', {'workflow_id': workflow_id})
    
    async def _handle_workflow_started(self, data: Dict[str, Any]):
        """Handle workflow started event"""
        logger.info(f"Workflow started: {data.get('workflow_id')}")
    
    async def _handle_workflow_completed(self, data: Dict[str, Any]):
        """Handle workflow completed event"""
        logger.info(f"Workflow completed: {data.get('workflow_id')} - {data.get('status')}")
    
    async def _handle_workflow_progress(self, data: Dict[str, Any]):
        """Handle workflow progress update"""
        logger.debug(f"Workflow progress: {data.get('workflow_id')} - {data.get('progress_percentage')}%")
    
    async def _handle_task_completed(self, data: Dict[str, Any]):
        """Handle task completion"""
        logger.info(f"Task completed: {data.get('task_id')}")
    
    async def _handle_task_failed(self, data: Dict[str, Any]):
        """Handle task failure"""
        logger.error(f"Task failed: {data.get('task_id')} - {data.get('error')}")
    
    async def _handle_task_progress(self, data: Dict[str, Any]):
        """Handle task progress update"""
        logger.debug(f"Task progress: {data.get('task_id')} - {data.get('progress')}%")


class ExecutorSocketClient(SocketIOClient):
    """
    Socket.IO client for executor nodes
    
    Handles task reception and execution reporting
    """
    
    def __init__(
        self,
        node: ExecutorNode,
        task_handler: Optional[Callable] = None,
        **kwargs
    ):
        super().__init__(client_type=ClientType.EXECUTOR, **kwargs)
        self.node = node
        self.task_handler = task_handler
        self._setup_executor_handlers()
        
        # Heartbeat task
        self._heartbeat_task = None
    
    def _setup_executor_handlers(self):
        """Setup executor-specific handlers"""
        
        # Task assignment
        self.on('task:assign', self._handle_task_assignment)
        
        # Workflow events
        self.on('workflow:cancelled', self._handle_workflow_cancelled)
    
    async def register_node(self) -> None:
        """Register executor node with server"""
        await self.emit('node:register', {
            'node_id': self.node.id,
            'name': self.node.name,
            'capabilities': {
                'task_types': [t.value for t in self.node.capabilities.supported_task_types],
                'models': self.node.capabilities.available_models,
                'has_gpu': self.node.capabilities.has_gpu,
                'max_concurrent_tasks': self.node.capabilities.max_concurrent_tasks or 4
            },
            'metadata': self.node.metadata
        })
        
        logger.info(f"Registered node {self.node.name}")
        
        # Start heartbeat
        if not self._heartbeat_task:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats"""
        while self._connected:
            try:
                await self.emit('node:heartbeat', {
                    'node_id': self.node.id,
                    'status': self.node.status.value,
                    'current_tasks': len(self.node.assigned_tasks),
                    'timestamp': datetime.utcnow().isoformat()
                })
                
                await asyncio.sleep(30)  # Send heartbeat every 30 seconds
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)
    
    async def _handle_task_assignment(self, data: Dict[str, Any]):
        """Handle task assignment from server"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        
        logger.info(f"Received task assignment: {task_id}")
        
        # Accept task
        await self.emit('task:accepted', {
            'task_id': task_id,
            'node_id': self.node.id
        })
        
        # Execute task if handler provided
        if self.task_handler:
            try:
                # Report progress
                await self.emit('task:progress', {
                    'task_id': task_id,
                    'workflow_id': workflow_id,
                    'progress': 0,
                    'message': 'Starting task execution'
                })
                
                # Execute task
                result = await self.task_handler(data)
                
                # Report completion
                await self.emit('task:completed', {
                    'task_id': task_id,
                    'workflow_id': workflow_id,
                    'result': result,
                    'node_id': self.node.id
                })
                
                logger.info(f"Task {task_id} completed successfully")
                
            except Exception as e:
                # Report failure
                await self.emit('task:failed', {
                    'task_id': task_id,
                    'workflow_id': workflow_id,
                    'error': str(e),
                    'node_id': self.node.id
                })
                
                logger.error(f"Task {task_id} failed: {e}")
    
    async def _handle_workflow_cancelled(self, data: Dict[str, Any]):
        """Handle workflow cancellation"""
        workflow_id = data.get('workflow_id')
        logger.info(f"Workflow {workflow_id} cancelled")
        # TODO: Cancel any running tasks for this workflow
    
    async def update_status(self, status: str):
        """Update node status"""
        await self.emit('node:status', {
            'node_id': self.node.id,
            'status': status
        })
    
    async def disconnect(self):
        """Disconnect and cleanup"""
        # Cancel heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        
        await super().disconnect()


class DashboardSocketClient(SocketIOClient):
    """
    Socket.IO client for monitoring dashboards
    
    Handles real-time updates for UI display
    """
    
    def __init__(self, **kwargs):
        super().__init__(client_type=ClientType.DASHBOARD, **kwargs)
        self._setup_dashboard_handlers()
    
    def _setup_dashboard_handlers(self):
        """Setup dashboard-specific handlers"""
        
        # Workflow events
        self.on('workflow:started', self._handle_workflow_update)
        self.on('workflow:progress', self._handle_workflow_update)
        self.on('workflow:completed', self._handle_workflow_update)
        
        # Node events
        self.on('node:registered', self._handle_node_update)
        self.on('node:status_change', self._handle_node_update)
        self.on('node:disconnected', self._handle_node_update)
        
        # Cluster events
        self.on('cluster:stats_response', self._handle_stats_update)
    
    async def request_stats(self):
        """Request cluster statistics"""
        await self.emit('cluster:stats', {'request_id': str(uuid.uuid4())})
    
    async def _handle_workflow_update(self, data: Dict[str, Any]):
        """Handle workflow updates"""
        logger.info(f"Workflow update: {data}")
        # Override in subclass to update UI
    
    async def _handle_node_update(self, data: Dict[str, Any]):
        """Handle node updates"""
        logger.info(f"Node update: {data}")
        # Override in subclass to update UI
    
    async def _handle_stats_update(self, data: Dict[str, Any]):
        """Handle statistics update"""
        logger.info(f"Stats update: {data}")
        # Override in subclass to update UI