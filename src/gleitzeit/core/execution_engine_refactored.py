"""
Execution Engine for Gleitzeit V4 - REFACTORED

Central coordinator that orchestrates task execution by routing tasks from
the queue to protocol providers and managing workflow state progression.

This version uses ONLY the persistence backend for state management.
No in-memory structures for state tracking.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any, Callable, Union, TYPE_CHECKING
from datetime import datetime, timedelta
from enum import Enum

from gleitzeit.core.models import Task, TaskStatus, TaskResult, Workflow, WorkflowStatus, RetryConfig
from gleitzeit.core.errors import (
    GleitzeitError, TaskError, TaskTimeoutError, InvalidParameterError,
    TaskExecutionError, WorkflowError, ProviderNotFoundError, ErrorCode,
    is_retryable_error, create_error_from_exception
)
from gleitzeit.core.events import (
    EventType, GleitzeitEvent, create_workflow_started_event,
    create_workflow_completed_event, create_workflow_failed_event,
    create_task_started_event, create_task_completed_event,
    create_task_failed_event
)
from gleitzeit.task_queue.task_queue import QueueManager
from gleitzeit.providers.base import ProviderRegistry
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.scheduler import EventScheduler
from gleitzeit.core.retry_manager import RetryManager
from gleitzeit.core.dependency_tracker import DependencyTracker

if TYPE_CHECKING:
    from gleitzeit.providers.base import ProtocolProvider

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """Execution modes for the engine"""
    BATCH = "batch"  # Process all queued tasks then stop
    CONTINUOUS = "continuous"  # Keep running and processing tasks
    EVENT_DRIVEN = "event_driven"  # Respond to events and process tasks


class ExecutionStats:
    """Statistics tracking for execution engine"""
    def __init__(self):
        self.tasks_processed = 0
        self.tasks_succeeded = 0
        self.tasks_failed = 0
        self.workflows_processed = 0
        self.workflows_succeeded = 0
        self.workflows_failed = 0
        self.average_task_duration = 0.0
        self.total_execution_time = 0.0


class ExecutionEngine:
    """
    Core execution engine that processes tasks from the queue.
    
    ALL state is managed through the persistence backend.
    No in-memory state tracking.
    """
    
    def __init__(
        self,
        queue_manager: QueueManager,
        provider_registry: ProviderRegistry,
        persistence: Optional[PersistenceBackend] = None,
        scheduler: Optional[EventScheduler] = None,
        max_concurrent_tasks: int = 5,
        task_timeout: int = 300
    ):
        """
        Initialize the execution engine.
        
        Args:
            queue_manager: Queue manager for task queuing
            provider_registry: Registry of protocol providers
            persistence: Persistence backend for state management
            scheduler: Event scheduler for timed events
            max_concurrent_tasks: Maximum concurrent task executions
            task_timeout: Default task timeout in seconds
        """
        self.queue_manager = queue_manager
        self.provider_registry = provider_registry
        self.persistence = persistence
        self.scheduler = scheduler
        self.max_concurrent_tasks = max_concurrent_tasks
        self.task_timeout = task_timeout
        
        # Initialize retry manager with persistence backend
        self.retry_manager = RetryManager(
            queue_manager=queue_manager,
            persistence=persistence,
            scheduler=self.scheduler
        )
        
        # State management - ONLY track currently executing task IDs
        # All actual state is in persistence
        self.running = False
        self.executing_task_ids: Set[str] = set()
        
        # Execution tracking
        self.stats = ExecutionStats()
        self.start_time: Optional[datetime] = None
        
        # Event handlers
        self.event_handlers: Dict[str, List[Callable]] = {}
        
        # Concurrency control
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._shutdown_event = asyncio.Event()
        
        # Dependency tracking for idempotent submissions
        self.dependency_tracker = DependencyTracker()
        
        logger.info(f"Initialized ExecutionEngine with max_concurrent_tasks={max_concurrent_tasks}")
    
    def add_event_handler(self, event_type: str, handler: Callable) -> None:
        """Add event handler for specific event type"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
    
    async def emit_event(self, event: Union[GleitzeitEvent, str], data: Optional[Dict[str, Any]] = None) -> None:
        """Emit structured event to all registered handlers"""
        if isinstance(event, str):
            # Legacy string event type
            event_type = event
            event_data = data or {}
        else:
            # Structured GleitzeitEvent
            event_type = event.event_type
            event_data = event.to_dict()
        
        # Emit to registered handlers
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event_type, event_data)
                    else:
                        handler(event_type, event_data)
                except Exception as e:
                    logger.error(f"Error in event handler for {event_type}: {e}")
    
    async def emit_structured_event(self, event: GleitzeitEvent) -> None:
        """Emit a structured event"""
        await self.emit_event(event)
    
    async def start(self, mode: ExecutionMode = ExecutionMode.CONTINUOUS) -> None:
        """Start the execution engine"""
        if self.running:
            logger.warning("Execution engine is already running")
            return
        
        self.running = True
        self.start_time = datetime.utcnow()
        self._execution_mode = mode
        
        # Start retry manager
        await self.retry_manager.start()
        logger.info("Retry manager monitoring started")
        
        # Start scheduler if available
        if self.scheduler:
            await self.scheduler.start()
        
        logger.info(f"Started ExecutionEngine in {mode} mode")
        
        # Start appropriate execution mode
        if mode == ExecutionMode.EVENT_DRIVEN:
            await self._start_event_driven_mode()
        elif mode == ExecutionMode.CONTINUOUS:
            await self._start_continuous_mode()
        elif mode == ExecutionMode.BATCH:
            await self._process_batch()
    
    async def stop(self) -> None:
        """Stop the execution engine"""
        if not self.running:
            return
        
        logger.info("Stopping execution engine...")
        self.running = False
        
        # Wait for active tasks to complete
        if self.executing_task_ids:
            logger.info(f"Waiting for {len(self.executing_task_ids)} active tasks to complete...")
            while self.executing_task_ids:
                await asyncio.sleep(0.5)
        
        # Stop retry manager
        await self.retry_manager.stop()
        
        # Stop scheduler
        if self.scheduler:
            await self.scheduler.stop()
        
        # Calculate total execution time
        if self.start_time:
            self.stats.total_execution_time = (datetime.utcnow() - self.start_time).total_seconds()
        
        logger.info(f"Execution engine stopped. Processed {self.stats.tasks_processed} tasks")
    
    async def _start_event_driven_mode(self) -> None:
        """Start event-driven execution mode"""
        logger.info("Starting event-driven execution mode")
        
        # Process any already queued tasks
        while len(self.executing_task_ids) < self.max_concurrent_tasks:
            task = await self.queue_manager.dequeue_next_task()
            if not task:
                break
            asyncio.create_task(self._execute_task_with_cleanup(task))
        
        logger.info("ExecutionEngine will respond to events and check for queued tasks periodically")
        
        # Periodically check for queued tasks
        while self.running:
            await asyncio.sleep(2)  # Check every 2 seconds
            
            # Process available tasks up to concurrency limit
            while len(self.executing_task_ids) < self.max_concurrent_tasks:
                task = await self.queue_manager.dequeue_next_task()
                if not task:
                    break
                asyncio.create_task(self._execute_task_with_cleanup(task))
            
            logger.debug(f"Event-driven processing: {len(self.executing_task_ids)}/{self.max_concurrent_tasks} active tasks")
    
    async def _start_continuous_mode(self) -> None:
        """Start continuous execution mode"""
        logger.info("Starting continuous execution mode")
        
        while self.running:
            # Wait for available capacity
            while len(self.executing_task_ids) >= self.max_concurrent_tasks:
                await asyncio.sleep(0.1)
            
            # Get next task
            task = await self.queue_manager.dequeue_next_task()
            if task:
                asyncio.create_task(self._execute_task_with_cleanup(task))
            else:
                # No tasks available, wait before checking again
                await asyncio.sleep(1)
    
    async def _process_batch(self) -> None:
        """Process all currently queued tasks"""
        logger.info("Processing batch of queued tasks")
        
        tasks_to_process = []
        while True:
            task = await self.queue_manager.dequeue_next_task()
            if not task:
                break
            tasks_to_process.append(task)
        
        if not tasks_to_process:
            logger.info("No tasks to process")
            return
        
        logger.info(f"Processing batch of {len(tasks_to_process)} tasks")
        
        # Process tasks with concurrency limit
        for task in tasks_to_process:
            while len(self.executing_task_ids) >= self.max_concurrent_tasks:
                await asyncio.sleep(0.1)
            asyncio.create_task(self._execute_task_with_cleanup(task))
        
        # Wait for all tasks to complete
        while self.executing_task_ids:
            await asyncio.sleep(0.5)
        
        logger.info("Batch processing complete")
    
    async def _execute_task_with_cleanup(self, task: Task) -> TaskResult:
        """Execute task with cleanup"""
        try:
            # Check if task already has a result in persistence
            if self.persistence:
                existing_result = await self.persistence.get_task_result(task.id)
                if existing_result:
                    logger.info(f"Task {task.id} already has a result, skipping execution")
                    return existing_result
            
            # Execute the task
            result = await self._execute_task(task)
            
            # Handle the result and check workflow completion
            if result.status == TaskStatus.COMPLETED:
                # Check workflow completion if needed
                if task.workflow_id:
                    await self._check_workflow_completion(task.workflow_id)
            
            return result
            
        except Exception as exc:
            logger.error(f"Error executing task {task.id}: {exc}")
            
            # Create error result
            error_message = str(exc)
            error_type = type(exc).__name__
            
            task_result = TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.FAILED,
                error=error_message,
                started_at=task.started_at or datetime.utcnow(),
                completed_at=datetime.utcnow(),
                metadata={"execution_engine": True, "error_type": error_type}
            )
            
            # Store in persistence
            if self.persistence:
                await self.persistence.save_task_result(task_result)
            
            return task_result
        finally:
            # Cleanup tracking
            self.executing_task_ids.discard(task.id)
    
    async def _execute_task(self, task: Task) -> TaskResult:
        """Execute a single task"""
        async with self.semaphore:
            task_start_time = datetime.utcnow()
            self.executing_task_ids.add(task.id)
            
            try:
                # Update task status to EXECUTING
                task.status = TaskStatus.EXECUTING
                task.started_at = task_start_time
                
                # Persist the updated task status
                if self.persistence:
                    await self.persistence.save_task(task)
                
                # Update workflow status if needed
                if task.workflow_id and self.persistence:
                    workflow = await self.persistence.get_workflow(task.workflow_id)
                    if workflow and workflow.status == WorkflowStatus.PENDING:
                        workflow.status = WorkflowStatus.RUNNING
                        workflow.started_at = task_start_time
                        await self.persistence.save_workflow(workflow)
                
                # Increment retry count
                current_attempt = await self.retry_manager.increment_retry_count(task.id)
                
                # Emit task started event
                task_event = create_task_started_event(
                    task_id=task.id,
                    task_name=task.name,
                    protocol=task.protocol,
                    method=task.method,
                    workflow_id=task.workflow_id,
                    source="execution_engine"
                )
                await self.emit_structured_event(task_event)
                
                logger.info(f"Executing task {task.id} ({task.protocol}/{task.method})")
                
                # Perform parameter substitution if needed
                resolved_params = await self._resolve_task_parameters(task)
                
                # Route task to appropriate provider
                provider_result = await self._route_task_to_provider(task, resolved_params)
                
                # Create TaskResult
                if isinstance(provider_result, TaskResult):
                    task_result = provider_result
                else:
                    task_result = TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.COMPLETED,
                        result=provider_result,
                        started_at=task_start_time,
                        completed_at=datetime.utcnow(),
                        metadata={"execution_engine": True}
                    )
                
                # Update task status
                task.status = TaskStatus.COMPLETED
                task.completed_at = task_result.completed_at
                
                # Persist IMMEDIATELY
                if self.persistence:
                    await self.persistence.save_task(task)
                    await self.persistence.save_task_result(task_result)
                    
                    # Update workflow if needed
                    if task.workflow_id:
                        workflow = await self.persistence.get_workflow(task.workflow_id)
                        if workflow:
                            if task.id not in workflow.completed_tasks:
                                workflow.completed_tasks.append(task.id)
                            await self.persistence.save_workflow(workflow)
                
                # Mark as completed in queue
                await self.queue_manager.mark_task_completed(task.id)
                
                # Update stats
                self.stats.tasks_processed += 1
                self.stats.tasks_succeeded += 1
                
                # Emit task completed event
                duration = (task_result.completed_at - task_start_time).total_seconds()
                task_completed_event = create_task_completed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    duration=duration,
                    result_size=len(str(task_result.result)) if task_result.result else 0,
                    source="execution_engine"
                )
                await self.emit_structured_event(task_completed_event)
                
                logger.info(f"Task {task.id} completed successfully in {duration:.3f}s")
                return task_result
                
            except Exception as e:
                # Handle task failure
                error_message = str(e)
                
                # Emit task failed event
                failed_event = create_task_failed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    error_message=error_message,
                    error_type=type(e).__name__,
                    is_retryable=is_retryable_error(e) if isinstance(e, GleitzeitError) else True,
                    source="execution_engine"
                )
                await self.emit_structured_event(failed_event)
                
                # Let retry manager handle retry logic
                retry_scheduled = await self.retry_manager.schedule_retry(task, error_message)
                
                if retry_scheduled:
                    logger.info(f"Task {task.id} scheduled for retry")
                    task_result = TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.RETRY_PENDING,
                        error=error_message,
                        started_at=task_start_time,
                        completed_at=datetime.utcnow(),
                        metadata={"retry_scheduled": True}
                    )
                else:
                    # Final failure
                    task.status = TaskStatus.FAILED
                    task.completed_at = datetime.utcnow()
                    task.error_message = error_message
                    
                    task_result = TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.FAILED,
                        error=error_message,
                        started_at=task_start_time,
                        completed_at=task.completed_at,
                        metadata={"final_failure": True}
                    )
                
                # Persist the failed task
                if self.persistence:
                    await self.persistence.save_task(task)
                    await self.persistence.save_task_result(task_result)
                    
                    # Update workflow if needed
                    if task.workflow_id:
                        workflow = await self.persistence.get_workflow(task.workflow_id)
                        if workflow:
                            if task.id not in workflow.failed_tasks:
                                workflow.failed_tasks.append(task.id)
                            await self.persistence.save_workflow(workflow)
                
                # Mark as failed in queue if not retrying
                if not retry_scheduled:
                    await self.queue_manager.mark_task_failed(task.id)
                
                # Update stats
                self.stats.tasks_processed += 1
                self.stats.tasks_failed += 1
                
                logger.error(f"Task {task.id} failed: {error_message}")
                
                return task_result
    
    async def _resolve_task_parameters(self, task: Task) -> Dict[str, Any]:
        """Resolve parameter references in task parameters"""
        import re
        import json
        
        def substitute_parameters(obj: Any) -> Any:
            """Recursively substitute parameter references"""
            if isinstance(obj, str):
                # Look for ${task-id.field} patterns
                pattern = r'\$\{([^}]+)\}'
                matches = re.findall(pattern, obj)
                
                for match in matches:
                    parts = match.split('.')
                    if len(parts) == 2:
                        ref_task_name, field = parts
                        
                        # Get the referenced task result from persistence
                        if self.persistence:
                            # Find task by name in the same workflow
                            if task.workflow_id:
                                workflow = await self.persistence.get_workflow(task.workflow_id)
                                if workflow:
                                    # Find task ID by name
                                    for wf_task_id in workflow.task_ids:
                                        wf_task = await self.persistence.get_task(wf_task_id)
                                        if wf_task and wf_task.name == ref_task_name:
                                            # Get task result
                                            ref_result = await self.persistence.get_task_result(wf_task.id)
                                            if ref_result and ref_result.result:
                                                # Extract the requested field
                                                value = ref_result.result.get(field, '')
                                                obj = obj.replace(f'${{{match}}}', str(value))
                                            break
                
                return obj
            elif isinstance(obj, dict):
                return {k: substitute_parameters(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute_parameters(item) for item in obj]
            else:
                return obj
        
        # Resolve parameters
        if task.params:
            return substitute_parameters(task.params)
        return {}
    
    async def _route_task_to_provider(self, task: Task, params: Dict[str, Any]) -> Any:
        """Route task to appropriate provider"""
        # Get provider for the protocol
        provider = self.provider_registry.get_provider(task.protocol)
        if not provider:
            raise ProviderNotFoundError(
                protocol=task.protocol,
                available=list(self.provider_registry.providers.keys())
            )
        
        # Execute the task with timeout
        timeout = task.timeout or self.task_timeout
        
        try:
            result = await asyncio.wait_for(
                provider.execute(task.method, params),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            raise TaskTimeoutError(
                task_id=task.id,
                timeout=timeout
            )
    
    async def _check_workflow_completion(self, workflow_id: str) -> None:
        """Check if a workflow is complete and handle accordingly"""
        if not self.persistence:
            return
        
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            logger.warning(f"Workflow {workflow_id} not found")
            return
        
        # Get all task IDs for the workflow
        workflow_task_ids = set(workflow.task_ids)
        
        # Get completed task IDs from persistence
        completed_task_ids = set()
        failed_task_ids = set()
        
        for task_id in workflow_task_ids:
            task = await self.persistence.get_task(task_id)
            if task:
                if task.status == TaskStatus.COMPLETED:
                    completed_task_ids.add(task_id)
                elif task.status == TaskStatus.FAILED:
                    failed_task_ids.add(task_id)
        
        # Check if all tasks are done (either completed or failed)
        all_done = (completed_task_ids | failed_task_ids) == workflow_task_ids
        
        if all_done:
            if failed_task_ids:
                # Some tasks failed
                workflow.status = WorkflowStatus.FAILED
                workflow.completed_at = datetime.utcnow()
                logger.info(f"Workflow {workflow_id} failed with {len(failed_task_ids)} failed tasks")
            else:
                # All tasks completed successfully
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.utcnow()
                logger.info(f"Workflow {workflow_id} completed successfully")
            
            # Update workflow in persistence
            await self.persistence.save_workflow(workflow)
            
            # Update stats
            self.stats.workflows_processed += 1
            if workflow.status == WorkflowStatus.COMPLETED:
                self.stats.workflows_succeeded += 1
            else:
                self.stats.workflows_failed += 1
            
            # Emit workflow completion event
            if workflow.status == WorkflowStatus.COMPLETED:
                event = create_workflow_completed_event(
                    workflow_id=workflow_id,
                    duration=(workflow.completed_at - workflow.created_at).total_seconds(),
                    tasks_total=len(workflow_task_ids),
                    tasks_completed=len(completed_task_ids),
                    source="execution_engine"
                )
            else:
                event = create_workflow_failed_event(
                    workflow_id=workflow_id,
                    duration=(workflow.completed_at - workflow.created_at).total_seconds(),
                    tasks_total=len(workflow_task_ids),
                    tasks_failed=len(failed_task_ids),
                    error_message=f"Workflow failed with {len(failed_task_ids)} failed tasks",
                    source="execution_engine"
                )
            
            await self.emit_structured_event(event)
    
    async def submit_workflow(self, workflow: Workflow) -> None:
        """Submit a workflow for execution"""
        if not self.persistence:
            raise WorkflowError("Persistence backend required for workflow submission")
        
        # Save workflow to persistence
        await self.persistence.save_workflow(workflow)
        
        # Submit all tasks to queue
        for task_id in workflow.task_ids:
            task = await self.persistence.get_task(task_id)
            if task:
                await self.queue_manager.enqueue_task(task)
        
        # Emit workflow started event
        event = create_workflow_started_event(
            workflow_id=workflow.id,
            name=workflow.name,
            tasks_total=len(workflow.task_ids),
            source="execution_engine"
        )
        await self.emit_structured_event(event)
        
        logger.info(f"Submitted workflow {workflow.id} with {len(workflow.task_ids)} tasks")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics"""
        return {
            "running": self.running,
            "active_tasks": len(self.executing_task_ids),
            "tasks_processed": self.stats.tasks_processed,
            "tasks_succeeded": self.stats.tasks_succeeded,
            "tasks_failed": self.stats.tasks_failed,
            "workflows_processed": self.stats.workflows_processed,
            "workflows_succeeded": self.stats.workflows_succeeded,
            "workflows_failed": self.stats.workflows_failed,
            "average_task_duration": self.stats.average_task_duration,
            "total_execution_time": self.stats.total_execution_time
        }