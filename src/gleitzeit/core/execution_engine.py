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
        pooling_adapter: Optional[Any] = None
    ):
        self.registry = registry
        self.queue_manager = queue_manager
        self.dependency_resolver = dependency_resolver
        self.persistence = persistence
        self.max_concurrent_tasks = max_concurrent_tasks
        self.pooling_adapter = pooling_adapter
        
        # Initialize event scheduler for delayed events (non-retry)
        self.scheduler = EventScheduler(emit_callback=self.emit_event)
        
        # Initialize retry manager for centralized retry logic
        if persistence is None:
            from gleitzeit.persistence.base import InMemoryBackend
            persistence = InMemoryBackend()
        
        self.retry_manager = RetryManager(
            queue_manager=queue_manager,
            persistence=persistence,
            scheduler=self.scheduler
        )
        
        # State management
        self.running = False
        self.active_tasks: Dict[str, Task] = {}
        self.task_results: Dict[str, TaskResult] = {}
        self.workflow_states: Dict[str, Workflow] = {}
        
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
            
            # Emit to both legacy and new handlers
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
        
        # Note: RetryManager is used for logic only, not background tasks
        # Actual retry scheduling is handled by EventScheduler
        
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
        
        # RetryManager doesn't need stopping (no background tasks)
        
        # Wait for active tasks to complete (with timeout)
        if self.active_tasks:
            logger.info(f"Waiting for {len(self.active_tasks)} active tasks to complete...")
            await asyncio.sleep(1.0)  # Give tasks time to finish
        
        # Calculate final stats
        if self.start_time:
            self.stats.total_execution_time = (
                datetime.utcnow() - self.start_time
            ).total_seconds()
        
        # Emit structured engine stopped event
        engine_data = EngineEventData(
            stats=self._get_stats_dict()
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
            
        while len(self.active_tasks) < self.max_concurrent_tasks:
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
            
        logger.debug(f"Event-driven processing: {len(self.active_tasks)}/{self.max_concurrent_tasks} active tasks")
    
    async def _execute_event_driven(self) -> None:
        """Event-driven execution mode - only respond to Socket.IO events"""
        logger.info("Starting event-driven execution mode")
        logger.info("ExecutionEngine will only respond to incoming events (task:assigned, task:retry, etc.)")
        
        # Just wait for events - no polling or background processing
        while self.running and not self._shutdown_event.is_set():
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
            # Return it instead of propagating the exception
            if task.id in self.task_results:
                return self.task_results[task.id]
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
            # Cleanup active task tracking
            self.active_tasks.pop(task.id, None)
    
    async def _execute_task(self, task: Task) -> TaskResult:
        """Execute a single task"""
        async with self.semaphore:
            task_start_time = datetime.utcnow()
            self.active_tasks[task.id] = task
            error_message = None
            e = None
            
            try:
                # Update task status
                task.status = TaskStatus.EXECUTING
                task.started_at = task_start_time
                
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
                
                # Update task and store result
                task.status = TaskStatus.COMPLETED
                task.completed_at = task_result.completed_at
                self.task_results[task.id] = task_result
                logger.debug(f"Stored result for task {task.id}: {task_result.result}")
                
                # Persist the task result
                if self.persistence:
                    await self.persistence.save_task_result(task_result)
                    await self.persistence.save_task(task)
                
                # Mark as completed in queue
                await self.queue_manager.mark_task_completed(task.id)
                
                # In event-driven mode, check for newly available tasks after completion
                if (hasattr(self, '_execution_mode') and 
                    self._execution_mode == ExecutionMode.EVENT_DRIVEN and
                    len(self.active_tasks) < self.max_concurrent_tasks):
                    # Try to execute any newly available dependent tasks
                    ready_task = await self.queue_manager.dequeue_next_task()
                    if ready_task:
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
                
                # Emit structured task completed event
                task_completed_event = create_task_completed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    duration=duration,
                    result_size=len(str(task_result.result)) if task_result.result else 0,
                    source="execution_engine"
                )
                
                await self.emit_structured_event(task_completed_event)
                
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
                
                # Get current retry count from retry manager
                retry_info = await self.retry_manager.get_task_retry_info(task.id)
                current_retry_count = retry_info.get('count', 0)
                max_attempts = task.retry_config.max_attempts if task.retry_config else 3
                
                logger.debug(f"Task {task.id} retry info: count={current_retry_count}, max={max_attempts}")
                
                # Check if we can retry based on database retry count and retryable error
                should_retry = (current_retry_count < max_attempts and 
                              is_retryable_error(structured_error))
            
            if should_retry:
                # Schedule retry via retry manager
                await self.retry_manager.schedule_retry(task, error_message)
                
                logger.info(f"Task {task.id} scheduled for retry (attempt {current_retry_count})")
                
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
                        "retry_attempt": current_retry_count,
                        "max_attempts": max_attempts
                    }
                )
            else:
                # Final failure - no more retries
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.error_message = error_message
                
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
                        "total_attempts": total_attempts
                    }
                )
                
                # Persist the failed task result
                if self.persistence:
                    await self.persistence.save_task_result(task_result)
                    await self.persistence.save_task(task)
                
                # Mark as failed in queue
                await self.queue_manager.mark_task_failed(task.id)
                
                # Check workflow completion if task permanently failed
                if task.workflow_id:
                    await self._check_workflow_completion(task.workflow_id)
            
            self.task_results[task.id] = task_result
            
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
            
            # Mark dependent workflows as failed if needed
            if task.workflow_id:
                await self._handle_workflow_task_failure(task.workflow_id, task.id)
            
            # Return the TaskResult instead of raising for _execute_task_with_cleanup
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
                    ref_task_id = parts[0]
                    field_path = parts[1:] if len(parts) > 1 else ['result']
                    
                    # Try to resolve task name to task ID if it's not already an ID
                    actual_task_id = ref_task_id
                    if hasattr(self, 'task_name_to_id_map') and ref_task_id in self.task_name_to_id_map:
                        actual_task_id = self.task_name_to_id_map[ref_task_id]
                        logger.debug(f"Resolved task name '{ref_task_id}' to ID '{actual_task_id}'")
                    
                    # Get referenced result
                    logger.debug(f"Looking for task {actual_task_id} in results: {list(self.task_results.keys())}")
                    if actual_task_id in self.task_results:
                        ref_result = self.task_results[actual_task_id]
                        
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
                return {k: substitute_parameters(v) for k, v in obj.items()}
            
            elif isinstance(obj, list):
                return [substitute_parameters(item) for item in obj]
            
            else:
                return obj
        
        return substitute_parameters(task.params.copy())
    
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
                
                # Also store in memory for consistency
                self.task_results[task.id] = task_result
                
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
        self.workflow_states[workflow.id] = workflow
        
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
                
                # Check for failures
                failed_tasks = []
                for i, result in enumerate(level_results):
                    if isinstance(result, Exception):
                        failed_tasks.append(level_tasks[i].id)
                
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
            
            # Emit structured workflow completed event
            workflow_completed_event = create_workflow_completed_event(
                workflow_id=workflow.id,
                duration=(workflow.completed_at - workflow.started_at).total_seconds(),
                tasks_completed=len(workflow.tasks),
                source="execution_engine"
            )
            
            await self.emit_structured_event(workflow_completed_event)
            
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
        if workflow_id not in self.workflow_states:
            return
        
        # Check if we should resolve (prevents duplicate concurrent resolutions)
        if not await self.dependency_tracker.should_resolve_workflow(workflow_id):
            logger.debug(f"Skipping duplicate resolution for workflow {workflow_id}")
            return
        
        try:
            workflow = self.workflow_states[workflow_id]
            
            # Get completed task IDs for this workflow from both internal results and persistence
            completed_task_ids = {
                task_id for task_id, result in self.task_results.items()
                if result.workflow_id == workflow_id and result.status == TaskStatus.COMPLETED
            }
            
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
                if task.id in self.task_results:
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
                    # Task has no dependencies, but wasn't submitted yet
                    # This shouldn't normally happen, but handle it
                    ready_tasks.append(task)
            
            # Submit ready tasks to the queue  
            for task in ready_tasks:
                await self.submit_task(task)
            
            # Check if workflow is complete
            workflow_task_ids = {task.id for task in workflow.tasks}
            
            if completed_task_ids == workflow_task_ids:
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.utcnow()
                
                self.stats.workflows_completed += 1
                
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
        if workflow_id in self.workflow_states:
            workflow = self.workflow_states[workflow_id]
            
            # Check if workflow should be marked as failed
            # This depends on workflow failure policy (fail-fast vs. continue)
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.utcnow()
            
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
    
    def _get_stats_dict(self) -> Dict[str, Any]:
        """Get stats as dictionary"""
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
            "active_tasks": len(self.active_tasks),
            "max_concurrent_tasks": self.max_concurrent_tasks
        }
    
    def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get result for a specific task"""
        return self.task_results.get(task_id)
    
    def get_workflow_results(self, workflow_id: str) -> List[TaskResult]:
        """Get all results for a workflow"""
        return [
            result for result in self.task_results.values()
            if result.workflow_id == workflow_id
        ]
    
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
        if (self.running and 
            len(self.active_tasks) < self.max_concurrent_tasks and
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
        
        self.workflow_states[workflow.id] = workflow
        
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
    
    async def get_retry_stats(self) -> Dict[str, Any]:
        """Get retry statistics from the centralized retry manager"""
        return await self.retry_manager.get_retry_stats()