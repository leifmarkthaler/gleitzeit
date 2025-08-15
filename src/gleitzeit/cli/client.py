"""
Gleitzeit CLI Client

Event-native client that communicates with Gleitzeit execution engines
via Socket.IO for distributed coordination or direct API for local mode.
"""

import asyncio
import logging
import socketio
from typing import Dict, Any, Optional, AsyncIterator, Callable, List
from datetime import datetime
import json

from gleitzeit.cli.config import CLIConfig
from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus, TaskResult
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.errors import (
    ErrorCode, SystemError, NetworkError, ConnectionTimeoutError,
    WorkflowError, TaskError, ConfigurationError
)
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.persistence.sqlite_backend import SQLiteBackend
from gleitzeit.persistence.redis_backend import RedisBackend

logger = logging.getLogger(__name__)


class GleitzeitClient:
    """
    Event-native client for Gleitzeit V4
    
    Supports both local mode (direct execution engine) and cluster mode
    (Socket.IO communication with central server).
    """
    
    def __init__(self, config: CLIConfig):
        self.config = config
        self.mode = config.mode
        self._sio: Optional[socketio.AsyncClient] = None
        self._local_engine: Optional[ExecutionEngine] = None
        self._event_handlers: Dict[str, Callable] = {}
        self._connected = False
        
    async def connect(self) -> None:
        """Connect to cluster or initialize local engine"""
        if self.mode == "auto":
            # Try cluster first, fall back to local
            try:
                await self._connect_cluster()
                self.mode = "cluster"
            except Exception as e:
                logger.debug(f"Cluster connection failed: {e}, using local mode")
                await self._initialize_local()
                self.mode = "local"
        elif self.mode == "cluster":
            await self._connect_cluster()
        else:  # local mode
            await self._initialize_local()
        
        self._connected = True
        logger.info(f"Connected in {self.mode} mode")
    
    async def disconnect(self) -> None:
        """Disconnect from cluster or shutdown local engine"""
        if self._sio and self._sio.connected:
            await self._sio.disconnect()
        
        if self._local_engine:
            await self._local_engine.stop()
        
        self._connected = False
    
    async def _connect_cluster(self) -> None:
        """Connect to Socket.IO cluster"""
        self._sio = socketio.AsyncClient()
        
        # Register event handlers
        @self._sio.event
        async def connect():
            logger.debug("Connected to cluster")
        
        @self._sio.event
        async def disconnect():
            logger.debug("Disconnected from cluster")
        
        @self._sio.event  
        async def workflow_submitted(data):
            await self._handle_event("workflow:submitted", data)
        
        @self._sio.event
        async def workflow_started(data):
            await self._handle_event("workflow:started", data)
        
        @self._sio.event
        async def workflow_completed(data):
            await self._handle_event("workflow:completed", data)
        
        @self._sio.event
        async def workflow_failed(data):
            await self._handle_event("workflow:failed", data)
        
        @self._sio.event
        async def task_result(data):
            await self._handle_event("task:result", data)
        
        # Connect with authentication
        connect_kwargs = {}
        if self.config.cluster.token:
            connect_kwargs['auth'] = {'token': self.config.cluster.token}
        
        endpoint = self.config.cluster.endpoint
        if not endpoint.startswith('http'):
            protocol = 'https' if self.config.cluster.tls else 'http'
            endpoint = f"{protocol}://{endpoint}"
        
        await self._sio.connect(
            endpoint,
            timeout=self.config.cluster.timeout,
            **connect_kwargs
        )
    
    async def _initialize_local(self) -> None:
        """Initialize local execution engine"""
        # Set up persistence
        if self.config.local.persistence == "redis":
            persistence = RedisBackend(
                host=self.config.local.redis_host,
                port=self.config.local.redis_port
            )
        else:
            persistence = SQLiteBackend(self.config.local.db_path)
        
        await persistence.initialize()
        
        # Initialize components
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        # Set up queue with persistence
        queue = queue_manager.get_default_queue()
        queue.persistence = persistence
        await queue.initialize()
        
        # Create execution engine
        self._local_engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=persistence
        )
        
        # Register event handlers for local engine
        self._local_engine.add_event_handler("workflow:submitted", self._local_event_handler)
        self._local_engine.add_event_handler("workflow:started", self._local_event_handler)
        self._local_engine.add_event_handler("workflow:completed", self._local_event_handler)
        self._local_engine.add_event_handler("workflow:failed", self._local_event_handler)
        self._local_engine.add_event_handler("task:started", self._local_event_handler)
        self._local_engine.add_event_handler("task:completed", self._local_event_handler)
        self._local_engine.add_event_handler("task:failed", self._local_event_handler)
        self._local_engine.add_event_handler("task:retry_executed", self._local_event_handler)
        
        # Start execution engine in event-driven mode (default)
        await self._local_engine.start()
    
    async def _local_event_handler(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle events from local execution engine"""
        await self._handle_event(event_type, data)
    
    async def _handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle incoming events"""
        if event_type in self._event_handlers:
            try:
                await self._event_handlers[event_type](data)
            except Exception as e:
                logger.error(f"Error handling {event_type} event: {e}")
    
    def add_event_handler(self, event_type: str, handler: Callable) -> None:
        """Add event handler"""
        self._event_handlers[event_type] = handler
    
    async def submit_workflow(self, workflow: Workflow, priority: str = "normal") -> str:
        """Submit workflow for execution"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"mode": self.mode, "connected": self._connected}
            )
        
        if self.mode == "cluster":
            # Submit via Socket.IO
            try:
                response = await self._sio.call('submit_workflow', {
                    'workflow': {
                        'id': workflow.id,
                        'name': workflow.name,
                        'description': workflow.description,
                        'tasks': [task.dict() for task in workflow.tasks],
                        'metadata': workflow.metadata
                    },
                    'priority': priority
                })
                
                if 'error' in response:
                    raise WorkflowError(
                        message=f"Workflow submission failed: {response['error']}",
                        code=ErrorCode.WORKFLOW_EXECUTION_FAILED,
                        workflow_id=workflow.id,
                        data={"server_error": response['error']}
                    )
                
                return response['workflow_id']
                
            except Exception as e:
                if isinstance(e, WorkflowError):
                    raise
                
                # Network or Socket.IO errors
                raise NetworkError(
                    message=f"Failed to submit workflow via cluster: {e}",
                    code=ErrorCode.CONNECTION_LOST,
                    endpoint=self.config.cluster_url,
                    cause=e
                )
        
        else:
            # Submit to local engine
            await self._local_engine.submit_workflow(workflow)
            return workflow.id
    
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"method": "get_workflow_status"}
            )
        
        if self.mode == "cluster":
            # Query via Socket.IO
            return await self._sio.call('get_workflow_status', {
                'workflow_id': workflow_id
            })
        else:
            # Query local engine
            workflow = self._local_engine.workflow_states.get(workflow_id)
            if not workflow:
                return {'status': 'not_found'}
            
            # Get task results
            task_results = self._local_engine.get_workflow_results(workflow_id)
            
            return {
                'workflow_id': workflow_id,
                'status': workflow.status,
                'started_at': workflow.started_at.isoformat() if workflow.started_at else None,
                'completed_at': workflow.completed_at.isoformat() if workflow.completed_at else None,
                'task_count': len(workflow.tasks),
                'completed_tasks': len([r for r in task_results if r.status == TaskStatus.COMPLETED]),
                'failed_tasks': len([r for r in task_results if r.status == TaskStatus.FAILED]),
                'tasks': [
                    {
                        'id': task.id,
                        'name': task.name,
                        'status': task.status,
                        'started_at': task.started_at.isoformat() if task.started_at else None,
                        'completed_at': task.completed_at.isoformat() if task.completed_at else None
                    }
                    for task in workflow.tasks
                ]
            }
    
    async def get_workflow_results(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow execution results"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"method": "get_workflow_results"}
            )
        
        if self.mode == "cluster":
            return await self._sio.call('get_workflow_results', {
                'workflow_id': workflow_id
            })
        else:
            # Get results from local engine
            task_results = self._local_engine.get_workflow_results(workflow_id)
            
            return {
                'workflow_id': workflow_id,
                'results': [
                    {
                        'task_id': result.task_id,
                        'status': result.status,
                        'result': result.result,
                        'error': result.error,
                        'started_at': result.started_at.isoformat() if result.started_at else None,
                        'completed_at': result.completed_at.isoformat() if result.completed_at else None,
                        'metadata': result.metadata
                    }
                    for result in task_results
                ]
            }
    
    async def cancel_workflow(self, workflow_id: str, force: bool = False) -> bool:
        """Cancel workflow execution"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"method": "cancel_workflow"}
            )
        
        if self.mode == "cluster":
            response = await self._sio.call('cancel_workflow', {
                'workflow_id': workflow_id,
                'force': force
            })
            return response.get('cancelled', False)
        else:
            # Cancel in local engine (simplified)
            if workflow_id in self._local_engine.workflow_states:
                workflow = self._local_engine.workflow_states[workflow_id]
                workflow.status = WorkflowStatus.CANCELLED
                return True
            return False
    
    async def stream_workflow_events(self, workflow_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Stream workflow execution events"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"method": "stream_workflow_events"}
            )
        
        event_queue = asyncio.Queue()
        
        async def event_collector(data):
            if data.get('workflow_id') == workflow_id:
                await event_queue.put(data)
        
        # Subscribe to relevant events
        self.add_event_handler("workflow:started", event_collector)
        self.add_event_handler("workflow:completed", event_collector)
        self.add_event_handler("workflow:failed", event_collector)
        self.add_event_handler("task:started", event_collector)
        self.add_event_handler("task:completed", event_collector)
        self.add_event_handler("task:failed", event_collector)
        self.add_event_handler("task:retry_executed", event_collector)
        
        try:
            while True:
                try:
                    # Wait for events with timeout
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    yield event
                    
                    # Stop if workflow is complete or failed
                    if event.get('event_type') in ['workflow:completed', 'workflow:failed']:
                        break
                        
                except asyncio.TimeoutError:
                    # Check if workflow is still active
                    status = await self.get_workflow_status(workflow_id)
                    if status.get('status') in ['completed', 'failed', 'cancelled']:
                        break
                    continue
                    
        except Exception as e:
            logger.error(f"Error streaming workflow events: {e}")
        
        # Clean up event handlers
        for event_type in ["workflow:started", "workflow:completed", "workflow:failed",
                          "task:started", "task:completed", "task:failed", "task:retry_executed"]:
            if event_type in self._event_handlers:
                del self._event_handlers[event_type]
    
    async def list_providers(self) -> List[Dict[str, Any]]:
        """List available providers"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"method": "list_providers"}
            )
        
        if self.mode == "cluster":
            return await self._sio.call('list_providers')
        else:
            # Get from local registry
            providers = []
            for provider_id, provider_info in self._local_engine.registry._providers.items():
                providers.append({
                    'provider_id': provider_id,
                    'protocol_id': provider_info['protocol_id'],
                    'supported_methods': list(provider_info.get('supported_methods', [])),
                    'status': 'online'
                })
            return providers
    
    async def list_protocols(self) -> List[Dict[str, Any]]:
        """List available protocols"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"method": "list_protocols"}
            )
        
        if self.mode == "cluster":
            return await self._sio.call('list_protocols')
        else:
            # Get from local registry
            protocols = []
            for protocol_id, protocol_spec in self._local_engine.registry._protocols.items():
                protocols.append({
                    'protocol_id': protocol_id,
                    'name': protocol_spec.name,
                    'version': protocol_spec.version,
                    'description': protocol_spec.description,
                    'methods': list(protocol_spec.methods.keys())
                })
            return protocols
    
    async def get_protocol_methods(self, protocol_id: str) -> List[Dict[str, Any]]:
        """Get methods for a protocol"""
        if not self._connected:
            raise SystemError(
                message="Client not connected - call connect() first",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"method": "get_protocol_methods"}
            )
        
        if self.mode == "cluster":
            return await self._sio.call('get_protocol_methods', {
                'protocol_id': protocol_id
            })
        else:
            # Get from local registry
            if protocol_id not in self._local_engine.registry._protocols:
                return []
            
            protocol_spec = self._local_engine.registry._protocols[protocol_id]
            methods = []
            for method_name, method_spec in protocol_spec.methods.items():
                methods.append({
                    'name': method_name,
                    'description': method_spec.description,
                    'parameters': getattr(method_spec, 'parameters', {}),
                })
            return methods