"""
Central Socket.IO Server for Gleitzeit V3

This server coordinates all distributed components:
- Providers connect and register their capabilities
- Workflow engines connect and manage workflows
- Clients connect and submit workflows
- Server manages provider lifecycle and emits events
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Set, Any, Optional, List
import socketio
import uvicorn
from fastapi import FastAPI

from ..events.schemas import EventType, EventEnvelope, create_event, EventSeverity
from ..core.models import Workflow, Task, WorkflowStatus, TaskStatus

logger = logging.getLogger(__name__)


class ProviderInfo:
    """Information about a connected provider"""
    
    def __init__(self, provider_id: str, socket_id: str, registration_data: Dict[str, Any]):
        self.provider_id = provider_id
        self.socket_id = socket_id
        self.name = registration_data.get('provider_name', provider_id)
        self.provider_type = registration_data.get('provider_type', 'unknown')
        self.supported_functions = set(registration_data.get('supported_functions', []))
        self.max_concurrent_tasks = registration_data.get('max_concurrent_tasks', 5)
        self.version = registration_data.get('version', '1.0.0')
        
        # Connection state
        self.connected_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        self.status = "available"
        self.current_tasks = 0
        
        # Health metrics
        self.health_score = 1.0
        self.tasks_completed = 0
        self.tasks_failed = 0


class CentralServer:
    """Central coordination server for Gleitzeit V3"""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        
        # Connected components
        self.providers: Dict[str, ProviderInfo] = {}  # provider_id -> info
        self.workflow_engines: Set[str] = set()  # socket_ids
        self.clients: Set[str] = set()  # socket_ids
        
        # Workflow queue management
        self.workflow_queue: List[Workflow] = []  # Queued workflows
        self.active_workflows: Dict[str, Workflow] = {}  # Currently running workflows
        self.completed_workflows: Dict[str, Workflow] = {}  # Completed workflows
        
        # Socket mappings
        self.socket_to_provider: Dict[str, str] = {}  # socket_id -> provider_id
        self.socket_to_component_type: Dict[str, str] = {}  # socket_id -> type
        
        # Setup Socket.IO server with async_mode
        self.sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")
        self.app = FastAPI(title="Gleitzeit V3 Central Server")
        
        # Create combined ASGI app (don't mount, replace)
        self.socket_app = socketio.ASGIApp(self.sio, self.app)
        
        # Setup event handlers
        self._setup_socket_handlers()
        
        # Health check task
        self.health_check_task: Optional[asyncio.Task] = None
        
        logger.info(f"Central server initialized on {host}:{port}")
    
    def _setup_socket_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f"Socket connected: {sid}")
        
        @self.sio.event
        async def disconnect(sid):
            logger.info(f"Socket disconnected: {sid}")
            await self._handle_disconnect(sid)
        
        @self.sio.on('provider:register')
        async def provider_register(sid, data):
            await self._handle_provider_register(sid, data)
        
        @self.sio.on('provider:heartbeat')
        async def provider_heartbeat(sid, data):
            await self._handle_provider_heartbeat(sid, data)
        
        @self.sio.on('provider:task_completed')
        async def provider_task_completed(sid, data):
            await self._handle_provider_task_completed(sid, data)
        
        @self.sio.on('workflow_engine:register')
        async def workflow_engine_register(sid, data):
            await self._handle_workflow_engine_register(sid, data)
        
        @self.sio.on('client:register')
        async def client_register(sid, data):
            await self._handle_client_register(sid, data)
        
        @self.sio.on('event:publish')
        async def event_publish(sid, data):
            await self._handle_event_publish(sid, data)
        
        @self.sio.on('task:execute')
        async def task_execute(sid, data):
            await self._handle_task_execute(sid, data)
        
        @self.sio.on('workflow:started')
        async def workflow_started(sid, data):
            await self._handle_workflow_started(sid, data)
        
        @self.sio.on('workflow:completed')
        async def workflow_completed(sid, data):
            await self._handle_workflow_completed(sid, data)
        
        @self.sio.on('workflow:submit')
        async def workflow_submit(sid, data):
            await self._handle_workflow_submit(sid, data)
        
        @self.sio.on('queue:list')
        async def queue_list(sid, data):
            await self._handle_queue_list(sid, data)
        
        @self.sio.on('queue:stats')
        async def queue_stats(sid, data):
            await self._handle_queue_stats(sid, data)
    
    async def _handle_provider_register(self, sid: str, data: Dict[str, Any]):
        """Handle provider registration"""
        provider_id = data.get('provider_id')
        if not provider_id:
            await self.sio.emit('error', {'message': 'provider_id is required'}, room=sid)
            return
        
        # Create provider info
        provider_info = ProviderInfo(provider_id, sid, data)
        self.providers[provider_id] = provider_info
        self.socket_to_provider[sid] = provider_id
        self.socket_to_component_type[sid] = 'provider'
        
        logger.info(f"Provider registered: {provider_id} ({provider_info.name})")
        
        # Confirm registration
        await self.sio.emit('provider:registered', {
            'provider_id': provider_id,
            'server_time': datetime.utcnow().isoformat()
        }, room=sid)
        
        # Emit provider connected event to all workflow engines
        await self._emit_to_workflow_engines('provider:connected', {
            'provider_id': provider_id,
            'provider_name': provider_info.name,
            'provider_type': provider_info.provider_type,
            'supported_functions': list(provider_info.supported_functions),
            'max_concurrent_tasks': provider_info.max_concurrent_tasks,
            'version': provider_info.version,
            'connected_at': provider_info.connected_at.isoformat()
        })
    
    async def _handle_provider_heartbeat(self, sid: str, data: Dict[str, Any]):
        """Handle provider heartbeat"""
        provider_id = self.socket_to_provider.get(sid)
        if not provider_id or provider_id not in self.providers:
            return
        
        provider = self.providers[provider_id]
        provider.last_heartbeat = datetime.utcnow()
        
        # Update provider metrics from heartbeat
        provider.status = data.get('status', provider.status)
        provider.current_tasks = data.get('current_tasks', provider.current_tasks)
        provider.health_score = data.get('health_score', provider.health_score)
        
        # Emit heartbeat event to workflow engines
        await self._emit_to_workflow_engines('provider:heartbeat', {
            'provider_id': provider_id,
            'status': provider.status,
            'current_tasks': provider.current_tasks,
            'health_score': provider.health_score,
            'last_heartbeat': provider.last_heartbeat.isoformat()
        })
    
    async def _handle_provider_task_completed(self, sid: str, data: Dict[str, Any]):
        """Handle provider task completion"""
        provider_id = self.socket_to_provider.get(sid)
        if not provider_id or provider_id not in self.providers:
            return
        
        provider = self.providers[provider_id]
        if data.get('success', True):
            provider.tasks_completed += 1
        else:
            provider.tasks_failed += 1
        
        provider.current_tasks = max(0, provider.current_tasks - 1)
        
        task_id = data.get('task_id')
        success = data.get('success', False)
        logger.info(f"Task {task_id} completed by {provider_id}: {'success' if success else 'failed'}")
        
        # Forward task completion to workflow engines
        await self._emit_to_workflow_engines('task:completed', data)
    
    async def _handle_workflow_engine_register(self, sid: str, data: Dict[str, Any]):
        """Handle workflow engine registration"""
        self.workflow_engines.add(sid)
        self.socket_to_component_type[sid] = 'workflow_engine'
        
        engine_id = data.get('engine_id', f'engine_{sid}')
        logger.info(f"Workflow engine registered: {engine_id}")
        
        # Confirm registration
        await self.sio.emit('workflow_engine:registered', {
            'engine_id': engine_id,
            'server_time': datetime.utcnow().isoformat()
        }, room=sid)
        
        # Send current provider list to new engine
        provider_list = []
        for provider_id, provider in self.providers.items():
            provider_list.append({
                'provider_id': provider_id,
                'provider_name': provider.name,
                'provider_type': provider.provider_type,
                'supported_functions': list(provider.supported_functions),
                'status': provider.status,
                'current_tasks': provider.current_tasks,
                'health_score': provider.health_score
            })
        
        await self.sio.emit('providers:list', {
            'providers': provider_list
        }, room=sid)
    
    async def _handle_client_register(self, sid: str, data: Dict[str, Any]):
        """Handle client registration"""
        self.clients.add(sid)
        self.socket_to_component_type[sid] = 'client'
        
        client_id = data.get('client_id', f'client_{sid}')
        logger.info(f"Client registered: {client_id}")
    
    async def _handle_task_execute(self, sid: str, data: Dict[str, Any]):
        """Handle task execution request from workflow engine"""
        task_id = data.get('task_id')
        provider_id = data.get('provider_id')
        
        if not task_id or not provider_id:
            await self.sio.emit('error', {'message': 'task_id and provider_id required'}, room=sid)
            return
        
        # Find provider
        if provider_id not in self.providers:
            await self.sio.emit('task:completed', {
                'task_id': task_id,
                'success': False,
                'error': f'Provider {provider_id} not found'
            }, room=sid)
            return
        
        provider = self.providers[provider_id]
        
        # Update provider task count
        provider.current_tasks += 1
        
        # Forward to provider
        await self.sio.emit('task:execute', data, room=provider.socket_id)
        
        logger.info(f"Task {task_id} forwarded to provider {provider_id}")
    
    async def _handle_workflow_started(self, sid: str, data: Dict[str, Any]):
        """Handle workflow started notification"""
        workflow_id = data.get('workflow_id')
        logger.info(f"Workflow started: {workflow_id}")
        
        # Could broadcast to monitoring components
        await self._emit_to_component_type('monitor', 'workflow:started', data)
    
    async def _handle_workflow_completed(self, sid: str, data: Dict[str, Any]):
        """Handle workflow completed notification"""
        workflow_id = data.get('workflow_id')
        status = data.get('status')
        logger.info(f"Workflow completed: {workflow_id} - {status}")
        
        # Could broadcast to monitoring components
        await self._emit_to_component_type('monitor', 'workflow:completed', data)
        
        # Move workflow from active to completed
        if workflow_id in self.active_workflows:
            workflow = self.active_workflows.pop(workflow_id)
            self.completed_workflows[workflow_id] = workflow
            
            # Try to start next queued workflow
            await self._try_start_next_workflow()
    
    async def _handle_workflow_submit(self, sid: str, data: Dict[str, Any]):
        """Handle workflow submission to queue"""
        try:
            # Deserialize workflow data
            workflow_data = data.get('workflow')
            if not workflow_data:
                await self.sio.emit('error', {'message': 'workflow data required'}, room=sid)
                return
            
            # Create workflow object (simplified - would need proper deserialization)
            workflow = Workflow(
                name=workflow_data.get('name', 'Unnamed Workflow'),
                description=workflow_data.get('description', ''),
                priority=workflow_data.get('priority', 'normal')
            )
            
            # Add tasks with proper TaskParameters
            from ..core.models import TaskParameters
            for task_data in workflow_data.get('tasks', []):
                task = Task(
                    name=task_data.get('name', 'Unnamed Task'),
                    priority=task_data.get('priority', 'normal'),
                    parameters=TaskParameters(data=task_data.get('parameters', {})),
                    dependencies=task_data.get('dependencies', [])
                )
                workflow.add_task(task)
            
            # Add to queue (sorted by priority)
            self._add_workflow_to_queue(workflow)
            
            # Emit confirmation
            await self.sio.emit('workflow:queued', {
                'workflow_id': workflow.id,
                'queue_position': len(self.workflow_queue)
            }, room=sid)
            
            # Try to start workflow if possible
            await self._try_start_next_workflow()
            
            logger.info(f"Workflow queued: {workflow.id}")
            
        except Exception as e:
            logger.error(f"Error handling workflow submission: {e}")
            await self.sio.emit('error', {'message': f'Failed to queue workflow: {e}'}, room=sid)
    
    async def _handle_queue_list(self, sid: str, data: Dict[str, Any]):
        """Handle queue list request"""
        limit = data.get('limit', 50)
        include_completed = data.get('include_completed', False)
        
        queue_data = []
        
        # Add queued workflows
        for workflow in self.workflow_queue[:limit]:
            queue_data.append({
                'id': workflow.id,
                'name': workflow.name,
                'priority': workflow.priority,
                'status': 'queued',
                'created_at': workflow.created_at.isoformat(),
                'task_count': len(workflow.tasks)
            })
        
        # Add active workflows
        for workflow in self.active_workflows.values():
            if len(queue_data) >= limit:
                break
            queue_data.append({
                'id': workflow.id,
                'name': workflow.name,
                'priority': workflow.priority,
                'status': workflow.status.value,
                'created_at': workflow.created_at.isoformat(),
                'task_count': len(workflow.tasks),
                'completed_tasks': len(workflow.completed_tasks)
            })
        
        # Add completed workflows if requested
        if include_completed:
            for workflow in list(self.completed_workflows.values())[-10:]:  # Last 10
                if len(queue_data) >= limit:
                    break
                workflow_data = {
                    'id': workflow.id,
                    'name': workflow.name,
                    'priority': workflow.priority,
                    'status': workflow.status.value,
                    'created_at': workflow.created_at.isoformat(),
                    'completed_at': getattr(workflow, 'updated_at', workflow.created_at).isoformat(),
                    'task_count': len(workflow.tasks),
                    'completed_tasks': len(workflow.completed_tasks)
                }
                
                # Include task results if available
                if hasattr(workflow, 'task_results') and workflow.task_results:
                    workflow_data['task_results'] = workflow.task_results
                
                queue_data.append(workflow_data)
        
        await self.sio.emit('queue:list_response', {
            'workflows': queue_data,
            'total_queued': len(self.workflow_queue),
            'total_active': len(self.active_workflows),
            'total_completed': len(self.completed_workflows)
        }, room=sid)
    
    async def _handle_queue_stats(self, sid: str, data: Dict[str, Any]):
        """Handle queue statistics request"""
        stats = {
            'queued': len(self.workflow_queue),
            'active': len(self.active_workflows),
            'completed': len(self.completed_workflows),
            'queue_by_priority': {},
            'active_by_status': {}
        }
        
        # Count queued workflows by priority
        for workflow in self.workflow_queue:
            priority = workflow.priority
            stats['queue_by_priority'][priority] = stats['queue_by_priority'].get(priority, 0) + 1
        
        # Count active workflows by status
        for workflow in self.active_workflows.values():
            status = workflow.status.value
            stats['active_by_status'][status] = stats['active_by_status'].get(status, 0) + 1
        
        await self.sio.emit('queue:stats_response', stats, room=sid)
    
    def _add_workflow_to_queue(self, workflow: Workflow):
        """Add workflow to queue, maintaining priority order"""
        priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        
        # Find insertion point based on priority
        insert_index = 0
        workflow_priority = priority_order.get(workflow.priority, 2)
        
        for i, queued_workflow in enumerate(self.workflow_queue):
            queued_priority = priority_order.get(queued_workflow.priority, 2)
            if workflow_priority < queued_priority:
                insert_index = i
                break
            insert_index = i + 1
        
        self.workflow_queue.insert(insert_index, workflow)
    
    async def _try_start_next_workflow(self):
        """Try to start the next workflow in the queue"""
        if not self.workflow_queue:
            return
        
        # Check if we have available workflow engines
        if not self.workflow_engines:
            return
        
        # For now, limit to one active workflow per engine
        # Could be made more sophisticated
        if len(self.active_workflows) >= len(self.workflow_engines):
            return
        
        # Get next workflow
        workflow = self.workflow_queue.pop(0)
        workflow.status = WorkflowStatus.RUNNING
        self.active_workflows[workflow.id] = workflow
        
        # Send to first available workflow engine
        engine_sid = next(iter(self.workflow_engines))
        
        # Convert workflow to dict for transmission
        workflow_data = {
            'id': workflow.id,
            'name': workflow.name,
            'description': workflow.description,
            'priority': workflow.priority,
            'tasks': [
                {
                    'id': task.id,
                    'name': task.name,
                    'priority': task.priority,
                    'parameters': task.parameters.data,
                    'dependencies': task.dependencies
                }
                for task in workflow.tasks
            ]
        }
        
        await self.sio.emit('workflow:execute', {
            'workflow': workflow_data
        }, room=engine_sid)
        
        logger.info(f"Started workflow from queue: {workflow.id}")
    
    async def _handle_event_publish(self, sid: str, data: Dict[str, Any]):
        """Handle event publication and routing"""
        event_data = data.get('event', {})
        target_components = data.get('target_components')
        source_component = data.get('source_component', 'unknown')
        
        # Route event based on type and targets
        if target_components:
            # Send to specific components
            for component_type in target_components:
                await self._emit_to_component_type(component_type, 'event:dispatch', data)
        else:
            # Broadcast to all relevant components
            await self._emit_to_workflow_engines('event:dispatch', data)
        
        # Send acknowledgment
        await self.sio.emit('event:ack', {
            'event_id': event_data.get('event_id'),
            'server_time': datetime.utcnow().isoformat()
        }, room=sid)
    
    async def _handle_disconnect(self, sid: str):
        """Handle socket disconnection"""
        component_type = self.socket_to_component_type.get(sid)
        
        if component_type == 'provider':
            provider_id = self.socket_to_provider.get(sid)
            if provider_id and provider_id in self.providers:
                logger.info(f"Provider disconnected: {provider_id}")
                
                # Remove provider
                del self.providers[provider_id]
                del self.socket_to_provider[sid]
                
                # Emit disconnect event to workflow engines
                await self._emit_to_workflow_engines('provider:disconnected', {
                    'provider_id': provider_id,
                    'disconnected_at': datetime.utcnow().isoformat()
                })
        
        elif component_type == 'workflow_engine':
            self.workflow_engines.discard(sid)
            logger.info(f"Workflow engine disconnected: {sid}")
        
        elif component_type == 'client':
            self.clients.discard(sid)
            logger.info(f"Client disconnected: {sid}")
        
        # Clean up mappings
        self.socket_to_component_type.pop(sid, None)
    
    async def _emit_to_workflow_engines(self, event: str, data: Dict[str, Any]):
        """Emit event to all workflow engines"""
        for engine_sid in self.workflow_engines:
            await self.sio.emit(event, data, room=engine_sid)
    
    async def _emit_to_component_type(self, component_type: str, event: str, data: Dict[str, Any]):
        """Emit event to all components of a specific type"""
        target_sockets = [
            sid for sid, comp_type in self.socket_to_component_type.items()
            if comp_type == component_type
        ]
        
        for sid in target_sockets:
            await self.sio.emit(event, data, room=sid)
    
    async def start_health_monitoring(self):
        """Start health monitoring for providers"""
        self.health_check_task = asyncio.create_task(self._health_check_loop())
    
    async def _health_check_loop(self):
        """Monitor provider health and emit alerts"""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                now = datetime.utcnow()
                unhealthy_providers = []
                
                for provider_id, provider in self.providers.items():
                    # Check if provider hasn't sent heartbeat in too long
                    if now - provider.last_heartbeat > timedelta(minutes=2):
                        unhealthy_providers.append(provider_id)
                        
                        # Emit unhealthy event
                        await self._emit_to_workflow_engines('provider:unhealthy', {
                            'provider_id': provider_id,
                            'last_heartbeat': provider.last_heartbeat.isoformat(),
                            'reason': 'heartbeat_timeout'
                        })
                
                if unhealthy_providers:
                    logger.warning(f"Unhealthy providers detected: {unhealthy_providers}")
                
            except Exception as e:
                logger.error(f"Health check error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics"""
        return {
            'providers': len(self.providers),
            'workflow_engines': len(self.workflow_engines),
            'clients': len(self.clients),
            'total_connections': len(self.socket_to_component_type),
            'provider_details': [
                {
                    'id': p.provider_id,
                    'name': p.name,
                    'status': p.status,
                    'current_tasks': p.current_tasks,
                    'health_score': p.health_score,
                    'uptime_seconds': (datetime.utcnow() - p.connected_at).total_seconds()
                }
                for p in self.providers.values()
            ]
        }
    
    async def start(self):
        """Start the central server"""
        logger.info(f"Starting central server on {self.host}:{self.port}")
        
        # Start health monitoring
        await self.start_health_monitoring()
        
        # Start uvicorn server with socket_app
        config = uvicorn.Config(
            self.socket_app, 
            host=self.host, 
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def stop(self):
        """Stop the central server"""
        if self.health_check_task:
            self.health_check_task.cancel()
        logger.info("Central server stopped")


async def main():
    """Run the central server"""
    server = CentralServer()
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        await server.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())