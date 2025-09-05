"""
Task Executor for Gleitzeit

Extracted from ExecutionEngine to handle pure task execution logic.
Focuses solely on executing individual tasks through providers.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from gleitzeit.core.models import Task, TaskStatus, TaskResult
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.parameter_resolver import ParameterResolver
from gleitzeit.core.errors import (
    TaskError, ErrorCode, TaskTimeoutError, 
    TaskExecutionError, error_to_jsonrpc
)
from gleitzeit.core.events import (
    EventType, GleitzeitEvent,
    create_task_started_event,
    create_task_completed_event,
    create_task_failed_event
)

logger = logging.getLogger(__name__)


class TaskExecutor:
    """
    Pure task execution logic extracted from ExecutionEngine.
    
    Responsibilities:
    - Execute tasks through protocol providers
    - Handle parameter resolution
    - Manage task timeouts
    - Create task results
    - Emit task lifecycle events
    
    Does NOT handle:
    - Workflow management
    - Retry logic
    - Task queuing
    - Dependency resolution
    """
    
    def __init__(
        self,
        pooling_adapter: Any,  # Required, not optional
        persistence: Optional[PersistenceBackend] = None,
        parameter_resolver: Optional[ParameterResolver] = None,
        event_bus: Optional[Any] = None,
        task_timeout: int = 300
    ):
        """
        Initialize TaskExecutor.
        
        Args:
            pooling_adapter: Adapter for pooled provider execution (required)
            persistence: Backend for storing task results
            parameter_resolver: Service for resolving task parameters
            event_bus: Event bus for emitting task events
            task_timeout: Default timeout for task execution in seconds
        """
        if not pooling_adapter:
            raise ValueError("TaskExecutor requires a pooling_adapter")
            
        self.pooling_adapter = pooling_adapter
        self.persistence = persistence
        self.parameter_resolver = parameter_resolver or (
            ParameterResolver(persistence) if persistence else None
        )
        self.event_bus = event_bus
        self.task_timeout = task_timeout
        
        logger.info(f"Initialized TaskExecutor with timeout={task_timeout}s")
        
    async def execute_task(self, task: Task) -> TaskResult:
        """
        Execute a single task.
        
        Args:
            task: Task to execute
            
        Returns:
            TaskResult with execution outcome
            
        Raises:
            TaskError: If task execution fails
        """
        task_start_time = datetime.utcnow()
        
        try:
            # Update task status to EXECUTING
            await self._update_task_status(task, TaskStatus.EXECUTING, task_start_time)
            
            # Emit task started event
            await self._emit_task_started(task)
            
            # Resolve parameters if task has dependencies
            params = task.params
            if task.dependencies and self.parameter_resolver:
                logger.info(f"Resolving parameters for task {task.id}")
                params = await self.parameter_resolver.resolve_parameters(task)
                
            # Route to provider and execute
            logger.info(f"Executing task {task.id} ({task.protocol}/{task.method})")
            result = await self._route_and_execute(task, params)
            
            # Check if result is already a TaskResult (from pooling adapter)
            if isinstance(result, TaskResult):
                task_result = result
                # Update with our start time if not set
                if not task_result.started_at:
                    task_result.started_at = task_start_time
                    
                # Check if the task failed
                if task_result.status == TaskStatus.FAILED:
                    # Update task status to FAILED
                    await self._update_task_status(task, TaskStatus.FAILED, completed_at=task_result.completed_at)
                    
                    # Store result in persistence
                    if self.persistence:
                        await self.persistence.save_task_result(task_result)
                    
                    # Emit task failed event
                    await self._emit_task_failed(task, task_result.error or "Task execution failed")
                    
                    logger.info(f"Task {task.id} failed: {task_result.error}")
                    return task_result
            else:
                # Create successful task result from raw result
                task_result = TaskResult(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    result=result,
                    error=None,
                    started_at=task_start_time,
                    completed_at=datetime.utcnow(),
                    metadata={"executor": "TaskExecutor"}
                )
            
            # Update task status to COMPLETED (only if we get here)
            await self._update_task_status(task, TaskStatus.COMPLETED, completed_at=task_result.completed_at)
            
            # Store result in persistence
            if self.persistence:
                await self.persistence.save_task_result(task_result)
                
            # Emit task completed event
            await self._emit_task_completed(task, task_result)
            
            logger.info(f"Task {task.id} completed successfully")
            return task_result
            
        except asyncio.TimeoutError:
            error_msg = f"Task execution timed out after {self.task_timeout} seconds"
            logger.error(f"Task {task.id} failed: {error_msg}")
            
            # Create timeout error result
            task_result = await self._create_error_result(
                task, error_msg, ErrorCode.TASK_TIMEOUT, task_start_time
            )
            
            # Emit task failed event
            await self._emit_task_failed(task, error_msg)
            
            return task_result
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Task {task.id} failed with error: {error_msg}")
            
            # Determine error code based on exception type
            from gleitzeit.core.errors import is_retryable_error, GleitzeitError
            
            if isinstance(e, GleitzeitError):
                error_code = e.code
            else:
                error_code = ErrorCode.TASK_EXECUTION_FAILED
            
            # Create error result
            task_result = await self._create_error_result(
                task, error_msg, error_code, task_start_time
            )
            
            # Emit task failed event - stateless system will determine retryability
            await self._emit_task_failed(task, error_msg)
            
            return task_result
            
    async def _route_and_execute(self, task: Task, params: Dict[str, Any]) -> Any:
        """
        Route task to appropriate provider via pooling adapter.
        
        Args:
            task: Task to execute
            params: Resolved parameters
            
        Returns:
            Execution result from provider
            
        Raises:
            TaskTimeoutError: If execution times out
            TaskExecutionError: If execution fails or pooling adapter not available
        """
        # Pooling adapter is required - no fallback
        if not self.pooling_adapter:
            raise TaskExecutionError(
                task_id=task.id,
                message=f"No pooling adapter available for task execution"
            )
        
        if not self.pooling_adapter.is_protocol_available(task.protocol):
            raise TaskExecutionError(
                task_id=task.id,
                message=f"Protocol {task.protocol} not available in provider pool"
            )
        
        logger.debug(f"Routing task {task.id} via pooling adapter")
        
        # Execute via pooling system with timeout
        try:
            result = await asyncio.wait_for(
                self.pooling_adapter.execute_task(task),
                timeout=float(self.task_timeout)
            )
            return result
            
        except asyncio.TimeoutError:
            raise TaskTimeoutError(
                task_id=task.id,
                timeout=self.task_timeout
            )
                
    async def _update_task_status(
        self, 
        task: Task, 
        status: TaskStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None
    ):
        """Update task status in persistence."""
        task.status = status
        
        if started_at:
            task.started_at = started_at
        if completed_at:
            task.completed_at = completed_at
            
        if self.persistence:
            await self.persistence.save_task(task)
            logger.debug(f"Task {task.id} status updated to {status}")
            
    async def _create_error_result(
        self,
        task: Task,
        error_msg: str,
        error_code: ErrorCode,
        start_time: datetime
    ) -> TaskResult:
        """Create error task result."""
        task_result = TaskResult(
            task_id=task.id,
            status=TaskStatus.FAILED,
            result=None,
            error=error_msg,  # TaskResult expects string, not JSONRPCError
            started_at=start_time,
            completed_at=datetime.utcnow(),
            metadata={"executor": "TaskExecutor", "error_code": error_code.value}
        )
        
        # Update task status
        await self._update_task_status(
            task, 
            TaskStatus.FAILED, 
            completed_at=task_result.completed_at
        )
        
        # Store result
        if self.persistence:
            await self.persistence.save_task_result(task_result)
            
        return task_result
        
    async def _emit_task_started(self, task: Task):
        """Emit task started event."""
        if not self.event_bus:
            return
            
        event = create_task_started_event(
            task_id=task.id,
            task_name=task.name or task.id,  # Use name or fallback to id
            protocol=task.protocol,
            method=task.method,
            workflow_id=task.workflow_id,
            source="task_executor"
        )
        await self.event_bus.emit(event)
        logger.debug(f"Emitted TASK_STARTED event for {task.id}")
        
    async def _emit_task_completed(self, task: Task, result: TaskResult):
        """Emit task completed event."""
        if not self.event_bus:
            return
            
        event = create_task_completed_event(
            task_id=task.id,
            workflow_id=task.workflow_id,
            duration=(result.completed_at - result.started_at).total_seconds() if result.started_at else 0,
            source="task_executor"
        )
        await self.event_bus.emit(event)
        logger.debug(f"Emitted TASK_COMPLETED event for {task.id}")
        
    async def _emit_task_failed(self, task: Task, error_msg: str):
        """Emit task failed event - stateless, no retryability determination here."""
        if not self.event_bus:
            return
            
        event = create_task_failed_event(
            task_id=task.id,
            error_message=error_msg,
            workflow_id=task.workflow_id,
            source="task_executor"
        )
        await self.event_bus.emit(event)
        logger.debug(f"Emitted TASK_FAILED event for {task.id}")
        
    async def validate_task(self, task: Task) -> bool:
        """
        Validate that a task can be executed.
        
        Args:
            task: Task to validate
            
        Returns:
            True if task is valid
            
        Raises:
            ValueError: If task is invalid
        """
        if not task.protocol:
            raise ValueError(f"Task {task.id} has no protocol specified")
            
        if not task.method:
            raise ValueError(f"Task {task.id} has no method specified")
            
        # Check if protocol is supported
        if not self.registry.is_protocol_available(task.protocol):
            if self.pooling_adapter:
                if not self.pooling_adapter.is_protocol_available(task.protocol):
                    raise ValueError(f"Protocol {task.protocol} not available")
            else:
                raise ValueError(f"Protocol {task.protocol} not available")
                
        return True