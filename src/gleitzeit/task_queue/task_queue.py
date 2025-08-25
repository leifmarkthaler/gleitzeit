"""
Task Queue implementation for Gleitzeit V4

Priority-based task queuing with dependency management and workflow orchestration.
"""

import asyncio
import heapq
import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime, timedelta
from enum import IntEnum
from dataclasses import dataclass, field

from gleitzeit.core.models import Task, Workflow, TaskStatus, Priority, WorkflowStatus
from gleitzeit.persistence.base import PersistenceBackend, InMemoryBackend

logger = logging.getLogger(__name__)


class QueuePriority(IntEnum):
    """Numeric priority values for heap sorting"""
    URGENT = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class QueuedTask:
    """Task wrapper for priority queue with ordering"""
    priority: int
    queued_at: datetime
    task: Task
    
    def __lt__(self, other):
        """Define ordering for heapq"""
        # Primary: priority (lower number = higher priority)
        if self.priority != other.priority:
            return self.priority < other.priority
        
        # Secondary: queued time (earlier = higher priority)
        return self.queued_at < other.queued_at


class TaskQueue:
    """
    Priority-based task queue using persistence backend
    
    Features:
    - Priority-based ordering (urgent > high > normal > low)
    - FIFO within same priority level
    - Dependency checking before task dequeue
    - Workflow-aware task management
    - All operations use persistence backend directly
    """
    
    def __init__(self, name: str = "default", persistence: Optional[PersistenceBackend] = None, event_bus: Optional[Any] = None):
        self.name = name
        self.persistence = persistence or InMemoryBackend()
        self.event_bus = event_bus
        
        # No more in-memory structures - everything goes through persistence
        self._lock = asyncio.Lock()
        
        # Statistics (these could also be persisted)
        self.total_enqueued = 0
        self.total_dequeued = 0
        self.created_at = datetime.utcnow()
        self._initialized = False
        
        # Monitoring task
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info(f"Initialized TaskQueue: {name} (persistence-backed)")
    
    async def initialize(self) -> None:
        """Initialize persistence backend"""
        if self._initialized:
            return
        
        await self.persistence.initialize()
        self._initialized = True
        
        logger.info(f"TaskQueue {self.name} initialized with persistence backend")
    
    
    async def enqueue(self, task: Task) -> None:
        """
        Add a task to the queue - just saves to persistence with QUEUED status
        
        Args:
            task: Task to enqueue
        """
        async with self._lock:
            # Check if task already exists and is queued
            existing_task = await self.persistence.get_task(task.id)
            if existing_task and existing_task.status == TaskStatus.QUEUED:
                logger.warning(f"Task {task.id} already queued, skipping")
                return
            
            # Check if dependencies are satisfied before enqueueing
            if task.dependencies:
                if not await self._are_dependencies_satisfied(task):
                    # Dependencies not satisfied, save as PENDING
                    task.status = TaskStatus.PENDING
                    await self.persistence.save_task(task)
                    logger.info(f"Task {task.id} has unsatisfied dependencies {task.dependencies}, saved as pending")
                    return
            
            # Save to persistence with QUEUED status
            task.status = TaskStatus.QUEUED
            await self.persistence.save_task(task)
            
            self.total_enqueued += 1
            logger.debug(f"Enqueued task {task.id} with priority {task.priority} to persistence")
    
    
    async def dequeue(self, check_dependencies: bool = True) -> Optional[Task]:
        """
        Get the next available task from persistence
        
        Args:
            check_dependencies: Whether to check task dependencies
            
        Returns:
            Next available task or None if no tasks ready
        """
        async with self._lock:
            # Get all queued tasks from persistence
            result = await self.persistence.list_tasks(status=TaskStatus.QUEUED)
            if isinstance(result, dict):
                queued_tasks = result.get('tasks', [])
            else:
                queued_tasks = result if isinstance(result, list) else []
            
            if not queued_tasks:
                return None
            
            # Sort by priority and creation time
            priority_order = {
                Priority.URGENT: 0,
                Priority.HIGH: 1, 
                Priority.NORMAL: 2,
                Priority.LOW: 3
            }
            
            queued_tasks.sort(key=lambda t: (
                priority_order.get(t.priority, 2),
                t.created_at or datetime.utcnow()
            ))
            
            # Find first task with satisfied dependencies
            for task in queued_tasks:
                # Double-check the task is actually QUEUED (avoid race conditions)
                fresh_task = await self.persistence.get_task(task.id)
                if not fresh_task or fresh_task.status != TaskStatus.QUEUED:
                    logger.debug(f"Task {task.id} no longer QUEUED (status: {fresh_task.status if fresh_task else 'not found'}), skipping")
                    continue
                
                if check_dependencies and fresh_task.dependencies:
                    if not await self._are_dependencies_satisfied(fresh_task):
                        continue
                
                # Check if task already has a result (avoid re-executing completed tasks)
                existing_result = await self.persistence.get_task_result(fresh_task.id)
                if existing_result:
                    # Allow retry if the result status is RETRY_PENDING
                    if existing_result.status == TaskStatus.RETRY_PENDING:
                        logger.debug(f"Task {fresh_task.id} has retry_pending result, allowing re-execution")
                    else:
                        logger.warning(f"Task {fresh_task.id} already has result (status: {existing_result.status}) but was QUEUED, skipping")
                        # Fix the inconsistent state
                        fresh_task.status = TaskStatus.COMPLETED
                        await self.persistence.save_task(fresh_task)
                        continue
                
                # Found available task - update its status to EXECUTING
                fresh_task.status = TaskStatus.EXECUTING
                fresh_task.started_at = datetime.utcnow()
                await self.persistence.save_task(fresh_task)
                
                self.total_dequeued += 1
                logger.debug(f"Dequeued task {fresh_task.id} from persistence")
                return fresh_task
            
            return None
    
    async def _are_dependencies_satisfied(self, task: Task) -> bool:
        """Check if all task dependencies are completed"""
        if not task.dependencies:
            return True
        
        # Check each dependency in persistence
        for dep_id in task.dependencies:
            dep_task = await self.persistence.get_task(dep_id)
            if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                # If dependency belongs to same workflow, check if it's completed
                if task.workflow_id and dep_task and dep_task.workflow_id == task.workflow_id:
                    if dep_task.status != TaskStatus.COMPLETED:
                        return False
                else:
                    return False
        
        return True
    
    async def remove_task(self, task_id: str) -> bool:
        """
        Remove a task from the queue by marking it as cancelled
        
        Args:
            task_id: ID of task to remove
            
        Returns:
            True if task was removed, False if not found
        """
        async with self._lock:
            task = await self.persistence.get_task(task_id)
            if not task or task.status not in [TaskStatus.QUEUED, TaskStatus.PENDING]:
                return False
            
            # Mark as cancelled in persistence
            task.status = TaskStatus.CANCELLED
            await self.persistence.save_task(task)
            
            logger.debug(f"Removed task {task_id} from queue (marked as cancelled)")
            return True
    
    async def mark_task_completed(self, task_id: str) -> None:
        """Handle workflow completion and dependency resolution when a task completes.
        Note: Task status should already be set to COMPLETED by ExecutionEngine."""
        async with self._lock:
            # Get task for workflow processing (don't modify task status here)
            task = await self.persistence.get_task(task_id)
            if task:
                # Check if task is actually completed (should be set by ExecutionEngine)
                if task.status == TaskStatus.COMPLETED:
                    logger.debug(f"Task {task_id} confirmed as completed, processing workflow dependencies")
                else:
                    logger.warning(f"Task {task_id} not marked as completed by ExecutionEngine (status: {task.status})")
                
                # Check if any tasks from the same workflow can now be enqueued
                if task.workflow_id:
                    await self._check_workflow_completion(task.workflow_id)
                    await self._enqueue_ready_workflow_tasks(task.workflow_id)
            else:
                logger.warning(f"Could not find task {task_id} in persistence for workflow processing")
    
    async def mark_task_failed(self, task_id: str) -> None:
        """Mark a task as failed"""
        async with self._lock:
            # Update task status in persistence
            task = await self.persistence.get_task(task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                await self.persistence.save_task(task)
                
                # Check if workflow is complete (or failed)
                if task.workflow_id:
                    await self._check_workflow_completion(task.workflow_id)
            
            logger.debug(f"Marked task {task_id} as failed")
    
    async def _enqueue_ready_workflow_tasks(self, workflow_id: str) -> None:
        """Check if any workflow tasks can now be enqueued after a task completion"""
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return
        
        # Check each task in the workflow
        for task in workflow.tasks:
            # Get fresh task status from persistence
            fresh_task = await self.persistence.get_task(task.id)
            if not fresh_task:
                continue
                
            # Skip if not pending
            if fresh_task.status != TaskStatus.PENDING:
                continue
            
            # Check if task already has a result (avoid re-enqueueing completed tasks)
            existing_result = await self.persistence.get_task_result(fresh_task.id)
            if existing_result:
                logger.debug(f"Task {fresh_task.id} already has result, not re-enqueueing")
                continue
            
            # Check if all dependencies are satisfied
            if await self._are_dependencies_satisfied(fresh_task):
                # Dependencies are satisfied, update to queued and emit TASK_READY event
                logger.info(f"Task {fresh_task.id} dependencies satisfied, enqueueing")
                fresh_task.status = TaskStatus.QUEUED
                await self.persistence.save_task(fresh_task)
                
                # Emit TASK_READY event for ExecutionEngine to pick up
                if self.event_bus:
                    from ..core.events import EventType, create_custom_event
                    ready_event = create_custom_event(
                        event_type=EventType.TASK_READY,
                        data={
                            'task_id': fresh_task.id,
                            'workflow_id': fresh_task.workflow_id,
                            'protocol': fresh_task.protocol,
                            'method': fresh_task.method
                        },
                        source="task_queue"
                    )
                    await self.event_bus.emit(ready_event)
                    logger.info(f"Emitted TASK_READY event for {fresh_task.id}")
    
    async def _check_workflow_completion(self, workflow_id: str) -> None:
        """Check if a workflow is complete and update its status"""
        logger.debug(f"Checking workflow completion for {workflow_id}")
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            logger.warning(f"Workflow {workflow_id} not found in persistence")
            return
        
        # Check status of all tasks in the workflow
        all_completed = True
        has_failed = False
        completed_tasks = []
        failed_tasks = []
        task_results = {}
        
        for task in workflow.tasks:
            # Force a fresh read from the database to get latest status
            fresh_task = await self.persistence.get_task(task.id)
            if not fresh_task:
                continue
                
            if fresh_task.status == TaskStatus.COMPLETED:
                completed_tasks.append(task.id)
                # Get task result for the workflow completion event
                task_result = await self.persistence.get_task_result(task.id)
                if task_result:
                    task_results[task.id] = {
                        "status": "completed",
                        "result": task_result.result,
                        "error": task_result.error
                    }
            elif fresh_task.status == TaskStatus.FAILED:
                failed_tasks.append(task.id)
                has_failed = True
                all_completed = False
                # Get task result for failed task
                task_result = await self.persistence.get_task_result(task.id)
                if task_result:
                    task_results[task.id] = {
                        "status": "failed",
                        "result": task_result.result,
                        "error": task_result.error
                    }
            elif fresh_task.status not in [TaskStatus.CANCELLED]:
                # Task is still pending/queued/executing
                all_completed = False
        
        # Update workflow task lists
        workflow.completed_tasks = completed_tasks
        workflow.failed_tasks = failed_tasks
        
        # Check if all tasks are done
        logger.debug(f"Workflow {workflow_id}: {len(completed_tasks)} completed, {len(failed_tasks)} failed, {len(workflow.tasks)} total")
        if all_completed or (has_failed and len(completed_tasks) + len(failed_tasks) == len(workflow.tasks)):
            # Workflow is complete
            if has_failed:
                workflow.status = WorkflowStatus.FAILED
            else:
                workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = datetime.utcnow()
            
            logger.info(f"Workflow {workflow_id} completed with status: {workflow.status}")
            
            # Persist the updated workflow
            await self.persistence.save_workflow(workflow)
            
            # Emit workflow completion event with results
            if self.event_bus:
                from ..core.events import EventType, EventSeverity, GleitzeitEvent
                workflow_completed_event = GleitzeitEvent(
                    event_type=EventType.WORKFLOW_COMPLETED,
                    severity=EventSeverity.INFO,
                    data={
                        "workflow_id": workflow_id,
                        "workflow_name": workflow.name,
                        "status": workflow.status.value if hasattr(workflow.status, 'value') else str(workflow.status),
                        "completed_tasks": completed_tasks,
                        "failed_tasks": failed_tasks,
                        "task_results": task_results,
                        "duration": (workflow.completed_at - workflow.started_at).total_seconds() if workflow.started_at else 0
                    },
                    source="queue_manager",
                    tags={"component": "queue"}
                )
                await self.event_bus.emit(workflow_completed_event)
                logger.info(f"Emitted WORKFLOW_COMPLETED event for workflow {workflow_id}")
    
    async def get_ready_tasks(self, limit: Optional[int] = None) -> List[Task]:
        """
        Get list of tasks that are ready to execute (dependencies satisfied)
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of ready tasks
        """
        async with self._lock:
            # Get all queued tasks from persistence
            result = await self.persistence.list_tasks(status=TaskStatus.QUEUED)
            if isinstance(result, dict):
                queued_tasks = result.get('tasks', [])
            else:
                queued_tasks = result if isinstance(result, list) else []
            
            ready_tasks = []
            for task in queued_tasks:
                if limit and len(ready_tasks) >= limit:
                    break
                    
                if await self._are_dependencies_satisfied(task):
                    ready_tasks.append(task)
            
            return ready_tasks
    
    async def size(self) -> int:
        """Get current queue size"""
        result = await self.persistence.list_tasks(status=TaskStatus.QUEUED)
        if isinstance(result, dict):
            return result.get('total', 0)
        return len(result) if isinstance(result, list) else 0
    
    async def is_empty(self) -> bool:
        """Check if queue is empty"""
        return await self.size() == 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        async with self._lock:
            # Get counts by status from persistence
            queued_count = await self.size()
            
            completed_result = await self.persistence.list_tasks(status=TaskStatus.COMPLETED)
            completed_count = completed_result.get('total', 0) if isinstance(completed_result, dict) else len(completed_result)
            
            failed_result = await self.persistence.list_tasks(status=TaskStatus.FAILED)
            failed_count = failed_result.get('total', 0) if isinstance(failed_result, dict) else len(failed_result)
            
            return {
                "name": self.name,
                "current_size": queued_count,
                "total_enqueued": self.total_enqueued,
                "total_dequeued": self.total_dequeued,
                "completed_tasks": completed_count,
                "failed_tasks": failed_count,
                "created_at": self.created_at.isoformat()
            }
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a specific workflow"""
        async with self._lock:
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                return []
            return workflow.tasks
    
    async def clear(self) -> int:
        """Clear all queued tasks by marking them as cancelled"""
        async with self._lock:
            # Get all queued tasks
            result = await self.persistence.list_tasks(status=TaskStatus.QUEUED)
            if isinstance(result, dict):
                queued_tasks = result.get('tasks', [])
            else:
                queued_tasks = result if isinstance(result, list) else []
            
            # Mark each as cancelled
            for task in queued_tasks:
                task.status = TaskStatus.CANCELLED
                await self.persistence.save_task(task)
            
            cleared_count = len(queued_tasks)
            logger.info(f"Cleared {cleared_count} tasks from queue {self.name}")
            return cleared_count

    async def start_monitoring(self, interval: int = 5) -> None:
        """Start monitoring for pending tasks that can be enqueued
        
        Args:
            interval: Check interval in seconds
        """
        if self._running:
            logger.warning("Monitoring already running")
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))
        logger.info(f"Started queue monitoring with {interval}s interval")
    
    async def stop_monitoring(self) -> None:
        """Stop the monitoring task"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("Stopped queue monitoring")
    
    async def _monitor_loop(self, interval: int) -> None:
        """Monitoring loop that checks for pending tasks with satisfied dependencies"""
        while self._running:
            try:
                await self._check_and_enqueue_ready_tasks()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(interval)
    
    async def _check_and_enqueue_ready_tasks(self) -> None:
        """Check for pending tasks that have satisfied dependencies and enqueue them"""
        async with self._lock:
            # Get all pending tasks from persistence
            result = await self.persistence.list_tasks(status=TaskStatus.PENDING)
            if isinstance(result, dict):
                pending_tasks = result.get('tasks', [])
            else:
                pending_tasks = result if isinstance(result, list) else []
            
            if not pending_tasks:
                return
            
            # Check each pending task
            for task in pending_tasks:
                # Get fresh task status to avoid race conditions
                fresh_task = await self.persistence.get_task(task.id)
                if not fresh_task:
                    continue
                
                # Skip if task is not actually pending anymore
                if fresh_task.status != TaskStatus.PENDING:
                    logger.debug(f"Task {task.id} no longer pending (status: {fresh_task.status}), skipping")
                    continue
                
                # Check if task has already been processed (has a result)
                existing_result = await self.persistence.get_task_result(task.id)
                if existing_result:
                    logger.debug(f"Task {task.id} already has result (status: {existing_result.status}), skipping")
                    continue
                
                # Skip tasks without dependencies (they should already be queued)
                if not fresh_task.dependencies:
                    # Only enqueue if truly pending
                    if fresh_task.status == TaskStatus.PENDING:
                        fresh_task.status = TaskStatus.QUEUED
                        await self.persistence.save_task(fresh_task)
                        logger.info(f"Enqueued pending task {fresh_task.id} with no dependencies")
                    continue
                
                # Check if dependencies are satisfied
                if await self._are_dependencies_satisfied(fresh_task):
                    # Dependencies satisfied - change status to QUEUED
                    fresh_task.status = TaskStatus.QUEUED
                    await self.persistence.save_task(fresh_task)
                    logger.info(f"Enqueued task {fresh_task.id} - dependencies satisfied")
                    
                    # Emit TASK_READY event for ExecutionEngine to pick up
                    if self.event_bus:
                        from ..core.events import EventType, create_custom_event
                        ready_event = create_custom_event(
                            event_type=EventType.TASK_READY,
                            data={
                                'task_id': fresh_task.id,
                                'workflow_id': fresh_task.workflow_id,
                                'protocol': fresh_task.protocol,
                                'method': fresh_task.method
                            },
                            source="task_queue"
                        )
                        await self.event_bus.emit(ready_event)
                        logger.info(f"Emitted TASK_READY event for {fresh_task.id}")


class QueueManager:
    """
    Manager for multiple task queues with routing and load balancing
    """
    
    def __init__(self, persistence: Optional[PersistenceBackend] = None, event_bus: Optional[Any] = None):
        self.persistence = persistence
        self.event_bus = event_bus
        self.queues: Dict[str, TaskQueue] = {}
        self.default_queue_name = "default"
        self._stats_lock = asyncio.Lock()
        
        # Create default queue with persistence and event bus
        self.queues[self.default_queue_name] = TaskQueue(self.default_queue_name, persistence=self.persistence, event_bus=self.event_bus)
        
        # Register event handlers if event bus is available
        if self.event_bus:
            self._register_event_handlers()
        
        logger.info("Initialized QueueManager with persistence backend")
    
    def _register_event_handlers(self):
        """Register event handlers for task and workflow management"""
        from ..core.events import EventType
        
        # Task lifecycle events
        self.event_bus.register(EventType.TASK_SUBMITTED, self._on_task_submitted)
        
        # Retry events
        self.event_bus.register(EventType.TASK_READY_FOR_RETRY, self._on_task_ready_for_retry)
        
        # Workflow events
        self.event_bus.register(EventType.WORKFLOW_SUBMITTED, self._on_workflow_submitted)
        
        logger.debug("QueueManager registered event handlers")
    
    async def _on_task_submitted(self, event):
        """Handle task submission - enqueue if dependencies satisfied"""
        from ..core.events import EventType, create_custom_event
        from ..core.models import TaskStatus
        
        task_id = event.data.get('task_id')
        if not task_id:
            return
        
        logger.debug(f"Processing TASK_SUBMITTED event for {task_id}")
        
        # Get task from persistence
        task = await self.persistence.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found in persistence")
            return
        
        # Check if dependencies are satisfied
        if await self._are_task_dependencies_satisfied(task):
            # Enqueue immediately and emit TASK_READY event
            await self._enqueue_task_with_ready_event(task)
        else:
            # Mark as pending (waiting for dependencies)
            task.status = TaskStatus.PENDING
            await self.persistence.save_task(task)
            logger.info(f"Task {task_id} waiting for dependencies")
    
    async def _on_task_ready_for_retry(self, event):
        """Handle task ready for retry - enqueue it"""
        task_id = event.data.get('task_id')
        if not task_id:
            return
        
        logger.debug(f"Processing TASK_READY_FOR_RETRY event for {task_id}")
        
        # Get task from persistence
        task = await self.persistence.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for retry")
            return
        
        # Enqueue for retry execution
        await self._enqueue_task_with_ready_event(task)
        logger.info(f"Task {task_id} ready for retry attempt #{event.data.get('attempt_number', 1)}")
    
    async def _on_workflow_submitted(self, event):
        """Handle workflow submission - enqueue initial tasks"""
        workflow_id = event.data.get('workflow_id')
        if not workflow_id:
            return
        
        logger.debug(f"Processing WORKFLOW_SUBMITTED event for {workflow_id}")
        
        # Get workflow from persistence
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            logger.warning(f"Workflow {workflow_id} not found in persistence")
            return
        
        # Check each task for immediate enqueueing
        for task in workflow.tasks:
            if not task.dependencies:
                # Tasks with no dependencies can be enqueued immediately
                await self._enqueue_task_with_ready_event(task)
    
    async def _enqueue_task_with_ready_event(self, task):
        """Enqueue task and emit TASK_READY event"""
        from ..core.events import EventType, create_custom_event
        from ..core.models import TaskStatus
        
        # Update task status to QUEUED
        task.status = TaskStatus.QUEUED
        await self.persistence.save_task(task)
        logger.info(f"Enqueued task {task.id}")
        
        # Emit TASK_READY event for ExecutionEngine
        ready_event = create_custom_event(
            event_type=EventType.TASK_READY,
            data={
                'task_id': task.id,
                'workflow_id': task.workflow_id,
                'protocol': task.protocol,
                'method': task.method
            },
            source="queue_manager"
        )
        await self.event_bus.emit(ready_event)
        logger.info(f"Emitted TASK_READY event for {task.id}")
    
    async def _are_task_dependencies_satisfied(self, task):
        """Check if all task dependencies are completed"""
        from ..core.models import TaskStatus
        
        if not task.dependencies:
            return True
        
        for dep_id in task.dependencies:
            dep_result = await self.persistence.get_task_result(dep_id)
            if not dep_result or dep_result.status != TaskStatus.COMPLETED:
                return False
        
        return True
    
    async def initialize(self) -> None:
        """Initialize all queues and start monitoring"""
        for queue in self.queues.values():
            await queue.initialize()
            # TEMPORARILY DISABLE monitoring to fix race condition
            # await queue.start_monitoring(interval=2)  # Check every 2 seconds
        logger.info(f"QueueManager initialized with {len(self.queues)} queue(s) - monitoring DISABLED to fix race condition")
    
    def create_queue(self, name: str) -> TaskQueue:
        """Create a new task queue"""
        if name in self.queues:
            raise ValueError(f"Queue {name} already exists")
        
        queue = TaskQueue(name, persistence=self.persistence)
        self.queues[name] = queue
        
        logger.info(f"Created queue: {name}")
        return queue
    
    def get_queue(self, name: str) -> Optional[TaskQueue]:
        """Get a queue by name"""
        return self.queues.get(name)
    
    def get_default_queue(self) -> TaskQueue:
        """Get the default queue"""
        return self.queues[self.default_queue_name]
    
    async def enqueue_task(self, task: Task, queue_name: Optional[str] = None) -> None:
        """
        Enqueue a task to a specific queue or the default queue
        
        Args:
            task: Task to enqueue
            queue_name: Target queue name (uses default if None)
        """
        target_queue_name = queue_name or self.default_queue_name
        queue = self.get_queue(target_queue_name)
        
        if not queue:
            raise ValueError(f"Queue not found: {target_queue_name}")
        
        await queue.enqueue(task)
    
    async def dequeue_next_task(self, queue_names: Optional[List[str]] = None) -> Optional[Task]:
        """
        Get the next available task from specified queues (or all queues)
        
        Args:
            queue_names: List of queue names to check (all queues if None)
            
        Returns:
            Next available task with highest priority across all queues
        """
        target_queues = queue_names or list(self.queues.keys())
        available_tasks = []
        
        # Collect available tasks from all target queues
        for queue_name in target_queues:
            queue = self.get_queue(queue_name)
            if queue:
                ready_tasks = await queue.get_ready_tasks(limit=5)  # Get top 5 from each
                for task in ready_tasks:
                    available_tasks.append((task, queue_name))
        
        if not available_tasks:
            return None
        
        # Sort by priority and queue time
        available_tasks.sort(key=lambda x: (
            QueuePriority[x[0].priority.upper()].value,
            x[0].created_at
        ))
        
        # Dequeue the highest priority task
        best_task, best_queue_name = available_tasks[0]
        queue = self.get_queue(best_queue_name)
        
        if queue:
            # Try to dequeue the specific task
            dequeued_task = await queue.dequeue()
            if dequeued_task and dequeued_task.id == best_task.id:
                return dequeued_task
        
        return None
    
    async def mark_task_completed(self, task_id: str, queue_name: Optional[str] = None) -> None:
        """Mark a task as completed across all queues or specific queue"""
        if queue_name:
            queue = self.get_queue(queue_name)
            if queue:
                await queue.mark_task_completed(task_id)
        else:
            # Mark in all queues
            for queue in self.queues.values():
                await queue.mark_task_completed(task_id)
    
    async def mark_task_failed(self, task_id: str, queue_name: Optional[str] = None) -> None:
        """Mark a task as failed across all queues or specific queue"""
        if queue_name:
            queue = self.get_queue(queue_name)
            if queue:
                await queue.mark_task_failed(task_id)
        else:
            # Mark in all queues
            for queue in self.queues.values():
                await queue.mark_task_failed(task_id)
    
    async def get_global_stats(self) -> Dict[str, Any]:
        """Get statistics for all queues"""
        async with self._stats_lock:
            queue_stats = {}
            total_size = 0
            total_enqueued = 0
            total_dequeued = 0
            
            for name, queue in self.queues.items():
                stats = await queue.get_stats()
                queue_stats[name] = stats
                total_size += stats["current_size"]
                total_enqueued += stats["total_enqueued"]
                total_dequeued += stats["total_dequeued"]
            
            return {
                "total_queues": len(self.queues),
                "total_size": total_size,
                "total_enqueued": total_enqueued,
                "total_dequeued": total_dequeued,
                "queue_details": queue_stats
            }
    
    async def get_queue_length(self) -> int:
        """Get total number of queued tasks across all queues"""
        total = 0
        for queue in self.queues.values():
            total += await queue.size()
        return total
    
    async def shutdown(self) -> None:
        """Shutdown all queues and stop monitoring"""
        total_cleared = 0
        
        for queue in self.queues.values():
            # Stop monitoring first
            await queue.stop_monitoring()
            cleared = await queue.clear()
            total_cleared += cleared
        
        logger.info(f"QueueManager shutdown complete, cleared {total_cleared} tasks")