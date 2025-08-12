"""
Queue Manager Client for Gleitzeit V5

Distributed queue management component that handles task queuing,
priority scheduling, and dependency tracking through pure Socket.IO events.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum
import uuid

from ..base.component import SocketIOComponent
from ..base.config import ComponentConfig

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """Task priority levels"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class QueuedTask:
    """Represents a task in the queue"""
    task_id: str
    workflow_id: str
    task_type: str
    method: str
    parameters: Dict[str, Any]
    dependencies: List[str]
    priority: TaskPriority
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    dependency_results: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.dependency_results is None:
            self.dependency_results = {}


class QueueManagerClient(SocketIOComponent):
    """
    Queue Manager Client for distributed task queue management
    
    Responsibilities:
    - Maintain priority queues for different task types
    - Handle task dependency tracking and resolution
    - Coordinate with DependencyResolver for dependency management
    - Notify ExecutionEngine when tasks are ready for execution
    - Track task states and provide queue statistics
    
    Events Emitted:
    - task_ready_for_execution: When a task has all dependencies satisfied
    - dependency_check_request: Request dependency resolution
    - queue_stats_updated: When queue statistics change
    
    Events Handled:
    - queue_task: Add a new task to the queue
    - task_completed: Mark task as completed and check dependent tasks
    - task_failed: Handle task failure and dependency propagation
    - dependency_resolved: Handle resolved dependency from DependencyResolver
    - get_queue_stats: Return current queue statistics
    """
    
    def __init__(
        self,
        component_id: Optional[str] = None,
        config: Optional[ComponentConfig] = None,
        hub_url: str = "http://localhost:8000"
    ):
        if config is None:
            config = ComponentConfig()
        config.hub_url = hub_url
        
        super().__init__(
            component_type="queue_manager",
            component_id=component_id or f"queue-{uuid.uuid4().hex[:8]}",
            config=config
        )
        
        # Task queues by priority
        self.queues: Dict[TaskPriority, List[QueuedTask]] = {
            priority: [] for priority in TaskPriority
        }
        
        # Task tracking
        self.pending_tasks: Dict[str, QueuedTask] = {}  # task_id -> task
        self.dependency_waiting: Dict[str, Set[str]] = {}  # task_id -> set of dependency_task_ids
        self.completed_tasks: Set[str] = set()
        self.failed_tasks: Set[str] = set()
        
        # Workflow tracking
        self.workflow_tasks: Dict[str, Set[str]] = {}  # workflow_id -> set of task_ids
        
        # Statistics
        self.stats = {
            'tasks_queued': 0,
            'tasks_completed': 0,
            'tasks_failed': 0,
            'tasks_ready_for_execution': 0,
            'workflows_active': 0
        }
        
        logger.info(f"Initialized Queue Manager: {self.component_id}")
    
    def setup_events(self):
        """Setup event handlers for queue management"""
        
        @self.sio.on('queue_task')
        async def handle_queue_task(data):
            """Handle incoming task queueing request"""
            try:
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                task = QueuedTask(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    task_type=data.get('task_type', 'generic'),
                    method=data['method'],
                    parameters=data.get('parameters', {}),
                    dependencies=data.get('dependencies', []),
                    priority=TaskPriority(data.get('priority', TaskPriority.NORMAL.value)),
                    created_at=datetime.utcnow()
                )
                
                await self._queue_task(task, correlation_id)
                
            except Exception as e:
                logger.error(f"Error handling queue_task: {e}")
                await self.emit_with_correlation('task_queue_error', {
                    'task_id': data.get('task_id', 'unknown'),
                    'error': str(e)
                })
        
        @self.sio.on('task_completed')
        async def handle_task_completed(data):
            """Handle task completion notification"""
            try:
                task_id = data['task_id']
                result = data.get('result')
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                await self._handle_task_completion(task_id, result, correlation_id)
                
            except Exception as e:
                logger.error(f"Error handling task_completed: {e}")
        
        @self.sio.on('task_failed')
        async def handle_task_failed(data):
            """Handle task failure notification"""
            try:
                task_id = data['task_id']
                error = data.get('error', 'Unknown error')
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                await self._handle_task_failure(task_id, error, correlation_id)
                
            except Exception as e:
                logger.error(f"Error handling task_failed: {e}")
        
        @self.sio.on('dependency_resolved')
        async def handle_dependency_resolved(data):
            """Handle dependency resolution from DependencyResolver"""
            try:
                task_id = data['dependent_task_id']
                dependency_id = data['dependency_task_id']
                result = data['result']
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                await self._resolve_dependency(task_id, dependency_id, result, correlation_id)
                
            except Exception as e:
                logger.error(f"Error handling dependency_resolved: {e}")
        
        @self.sio.on('get_queue_stats')
        async def handle_get_queue_stats(data):
            """Return current queue statistics"""
            try:
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                stats = self._get_queue_statistics()
                
                await self.emit_with_correlation('queue_stats_response', {
                    'stats': stats,
                    '_response_to': correlation_id
                }, correlation_id)
                
            except Exception as e:
                logger.error(f"Error handling get_queue_stats: {e}")
        
        @self.sio.on('clear_completed_tasks')
        async def handle_clear_completed_tasks(data):
            """Clear completed tasks from tracking"""
            try:
                workflow_id = data.get('workflow_id')
                
                if workflow_id:
                    await self._clear_workflow_tasks(workflow_id)
                else:
                    await self._clear_all_completed_tasks()
                    
                logger.info(f"Cleared completed tasks for workflow: {workflow_id or 'all'}")
                
            except Exception as e:
                logger.error(f"Error clearing completed tasks: {e}")
    
    def get_capabilities(self) -> List[str]:
        """Return list of capabilities this component provides"""
        return ['task_queuing', 'priority_scheduling', 'dependency_tracking', 'workflow_coordination']
    
    async def on_ready(self):
        """Called when component is registered and ready"""
        logger.info(f"Queue Manager {self.component_id} is ready")
    
    async def on_shutdown(self):
        """Called during graceful shutdown for component-specific cleanup"""
        # Clear all pending tasks
        await self._clear_all_completed_tasks()
        logger.info(f"Queue Manager {self.component_id} shutdown cleanup completed")
    
    async def _queue_task(self, task: QueuedTask, correlation_id: str):
        """Queue a task and check if it's ready for execution"""
        
        # Add to pending tasks
        self.pending_tasks[task.task_id] = task
        
        # Track workflow
        if task.workflow_id not in self.workflow_tasks:
            self.workflow_tasks[task.workflow_id] = set()
        self.workflow_tasks[task.workflow_id].add(task.task_id)
        
        # Update statistics
        self.stats['tasks_queued'] += 1
        self.stats['workflows_active'] = len(self.workflow_tasks)
        
        logger.info(f"Queued task {task.task_id} for workflow {task.workflow_id}")
        
        # Check dependencies
        if task.dependencies:
            # Route dependency check request to dependency resolver
            await self.emit_with_correlation('route_event', {
                'target_component_type': 'dependency_resolver',
                'event_name': 'dependency_check_request',
                'event_data': {
                    'task_id': task.task_id,
                    'dependencies': task.dependencies,
                    'workflow_id': task.workflow_id
                }
            }, correlation_id)
            
            # Track pending dependencies
            self.dependency_waiting[task.task_id] = set(task.dependencies)
            
        else:
            # No dependencies, ready for execution
            await self._make_task_ready(task, correlation_id)
    
    async def _make_task_ready(self, task: QueuedTask, correlation_id: str):
        """Mark a task as ready for execution"""
        
        # Add to priority queue
        self.queues[task.priority].append(task)
        
        # Sort queue by created_at (FIFO within priority)
        self.queues[task.priority].sort(key=lambda t: t.created_at)
        
        # Update statistics
        self.stats['tasks_ready_for_execution'] += 1
        
        # Route task ready notification to execution engine
        await self.emit_with_correlation('route_event', {
            'target_component_type': 'execution_engine',
            'event_name': 'task_ready_for_execution',
            'event_data': {
                'task_id': task.task_id,
                'workflow_id': task.workflow_id,
                'task_type': task.task_type,
                'method': task.method,
                'parameters': task.parameters,
                'priority': task.priority.value
            }
        }, correlation_id)
        
        logger.info(f"Task {task.task_id} is ready for execution")
    
    async def _resolve_dependency(
        self, 
        task_id: str, 
        dependency_id: str, 
        result: Any,
        correlation_id: str
    ):
        """Resolve a dependency for a task"""
        
        if task_id not in self.pending_tasks:
            logger.warning(f"Task {task_id} not found in pending tasks")
            return
        
        if task_id not in self.dependency_waiting:
            logger.warning(f"Task {task_id} not waiting for dependencies")
            return
        
        task = self.pending_tasks[task_id]
        waiting_deps = self.dependency_waiting[task_id]
        
        # Remove resolved dependency
        waiting_deps.discard(dependency_id)
        
        # Store dependency result
        task.dependency_results[dependency_id] = result
        
        logger.debug(f"Resolved dependency {dependency_id} for task {task_id}")
        
        # Check if all dependencies are resolved
        if not waiting_deps:
            # All dependencies resolved
            del self.dependency_waiting[task_id]
            await self._make_task_ready(task, correlation_id)
    
    async def _handle_task_completion(self, task_id: str, result: Any, correlation_id: str):
        """Handle task completion and update dependent tasks"""
        
        # Mark as completed
        self.completed_tasks.add(task_id)
        self.stats['tasks_completed'] += 1
        
        # Remove from queues if still there
        for priority, priority_queue in self.queues.items():
            self.queues[priority] = [t for t in priority_queue if t.task_id != task_id]
        
        # Remove from pending
        if task_id in self.pending_tasks:
            task = self.pending_tasks.pop(task_id)
            logger.info(f"Task {task_id} completed successfully")
            
            # Emit completion event for other components
            await self.emit_with_correlation('task_completion_processed', {
                'task_id': task_id,
                'workflow_id': task.workflow_id,
                'result': result
            }, correlation_id)
        
        # Update statistics
        self._update_execution_stats()
    
    async def _handle_task_failure(self, task_id: str, error: str, correlation_id: str):
        """Handle task failure and propagate to dependent tasks"""
        
        # Mark as failed
        self.failed_tasks.add(task_id)
        self.stats['tasks_failed'] += 1
        
        # Remove from queues and pending
        for priority, priority_queue in self.queues.items():
            self.queues[priority] = [t for t in priority_queue if t.task_id != task_id]
        
        if task_id in self.pending_tasks:
            task = self.pending_tasks.pop(task_id)
            logger.error(f"Task {task_id} failed: {error}")
            
            # Emit failure event
            await self.emit_with_correlation('task_failure_processed', {
                'task_id': task_id,
                'workflow_id': task.workflow_id,
                'error': error
            }, correlation_id)
        
        # Remove from dependency waiting
        self.dependency_waiting.pop(task_id, None)
        
        # Update statistics
        self._update_execution_stats()
    
    async def _clear_workflow_tasks(self, workflow_id: str):
        """Clear completed tasks for a specific workflow"""
        if workflow_id in self.workflow_tasks:
            task_ids = self.workflow_tasks[workflow_id].copy()
            
            # Remove completed tasks
            for task_id in task_ids:
                if task_id in self.completed_tasks:
                    self.completed_tasks.discard(task_id)
                    self.workflow_tasks[workflow_id].discard(task_id)
            
            # Remove workflow if no active tasks
            if not self.workflow_tasks[workflow_id]:
                del self.workflow_tasks[workflow_id]
                self.stats['workflows_active'] = len(self.workflow_tasks)
    
    async def _clear_all_completed_tasks(self):
        """Clear all completed task tracking"""
        # Keep only active tasks in workflow tracking
        for workflow_id in list(self.workflow_tasks.keys()):
            active_tasks = set()
            for task_id in self.workflow_tasks[workflow_id]:
                if task_id not in self.completed_tasks and task_id not in self.failed_tasks:
                    active_tasks.add(task_id)
            
            if active_tasks:
                self.workflow_tasks[workflow_id] = active_tasks
            else:
                del self.workflow_tasks[workflow_id]
        
        # Clear completed/failed sets
        self.completed_tasks.clear()
        self.failed_tasks.clear()
        
        self.stats['workflows_active'] = len(self.workflow_tasks)
    
    def _update_execution_stats(self):
        """Update execution-related statistics"""
        total_ready = sum(len(queue) for queue in self.queues.values())
        self.stats['tasks_ready_for_execution'] = total_ready
    
    def _get_queue_statistics(self) -> Dict[str, Any]:
        """Get comprehensive queue statistics"""
        
        queue_lengths = {
            priority.name: len(self.queues[priority])
            for priority in TaskPriority
        }
        
        return {
            **self.stats,
            'queue_lengths_by_priority': queue_lengths,
            'total_pending_tasks': len(self.pending_tasks),
            'tasks_waiting_for_dependencies': len(self.dependency_waiting),
            'active_workflows': list(self.workflow_tasks.keys()),
            'component_uptime_seconds': (
                datetime.utcnow() - self.health_metrics['started_at']
            ).total_seconds()
        }
    
    async def get_health_metrics(self) -> Dict[str, Any]:
        """Get health metrics for heartbeat responses"""
        return {
            'tasks_queued': self.stats['tasks_queued'],
            'tasks_ready': self.stats['tasks_ready_for_execution'],
            'active_workflows': self.stats['workflows_active'],
            'queue_utilization': len(self.pending_tasks) / 1000,  # Normalize to 0-1
            'status': 'healthy'
        }
    


# Convenience function to run the Queue Manager
async def run_queue_manager(
    component_id: Optional[str] = None,
    config: Optional[ComponentConfig] = None,
    hub_url: str = "http://localhost:8000"
):
    """Run a Queue Manager client"""
    
    queue_manager = QueueManagerClient(
        component_id=component_id,
        config=config,
        hub_url=hub_url
    )
    
    await queue_manager.start()


if __name__ == "__main__":
    import sys
    
    # Parse command line arguments
    component_id = sys.argv[1] if len(sys.argv) > 1 else None
    hub_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    
    asyncio.run(run_queue_manager(component_id=component_id, hub_url=hub_url))