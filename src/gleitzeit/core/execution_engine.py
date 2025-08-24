"""
Execution Engine for Gleitzeit V4

Central coordinator that orchestrates task execution by routing tasks from
the queue to protocol providers and managing workflow state progression.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any, Callable, Union, TYPE_CHECKING
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

from gleitzeit.core.models import Task, Workflow, TaskStatus, TaskResult, WorkflowStatus
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCError
from gleitzeit.core.scheduler import EventScheduler
from gleitzeit.core.dependency_tracker import DependencyTracker
from gleitzeit.core.retry_manager import RetryManager
from gleitzeit.core.errors import (
    ErrorCode, GleitzeitError, TaskError, TaskValidationError, 
    TaskTimeoutError, TaskDependencyError, WorkflowError, 
    WorkflowValidationError, SystemError, ResourceExhaustedError,
    is_retryable_error, error_to_jsonrpc
)
from gleitzeit.core.events import (
    EventType, EventSeverity, GleitzeitEvent,
    TaskEventData, WorkflowEventData, EngineEventData,
    create_task_started_event, create_task_completed_event,
    create_task_failed_event, create_workflow_started_event,
    create_workflow_completed_event
)
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import TaskQueue, QueueManager, DependencyResolver
from gleitzeit.persistence.base import PersistenceBackend

from gleitzeit.core.error_formatter import get_clean_logger

# Use clean logger that adjusts log levels for expected warnings
logger = get_clean_logger(__name__)


class ExecutionMode(Enum):
    """Execution modes for the engine"""
    SINGLE_SHOT = "single_shot"    # Execute one task and stop (for testing only)
    WORKFLOW_ONLY = "workflow_only"  # Only process complete workflows
    EVENT_DRIVEN = "event_driven"  # Only respond to Socket.IO events (default)


@dataclass
class ExecutionStats:
    """Statistics for execution engine"""
    tasks_processed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    workflows_completed: int = 0
    workflows_failed: int = 0
    average_task_duration: float = 0.0
    total_execution_time: float = 0.0


class ExecutionEngine:
    """
    Central execution coordinator for Gleitzeit V4
    
    Responsibilities:
    - Route tasks from queue to appropriate protocol providers
    - Manage task lifecycle and status updates
    - Handle parameter substitution between dependent tasks
    - Coordinate workflow execution and progression
    - Emit events for monitoring and observability
    """
    
    def __init__(
        self,
        registry: ProtocolProviderRegistry,
        queue_manager: QueueManager,
        dependency_resolver: DependencyResolver,
        persistence: Optional[PersistenceBackend] = None,
        max_concurrent_tasks: int = 10,
        pooling_adapter: Optional[Any] = None,
        event_bus: Optional[Any] = None
    ):
        self.registry = registry
        self.queue_manager = queue_manager
        self.dependency_resolver = dependency_resolver
        self.persistence = persistence
        self.max_concurrent_tasks = max_concurrent_tasks
        self.pooling_adapter = pooling_adapter
        self.event_bus = event_bus
        
        # Initialize event scheduler for delayed events (non-retry)
        self.scheduler = EventScheduler(emit_callback=self.emit_event)
        
        # Initialize retry manager for centralized retry logic
        if persistence is None:
            from gleitzeit.persistence.base import InMemoryBackend
            persistence = InMemoryBackend()
        
        self.retry_manager = RetryManager(
            queue_manager=queue_manager,
            persistence=persistence,
            scheduler=self.scheduler,
            event_bus=event_bus
        )
        
        # State management
        self.running = False
        # Remove local memory structures - use persistence backend only
        # Active tasks will be tracked via persistence queries with EXECUTING status
        # Task results will be stored/retrieved from persistence
        # Workflow states will be stored/retrieved from persistence
        
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
        """
        Emit structured event to all registered handlers
        
        Args:
            event: Either a GleitzeitEvent object or legacy string event_type
            data: Legacy data dict (only used with string event_type)
        """
        # Handle legacy string events for backward compatibility
        if isinstance(event, str):
            event_type = event
            
            # Handle retry events through RetryManager
            if event_type == "task:retry" and data and "task_id" in data:
                await self.retry_manager.handle_retry_event(data["task_id"])
                return
            
            
            # Emit to legacy handlers
            if event_type in self.event_handlers:
                for handler in self.event_handlers[event_type]:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event_type, data or {})
                        else:
                            handler(event_type, data or {})
                    except Exception as e:
                        logger.error(f"Event handler error for {event_type}: {e}")
            return
        
        # Handle structured GleitzeitEvent
        if isinstance(event, GleitzeitEvent):
            event_name, event_data = event.to_socket_io()
            
            # Handle scheduled retry events
            if event.event_type == EventType.TASK_RETRY_EXECUTED:
                await self._handle_retry_event(event_data.get("data", {}))
            
            # Emit to EventBus if available
            if hasattr(self, 'event_bus') and self.event_bus:
                await self.event_bus.emit(event)
            
            # Also emit to legacy handlers for backward compatibility
            if event_name in self.event_handlers:
                for handler in self.event_handlers[event_name]:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event_name, event_data)
                        else:
                            handler(event_name, event_data)
                    except Exception as e:
                        logger.error(f"Event handler error for {event_name}: {e}")
    
    async def emit_structured_event(self, event: GleitzeitEvent) -> None:
        """Emit a structured event"""
        await self.emit_event(event)
    
    async def start(self, mode: ExecutionMode = ExecutionMode.EVENT_DRIVEN) -> None:
        """Start the execution engine"""
        if self.running:
            logger.warning("ExecutionEngine already running")
            return
        
        self.running = True
        self.start_time = datetime.utcnow()
        self._shutdown_event.clear()
        
        # Start event scheduler
        await self.scheduler.start()
        
        # Start retry manager monitoring for stuck tasks
        if self.retry_manager:
            await self.retry_manager.start()
            logger.info("Retry manager monitoring started")
        
        # Emit structured engine started event
        engine_data = EngineEventData(
            mode=mode.value,
            max_concurrent_tasks=self.max_concurrent_tasks
        )
        
        engine_event = GleitzeitEvent(
            event_type=EventType.ENGINE_STARTED,
            severity=EventSeverity.INFO,
            data=engine_data.to_dict(),
            source="execution_engine",
            tags={"component": "engine", "mode": mode.value}
        )
        
        await self.emit_structured_event(engine_event)
        
        logger.info(f"Started ExecutionEngine in {mode.value} mode")
        
        # Store execution mode for task submission logic
        self._execution_mode = mode
        
        try:
            if mode == ExecutionMode.SINGLE_SHOT:
                await self._execute_single_task()
            elif mode == ExecutionMode.WORKFLOW_ONLY:
                await self._execute_workflows()
            elif mode == ExecutionMode.EVENT_DRIVEN:
                await self._execute_event_driven()
            else:
                raise SystemError(f"Unknown execution mode: {mode}")
                
        except Exception as e:
            logger.error(f"ExecutionEngine startup failed: {e}")
            raise SystemError(
                message=f"ExecutionEngine failed to start: {e}",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                cause=e
            )
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the execution engine"""
        if not self.running:
            return
        
        self.running = False
        self._shutdown_event.set()
        
        # Stop event scheduler
        await self.scheduler.stop()
        
        # Stop retry manager monitoring
        if self.retry_manager:
            await self.retry_manager.stop()
        
        # Wait for active tasks to complete (with timeout)
        active_tasks = await self._get_active_task_count()
        if active_tasks > 0:
            logger.info(f"Waiting for {active_tasks} active tasks to complete...")
            await asyncio.sleep(1.0)  # Give tasks time to finish
        
        # Calculate final stats
        if self.start_time:
            self.stats.total_execution_time = (
                datetime.utcnow() - self.start_time
            ).total_seconds()
        
        # Emit structured engine stopped event
        engine_data = EngineEventData(
            stats=await self._get_stats_dict()
        )
        
        engine_stopped_event = GleitzeitEvent(
            event_type=EventType.ENGINE_STOPPED,
            severity=EventSeverity.INFO,
            data=engine_data.to_dict(),
            source="execution_engine",
            tags={"component": "engine"}
        )
        
        await self.emit_structured_event(engine_stopped_event)
        
        # Stop registry and cleanup all providers
        if hasattr(self.registry, 'stop'):
            await self.registry.stop()
        
        logger.info("Stopped ExecutionEngine")
    
    async def _execute_single_task(self) -> Optional[TaskResult]:
        """Execute a single task from the queue"""
        task = await self.queue_manager.dequeue_next_task()
        if not task:
            logger.info("No tasks available in queue")
            return None
        
        return await self._execute_task(task)
    
    async def _process_ready_tasks(self, queue_name: Optional[str] = None) -> None:
        """Process any ready tasks up to capacity limit - used in event-driven mode"""
        if not self.running:
            return
            
        active_count = await self._get_active_task_count()
        while active_count < self.max_concurrent_tasks:
            # Try to dequeue the next ready task
            if queue_name:
                task = await self.queue_manager.dequeue_next_task(queue_name)
            else:
                task = await self.queue_manager.dequeue_next_task()
            
            if not task:
                # No more ready tasks available
                break
                
            # Execute task in background
            asyncio.create_task(self._execute_task(task))
            
            active_count = await self._get_active_task_count()
        logger.debug(f"Event-driven processing: {active_count}/{self.max_concurrent_tasks} active tasks")
    
    async def _execute_event_driven(self) -> None:
        """Event-driven execution mode - respond to events and periodically check queue"""
        logger.info("Starting event-driven execution mode")
        logger.info("ExecutionEngine will respond to events and check for queued tasks periodically")
        
        last_queue_check = asyncio.get_event_loop().time()
        queue_check_interval = 5.0  # Check queue every 5 seconds
        
        while self.running and not self._shutdown_event.is_set():
            # Periodically check for queued tasks that might be stuck
            current_time = asyncio.get_event_loop().time()
            if current_time - last_queue_check >= queue_check_interval:
                active_count = await self._get_active_task_count()
                if active_count < self.max_concurrent_tasks:
                    # Try to process any ready tasks from the queue
                    await self._process_ready_tasks()
                last_queue_check = current_time
            
            await asyncio.sleep(1.0)  # Keep the event loop alive
    
    
    async def _execute_workflows(self) -> None:
        """Execute complete workflows only"""
        logger.info("Starting workflow-only execution mode")
        
        while self.running and not self._shutdown_event.is_set():
            # Get workflows that are ready to execute
            ready_workflows = await self._get_ready_workflows()
            
            if not ready_workflows:
                await asyncio.sleep(2.0)
                continue
            
            # Execute workflows concurrently
            workflow_tasks = []
            for workflow in ready_workflows:
                if len(workflow_tasks) < self.max_concurrent_tasks:
                    workflow_tasks.append(
                        asyncio.create_task(self._execute_workflow(workflow))
                    )
            
            if workflow_tasks:
                await asyncio.gather(*workflow_tasks, return_exceptions=True)
    
    async def _execute_task_with_cleanup(self, task: Task) -> TaskResult:
        """Execute task and handle cleanup"""
        try:
            return await self._execute_task(task)
        except Exception as exc:
            # If _execute_task raised an exception, the TaskResult should already be stored
            # Return it from persistence instead of propagating the exception
            result = await self.persistence.get_task_result(task.id)
            if result:
                return result
            else:
                # Fallback - create a minimal failed TaskResult using centralized error handling
                from datetime import datetime
                if isinstance(exc, GleitzeitError):
                    error_message = str(exc)
                    error_type = type(exc).__name__
                else:
                    task_error = TaskError(
                        message=f"Task cleanup failed: {exc}",
                        code=ErrorCode.TASK_EXECUTION_FAILED,
                        task_id=task.id,
                        cause=exc
                    )
                    error_message = str(task_error)
                    error_type = type(task_error).__name__
                
                return TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    status=TaskStatus.FAILED,
                    error=error_message,
                    started_at=task.started_at or datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    metadata={"execution_engine": True, "error_type": error_type}
                )
        finally:
            # Cleanup active task tracking in persistence by updating status
            pass  # Status update handled in _execute_task
    
    async def _execute_task(self, task: Task) -> TaskResult:
        """Execute a single task"""
        async with self.semaphore:
            task_start_time = datetime.utcnow()
            # Mark task as executing in persistence instead of local memory
            error_message = None
            e = None
            
            try:
                # Update task status locally
                task.status = TaskStatus.EXECUTING
                task.started_at = task_start_time
                
                # Emit task started event - this will trigger persistence updates
                if hasattr(self, 'event_bus') and self.event_bus:
                    from ..core.events import create_task_started_event
                    started_event = create_task_started_event(
                        task_id=task.id,
                        task_name=task.name,
                        protocol=task.protocol,
                        method=task.method,
                        workflow_id=task.workflow_id,
                        source="execution_engine"
                    )
                    await self.event_bus.emit(started_event)
                    logger.debug(f"Task {task.id} started event emitted")
                else:
                    # Fallback to direct persistence if no event bus
                    if self.persistence:
                        await self.persistence.save_task(task)
                
                # Update workflow status to RUNNING if it's the first task
                if task.workflow_id:
                    workflow = await self.persistence.get_workflow(task.workflow_id)
                    if workflow and workflow.status == WorkflowStatus.PENDING:
                        workflow.status = WorkflowStatus.RUNNING
                        workflow.started_at = task_start_time
                        # Persist the updated workflow status
                        if self.persistence:
                            await self.persistence.save_workflow(workflow)
                        logger.debug(f"Workflow {workflow.id} status updated to RUNNING")
                
                # Increment retry count using retry manager
                current_attempt = await self.retry_manager.increment_retry_count(task.id)
                
                # Emit structured task started event
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
                
                # Check if the provider returned a TaskResult (from pooling) or raw result
                if isinstance(provider_result, TaskResult):
                    # Pooling adapter returned a complete TaskResult
                    task_result = provider_result
                    # Update timing info if not set
                    if not task_result.started_at:
                        task_result.started_at = task_start_time
                    if not task_result.completed_at:
                        task_result.completed_at = datetime.utcnow()
                else:
                    # Direct provider returned raw result, create TaskResult
                    task_result = TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.COMPLETED,
                        result=provider_result,
                        started_at=task_start_time,
                        completed_at=datetime.utcnow(),
                        metadata={"execution_engine": True}
                    )
                
                # Update task status locally
                task.status = TaskStatus.COMPLETED
                task.completed_at = task_result.completed_at
                logger.debug(f"Task {task.id} completed with result: {task_result.result}")
                
                # Emit task completion event - this will trigger all necessary updates
                from ..core.events import create_task_completed_event
                completion_event = create_task_completed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    duration=(task_result.completed_at - task_start_time).total_seconds(),
                    result_size=len(str(task_result.result)) if task_result.result else 0,
                    source="execution_engine"
                )
                
                # Save task result first (important for dependency resolution)
                if self.persistence:
                    await self.persistence.save_task_result(task_result)
                
                # Emit the event to trigger persistence, queue management, and workflow processing
                if hasattr(self, 'event_bus') and self.event_bus:
                    await self.event_bus.emit(completion_event)
                    logger.info(f"Task {task.id} completion event emitted")
                else:
                    logger.warning(f"No event bus configured, falling back to direct calls for task {task.id}")
                    # Fallback to direct calls if no event bus
                    if self.persistence:
                        await self.persistence.save_task(task)
                    await self.queue_manager.mark_task_completed(task.id)
                
                # In event-driven mode, check for newly available tasks after completion
                active_count = await self._get_active_task_count()
                if (hasattr(self, '_execution_mode') and 
                    self._execution_mode == ExecutionMode.EVENT_DRIVEN and
                    active_count < self.max_concurrent_tasks):
                    # Small delay to ensure persistence has committed the status change
                    await asyncio.sleep(0.1)
                    # Try to execute any newly available dependent tasks
                    ready_task = await self.queue_manager.dequeue_next_task()
                    # Ensure we don't re-execute the task we just completed
                    if ready_task and ready_task.id != task.id:
                        asyncio.create_task(self._execute_task(ready_task))
                
                # Update stats
                self.stats.tasks_processed += 1
                self.stats.tasks_succeeded += 1
                
                # Update average duration
                duration = (task_result.completed_at - task_start_time).total_seconds()
                if self.stats.tasks_processed == 1:
                    self.stats.average_task_duration = duration
                else:
                    self.stats.average_task_duration = (
                        (self.stats.average_task_duration * (self.stats.tasks_processed - 1) + duration)
                        / self.stats.tasks_processed
                    )
                
                # Note: Task completed event already emitted above via event_bus
                # No need to emit again via emit_structured_event to avoid duplicates
                
                # Check if workflow is complete and process dependencies
                if task.workflow_id:
                    await self._check_workflow_completion(task.workflow_id)
                
                logger.info(f"Task {task.id} completed successfully in {duration:.3f}s")
                return task_result
                
            except Exception as e:
                # Use centralized error handling
                if isinstance(e, asyncio.TimeoutError):
                    structured_error = TaskTimeoutError(
                        task_id=task.id,
                        timeout=task.timeout or 60.0,
                        cause=e
                    )
                elif isinstance(e, GleitzeitError):
                    # Already a structured error
                    structured_error = e
                else:
                    # Wrap unexpected errors in TaskError
                    structured_error = TaskError(
                        message=f"Task execution failed: {e}",
                        code=ErrorCode.TASK_EXECUTION_FAILED,
                        task_id=task.id,
                        cause=e
                    )
                
                error_message = str(structured_error)
                
                # Emit task:failed event for event-driven retry handling
                from gleitzeit.core.events import EventType, create_task_failed_event
                failed_event = create_task_failed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    error_message=error_message,
                    error_type=type(structured_error).__name__,
                    is_retryable=is_retryable_error(structured_error),
                    source="execution_engine"
                )
                
                await self.emit_structured_event(failed_event)
                logger.debug(f"Task {task.id} failed, emitted task:failed event")
                
                # Let the retry manager handle retry logic
                # The retry manager will check if retry is possible and schedule it
                retry_scheduled = await self.retry_manager.schedule_retry(task, error_message)
                
                if retry_scheduled:
                    logger.info(f"Task {task.id} scheduled for retry by retry manager")
                    
                    # The retry manager already set the task status to RETRY_PENDING
                    # We just need to create the result for tracking
                    
                    # Create retry-pending result
                    task_result = TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.RETRY_PENDING,
                        error=error_message,
                        started_at=task_start_time,
                        completed_at=datetime.utcnow(),
                        metadata={
                            "execution_engine": True, 
                            "error_type": type(structured_error).__name__,
                            "retry_scheduled": True,
                            "failure_reason": "Task failed but will be retried"
                        }
                    )
                    
                    # Save the retry-pending result
                    if self.persistence:
                        await self.persistence.save_task_result(task_result)
                    
                    # Return early - don't process as a final failure
                    return task_result
                else:
                    # Final failure - no more retries or no retry config
                    # Initialize failure_reason early
                    failure_reason = "Task failed permanently"
                    
                    # The retry manager may have already updated the task, so refresh from persistence
                    if self.persistence:
                        fresh_task = await self.persistence.get_task(task.id)
                        if fresh_task and fresh_task.status == TaskStatus.FAILED:
                            # Retry manager already marked it as failed, use its state
                            task = fresh_task
                            # Set failure reason based on retry manager's decision
                            if "Max retry attempts" in (task.error_message or ""):
                                failure_reason = "Task failed (max retry attempts reached)"
                        else:
                            # Set failure status ourselves
                            task.status = TaskStatus.FAILED
                            task.completed_at = datetime.utcnow()
                    else:
                        task.status = TaskStatus.FAILED
                        task.completed_at = datetime.utcnow()
                    
                    # Only set error message if not already set by retry manager
                    if not task.error_message or "Max retry attempts" not in task.error_message:
                        # Determine failure reason
                        if not task.retry_config:
                            failure_reason = "Task failed (no retry configured)"
                        elif "INVALID_PARAMS" in error_message:
                            failure_reason = "Task failed (invalid parameters - not retryable)"
                        elif "Invalid parameter" in error_message:
                            failure_reason = "Task failed (parameter validation error - not retryable)"
                        else:
                            # Get retry info to check if max attempts reached
                            retry_info = await self.retry_manager.get_task_retry_info(task.id)
                            if retry_info.get('count', 0) >= (task.retry_config.max_attempts if task.retry_config else 3):
                                failure_reason = f"Task failed (max retry attempts reached)"
                        
                        # Set detailed error message with reason
                        task.error_message = f"{failure_reason}: {error_message}"
                    
                    # Get final retry count from retry manager
                    retry_info = await self.retry_manager.get_task_retry_info(task.id)
                    total_attempts = retry_info.get('count', 1)
                    
                    # Create error result
                    task_result = TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.FAILED,
                        error=error_message,
                        started_at=task_start_time,
                        completed_at=task.completed_at,
                        metadata={
                            "execution_engine": True, 
                            "error_type": type(structured_error).__name__,
                            "final_failure": True,
                            "total_attempts": total_attempts,
                            "failure_reason": failure_reason
                        }
                    )
                
                # Update workflow's failed_tasks list if task belongs to a workflow
                if task.workflow_id:
                    workflow = await self.persistence.get_workflow(task.workflow_id)
                    if workflow and task.id not in workflow.failed_tasks:
                        workflow.failed_tasks.append(task.id)
                        # Save will happen below
                
                # Persist the failed task result
                if self.persistence:
                    await self.persistence.save_task_result(task_result)
                    # Only save task if we updated it (not if retry manager already did)
                    if task.status == TaskStatus.FAILED and not (task.metadata and task.metadata.get('max_retries_reached')):
                        await self.persistence.save_task(task)
                    # Also persist workflow if it was updated
                    if task.workflow_id and workflow:
                        await self.persistence.save_workflow(workflow)
                
                # Only mark as failed in queue if NOT scheduled for retry and not already done by retry manager
                if not retry_scheduled and not (task.metadata and task.metadata.get('max_retries_reached')):
                    await self.queue_manager.mark_task_failed(task.id)
                
                # Check workflow completion if task permanently failed
                if task.workflow_id:
                    await self._check_workflow_completion(task.workflow_id)
            
            # Store result in persistence only, not in memory
            if self.persistence:
                await self.persistence.save_task_result(task_result)
            
            # Update stats
            self.stats.tasks_processed += 1
            self.stats.tasks_failed += 1
            
            # Emit structured task failed event
            task_failed_event = create_task_failed_event(
                task_id=task.id,
                error_message=error_message,
                workflow_id=task.workflow_id,
                source="execution_engine"
            )
            
            await self.emit_structured_event(task_failed_event)
            
            logger.error(f"Task {task.id} failed: {error_message}")
            
            # Mark dependent workflows as failed if needed (only if NOT scheduled for retry)
            if task.workflow_id and not retry_scheduled:
                await self._handle_workflow_task_failure(task.workflow_id, task.id)
            
            # Return the TaskResult instead of raising for _execute_task_with_cleanup
            return task_result
    
    async def _resolve_task_parameters(self, task: Task) -> Dict[str, Any]:
        """Resolve parameter references in task parameters"""
        import re
        import json
        
        async def substitute_parameters(obj: Any) -> Any:
            """Recursively substitute parameter references"""
            if isinstance(obj, str):
                # Look for ${task-id.field} patterns
                pattern = r'\$\{([^}]+)\}'
                matches = re.findall(pattern, obj)
                
                for match in matches:
                    parts = match.split('.')
                    ref_task_id = parts[0]
                    field_path = parts[1:] if len(parts) > 1 else ['result']
                    
                    # Try to resolve task name to task ID if it's not already an ID
                    actual_task_id = ref_task_id
                    if hasattr(self, 'task_name_to_id_map') and ref_task_id in self.task_name_to_id_map:
                        actual_task_id = self.task_name_to_id_map[ref_task_id]
                        logger.debug(f"Resolved task name '{ref_task_id}' to ID '{actual_task_id}'")
                    
                    # Get referenced result from persistence
                    ref_result = await self.persistence.get_task_result(actual_task_id)
                    if ref_result:
                        
                        # Navigate through the field path
                        # Start with the result field of TaskResult if it exists
                        ref_value = ref_result.result if hasattr(ref_result, 'result') else ref_result
                        for field in field_path:
                            if field == 'result' and hasattr(ref_value, 'result'):
                                ref_value = ref_value.result
                            elif isinstance(ref_value, dict) and field in ref_value:
                                ref_value = ref_value[field]
                            elif hasattr(ref_value, field):
                                ref_value = getattr(ref_value, field)
                            else:
                                logger.warning(f"Field {field} not found in task {actual_task_id} result")
                                logger.warning(f"  Available fields in ref_value: {list(ref_value.keys()) if isinstance(ref_value, dict) else dir(ref_value)}")
                                logger.warning(f"  ref_value type: {type(ref_value)}")
                                ref_value = None
                                break
                        
                        # Replace the reference
                        if ref_value is not None:
                            # If the entire string is just the reference, return the actual value
                            if obj == f"${{{match}}}":
                                return ref_value
                            # Otherwise, do string replacement (which requires converting to string)
                            else:
                                replacement = str(ref_value) if not isinstance(ref_value, str) else ref_value
                                obj = obj.replace(f"${{{match}}}", replacement)
                    else:
                        logger.warning(f"Referenced task {actual_task_id} not found in results")
                
                return obj
            
            elif isinstance(obj, dict):
                return {k: await substitute_parameters(v) for k, v in obj.items()}
            
            elif isinstance(obj, list):
                return [await substitute_parameters(item) for item in obj]
            
            else:
                return obj
        
        return await substitute_parameters(task.params.copy())
    
    async def _route_task_to_provider(self, task: Task, params: Dict[str, Any]) -> Any:
        """Route task to appropriate protocol provider"""
        # Check if pooling adapter is available and supports this protocol
        if (self.pooling_adapter and 
            hasattr(self.pooling_adapter, 'is_protocol_available') and
            self.pooling_adapter.is_protocol_available(task.protocol)):
            
            # Use pooling adapter for execution
            logger.debug(f"Routing task {task.id} via pooling adapter")
            
            # Execute via pooling system
            task_result = await self.pooling_adapter.execute_task(task)
            
            # Handle the result and check workflow completion
            if task_result.status == TaskStatus.COMPLETED:
                # Save result to persistence BEFORE checking workflow completion
                # This ensures the dependency resolution can find the completed task
                if self.persistence:
                    await self.persistence.save_task_result(task_result)
                
                # Update task status locally
                task.status = TaskStatus.COMPLETED
                task.completed_at = task_result.completed_at or datetime.utcnow()
                
                # Emit task completion event to update task status in database
                if hasattr(self, 'event_bus') and self.event_bus:
                    from ..core.events import create_task_completed_event
                    completion_event = create_task_completed_event(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        duration=(task.completed_at - task_result.started_at).total_seconds() if task_result.started_at else 0,
                        result_size=len(str(task_result.result)) if task_result.result else 0,
                        source="execution_engine_pooling"
                    )
                    await self.event_bus.emit(completion_event)
                    logger.info(f"Task {task.id} completion event emitted (pooling adapter)")
                else:
                    # Fallback to direct save if no event bus
                    if self.persistence:
                        await self.persistence.save_task(task)
                
                # Now check if workflow is complete and process dependencies
                if task.workflow_id:
                    await self._check_workflow_completion(task.workflow_id)
                
                return task_result
            else:
                error_msg = task_result.error or "Task execution failed via pooling"
                raise TaskError(
                    message=error_msg,
                    code=ErrorCode.TASK_EXECUTION_FAILED,
                    task_id=task.id
                )
        
        # Fallback to direct registry execution
        logger.debug(f"Routing task {task.id} via direct registry")
        
        # Create JSON-RPC request
        jsonrpc_request = JSONRPCRequest(
            method=task.method,
            params=params,
            id=task.id
        )
        
        # Execute request via registry
        response = await self.registry.execute_request(
            protocol_id=task.protocol,
            request=jsonrpc_request
        )
        
        # Check for JSON-RPC error
        if hasattr(response, 'error') and response.error is not None:
            raise TaskError(
                message=f"Provider error: {response.error.message}",
                code=ErrorCode.TASK_EXECUTION_FAILED,
                task_id=task.id,
                data={"provider_error_code": getattr(response.error, 'code', None)}
            )
        
        # Return the result
        result = response.result if hasattr(response, 'result') else response
        logger.debug(f"Task {task.id} executed successfully")
        return result
    
    async def _execute_workflow(self, workflow: Workflow) -> None:
        """Execute all tasks in a workflow with dependency ordering"""
        logger.info(f"Executing workflow {workflow.id}")
        
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.utcnow()
        # Store workflow in persistence
        if self.persistence:
            await self.persistence.save_workflow(workflow)
        
        try:
            # Add workflow to dependency resolver
            self.dependency_resolver.add_workflow(workflow)
            
            # Get execution order
            execution_levels = self.dependency_resolver.get_execution_order(workflow.id)
            
            # Emit structured workflow started event
            workflow_started_event = create_workflow_started_event(
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                total_tasks=len(workflow.tasks),
                execution_levels=len(execution_levels),
                source="execution_engine"
            )
            
            await self.emit_structured_event(workflow_started_event)
            
            # Execute tasks level by level
            all_task_results = {}  # Collect all task results
            for level_index, task_ids in enumerate(execution_levels):
                logger.info(f"Workflow {workflow.id} executing level {level_index + 1}/{len(execution_levels)}")
                
                # Get tasks for this level
                level_tasks = [task for task in workflow.tasks if task.id in task_ids]
                
                # Execute tasks in parallel within the level
                task_futures = []
                for task in level_tasks:
                    future = asyncio.create_task(self._execute_task(task))
                    task_futures.append(future)
                
                # Wait for all tasks in this level to complete
                level_results = await asyncio.gather(*task_futures, return_exceptions=True)
                
                # Check for failures and collect results
                failed_tasks = []
                for i, result in enumerate(level_results):
                    task_id = level_tasks[i].id
                    if isinstance(result, Exception):
                        failed_tasks.append(task_id)
                    elif isinstance(result, TaskResult):
                        # Store the task result
                        all_task_results[task_id] = {
                            "status": "completed" if result.status == TaskStatus.COMPLETED else "failed",
                            "result": result.result,
                            "error": result.error
                        }
                
                if failed_tasks:
                    raise WorkflowError(
                        message=f"Tasks failed in workflow level {level_index + 1}",
                        code=ErrorCode.WORKFLOW_EXECUTION_FAILED,
                        workflow_id=workflow.id,
                        data={"failed_tasks": failed_tasks, "level": level_index + 1}
                    )
            
            # Mark workflow as completed
            workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = datetime.utcnow()
            
            self.stats.workflows_completed += 1
            
            # Emit workflow completed event with all task results
            from ..core.events import EventType, EventSeverity, GleitzeitEvent
            completed_tasks = [t_id for t_id, r in all_task_results.items() if r["status"] == "completed"]
            failed_tasks = [t_id for t_id, r in all_task_results.items() if r["status"] == "failed"]
            
            workflow_completed_event = GleitzeitEvent(
                event_type=EventType.WORKFLOW_COMPLETED,
                severity=EventSeverity.INFO,
                data={
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "status": "completed",
                    "completed_tasks": completed_tasks,
                    "failed_tasks": failed_tasks,
                    "task_results": all_task_results,
                    "duration": (workflow.completed_at - workflow.started_at).total_seconds()
                },
                source="execution_engine",
                tags={"component": "engine"}
            )
            await self.emit_structured_event(workflow_completed_event)
            logger.info(f"Emitted WORKFLOW_COMPLETED event for workflow {workflow.id} with {len(all_task_results)} task results")
            
            logger.info(f"Workflow {workflow.id} completed successfully")
            
        except WorkflowError as e:
            # Already a workflow error, just handle it
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.utcnow()
            logger.error(f"Workflow {workflow.id} failed: {e}")
            raise
            
        except Exception as e:
            # Wrap unexpected errors
            workflow_error = WorkflowError(
                message=f"Workflow execution failed: {e}",
                code=ErrorCode.WORKFLOW_EXECUTION_FAILED,
                workflow_id=workflow.id,
                cause=e
            )
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.utcnow()
            logger.error(f"Workflow {workflow.id} failed: {workflow_error}")
            raise workflow_error
            
            self.stats.workflows_failed += 1
            
            # Emit structured workflow failed event
            workflow_data = WorkflowEventData(
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                error_message=str(e),
                status=WorkflowStatus.FAILED
            )
            
            workflow_failed_event = GleitzeitEvent.create_workflow_event(
                EventType.WORKFLOW_FAILED,
                workflow_data,
                severity=EventSeverity.ERROR,
                source="execution_engine"
            )
            
            await self.emit_structured_event(workflow_failed_event)
            
            logger.error(f"Workflow {workflow.id} failed: {e}")
            raise
    
    async def _get_ready_workflows(self) -> List[Workflow]:
        """Get workflows that are ready for execution"""
        # This is a simplified implementation
        # In practice, you'd check workflow dependencies and readiness
        return []
    
    async def _check_workflow_completion(self, workflow_id: str) -> None:
        """Check if a workflow is complete and submit ready dependent tasks"""
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return
        
        # Check if we should resolve (prevents duplicate concurrent resolutions)
        if not await self.dependency_tracker.should_resolve_workflow(workflow_id):
            logger.debug(f"Skipping duplicate resolution for workflow {workflow_id}")
            return
        
        try:
            
            # Get completed task IDs for this workflow from persistence
            completed_task_ids = set()
            
            # Also check persistence for completed tasks (needed when using pooling adapter)
            if self.persistence:
                for task in workflow.tasks:
                    if task.id not in completed_task_ids:  # Don't double-check
                        persisted_result = await self.persistence.get_task_result(task.id)
                        if (persisted_result and 
                            persisted_result.workflow_id == workflow_id and 
                            persisted_result.status == TaskStatus.COMPLETED):
                            completed_task_ids.add(task.id)
            
            # Check for tasks that are now ready to run (dependencies satisfied)
            ready_tasks = []
            for task in workflow.tasks:
                # Skip if already submitted (prevents duplicate submissions)
                if await self.dependency_tracker.is_task_submitted(task.id):
                    continue
                
                # Skip tasks that are already completed or failed
                if task.id in completed_task_ids:
                    continue
                    
                # Check if task already has a result (failed, in progress, etc.)
                existing_result = await self.persistence.get_task_result(task.id)
                if existing_result:
                    continue
                
                # Get fresh task status from persistence to avoid re-submitting completed tasks
                fresh_task = await self.persistence.get_task(task.id)
                if fresh_task and fresh_task.status in [TaskStatus.COMPLETED, TaskStatus.EXECUTING, TaskStatus.FAILED]:
                    continue
                    
                # Check if all dependencies are satisfied
                if task.dependencies:
                    dependencies_satisfied = all(
                        dep_task_id in completed_task_ids 
                        for dep_task_id in task.dependencies
                    )
                    if dependencies_satisfied:
                        ready_tasks.append(task)
                else:
                    # Task has no dependencies - only add if it's not already completed/executing/failed
                    if not fresh_task or fresh_task.status in [TaskStatus.PENDING, TaskStatus.QUEUED]:
                        ready_tasks.append(task)
            
            # Submit ready tasks to the queue  
            for task in ready_tasks:
                await self.submit_task(task)
            
            # Check if workflow is complete
            workflow_task_ids = {task.id for task in workflow.tasks}
            
            logger.debug(f"Workflow {workflow_id}: completed_task_ids={completed_task_ids}, workflow_task_ids={workflow_task_ids}")
            
            if completed_task_ids == workflow_task_ids:
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.utcnow()
                
                # Update the workflow's completed_tasks list
                workflow.completed_tasks = list(completed_task_ids)
                
                self.stats.workflows_completed += 1
                
                logger.info(f"Workflow {workflow_id} completed successfully")
                
                # Persist the updated workflow status
                if self.persistence:
                    await self.persistence.save_workflow(workflow)
                
                # Clean up dependency tracker for completed workflow
                await self.dependency_tracker.cleanup_completed_workflows([workflow_id])
                
                # Emit structured workflow completed event
                workflow_completed_event = create_workflow_completed_event(
                    workflow_id=workflow_id,
                    duration=(workflow.completed_at - workflow.started_at).total_seconds() if workflow.started_at else 0.0,
                    tasks_completed=len(workflow.tasks),
                    source="execution_engine"
                )
                
                await self.emit_structured_event(workflow_completed_event)
                logger.info(f"Workflow {workflow_id} completed successfully")
            
            # Mark resolution as successful
            await self.dependency_tracker.complete_resolution(workflow_id, success=True)
            
        except Exception as e:
            # Mark resolution as failed
            await self.dependency_tracker.complete_resolution(workflow_id, success=False, error=str(e))
            logger.error(f"Failed to check workflow completion for {workflow_id}: {e}")
            raise
    
    async def _handle_workflow_task_failure(self, workflow_id: str, failed_task_id: str) -> None:
        """Handle task failure within a workflow"""
        workflow = await self.persistence.get_workflow(workflow_id)
        if workflow:
            
            # Check if workflow should be marked as failed
            # This depends on workflow failure policy (fail-fast vs. continue)
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.utcnow()
            
            # Persist the updated workflow status
            if self.persistence:
                await self.persistence.save_workflow(workflow)
            
            self.stats.workflows_failed += 1
            
            # Emit structured workflow failed event
            workflow_data = WorkflowEventData(
                workflow_id=workflow_id,
                status=WorkflowStatus.FAILED,
                error_message=f"Task {failed_task_id} failed"
            )
            
            workflow_failed_event = GleitzeitEvent.create_workflow_event(
                EventType.WORKFLOW_FAILED,
                workflow_data,
                severity=EventSeverity.ERROR,
                source="execution_engine"
            )
            
            await self.emit_structured_event(workflow_failed_event)
    
    def get_stats(self) -> ExecutionStats:
        """Get execution statistics"""
        return self.stats
    
    async def _get_stats_dict(self) -> Dict[str, Any]:
        """Get stats as dictionary"""
        active_count = await self._get_active_task_count()
        return {
            "tasks_processed": self.stats.tasks_processed,
            "tasks_succeeded": self.stats.tasks_succeeded,
            "tasks_failed": self.stats.tasks_failed,
            "workflows_completed": self.stats.workflows_completed,
            "workflows_failed": self.stats.workflows_failed,
            "average_task_duration": self.stats.average_task_duration,
            "total_execution_time": self.stats.total_execution_time,
            "success_rate": (
                self.stats.tasks_succeeded / self.stats.tasks_processed * 100
                if self.stats.tasks_processed > 0 else 100.0
            ),
            "active_tasks": active_count,
            "max_concurrent_tasks": self.max_concurrent_tasks
        }
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get result for a specific task"""
        return await self.persistence.get_task_result(task_id)
    
    async def get_workflow_results(self, workflow_id: str) -> List[TaskResult]:
        """Get all results for a workflow"""
        # Get all tasks for the workflow and their results
        tasks = await self.persistence.get_tasks_by_workflow(workflow_id)
        results = []
        for task in tasks:
            result = await self.persistence.get_task_result(task.id)
            if result:
                results.append(result)
        return results
    
    async def submit_task(self, task: Task, queue_name: Optional[str] = None) -> None:
        """Submit a single task for execution (idempotent)"""
        
        # Auto-create single-task workflow if task has no workflow_id
        if not task.workflow_id:
            from datetime import datetime
            from gleitzeit.core.models import Workflow
            
            # Generate workflow ID for single task
            workflow_id = f"single-task-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{task.id[:8]}"
            task.workflow_id = workflow_id
            
            # Create and persist the single-task workflow
            workflow = Workflow(
                id=workflow_id,
                name=f"Single Task: {task.name}",
                description=f"Auto-generated workflow for task {task.id}",
                tasks=[task]
            )
            
            # Save workflow to persistence if available
            if self.persistence:
                await self.persistence.save_workflow(workflow)
            
            logger.debug(f"Auto-created workflow {workflow_id} for task {task.id}")
        
        # Check if task was already submitted (idempotency)
        if not await self.dependency_tracker.mark_task_submitted(task.id, task.workflow_id):
            logger.debug(f"Task {task.id} already submitted, skipping duplicate submission")
            return
        
        await self.queue_manager.enqueue_task(task, queue_name)
        
        # Emit structured task submitted event
        task_data = TaskEventData(
            task_id=task.id,
            task_name=task.name,
            protocol=task.protocol,
            method=task.method,
            priority=task.priority,
            status=TaskStatus.QUEUED
        )
        
        task_submitted_event = GleitzeitEvent.create_task_event(
            EventType.TASK_SUBMITTED,
            task_data,
            source="execution_engine",
            correlation_id=task.workflow_id
        )
        
        await self.emit_structured_event(task_submitted_event)
        
        # In event-driven mode, immediately try to process ready tasks if capacity allows
        active_count = await self._get_active_task_count()
        if (self.running and 
            active_count < self.max_concurrent_tasks and
            hasattr(self, '_execution_mode') and self._execution_mode == ExecutionMode.EVENT_DRIVEN):
            # Try to dequeue and execute any ready tasks (not just the one we submitted)
            await self._process_ready_tasks(queue_name)
        
    
    async def submit_workflow(self, workflow: Workflow, queue_name: Optional[str] = None) -> None:
        """Submit a complete workflow for execution"""
        # Add workflow to dependency resolver for validation
        errors = self.dependency_resolver.validate_workflow_dependencies(workflow)
        if errors:
            raise WorkflowValidationError(
                workflow.id,
                errors
            )
        
        # Build name-to-ID mapping for parameter substitution
        self._build_name_to_id_mapping(workflow)
        
        # Submit workflow tasks using submit_task to trigger automatic execution
        for task in workflow.tasks:
            await self.submit_task(task, queue_name)
        
        # Store workflow in persistence
        if self.persistence:
            await self.persistence.save_workflow(workflow)
        
        # Emit structured workflow submitted event
        workflow_data = WorkflowEventData(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            total_tasks=len(workflow.tasks),
            status=WorkflowStatus.PENDING
        )
        
        workflow_submitted_event = GleitzeitEvent.create_workflow_event(
            EventType.WORKFLOW_SUBMITTED,
            workflow_data,
            source="execution_engine"
        )
        
        await self.emit_structured_event(workflow_submitted_event)
    
    def _build_name_to_id_mapping(self, workflow: Workflow) -> None:
        """Build mapping from task names to task IDs for parameter substitution"""
        if not hasattr(self, 'task_name_to_id_map'):
            self.task_name_to_id_map: Dict[str, str] = {}
        
        for task in workflow.tasks:
            self.task_name_to_id_map[task.name] = task.id
            logger.debug(f"Mapped task name '{task.name}' to ID '{task.id}'")
    
    async def _get_active_task_count(self) -> int:
        """Get count of currently executing tasks from persistence"""
        if not self.persistence:
            return 0
        executing_tasks = await self.persistence.get_tasks_by_status(TaskStatus.EXECUTING)
        return len(executing_tasks)
    
    async def get_retry_stats(self) -> Dict[str, Any]:
        """Get retry statistics from the centralized retry manager"""
        return await self.retry_manager.get_retry_stats()