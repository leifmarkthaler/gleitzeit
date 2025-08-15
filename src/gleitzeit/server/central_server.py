"""
Central Socket.IO Server for Gleitzeit V4

Combines the protocol-based architecture of V4 with the distributed
Socket.IO coordination system from V3.
"""

import asyncio
import logging
from typing import Dict, List, Set, Any, Optional
from datetime import datetime
import json
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from gleitzeit.core import Task, Workflow, TaskStatus, WorkflowStatus, Priority, TaskResult
from gleitzeit.core.models import RetryConfig
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver

logger = logging.getLogger(__name__)


class CentralServer:
    """
    Central coordination server for Gleitzeit V4
    
    Manages:
    - Protocol-based provider registration and routing
    - Distributed task queue with Socket.IO coordination
    - Workflow orchestration across multiple engines
    - Protocol registry and provider health monitoring
    """
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        
        # Core V4 components
        self.protocol_registry = ProtocolProviderRegistry()
        self.queue_manager = QueueManager()
        self.dependency_resolver = DependencyResolver()
        
        # Socket.IO server
        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins="*",
            logger=True
        )
        
        # FastAPI app
        self.app = FastAPI(title="Gleitzeit V4 Central Server")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Connected components
        self.connected_providers: Dict[str, Dict[str, Any]] = {}  # sid -> provider_info
        self.connected_engines: Dict[str, Dict[str, Any]] = {}   # sid -> engine_info
        
        # Workflow management
        self.active_workflows: Dict[str, Workflow] = {}
        self.completed_workflows: Dict[str, Workflow] = {}
        self.workflow_results: Dict[str, Dict[str, TaskResult]] = {}
        
        # Setup Socket.IO events
        self._setup_socketio_events()
        
        # Mount Socket.IO app
        socket_app = socketio.ASGIApp(self.sio, self.app)
        self.app.mount("/", socket_app)
        
        logger.info(f"Initialized CentralServer for {host}:{port}")
    
    def _setup_socketio_events(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f"Client connected: {sid}")
            await self.sio.emit('connected', {'message': 'Connected to Gleitzeit V4 Central Server'}, room=sid)
        
        @self.sio.event
        async def disconnect(sid):
            logger.info(f"Client disconnected: {sid}")
            
            # Clean up provider if it was registered
            if sid in self.connected_providers:
                provider_info = self.connected_providers.pop(sid)
                provider_id = provider_info.get('provider_id')
                if provider_id:
                    self.protocol_registry.unregister_provider(provider_id)
                    logger.info(f"Unregistered provider: {provider_id}")
            
            # Clean up engine if it was registered
            if sid in self.connected_engines:
                engine_info = self.connected_engines.pop(sid)
                logger.info(f"Unregistered engine: {engine_info.get('engine_id')}")
        
        # Protocol Management Events
        @self.sio.on('register_protocol')
        async def register_protocol(sid, data):
            """Register a new protocol specification"""
            try:
                protocol_data = data.get('protocol')
                if not protocol_data:
                    await self.sio.emit('error', {'message': 'Protocol data required'}, room=sid)
                    return
                
                # Create protocol spec
                methods = {}
                for method_name, method_data in protocol_data.get('methods', {}).items():
                    methods[method_name] = MethodSpec(
                        name=method_name,
                        description=method_data.get('description', '')
                    )
                
                protocol = ProtocolSpec(
                    name=protocol_data['name'],
                    version=protocol_data['version'],
                    description=protocol_data.get('description', ''),
                    methods=methods
                )
                
                self.protocol_registry.register_protocol(protocol)
                
                await self.sio.emit('protocol_registered', {
                    'protocol_id': protocol.protocol_id,
                    'message': f'Protocol {protocol.protocol_id} registered successfully'
                }, room=sid)
                
                logger.info(f"Registered protocol: {protocol.protocol_id}")
                
            except Exception as e:
                await self.sio.emit('error', {'message': f'Failed to register protocol: {str(e)}'}, room=sid)
        
        # Provider Management Events
        @self.sio.on('register_provider')
        async def register_provider(sid, data):
            """Register a protocol provider"""
            try:
                provider_id = data.get('provider_id')
                protocol_id = data.get('protocol_id')
                supported_methods = data.get('supported_methods', [])
                
                if not provider_id or not protocol_id:
                    await self.sio.emit('error', {'message': 'provider_id and protocol_id required'}, room=sid)
                    return
                
                # Store provider connection info
                provider_info = {
                    'provider_id': provider_id,
                    'protocol_id': protocol_id,
                    'supported_methods': supported_methods,
                    'sid': sid,
                    'connected_at': datetime.utcnow(),
                    'status': 'online'
                }
                
                self.connected_providers[sid] = provider_info
                
                # Register with protocol registry (using a SocketIO proxy)
                socket_provider = SocketIOProviderProxy(sid, self.sio, provider_info)
                self.protocol_registry.register_provider(
                    provider_id,
                    protocol_id,
                    socket_provider,
                    set(supported_methods) if supported_methods else None
                )
                
                await self.sio.emit('provider_registered', {
                    'provider_id': provider_id,
                    'protocol_id': protocol_id,
                    'message': f'Provider {provider_id} registered for {protocol_id}'
                }, room=sid)
                
                # Broadcast provider availability
                await self.sio.emit('provider_available', {
                    'provider_id': provider_id,
                    'protocol_id': protocol_id,
                    'supported_methods': supported_methods
                })
                
                logger.info(f"Registered provider: {provider_id} for protocol {protocol_id}")
                
            except Exception as e:
                await self.sio.emit('error', {'message': f'Failed to register provider: {str(e)}'}, room=sid)
        
        # Engine Management Events
        @self.sio.on('register_engine')
        async def register_engine(sid, data):
            """Register a workflow engine"""
            try:
                engine_id = data.get('engine_id', f'engine-{sid}')
                engine_info = {
                    'engine_id': engine_id,
                    'sid': sid,
                    'connected_at': datetime.utcnow(),
                    'status': 'ready',
                    'active_workflows': []
                }
                
                self.connected_engines[sid] = engine_info
                
                await self.sio.emit('engine_registered', {
                    'engine_id': engine_id,
                    'message': f'Engine {engine_id} registered successfully'
                }, room=sid)
                
                logger.info(f"Registered engine: {engine_id}")
                
            except Exception as e:
                await self.sio.emit('error', {'message': f'Failed to register engine: {str(e)}'}, room=sid)
        
        # Task Execution Events
        @self.sio.on('submit_task')
        async def submit_task(sid, data):
            """Submit a task for execution"""
            try:
                task_data = data.get('task')
                if not task_data:
                    await self.sio.emit('error', {'message': 'Task data required'}, room=sid)
                    return
                
                logger.info(f"Received task submission: {task_data.get('id')} ({task_data.get('protocol')}/{task_data.get('method')})")
                
                # Create task object
                task = Task(
                    id=task_data.get('id'),
                    name=task_data['name'],
                    protocol=task_data['protocol'],
                    method=task_data['method'],
                    params=task_data.get('params', {}),
                    dependencies=task_data.get('dependencies', []),
                    priority=Priority(task_data.get('priority', 'normal')),
                    timeout=task_data.get('timeout'),
                    workflow_id=task_data.get('workflow_id'),
                    retry_config=RetryConfig(**task_data.get('retry_config', {})) if 'retry_config' in task_data else RetryConfig(),
                    metadata=task_data.get('metadata', {})
                )
                
                # Add to queue
                await self.queue_manager.enqueue_task(task)
                logger.info(f"Task {task.id} added to queue")
                
                await self.sio.emit('task_submitted', {
                    'task_id': task.id,
                    'workflow_id': task.workflow_id,
                    'message': f'Task {task.id} submitted successfully'
                }, room=sid)
                
                # Notify engines about new task
                await self.sio.emit('task_available', {
                    'task_id': task.id,
                    'protocol': task.protocol,
                    'method': task.method,
                    'priority': task.priority
                })
                
                logger.info(f"Task submitted: {task.id} ({task.protocol}/{task.method})")
                
            except Exception as e:
                logger.error(f"Failed to submit task: {e}")
                await self.sio.emit('error', {'message': f'Failed to submit task: {str(e)}'}, room=sid)
        
        @self.sio.on('request_task')
        async def request_task(sid, data):
            """Engine requests next available task"""
            try:
                if sid not in self.connected_engines:
                    await self.sio.emit('error', {'message': 'Engine not registered'}, room=sid)
                    return
                
                # Check queue status
                queue_stats = await self.queue_manager.get_global_stats()
                logger.debug(f"Queue status: {queue_stats['total_size']} tasks available")
                
                # Get next task from queue
                task = await self.queue_manager.dequeue_next_task()
                
                if task:
                    # Mark task as routed
                    task.status = TaskStatus.ROUTED
                    
                    logger.info(f"Routing task {task.id} to engine {self.connected_engines[sid]['engine_id']}")
                    
                    # Send task to engine
                    await self.sio.emit('execute_task', {
                        'task': {
                            'id': task.id,
                            'name': task.name,
                            'protocol': task.protocol,
                            'method': task.method,
                            'params': task.params,
                            'dependencies': task.dependencies,
                            'priority': task.priority,
                            'timeout': task.timeout,
                            'workflow_id': task.workflow_id,
                            'metadata': task.metadata
                        }
                    }, room=sid)
                    
                    logger.info(f"Routed task {task.id} to engine {self.connected_engines[sid]['engine_id']}")
                else:
                    await self.sio.emit('no_tasks', {'message': 'No tasks available'}, room=sid)
                
            except Exception as e:
                logger.error(f"Failed to process task request: {e}")
                await self.sio.emit('error', {'message': f'Failed to get task: {str(e)}'}, room=sid)
        
        @self.sio.on('task_completed')
        async def task_completed(sid, data):
            """Handle task completion from engine"""
            try:
                task_id = data.get('task_id')
                result_data = data.get('result')
                error = data.get('error')
                
                if not task_id:
                    await self.sio.emit('error', {'message': 'task_id required'}, room=sid)
                    return
                
                # Create task result
                task_result = TaskResult(
                    task_id=task_id,
                    workflow_id=data.get('workflow_id'),
                    status=TaskStatus.COMPLETED if not error else TaskStatus.FAILED,
                    result=result_data,
                    error=error,
                    started_at=datetime.fromisoformat(data['started_at']) if data.get('started_at') else None,
                    completed_at=datetime.utcnow(),
                    metadata=data.get('metadata', {})
                )
                
                # Store result
                workflow_id = task_result.workflow_id
                if workflow_id:
                    if workflow_id not in self.workflow_results:
                        self.workflow_results[workflow_id] = {}
                    self.workflow_results[workflow_id][task_id] = task_result
                
                # Mark task as completed in queue
                if error:
                    await self.queue_manager.mark_task_failed(task_id)
                else:
                    await self.queue_manager.mark_task_completed(task_id)
                
                # Broadcast completion
                await self.sio.emit('task_result', {
                    'task_id': task_id,
                    'workflow_id': workflow_id,
                    'status': task_result.status,
                    'result': result_data,
                    'error': error
                })
                
                logger.info(f"Task completed: {task_id} with status {task_result.status}")
                
                # Check for dependent tasks that are now ready to execute
                if not error:  # Only if task completed successfully
                    await self._assign_available_tasks()
                
            except Exception as e:
                await self.sio.emit('error', {'message': f'Failed to process task completion: {str(e)}'}, room=sid)
        
        # Workflow Events
        @self.sio.on('submit_workflow')
        async def submit_workflow(sid, data):
            """Submit a complete workflow"""
            try:
                workflow_data = data.get('workflow')
                if not workflow_data:
                    await self.sio.emit('error', {'message': 'Workflow data required'}, room=sid)
                    return
                
                # Create tasks
                tasks = []
                for task_data in workflow_data.get('tasks', []):
                    task = Task(
                        id=task_data.get('id'),
                        name=task_data['name'],
                        protocol=task_data['protocol'],
                        method=task_data['method'],
                        params=task_data.get('params', {}),
                        dependencies=task_data.get('dependencies', []),
                        priority=Priority(task_data.get('priority', 'normal')),
                        timeout=task_data.get('timeout'),
                        workflow_id=workflow_data.get('id'),
                        retry_config=RetryConfig(**task_data.get('retry_config', {})) if 'retry_config' in task_data else RetryConfig(),
                        metadata=task_data.get('metadata', {})
                    )
                    tasks.append(task)
                
                # Create workflow
                workflow = Workflow(
                    id=workflow_data.get('id'),
                    name=workflow_data['name'],
                    description=workflow_data.get('description'),
                    tasks=tasks,
                    metadata=workflow_data.get('metadata', {})
                )
                
                # Validate dependencies
                validation_errors = self.dependency_resolver.validate_workflow_dependencies(workflow)
                if validation_errors:
                    await self.sio.emit('error', {
                        'message': f'Workflow validation failed: {"; ".join(validation_errors)}'
                    }, room=sid)
                    return
                
                # Store workflow and analyze dependencies
                self.active_workflows[workflow.id] = workflow
                self.dependency_resolver.add_workflow(workflow)
                
                # Only enqueue tasks that have no dependencies (can execute immediately)
                for task in workflow.tasks:
                    if not task.dependencies:  # Tasks with no dependencies
                        await self.queue_manager.enqueue_task(task)
                        logger.info(f"Enqueued task {task.id} (no dependencies)")
                    else:
                        logger.info(f"Holding task {task.id} until dependencies satisfied: {task.dependencies}")
                
                await self.sio.emit('workflow_submitted', {
                    'workflow_id': workflow.id,
                    'task_count': len(workflow.tasks),
                    'message': f'Workflow {workflow.id} submitted with {len(workflow.tasks)} tasks'
                }, room=sid)
                
                # Broadcast workflow start
                await self.sio.emit('workflow_started', {
                    'workflow_id': workflow.id,
                    'task_count': len(workflow.tasks)
                })
                
                # Proactively assign tasks to available engines
                await self._assign_available_tasks()
                
                logger.info(f"Workflow submitted: {workflow.id} with {len(workflow.tasks)} tasks")
                
            except Exception as e:
                await self.sio.emit('error', {'message': f'Failed to submit workflow: {str(e)}'}, room=sid)
        
        # Provider Request Handling
        @self.sio.on('provider_request')
        async def provider_request(sid, data):
            """Handle provider request from engine"""
            try:
                protocol = data.get('protocol')
                method = data.get('method')
                params = data.get('params', {})
                task_id = data.get('task_id')
                
                logger.info(f"Provider request: {protocol}/{method} for task {task_id}")
                
                # Find provider for this protocol
                provider_sid = None
                for p_sid, provider_info in self.connected_providers.items():
                    if provider_info['protocol_id'] == protocol:
                        provider_sid = p_sid
                        break
                
                if not provider_sid:
                    return {'error': f'No provider available for protocol {protocol}'}
                
                # Forward request to provider
                try:
                    response = await self.sio.call(
                        'execute_method',
                        {
                            'method': method,
                            'params': params
                        },
                        sid=provider_sid,
                        timeout=30
                    )
                    
                    logger.info(f"Provider response for task {task_id}: success")
                    return response
                    
                except Exception as e:
                    logger.error(f"Provider call failed for task {task_id}: {e}")
                    return {'error': str(e)}
                
            except Exception as e:
                logger.error(f"Provider request handling failed: {e}")
                return {'error': str(e)}
    
    async def start(self):
        """Start the central server"""
        logger.info(f"Starting Gleitzeit V4 Central Server on {self.host}:{self.port}")
        
        # Start the protocol registry health monitoring
        await self.protocol_registry.start()
        
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def stop(self):
        """Stop the central server"""
        logger.info("Stopping Gleitzeit V4 Central Server")
        await self.protocol_registry.stop()
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status"""
        return {
            "server": f"{self.host}:{self.port}",
            "connected_providers": len(self.connected_providers),
            "connected_engines": len(self.connected_engines),
            "active_workflows": len(self.active_workflows),
            "completed_workflows": len(self.completed_workflows),
            "queue_stats": asyncio.create_task(self.queue_manager.get_global_stats()),
            "registry_stats": self.protocol_registry.get_registry_stats()
        }
    
    async def _assign_available_tasks(self) -> None:
        """Proactively assign available tasks to connected engines"""
        try:
            # Check if we have available engines
            available_engines = [
                (sid, engine_info) for sid, engine_info in self.connected_engines.items()
                if engine_info.get('status') == 'ready'
            ]
            
            if not available_engines:
                logger.debug("No available engines for task assignment")
                return
            
            # First, check for newly ready dependent tasks in active workflows
            await self._enqueue_ready_dependent_tasks()
            
            # Assign tasks to engines
            assigned_count = 0
            for engine_sid, engine_info in available_engines:
                # Get next task from queue
                task = await self.queue_manager.dequeue_next_task()
                
                if not task:
                    break  # No more tasks available
                
                # Mark task as routed
                task.status = TaskStatus.ROUTED
                
                engine_id = engine_info['engine_id']
                logger.info(f"Proactively assigning task {task.id} to engine {engine_id}")
                
                # Send task to engine
                await self.sio.emit('execute_task', {
                    'task': {
                        'id': task.id,
                        'name': task.name,
                        'protocol': task.protocol,
                        'method': task.method,
                        'params': task.params,
                        'dependencies': task.dependencies,
                        'priority': task.priority,
                        'timeout': task.timeout,
                        'workflow_id': task.workflow_id,
                        'metadata': task.metadata
                    }
                }, room=engine_sid)
                
                assigned_count += 1
                logger.info(f"Assigned task {task.id} to engine {engine_id}")
            
            if assigned_count > 0:
                logger.info(f"Proactively assigned {assigned_count} tasks to engines")
            
        except Exception as e:
            logger.error(f"Failed to assign available tasks: {e}")
    
    async def _enqueue_ready_dependent_tasks(self) -> None:
        """Check active workflows for tasks whose dependencies are now satisfied"""
        try:
            for workflow_id, workflow in self.active_workflows.items():
                if workflow_id not in self.workflow_results:
                    continue
                    
                # Get completed task IDs for this workflow
                completed_task_ids = {
                    task_id for task_id, result in self.workflow_results[workflow_id].items()
                    if result.status == TaskStatus.COMPLETED
                }
                
                # Check each task in the workflow
                for task in workflow.tasks:
                    # Skip if task is already completed
                    if task.id in completed_task_ids:
                        continue
                    
                    # Skip if task has no dependencies (should already be enqueued)
                    if not task.dependencies:
                        continue
                    
                    # Check if all dependencies are satisfied
                    dependencies_satisfied = all(
                        dep_task_id in completed_task_ids 
                        for dep_task_id in task.dependencies
                    )
                    
                    if dependencies_satisfied:
                        # Check if task is already in queue (avoid duplicates)
                        queue_stats = await self.queue_manager.get_global_stats()
                        # We can't easily check if specific task is in queue, so we'll let the queue handle duplicates
                        
                        logger.info(f"Dependencies satisfied for task {task.id}, enqueueing...")
                        await self.queue_manager.enqueue_task(task)
                        
        except Exception as e:
            logger.error(f"Failed to enqueue ready dependent tasks: {e}")


class SocketIOProviderProxy:
    """Proxy for protocol providers connected via Socket.IO"""
    
    def __init__(self, sid: str, sio: socketio.AsyncServer, provider_info: Dict[str, Any]):
        self.sid = sid
        self.sio = sio
        self.provider_info = provider_info
        self.provider_id = provider_info['provider_id']
        self.protocol_id = provider_info['protocol_id']
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Forward request to Socket.IO provider"""
        try:
            # Send request to provider
            response = await self.sio.call(
                'execute_method',
                {
                    'method': method,
                    'params': params
                },
                sid=self.sid,
                timeout=30
            )
            
            if response.get('error'):
                raise Exception(response['error'])
            
            return response.get('result')
            
        except Exception as e:
            logger.error(f"Provider {self.provider_id} request failed: {e}")
            raise
    
    async def initialize(self):
        """Initialize provider"""
        try:
            await self.sio.call('initialize', {}, sid=self.sid, timeout=10)
        except Exception as e:
            logger.error(f"Provider {self.provider_id} initialization failed: {e}")
    
    async def shutdown(self):
        """Shutdown provider"""
        try:
            await self.sio.call('shutdown', {}, sid=self.sid, timeout=10)
        except Exception as e:
            logger.error(f"Provider {self.provider_id} shutdown failed: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check provider health"""
        try:
            response = await self.sio.call('health_check', {}, sid=self.sid, timeout=5)
            return response
        except Exception as e:
            return {
                "status": "unhealthy",
                "details": f"Health check failed: {str(e)}"
            }
    
    def get_supported_methods(self) -> List[str]:
        """Get supported methods"""
        return self.provider_info.get('supported_methods', [])


if __name__ == "__main__":
    import asyncio
    
    async def main():
        server = CentralServer()
        await server.start()
    
    asyncio.run(main())