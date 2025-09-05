"""
Task Orchestrator for Gleitzeit

Lightweight coordinator that orchestrates task execution by delegating
to specialized managers and services.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.core.task_executor import TaskExecutor
from gleitzeit.core.dependency_manager import UnifiedDependencyManager
from gleitzeit.core.parameter_resolver import ParameterResolver
from gleitzeit.core.errors import (
    TaskError, TaskExecutionError, WorkflowError, WorkflowValidationError,
    PersistenceError, QueueError
)
from gleitzeit.task_queue import QueueManager
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import EventType, GleitzeitEvent

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    """
    Lightweight task orchestration coordinator.
    
    This orchestrator acts as a thin coordination layer that:
    - Pulls tasks from the queue
    - Checks dependencies
    - Routes to TaskExecutor for execution
    - Handles task completion and workflow progression
    
    It delegates specialized work to:
    - TaskExecutor: Pure task execution
    - UnifiedDependencyManager: Dependency resolution
    - QueueManager: Task queuing
    - RetryManager: Retry handling (via events)
    - WorkflowManager: Workflow lifecycle (via events)
    """
    
    def __init__(
        self,
        queue_manager: QueueManager,
        dependency_manager: UnifiedDependencyManager,
        task_executor: TaskExecutor,  # Required, not optional
        persistence: Optional[PersistenceBackend] = None,
        event_bus: Optional[EventBus] = None,
        max_concurrent_tasks: int = 10
    ):
        """
        Initialize TaskOrchestrator.
        
        Args:
            queue_manager: Queue manager for task dequeuing
            dependency_manager: Unified dependency manager
            task_executor: Task executor (required)
            persistence: Persistence backend
            event_bus: Event bus for coordination
            max_concurrent_tasks: Maximum concurrent task executions
        """
        if not task_executor:
            raise ValueError("TaskOrchestrator requires a task_executor")
            
        self.queue_manager = queue_manager
        self.dependency_manager = dependency_manager
        self.task_executor = task_executor
        self.persistence = persistence
        self.event_bus = event_bus
        self.max_concurrent_tasks = max_concurrent_tasks
        
        # Track active tasks
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._running = False
        
        # Setup event handlers
        self._setup_event_handlers()
        
        logger.info(f"Initialized TaskOrchestrator with max_concurrent_tasks={max_concurrent_tasks}")
        
    def _setup_event_handlers(self):
        """Setup event subscriptions."""
        if not self.event_bus:
            return
            
        # Listen for workflow submission to enqueue initial tasks
        self.event_bus.register(EventType.WORKFLOW_SUBMITTED, self._handle_workflow_submitted)
        
        # Listen for task ready events from queue
        self.event_bus.register(EventType.TASK_READY, self._handle_task_ready)
        
        # Listen for task completion to check workflow progress
        self.event_bus.register(EventType.TASK_COMPLETED, self._handle_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._handle_task_failed)
        
        logger.debug("TaskOrchestrator event handlers registered")
        
    async def start(self):
        """Start the orchestrator."""
        self._running = True
        logger.info("TaskOrchestrator started (event-driven mode, no polling)")
        
    async def stop(self):
        """Stop the orchestrator."""
        self._running = False
        
        # Wait for active tasks
        if self._active_tasks:
            logger.info(f"Waiting for {len(self._active_tasks)} active tasks to complete")
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
            
        logger.info("TaskOrchestrator stopped")
        
                
    async def _schedule_task(self, task: Task):
        """Schedule a task for execution."""
        # Check dependencies one more time
        if task.dependencies:
            ready_tasks = await self.dependency_manager.get_ready_tasks(
                task.workflow_id,
                completed_tasks=await self._get_completed_task_ids(task.workflow_id)
            )
            
            if task.id not in [t.id for t in ready_tasks]:
                logger.debug(f"Task {task.id} dependencies not yet met, requeuing")
                await self.queue_manager.enqueue_task(task)
                return
                
        # Create execution coroutine
        task_coro = self._execute_task_with_semaphore(task)
        
        # Schedule as asyncio task
        asyncio_task = asyncio.create_task(task_coro)
        self._active_tasks[task.id] = asyncio_task
        
        # Add cleanup callback
        asyncio_task.add_done_callback(
            lambda t: self._active_tasks.pop(task.id, None)
        )
        
        logger.info(f"Scheduled task {task.id} for execution")
        
    async def _execute_task_with_semaphore(self, task: Task):
        """Execute task with semaphore control."""
        async with self._semaphore:
            try:
                # Execute through TaskExecutor
                result = await self.task_executor.execute_task(task)
                
                # Task executor handles events, we just log
                logger.info(f"Task {task.id} execution completed with status {result.status}")
                
                # Check for workflow progression
                if task.workflow_id:
                    await self._check_workflow_progression(task.workflow_id)
                    
            except Exception as e:
                logger.error(f"Error executing task {task.id}: {e}")
                
    async def _check_workflow_progression(self, workflow_id: str):
        """Check if workflow has more tasks ready after completion."""
        try:
            # Get workflow
            workflow = await self.persistence.get_workflow(workflow_id) if self.persistence else None
            if not workflow:
                return
                
            # Get both completed and failed tasks
            completed_tasks, failed_tasks = await self._get_finished_task_ids(workflow_id)
            
            # Check if workflow is complete (all tasks are either completed or failed)
            workflow_task_ids = {task.id for task in workflow.tasks}
            finished_tasks = completed_tasks | failed_tasks
            logger.info(f"Workflow {workflow_id}: completed={completed_tasks}, failed={failed_tasks}, all={workflow_task_ids}")
            
            # If any task has failed, check if it blocks other tasks
            if failed_tasks:
                initial_failed_count = len(failed_tasks)
                await self._mark_blocked_tasks_as_failed(workflow_id, failed_tasks)
                # Re-fetch to get the updated failed task IDs after cascade
                completed_tasks, failed_tasks = await self._get_finished_task_ids(workflow_id)
                finished_tasks = completed_tasks | failed_tasks
                logger.info(f"After cascade: completed={completed_tasks}, failed={failed_tasks}, all={workflow_task_ids}")
                
                # Mark workflow as failed immediately when any task fails permanently
                if workflow.status not in [WorkflowStatus.FAILED, WorkflowStatus.COMPLETED]:
                    workflow.status = WorkflowStatus.FAILED
                    workflow.completed_at = datetime.utcnow()
                    await self.persistence.save_workflow(workflow)
                    
                    # Emit workflow failed event
                    if self.event_bus:
                        await self.event_bus.emit(GleitzeitEvent(
                            event_type=EventType.WORKFLOW_FAILED,
                            data={"workflow_id": workflow_id}
                        ))
                        logger.info(f"Workflow {workflow_id} marked as FAILED due to permanent task failures")
                
            if finished_tasks == workflow_task_ids:
                # All tasks finished - workflow is done!
                if failed_tasks:
                    # Workflow should already be marked as failed above
                    if workflow.status != WorkflowStatus.FAILED:
                        workflow.status = WorkflowStatus.FAILED
                else:
                    # All tasks completed successfully
                    workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.utcnow()
                
                # Aggregate task results
                task_results = []
                if self.persistence:
                    for task_id in completed_tasks:
                        result = await self.persistence.get_task_result(task_id)
                        if result:
                            task_results.append({
                                "task_id": task_id,
                                "status": result.status,
                                "output": result.result,  # TaskResult uses 'result' not 'output'
                                "error": result.error
                            })
                    
                    await self.persistence.save_workflow(workflow)
                
                # Emit appropriate workflow event based on status
                if self.event_bus:
                    if workflow.status == WorkflowStatus.FAILED:
                        await self.event_bus.emit(GleitzeitEvent(
                            event_type=EventType.WORKFLOW_FAILED,
                            data={"workflow_id": workflow_id}
                        ))
                        logger.info(f"Workflow {workflow_id} failed with {len(failed_tasks)} failed tasks")
                    else:
                        await self.event_bus.emit(GleitzeitEvent(
                            event_type=EventType.WORKFLOW_COMPLETED,
                            data={"workflow_id": workflow_id}
                        ))
                        logger.info(f"Workflow {workflow_id} completed successfully with {len(task_results)} task results")
                return
            
            # Get newly ready tasks (only pass completed tasks, not failed ones)
            # This ensures tasks with failed dependencies won't be marked as ready
            ready_tasks = await self.dependency_manager.get_ready_tasks(
                workflow_id, 
                completed_tasks  # Only pass successfully completed tasks
            )
            
            # Track already queued tasks to prevent duplicates
            already_queued_key = f"queued_tasks:{workflow_id}"
            if self.persistence:
                already_queued = await self.persistence.get(already_queued_key)
                if already_queued:
                    # Handle both string and list formats
                    if isinstance(already_queued, list):
                        already_queued = set(already_queued)
                    else:
                        already_queued = set(json.loads(already_queued))
                else:
                    already_queued = set()
            else:
                already_queued = set()
            
            # Enqueue ready tasks
            for task in ready_tasks:
                # Check if task is already active or queued
                if task.id not in self._active_tasks and task.id not in already_queued:
                    await self.queue_manager.enqueue_task(task)
                    logger.info(f"Enqueued newly ready task {task.id} from workflow {workflow_id}")
                    
                    # Track that this task has been queued
                    already_queued.add(task.id)
                    if self.persistence:
                        await self.persistence.set(already_queued_key, json.dumps(list(already_queued)))
                    
                    # Emit TASK_READY event so the task gets executed
                    if self.event_bus:
                        await self.event_bus.emit(GleitzeitEvent(
                            event_type=EventType.TASK_READY,
                            data={"task_id": task.id}
                        ))
                        logger.debug(f"Emitted TASK_READY for {task.id}")
                else:
                    logger.debug(f"Task {task.id} already queued or active, skipping")
                    
        except Exception as e:
            logger.error(f"Error checking workflow progression for {workflow_id}: {e}")
            
    async def _get_completed_task_ids(self, workflow_id: str) -> set:
        """Get IDs of completed tasks in a workflow."""
        if not self.persistence or not workflow_id:
            return set()
            
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return set()
            
        completed = set()
        for task in workflow.tasks:
            # Check task result in persistence (more reliable than task.status)
            task_result = await self.persistence.get_task_result(task.id)
            if task_result:
                logger.info(f"Task {task.id} result status: {task_result.status}")
                if task_result.status == TaskStatus.COMPLETED:
                    completed.add(task.id)
            else:
                logger.info(f"No task result found for {task.id}, checking task status: {task.status}")
                if task.status == TaskStatus.COMPLETED:
                    # Fallback to task status if no result yet
                    completed.add(task.id)
                
        return completed
        
    async def _get_finished_task_ids(self, workflow_id: str) -> tuple[set, set]:
        """Get IDs of both completed and failed tasks in a workflow.
        
        Returns:
            Tuple of (completed_task_ids, failed_task_ids)
        """
        if not self.persistence or not workflow_id:
            return set(), set()
            
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return set(), set()
            
        completed = set()
        failed = set()
        
        for task in workflow.tasks:
            # Check task result in persistence (more reliable than task.status)
            task_result = await self.persistence.get_task_result(task.id)
            if task_result:
                if task_result.status == TaskStatus.COMPLETED:
                    completed.add(task.id)
                elif task_result.status == TaskStatus.FAILED:
                    failed.add(task.id)
            else:
                # Fallback to task status if no result yet
                if task.status == TaskStatus.COMPLETED:
                    completed.add(task.id)
                elif task.status == TaskStatus.FAILED:
                    failed.add(task.id)
                
        return completed, failed
        
    async def _mark_blocked_tasks_as_failed(self, workflow_id: str, failed_task_ids: set):
        """Mark tasks as failed if their dependencies have failed.
        
        This is the core of the stateless cascade failure mechanism.
        Called whenever we check workflow progression and find failed tasks.
        """
        if not self.persistence:
            return
            
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return
            
        # For each task, check if any of its dependencies have failed
        for task in workflow.tasks:
            # Skip if task is already finished
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                continue
                
            # Check if any dependency has failed
            if task.dependencies:
                failed_deps = set(task.dependencies) & failed_task_ids
                if failed_deps:
                    # This task is blocked by failed dependencies
                    logger.info(f"Task {task.id} blocked by failed dependencies: {failed_deps}")
                    
                    # Mark the task as failed
                    task.status = TaskStatus.FAILED
                    task.completed_at = datetime.utcnow()
                    await self.persistence.save_task(task)
                    
                    # Create a task result for the failed dependent
                    from ..core.models import TaskResult
                    task_result = TaskResult(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        result=None,
                        error=f"Dependencies failed: {', '.join(failed_deps)}",
                        started_at=task.started_at or datetime.utcnow(),
                        completed_at=datetime.utcnow(),
                        metadata={"failed_dependencies": list(failed_deps)}
                    )
                    await self.persistence.save_task_result(task_result)
                    
                    # Add this task to the failed set for recursive checking
                    failed_task_ids.add(task.id)
                    
                    logger.info(f"Task {task.id} marked as failed due to dependency failures")
                    
                    # Emit task failed event to trigger stateless progression check
                    if self.event_bus:
                        await self.event_bus.emit(GleitzeitEvent(
                            event_type=EventType.TASK_FAILED,
                            data={"task_id": task.id}
                        ))
        
        
    async def _handle_workflow_submitted(self, event: GleitzeitEvent):
        """Handle workflow submitted event - enqueue initial tasks."""
        workflow_id = event.data.get("workflow_id")
        if not workflow_id:
            return
        
        logger.debug(f"Processing WORKFLOW_SUBMITTED for {workflow_id}")
        
        # Trigger initial task enqueuing by checking workflow progression
        # This will enqueue tasks with no dependencies
        await self._check_workflow_progression(workflow_id)
    
    async def _handle_task_ready(self, event: GleitzeitEvent):
        """Handle task ready event from queue - execute the task."""
        task_id = event.data.get("task_id")
        if not task_id:
            return
            
        logger.debug(f"Task {task_id} marked as ready, scheduling for execution")
        
        # Check if we have capacity for more tasks
        if len(self._active_tasks) >= self.max_concurrent_tasks:
            logger.debug(f"At max capacity ({self.max_concurrent_tasks}), task {task_id} will wait")
            # Re-emit the event with a small delay to try again
            if self.event_bus:
                await asyncio.sleep(0.1)
                await self.event_bus.emit(event)
            return
        
        # Get the task from persistence
        if not self.persistence:
            logger.error(f"No persistence configured, cannot retrieve task {task_id}")
            return
            
        task = await self.persistence.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found in persistence")
            return
        
        # Schedule the task for execution
        await self._schedule_task(task)
        
    async def _handle_task_completed(self, event: GleitzeitEvent):
        """Handle task completion event."""
        task_id = event.data.get("task_id")
        
        # Get workflow_id from persistence
        if self.persistence and task_id:
            task = await self.persistence.get_task(task_id)
            if task and task.workflow_id:
                # Check for workflow progression
                await self._check_workflow_progression(task.workflow_id)
            
    async def _handle_task_failed(self, event: GleitzeitEvent):
        """Handle task failure event."""
        task_id = event.data.get("task_id")
        
        # Remove from active tasks if present
        if task_id in self._active_tasks:
            del self._active_tasks[task_id]
        
        # Get task from persistence to determine workflow and retryability
        if self.persistence and task_id:
            task = await self.persistence.get_task(task_id)
            if task and task.workflow_id:
                # Get task result to check if failure is permanent
                task_result = await self.persistence.get_task_result(task_id)
                if task_result:
                    # Check metadata for retryability info
                    metadata = task_result.metadata or {}
                    is_retryable = metadata.get("is_retryable", True)
                    is_permanent = metadata.get("is_permanent", False)
                    
                    # Check if this failure affects workflow completion
                    # Failure is permanent if explicitly marked as permanent or marked as non-retryable
                    if is_permanent or not is_retryable:
                        await self._check_workflow_failure(task.workflow_id, task_id)
                    
                    # RetryManager will handle retry logic via events
                    logger.debug(f"Task {task_id} failed (retryable={is_retryable})")
                else:
                    # No task result yet, check workflow progression anyway
                    await self._check_workflow_progression(task.workflow_id)
    
    async def _check_workflow_failure(self, workflow_id: str, failed_task_id: str):
        """Check if a task failure should fail the entire workflow and dependent tasks."""
        try:
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                return
            
            # Check if any tasks depend on this failed task
            has_dependents = False
            blocked_tasks = []
            for task in workflow.tasks:
                if failed_task_id in (task.dependencies or []):
                    has_dependents = True
                    blocked_tasks.append(task.id)
            
            if has_dependents:
                # Mark all dependent tasks as failed
                for blocked_task_id in blocked_tasks:
                    blocked_task = await self.persistence.get_task(blocked_task_id)
                    if blocked_task and blocked_task.status in [TaskStatus.PENDING, TaskStatus.QUEUED]:
                        # Mark dependent task as failed
                        blocked_task.status = TaskStatus.FAILED
                        blocked_task.completed_at = datetime.utcnow()
                        await self.persistence.save_task(blocked_task)
                        
                        # Create a task result for the failed dependent
                        from ..core.models import TaskResult
                        task_result = TaskResult(
                            task_id=blocked_task_id,
                            status=TaskStatus.FAILED,
                            result=None,
                            error=f"Dependency task {failed_task_id} failed",
                            started_at=blocked_task.started_at or datetime.utcnow(),
                            completed_at=datetime.utcnow(),
                            metadata={"failed_dependency": failed_task_id}
                        )
                        await self.persistence.save_task_result(task_result)
                        
                        # Recursively check if this task failure blocks other tasks
                        await self._check_workflow_failure(workflow_id, blocked_task_id)
                        
                        logger.info(f"Task {blocked_task_id} marked as failed due to dependency {failed_task_id} failure")
                
                # Workflow has blocked tasks - mark as failed
                workflow.status = WorkflowStatus.FAILED
                await self.persistence.save_workflow(workflow)
                
                # Emit workflow failed event
                if self.event_bus:
                    await self.event_bus.emit(GleitzeitEvent(
                        event_type=EventType.WORKFLOW_FAILED,
                        data={"workflow_id": workflow_id}
                    ))
                
                logger.warning(f"Workflow {workflow_id} failed due to task {failed_task_id} failure blocking {blocked_tasks}")
                
        except Exception as e:
            logger.error(f"Error checking workflow failure for {workflow_id}: {e}")
        
    async def execute_single_task(self, task: Task) -> Any:
        """
        Execute a single task directly (for testing or direct execution).
        
        Args:
            task: Task to execute
            
        Returns:
            Task execution result
        """
        return await self.task_executor.execute_task(task)
        
    async def submit_workflow(self, workflow: Workflow):
        """
        Submit a workflow for execution.
        
        Args:
            workflow: Workflow to submit
        """
        # Validate workflow
        await self.dependency_manager.validate_workflow(workflow)
        
        # Persist workflow and tasks
        if self.persistence:
            # Set workflow_id on all tasks BEFORE saving workflow
            for task in workflow.tasks:
                task.workflow_id = workflow.id
            
            # Now save workflow (with tasks that have workflow_id set)
            await self.persistence.save_workflow(workflow)
            
            # Also save tasks individually
            for task in workflow.tasks:
                await self.persistence.save_task(task)
            
        logger.info(f"Submitted workflow {workflow.id} with {len(workflow.tasks)} tasks")
        
        # Emit workflow submitted event - handler will enqueue initial tasks
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.WORKFLOW_SUBMITTED,
                data={"workflow_id": workflow.id}
            ))
            
    def get_statistics(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        return {
            "active_tasks": len(self._active_tasks),
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "running": self._running,
            "queue_stats": self.queue_manager.get_statistics() if hasattr(self.queue_manager, 'get_statistics') else {},
            "dependency_stats": self.dependency_manager.get_statistics()
        }