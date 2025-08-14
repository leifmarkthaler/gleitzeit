"""
Socket.IO Workflow Engine Client for Gleitzeit V4

Distributed workflow engine that connects to the central server
and executes tasks by routing them to appropriate providers.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import socketio
import json

from core import Task, TaskStatus, TaskResult, Priority
from core.models import RetryConfig

logger = logging.getLogger(__name__)


class SocketIOEngineClient:
    """
    Distributed workflow engine that connects via Socket.IO
    
    Responsibilities:
    - Connect to central server and register as execution engine
    - Request and execute tasks from the server queue
    - Route task execution to appropriate protocol providers
    - Handle parameter substitution for dependent tasks
    - Report task results back to central server
    """
    
    def __init__(
        self,
        engine_id: str,
        server_url: str = "http://localhost:8000",
        max_concurrent_tasks: int = 5
    ):
        self.engine_id = engine_id
        self.server_url = server_url
        self.max_concurrent_tasks = max_concurrent_tasks
        
        # Socket.IO client
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.running = False
        
        # Task execution state
        self.active_tasks: Dict[str, Task] = {}
        self.task_results: Dict[str, TaskResult] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        # Engine capabilities
        self.capabilities = ["task_execution", "parameter_substitution", "dependency_resolution"]
        
        # Setup event handlers
        self._setup_events()
        
        logger.info(f"Initialized SocketIO Engine Client: {engine_id}")
    
    def _setup_events(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info(f"Engine connected to central server: {self.server_url}")
            
            # Register with central server
            await self._register_engine()
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            logger.info("Engine disconnected from central server")
        
        @self.sio.event
        async def connected(data):
            logger.info(f"Server response: {data['message']}")
        
        @self.sio.event
        async def engine_registered(data):
            logger.info(f"Engine registered: {data['message']}")
            
            # Set up push-based task assignment instead of polling
            await self._setup_push_based_tasks()
        
        @self.sio.event
        async def error(data):
            logger.error(f"Server error: {data['message']}")
        
        @self.sio.event
        async def execute_task(data):
            """Handle task execution request from server"""
            try:
                task_data = data.get('task')
                if not task_data:
                    logger.error("No task data received")
                    return
                
                # Create task object
                task = Task(
                    id=task_data['id'],
                    name=task_data['name'],
                    protocol=task_data['protocol'],
                    method=task_data['method'],
                    params=task_data.get('params', {}),
                    dependencies=task_data.get('dependencies', []),
                    priority=Priority(task_data.get('priority', 'normal')),
                    timeout=task_data.get('timeout'),
                    workflow_id=task_data.get('workflow_id'),
                    metadata=task_data.get('metadata', {})
                )
                
                # Execute task concurrently
                asyncio.create_task(self._execute_task(task))
                
            except Exception as e:
                logger.error(f"Failed to handle task execution: {e}")
        
        @self.sio.event
        async def no_tasks(data):
            """Handle no tasks available response"""
            # Wait a bit before requesting again
            await asyncio.sleep(2)
        
        @self.sio.event
        async def task_available(data):
            """Handle notification of new task availability"""
            # In push-based system, server will assign tasks directly
            # No need to request - just wait for task_assigned event
            logger.debug("Task available notification received - waiting for task assignment")
        
        @self.sio.event
        async def task_result(data):
            """Handle task result broadcast from other engines"""
            task_id = data.get('task_id')
            workflow_id = data.get('workflow_id')
            
            if task_id and workflow_id:
                # Store result for parameter substitution
                result = TaskResult(
                    task_id=task_id,
                    workflow_id=workflow_id,
                    status=TaskStatus(data['status']),
                    result=data.get('result'),
                    error=data.get('error'),
                    completed_at=datetime.utcnow()
                )
                self.task_results[task_id] = result
                
                logger.debug(f"Received task result for dependency resolution: {task_id}")
    
    async def _register_engine(self):
        """Register this engine with the central server"""
        try:
            await self.sio.emit('register_engine', {
                'engine_id': self.engine_id,
                'max_concurrent_tasks': self.max_concurrent_tasks
            })
        except Exception as e:
            logger.error(f"Failed to register engine: {e}")
    
    async def _setup_push_based_tasks(self):
        """Set up push-based task assignment from server - no polling"""
        logger.info("Setting up push-based task assignment")
        
        # Register for task assignment events from server
        @self.sio.event
        async def task_assigned(data):
            """Handle task assignment from server - push-based, no polling"""
            try:
                if len(self.active_tasks) < self.max_concurrent_tasks:
                    await self._handle_assigned_task(data)
                else:
                    # Reject task if at capacity - server will reassign
                    await self.sio.emit('task_rejected', {
                        'task_id': data.get('task_id'),
                        'reason': 'at_capacity',
                        'current_load': len(self.active_tasks),
                        'max_capacity': self.max_concurrent_tasks
                    })
            except Exception as e:
                logger.error(f"Error handling assigned task: {e}")
        
        # Notify server of our capacity - only when capacity changes
        await self._notify_server_capacity()
    
    async def _handle_assigned_task(self, task_data):
        """Handle task assigned by server - push-based"""
        try:
            task_id = task_data.get('task_id')
            logger.info(f"Received task assignment: {task_id}")
            
            # Convert task_data to Task object
            task = Task.from_dict(task_data)
            
            # Execute the assigned task
            await self._execute_task(task)
            
        except Exception as e:
            logger.error(f"Error handling assigned task: {e}")
    
    async def _notify_server_capacity(self):
        """Notify server of our current capacity - called when capacity changes"""
        try:
            available_capacity = self.max_concurrent_tasks - len(self.active_tasks)
            
            await self.sio.emit('capacity_update', {
                'engine_id': self.engine_id,
                'available_capacity': available_capacity,
                'max_capacity': self.max_concurrent_tasks,
                'capabilities': self.capabilities,
                'active_tasks': len(self.active_tasks)
            })
            
            logger.debug(f"Updated server capacity: {available_capacity}/{self.max_concurrent_tasks}")
            
        except Exception as e:
            logger.error(f"Error notifying server capacity: {e}")
    
    async def _execute_task(self, task: Task):
        """Execute a task"""
        async with self.semaphore:
            task_start_time = datetime.utcnow()
            self.active_tasks[task.id] = task
            
            try:
                task.status = TaskStatus.EXECUTING
                task.started_at = task_start_time
                
                logger.info(f"Executing task {task.id} ({task.protocol}/{task.method})")
                
                # Resolve parameters if there are dependencies
                resolved_params = await self._resolve_parameters(task)
                
                # Execute task via protocol provider
                result = await self._execute_via_provider(task, resolved_params)
                
                # Create success result
                task_result = TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    status=TaskStatus.COMPLETED,
                    result=result,
                    started_at=task_start_time,
                    completed_at=datetime.utcnow(),
                    metadata={"engine_id": self.engine_id}
                )
                
                # Update task status
                task.status = TaskStatus.COMPLETED
                task.completed_at = task_result.completed_at
                
                # Store result locally for dependencies
                self.task_results[task.id] = task_result
                
                # Report completion to server
                await self.sio.emit('task_completed', {
                    'task_id': task.id,
                    'workflow_id': task.workflow_id,
                    'result': result,
                    'started_at': task_start_time.isoformat(),
                    'completed_at': task_result.completed_at.isoformat(),
                    'metadata': task_result.metadata
                })
                
                logger.info(f"Task {task.id} completed successfully")
                
                # Notify server of updated capacity after task completion
                await self._notify_server_capacity()
                
            except Exception as e:
                # Create failure result
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.error_message = str(e)
                
                task_result = TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    status=TaskStatus.FAILED,
                    error=str(e),
                    started_at=task_start_time,
                    completed_at=task.completed_at,
                    metadata={"engine_id": self.engine_id}
                )
                
                self.task_results[task.id] = task_result
                
                # Report failure to server
                await self.sio.emit('task_completed', {
                    'task_id': task.id,
                    'workflow_id': task.workflow_id,
                    'error': str(e),
                    'started_at': task_start_time.isoformat(),
                    'completed_at': task.completed_at.isoformat(),
                    'metadata': task_result.metadata
                })
                
                logger.error(f"Task {task.id} failed: {e}")
                
                # Notify server of updated capacity after task failure
                await self._notify_server_capacity()
                
            finally:
                # Cleanup
                self.active_tasks.pop(task.id, None)
    
    async def _resolve_parameters(self, task: Task) -> Dict[str, Any]:
        """Resolve parameter references for task execution"""
        if not task.dependencies:
            return task.params.copy()
        
        import re
        
        def substitute_references(obj):
            """Recursively substitute parameter references"""
            if isinstance(obj, str):
                # Look for ${task-id.field} patterns
                pattern = r'\$\{([^}]+)\}'
                
                # Check if the entire string is a single reference
                full_match = re.fullmatch(pattern, obj)
                if full_match:
                    # This is a complete reference, return the actual value
                    match = full_match.group(1)
                    parts = match.split('.')
                    ref_task_id = parts[0]
                    
                    # Navigate nested fields (e.g., task-id.result.field.subfield)
                    if ref_task_id in self.task_results:
                        ref_result = self.task_results[ref_task_id]
                        
                        # Start with the result object
                        ref_value = ref_result.result
                        
                        # Navigate through any additional fields
                        for field in parts[1:]:
                            if isinstance(ref_value, dict) and field in ref_value:
                                ref_value = ref_value[field]
                            elif hasattr(ref_value, field):
                                ref_value = getattr(ref_value, field)
                            else:
                                logger.warning(f"Field {field} not found in {ref_task_id} result, using value up to this point")
                                break  # Stop navigation but return current value
                        
                        # Return the actual value (not stringified)
                        return ref_value
                    else:
                        logger.warning(f"Referenced task {ref_task_id} not found in results")
                        return obj
                else:
                    # String contains references but isn't entirely a reference
                    matches = re.findall(pattern, obj)
                    
                    for match in matches:
                        parts = match.split('.')
                        ref_task_id = parts[0]
                        
                        # Get referenced result
                        if ref_task_id in self.task_results:
                            ref_result = self.task_results[ref_task_id]
                            
                            # Navigate to the referenced value
                            ref_value = ref_result.result
                            for field in parts[1:]:
                                if isinstance(ref_value, dict) and field in ref_value:
                                    ref_value = ref_value[field]
                                elif hasattr(ref_value, field):
                                    ref_value = getattr(ref_value, field)
                                else:
                                    logger.warning(f"Field {field} not found in {ref_task_id} result")
                                    continue
                            
                            # Replace the reference with string representation
                            if ref_value is not None:
                                replacement = json.dumps(ref_value) if not isinstance(ref_value, str) else str(ref_value)
                                obj = obj.replace(f"${{{match}}}", replacement)
                        else:
                            logger.warning(f"Referenced task {ref_task_id} not found in results")
                    
                    return obj
            
            elif isinstance(obj, dict):
                return {k: substitute_references(v) for k, v in obj.items()}
            
            elif isinstance(obj, list):
                return [substitute_references(item) for item in obj]
            
            else:
                return obj
        
        return substitute_references(task.params.copy())
    
    async def _execute_via_provider(self, task: Task, params: Dict[str, Any]) -> Any:
        """Execute task via protocol provider through central server"""
        try:
            # Send provider request to central server
            response = await self.sio.call(
                'provider_request',
                {
                    'protocol': task.protocol,
                    'method': task.method,
                    'params': params,
                    'task_id': task.id
                },
                timeout=task.timeout or 60
            )
            
            if response.get('error'):
                raise Exception(response['error'])
            
            return response.get('result')
            
        except Exception as e:
            logger.error(f"Provider execution failed for task {task.id}: {e}")
            # For testing, we can simulate provider execution
            if task.protocol == "echo/v1" and task.method == "ping":
                return {
                    "response": "pong",
                    "task_id": task.id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "simulated": True
                }
            raise
    
    async def start(self):
        """Start the engine client"""
        if self.running:
            return
        
        self.running = True
        logger.info(f"Starting engine client: {self.engine_id}")
        
        try:
            await self.sio.connect(self.server_url)
            
            # Keep running until stopped
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Engine client error: {e}")
            self.running = False
            raise
        finally:
            if self.sio.connected:
                await self.sio.disconnect()
    
    async def stop(self):
        """Stop the engine client"""
        self.running = False
        
        if self.sio.connected:
            await self.sio.disconnect()
        
        logger.info(f"Stopped engine client: {self.engine_id}")
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connected and self.sio.connected


# Convenience function for running engine
async def run_workflow_engine(
    engine_id: str = "engine-1",
    server_url: str = "http://localhost:8000",
    max_concurrent_tasks: int = 5
):
    """Run workflow engine as Socket.IO client"""
    engine = SocketIOEngineClient(
        engine_id=engine_id,
        server_url=server_url,
        max_concurrent_tasks=max_concurrent_tasks
    )
    await engine.start()