"""
Socket.IO-based Workflow Engine Client for Gleitzeit V3

Connects to the central server and manages workflows through server events.
"""

import asyncio
import logging
import re
import socketio
from typing import Dict, List, Optional, Any, Set
from datetime import datetime

from ..events.schemas import EventType, EventSeverity
from .models import Workflow, Task, TaskStatus, WorkflowStatus, TaskParameters

logger = logging.getLogger(__name__)


class WorkflowEngineClient:
    """
    Workflow engine that connects to the central server via Socket.IO.
    
    Features:
    - Connects to central server for coordination
    - Receives provider events from server
    - Manages workflow execution through server communication
    - Handles task assignment based on server-provided provider info
    """
    
    def __init__(
        self,
        engine_id: str = "workflow_engine_01",
        server_url: str = "http://localhost:8000"
    ):
        self.engine_id = engine_id
        self.server_url = server_url
        
        # Socket.IO client
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.registered = False
        
        # Active workflows and tasks
        self.workflows: Dict[str, Workflow] = {}
        self.tasks: Dict[str, Task] = {}
        
        # Provider tracking (updated from server)
        self.providers: Dict[str, Dict[str, Any]] = {}
        
        # Dependency tracking
        self.task_dependencies: Dict[str, Set[str]] = {}
        self.dependent_tasks: Dict[str, Set[str]] = {}
        
        # Assignment tracking
        self.pending_assignments: Set[str] = set()
        
        # Running state
        self._running = False
        
        # Setup Socket.IO handlers
        self._setup_socket_handlers()
        
        logger.info(f"WorkflowEngineClient initialized: {engine_id}")
    
    def _setup_socket_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info(f"🔗 Workflow engine connected to server: {self.server_url}")
            
            # Register with server
            await self.sio.emit('workflow_engine:register', {
                'engine_id': self.engine_id,
                'version': '1.0.0'
            })
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            self.registered = False
            logger.warning(f"🔌 Workflow engine disconnected from server")
        
        @self.sio.on('workflow_engine:registered')
        async def workflow_engine_registered(data):
            self.registered = True
            logger.info(f"✅ Workflow engine registered with server")
        
        @self.sio.on('providers:list')
        async def providers_list(data):
            """Handle initial provider list from server"""
            providers = data.get('providers', [])
            for provider_data in providers:
                provider_id = provider_data.get('provider_id')
                if provider_id:
                    self.providers[provider_id] = provider_data
                    logger.info(f"Provider available: {provider_id} - {provider_data.get('provider_name')}")
        
        @self.sio.on('provider:connected')
        async def provider_connected(data):
            """Handle provider connection notification from server"""
            provider_id = data.get('provider_id')
            logger.info(f"📡 Provider connected: {provider_id}")
            
            # Store provider info
            self.providers[provider_id] = {
                'provider_id': provider_id,
                'name': data.get('provider_name'),
                'type': data.get('provider_type'),
                'supported_functions': data.get('supported_functions', []),
                'status': 'available',
                'connected_at': data.get('connected_at')
            }
            
            # Check if we have pending tasks that can now be assigned
            await self._check_pending_assignments()
        
        @self.sio.on('provider:disconnected')
        async def provider_disconnected(data):
            """Handle provider disconnection notification from server"""
            provider_id = data.get('provider_id')
            logger.info(f"📡 Provider disconnected: {provider_id}")
            
            # Remove provider
            if provider_id in self.providers:
                del self.providers[provider_id]
        
        @self.sio.on('provider:status_changed')
        async def provider_status_changed(data):
            """Handle provider status change from server"""
            provider_id = data.get('provider_id')
            new_status = data.get('status')
            
            if provider_id in self.providers:
                self.providers[provider_id]['status'] = new_status
                logger.info(f"Provider {provider_id} status changed to: {new_status}")
                
                # If provider became available, check pending assignments
                if new_status == 'available':
                    await self._check_pending_assignments()
        
        @self.sio.on('task:completed')
        async def task_completed(data):
            """Handle task completion notification from server"""
            task_id = data.get('task_id')
            success = data.get('success', False)
            
            if task_id in self.tasks:
                task = self.tasks[task_id]
                
                if success:
                    result = data.get('result')
                    await self._handle_task_completion(task, result)
                else:
                    error = data.get('error', 'Unknown error')
                    await self._handle_task_failure(task, error)
        
        @self.sio.on('workflow:execute')
        async def workflow_execute(data):
            """Handle workflow execution from queue"""
            await self._handle_queued_workflow(data)
        
        @self.sio.on('error')
        async def error(data):
            logger.error(f"Server error: {data}")
    
    async def start(self):
        """Start the workflow engine client"""
        if self._running:
            return
        
        # Connect to central server
        try:
            await self.sio.connect(self.server_url)
            
            # Wait for registration
            max_wait = 10
            wait_time = 0
            while not self.registered and wait_time < max_wait:
                await asyncio.sleep(0.5)
                wait_time += 0.5
            
            if not self.registered:
                raise Exception("Failed to register with server")
            
            self._running = True
            logger.info(f"🚀 WorkflowEngineClient started")
            
        except Exception as e:
            logger.error(f"Failed to start workflow engine: {e}")
            raise
    
    async def stop(self):
        """Stop the workflow engine client"""
        if not self._running:
            return
        
        self._running = False
        
        # Disconnect from server
        if self.connected:
            await self.sio.disconnect()
        
        logger.info(f"🛑 WorkflowEngineClient stopped")
    
    async def _handle_queued_workflow(self, data: Dict[str, Any]):
        """Handle workflow execution from server queue"""
        workflow_data = data.get('workflow')
        if not workflow_data:
            logger.error("Received workflow:execute without workflow data")
            return
        
        try:
            # Reconstruct workflow from server data
            workflow = Workflow(
                id=workflow_data.get('id'),
                name=workflow_data.get('name', 'Unknown Workflow'),
                description=workflow_data.get('description', ''),
                priority=workflow_data.get('priority', 'normal')
            )
            
            # Reconstruct tasks
            for task_data in workflow_data.get('tasks', []):
                task = Task(
                    id=task_data.get('id'),
                    name=task_data.get('name', 'Unknown Task'),
                    priority=task_data.get('priority', 'normal'),
                    parameters=TaskParameters(data=task_data.get('parameters', {})),
                    dependencies=task_data.get('dependencies', [])
                )
                workflow.add_task(task)
            
            logger.info(f"📋 Executing queued workflow: {workflow.name} ({workflow.id})")
            
            # Execute the workflow
            await self._execute_workflow(workflow)
            
        except Exception as e:
            logger.error(f"Failed to handle queued workflow: {e}")
            # Report failure back to server
            if self.connected and workflow_data.get('id'):
                await self.sio.emit('workflow:completed', {
                    'workflow_id': workflow_data['id'],
                    'status': 'failed',
                    'error': str(e)
                })
    
    async def _execute_workflow(self, workflow: Workflow):
        """Execute a workflow (internal method)"""
        # Store workflow
        self.workflows[workflow.id] = workflow
        
        # Process all tasks
        for task in workflow.tasks:
            self.tasks[task.id] = task
            
            # Setup dependency tracking
            if task.dependencies:
                self.task_dependencies[task.id] = set(task.dependencies)
                for dep_id in task.dependencies:
                    if dep_id not in self.dependent_tasks:
                        self.dependent_tasks[dep_id] = set()
                    self.dependent_tasks[dep_id].add(task.id)
        
        # Update workflow status
        workflow.status = WorkflowStatus.RUNNING
        
        # Start executing tasks with no dependencies
        for task in workflow.tasks:
            if not task.dependencies:
                await self._mark_task_ready(task)
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit a workflow for execution"""
        if not self._running:
            raise RuntimeError("Workflow engine not running")
        
        # Store workflow
        self.workflows[workflow.id] = workflow
        
        # Process all tasks
        for task in workflow.tasks:
            self.tasks[task.id] = task
            
            # Setup dependency tracking
            if task.dependencies:
                self.task_dependencies[task.id] = set(task.dependencies)
                for dep_id in task.dependencies:
                    if dep_id not in self.dependent_tasks:
                        self.dependent_tasks[dep_id] = set()
                    self.dependent_tasks[dep_id].add(task.id)
        
        # Update workflow status
        workflow.status = WorkflowStatus.RUNNING
        
        # Emit workflow started event to server
        if self.connected:
            await self.sio.emit('workflow:started', {
                'workflow_id': workflow.id,
                'workflow_name': workflow.name,
                'task_count': len(workflow.tasks)
            })
        
        logger.info(f"📋 Workflow submitted: {workflow.name} ({workflow.id})")
        
        # Start executing tasks with no dependencies
        for task in workflow.tasks:
            if not task.dependencies:
                await self._mark_task_ready(task)
        
        return workflow.id
    
    async def _mark_task_ready(self, task: Task):
        """Mark a task as ready and attempt assignment"""
        task.status = TaskStatus.READY
        
        # Substitute parameters
        await self._substitute_task_parameters(task)
        
        # Add to pending assignments
        self.pending_assignments.add(task.id)
        
        # Try to assign immediately
        await self._try_assign_task(task)
    
    async def _try_assign_task(self, task: Task):
        """Try to assign a task to an available provider"""
        # Find suitable provider based on task function
        function_name = task.parameters.get("function")
        if not function_name:
            logger.error(f"Task {task.id} missing function parameter")
            await self._handle_task_failure(task, "Missing function parameter")
            return
        
        # Find available providers that support this function
        suitable_providers = [
            p for p in self.providers.values()
            if function_name in p.get('supported_functions', [])
            and p.get('status') == 'available'
        ]
        
        if not suitable_providers:
            logger.info(f"No suitable providers for task {task.id} (function: {function_name})")
            return
        
        # Pick the first available provider
        provider = suitable_providers[0]
        
        # Remove from pending
        self.pending_assignments.discard(task.id)
        
        # Update task status
        task.status = TaskStatus.ASSIGNED
        task.target_provider_id = provider['provider_id']
        
        # Send task to server for execution
        await self._send_task_for_execution(task, provider['provider_id'])
    
    async def _send_task_for_execution(self, task: Task, provider_id: str):
        """Send task to server for execution by provider"""
        if not self.connected:
            logger.error("Not connected to server, cannot send task")
            return
        
        task.status = TaskStatus.RUNNING
        
        # Send to server
        await self.sio.emit('task:execute', {
            'task_id': task.id,
            'provider_id': provider_id,
            'task_type': 'function',  # All tasks are function-based now
            'parameters': task.parameters.data,
            'workflow_id': task.workflow_id
        })
        
        logger.info(f"📤 Task {task.id} sent to provider {provider_id}")
    
    async def _handle_task_completion(self, task: Task, result: Any):
        """Handle successful task completion"""
        task.status = TaskStatus.COMPLETED
        
        # Store result in workflow
        if task.workflow_id in self.workflows:
            workflow = self.workflows[task.workflow_id]
            workflow.task_results[task.id] = result
            if task.id not in workflow.completed_tasks:
                workflow.completed_tasks.append(task.id)
        
        logger.info(f"✅ Task completed: {task.id}")
        
        # Check dependent tasks
        await self._check_dependent_tasks(task.id)
        
        # Check if workflow is complete
        await self._check_workflow_completion(task.workflow_id)
    
    async def _handle_task_failure(self, task: Task, error: str):
        """Handle task failure"""
        task.status = TaskStatus.FAILED
        
        # Update workflow
        if task.workflow_id in self.workflows:
            workflow = self.workflows[task.workflow_id]
            if task.id not in workflow.failed_tasks:
                workflow.failed_tasks.append(task.id)
        
        logger.error(f"❌ Task failed: {task.id} - {error}")
        
        # Check if workflow should fail
        await self._check_workflow_completion(task.workflow_id)
    
    async def _check_dependent_tasks(self, completed_task_id: str):
        """Check if dependent tasks can now run"""
        if completed_task_id not in self.dependent_tasks:
            return
        
        for dependent_task_id in self.dependent_tasks[completed_task_id]:
            if dependent_task_id not in self.tasks:
                continue
            
            task = self.tasks[dependent_task_id]
            
            # Check if all dependencies are complete
            if task.dependencies:
                all_complete = all(
                    dep_id in self.tasks and 
                    self.tasks[dep_id].status == TaskStatus.COMPLETED
                    for dep_id in task.dependencies
                )
                
                if all_complete:
                    await self._mark_task_ready(task)
    
    async def _check_workflow_completion(self, workflow_id: str):
        """Check if workflow is complete"""
        if workflow_id not in self.workflows:
            return
        
        workflow = self.workflows[workflow_id]
        
        # Check if all tasks are done (completed or failed)
        all_done = all(
            task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
            for task in workflow.tasks
        )
        
        if all_done:
            if workflow.failed_tasks:
                workflow.status = WorkflowStatus.FAILED
                logger.info(f"❌ Workflow failed: {workflow.name}")
            else:
                workflow.status = WorkflowStatus.COMPLETED
                logger.info(f"✅ Workflow completed: {workflow.name}")
            
            # Notify server
            if self.connected:
                await self.sio.emit('workflow:completed', {
                    'workflow_id': workflow.id,
                    'status': workflow.status.value,
                    'completed_tasks': len(workflow.completed_tasks),
                    'failed_tasks': len(workflow.failed_tasks)
                })
    
    async def _check_pending_assignments(self):
        """Check if any pending tasks can now be assigned"""
        for task_id in list(self.pending_assignments):
            if task_id in self.tasks:
                task = self.tasks[task_id]
                await self._try_assign_task(task)
    
    async def _substitute_task_parameters(self, task: Task):
        """Substitute parameters from previous task results"""
        if not task.workflow_id or task.workflow_id not in self.workflows:
            return
        
        workflow = self.workflows[task.workflow_id]
        
        # Pattern to match ${task_<id>_result}
        pattern = r'\$\{task_([a-f0-9\-]+)_result\}'
        
        def substitute(match):
            task_id = match.group(1)
            if task_id in workflow.task_results:
                result = workflow.task_results[task_id]
                # Try to simplify the result for substitution
                if isinstance(result, dict):
                    # If it's an MCP result with content, extract just the text
                    if 'content' in result and isinstance(result['content'], list):
                        texts = []
                        for item in result['content']:
                            if isinstance(item, dict) and 'text' in item:
                                texts.append(item['text'])
                        return ' '.join(texts) if texts else str(result)
                    # If it has a simple structure, convert to JSON
                    elif len(str(result)) < 1000:
                        import json
                        return json.dumps(result, indent=2)
                    else:
                        # Too long, just return a summary
                        return f"[Result too long: {len(str(result))} chars]"
                return str(result) if result else ""
            return match.group(0)
        
        # Substitute in all parameter values
        for key, value in task.parameters.data.items():
            if isinstance(value, str):
                task.parameters.data[key] = re.sub(pattern, substitute, value)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get workflow engine statistics"""
        total_tasks = len(self.tasks)
        running_tasks = sum(1 for t in self.tasks.values() if t.status == TaskStatus.RUNNING)
        ready_tasks = sum(1 for t in self.tasks.values() if t.status == TaskStatus.READY)
        
        return {
            'engine_id': self.engine_id,
            'connected': self.connected,
            'registered': self.registered,
            'total_workflows': len(self.workflows),
            'total_tasks': total_tasks,
            'running_tasks': running_tasks,
            'ready_tasks': ready_tasks,
            'pending_assignments': len(self.pending_assignments),
            'available_providers': len([p for p in self.providers.values() if p.get('status') == 'available'])
        }