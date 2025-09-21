"""
Simplified Execution Engine V2 for Gleitzeit

Refactored to delegate to specialized components for clean separation of concerns.
This is a lightweight coordinator that uses:
- StatelessTaskOrchestrator for task execution coordination (no loops!)
- TaskExecutor for actual task execution
- UnifiedDependencyManager for dependency resolution
- RetryManager for retry logic
- WorkflowManager for workflow lifecycle (via events)
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from dataclasses import dataclass

from gleitzeit.core.models import Task, Workflow, TaskStatus, TaskResult, WorkflowStatus
from gleitzeit.core.task_executor import TaskExecutor
from gleitzeit.core.stateless_task_orchestrator import StatelessTaskOrchestrator
from gleitzeit.core.dependency_manager import UnifiedDependencyManager
from gleitzeit.core.parameter_resolver import ParameterResolver
from gleitzeit.core.event_driven_retry_manager import EventDrivenRetryManager
from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.core.logging_mixin import LoggingMixin
from gleitzeit.task_queue import QueueManager
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.events import EventBus
from gleitzeit.core.errors import ConfigurationError
import os

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Execution modes for the engine"""
    EVENT_DRIVEN = "event_driven"  # Default mode, respond to events
    WORKFLOW_ONLY = "workflow_only"  # Only process complete workflows
    SINGLE_SHOT = "single_shot"  # Execute one task and stop (testing)


@dataclass
class ExecutionStats:
    """Statistics for execution engine"""
    tasks_processed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    workflows_completed: int = 0
    workflows_failed: int = 0


class ExecutionEngineV2(LoggingMixin):
    """
    Simplified Execution Engine that delegates to specialized components.
    
    This engine is now a thin coordination layer that:
    - Manages engine lifecycle (start/stop)
    - Delegates task execution to TaskOrchestrator
    - Provides high-level API for task/workflow submission
    - Coordinates between specialized managers
    
    All heavy lifting is done by:
    - StatelessTaskOrchestrator: Task scheduling and coordination (no loops!)
    - TaskExecutor: Actual task execution
    - UnifiedDependencyManager: Dependency resolution
    - RetryManager: Retry handling
    - WorkflowManager: Workflow lifecycle (via events)
    """
    
    def __init__(
        self,
        pooling_adapter: Any,  # Required for provider access
        queue_manager: QueueManager,
        dependency_resolver: Any = None,  # Optional, will create if not provided
        persistence: Optional[PersistenceBackend] = None,
        max_concurrent_tasks: int = 10,
        event_bus: Optional[EventBus] = None,
        task_timeout: int = 300,
        instance_id: Optional[str] = None
    ):
        """
        Initialize ExecutionEngineV2 with required components.
        
        Args:
            pooling_adapter: Pooling adapter for provider access (required)
            queue_manager: Queue manager for task management
            dependency_resolver: Optional dependency resolver (will create if not provided)
            persistence: Persistence backend
            max_concurrent_tasks: Maximum concurrent task executions
            event_bus: Event bus for coordination
            task_timeout: Default task timeout in seconds
        """
        if not pooling_adapter:
            raise ConfigurationError("ExecutionEngineV2 requires a pooling_adapter")
            
        # Initialize LoggingMixin
        super().__init__()
        
        self.pooling_adapter = pooling_adapter
        self.queue_manager = queue_manager
        self.persistence = persistence
        self.event_bus = event_bus
        self.max_concurrent_tasks = max_concurrent_tasks
        self.task_timeout = task_timeout
        self.instance_id = instance_id
        
        # Initialize specialized components
        self._init_components(pooling_adapter, dependency_resolver)
        
        # Engine state
        self._running = False
        self._mode = ExecutionMode.EVENT_DRIVEN
        self._stats = ExecutionStats()
        
        # Setup event handlers
        self._setup_event_handlers()
        
        # Note: Initial setup logging will be done on first async operation
        logger.info(f"Initialized ExecutionEngineV2 with max_concurrent_tasks={max_concurrent_tasks}")

    def register_with_stream_manager(self, stream_manager):
        """
        Register handlers with StreamSystemManager.

        This allows the orchestrator's handlers to be invoked
        by the MultiplexedStreamConsumer for stream-based events.

        Args:
            stream_manager: StreamSystemManager instance
        """
        if hasattr(self.task_orchestrator, 'register_with_stream_manager'):
            self.task_orchestrator.register_with_stream_manager(stream_manager)
            logger.info("ExecutionEngineV2 registered handlers with StreamSystemManager")
        
    def _init_components(self, pooling_adapter: Optional[Any], legacy_resolver: Any):
        """Initialize specialized components."""
        # Pooling adapter is required for clean architecture
        if not pooling_adapter:
            raise ConfigurationError("ExecutionEngineV2 requires a pooling_adapter for provider access")
        
        # Create unified dependency manager
        self.dependency_manager = UnifiedDependencyManager(
            persistence=self.persistence,
            max_attempts=3,
            attempt_timeout=300
        )
        
        # Create parameter resolver
        self.parameter_resolver = ParameterResolver(self.persistence) if self.persistence else None
        
        # Create task executor with required pooling adapter
        self.task_executor = TaskExecutor(
            pooling_adapter=pooling_adapter,
            persistence=self.persistence,
            parameter_resolver=self.parameter_resolver,
            event_bus=self.event_bus,
            task_timeout=self.task_timeout
        )
        
        # Create stateless task orchestrator (no persistent loops!)
        # Stream transport is handled at the QueueManager level
        self.task_orchestrator = StatelessTaskOrchestrator(
            queue_manager=self.queue_manager,
            dependency_manager=self.dependency_manager,
            task_executor=self.task_executor,
            persistence=self.persistence,
            event_bus=self.event_bus,
            max_concurrent_tasks=self.max_concurrent_tasks,
            instance_id=self.instance_id
        )
        
        # Always using Redis Streams for unified transport
        logger.info("Using Redis Streams for reliable event transport")
        
        # Initialize retry manager (reuse existing)
        if self.event_bus:
            from gleitzeit.core.event_driven_retry_manager import EventDrivenRetryManager
            self.retry_manager = EventDrivenRetryManager(
                persistence=self.persistence,
                scheduler=None,  # Will be set if needed
                event_bus=self.event_bus
            )
        else:
            self.retry_manager = RetryManager(
                queue_manager=self.queue_manager,
                persistence=self.persistence,
                scheduler=None,
                event_bus=None
            )
            
    def _setup_event_handlers(self):
        """Setup event subscriptions."""
        if not self.event_bus:
            return
            
        # Listen for workflow and task completion events for stats
        self.event_bus.register(EventType.TASK_COMPLETED, self._on_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._on_task_failed)
        self.event_bus.register(EventType.WORKFLOW_COMPLETED, self._on_workflow_completed)
        self.event_bus.register(EventType.WORKFLOW_FAILED, self._on_workflow_failed)
        
    async def start(self, mode: ExecutionMode = ExecutionMode.EVENT_DRIVEN) -> None:
        """
        Start the execution engine.
        
        Args:
            mode: Execution mode to use
        """
        if self._running:
            await self.log_debug(
                "execution_engine_already_running",
                "ExecutionEngine already running, ignoring start request",
                mode=mode.value
            )
            logger.warning("ExecutionEngine already running")
            return
        
        await self.log_operation(
            "execution_engine_start",
            mode=mode.value,
            max_concurrent_tasks=self.max_concurrent_tasks
        )
            
        self._mode = mode
        self._running = True
        
        logger.info(f"Starting ExecutionEngineV2 in {mode.value} mode")
        
        # Start retry manager if available
        if self.retry_manager:
            await self.log_debug(
                "retry_manager_start",
                "Starting retry manager"
            )
            await self.retry_manager.start()
            
        # Start task orchestrator
        await self.log_debug(
            "orchestrator_start",
            "Starting task orchestrator"
        )
        await self.task_orchestrator.start()
        
        # Emit engine started event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.ENGINE_STARTED,
                data={"mode": mode.value}
            ))
            
        await self.log_success(
            "execution_engine_started",
            description="ExecutionEngineV2 started successfully",
            mode=mode.value
        )
        
        logger.info("ExecutionEngineV2 started successfully")
        
    async def stop(self) -> None:
        """Stop the execution engine."""
        if not self._running:
            await self.log_debug(
                "execution_engine_not_running",
                "ExecutionEngine not running, ignoring stop request"
            )
            logger.warning("ExecutionEngine not running")
            return
        
        await self.log_operation(
            "execution_engine_stop",
            final_stats=self.get_stats()
        )
            
        logger.info("Stopping ExecutionEngineV2...")
        
        self._running = False
        
        # Stop orchestrator
        await self.log_debug(
            "orchestrator_stop",
            "Stopping task orchestrator"
        )
        await self.task_orchestrator.stop()
        
        # Stop retry manager
        if self.retry_manager:
            await self.log_debug(
                "retry_manager_stop",
                "Stopping retry manager"
            )
            await self.retry_manager.stop()
            
        # Emit engine stopped event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.ENGINE_STOPPED,
                data={"stats": self.get_stats()}
            ))
        
        await self.log_success(
            "execution_engine_stopped",
            description="ExecutionEngineV2 stopped successfully",
            final_stats=self.get_stats()
        )
            
        logger.info("ExecutionEngineV2 stopped")
        
    async def submit_task(self, task: Task, queue_name: Optional[str] = None) -> None:
        """
        Submit a single task for execution.
        
        Args:
            task: Task to submit
            queue_name: Optional queue name
        """
        await self.log_operation(
            "task_submit_start",
            task_id=task.id,
            task_name=task.name,
            protocol=task.protocol,
            method=task.method,
            queue_name=queue_name or "default",
            workflow_id=task.workflow_id
        )
        
        # Validate task
        await self.task_executor.validate_task(task)
        
        # Save to persistence
        if self.persistence:
            await self.log_debug(
                "task_persistence_save",
                "Saving task to persistence",
                task_id=task.id
            )
            await self.persistence.save_task(task)
            
        # Enqueue task
        await self.log_debug(
            "task_enqueue",
            "Enqueueing task for execution",
            task_id=task.id,
            queue_name=queue_name or "default"
        )
        await self.queue_manager.enqueue_task(task, queue_name)
        
        # Emit task submitted event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_SUBMITTED,
                data={
                    "task_id": task.id,
                    "task_name": task.name,
                    "protocol": task.protocol,
                    "queue": queue_name
                }
            ))
        
        await self.log_success(
            "task_submitted",
            description="Task submitted successfully",
            task_id=task.id,
            queue_name=queue_name or "default"
        )
            
        logger.info(f"Task {task.id} submitted to queue {queue_name or 'default'}")
        
    async def submit_workflow(self, workflow: Workflow, queue_name: Optional[str] = None) -> str:
        """
        Submit a workflow for execution.
        
        Args:
            workflow: Workflow to submit
            queue_name: Optional queue name
            
        Returns:
            The workflow ID
        """
        await self.log_operation(
            "workflow_submit",
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            task_count=len(workflow.tasks),
            queue_name=queue_name or "default"
        )
        
        # Delegate to orchestrator
        await self.task_orchestrator.submit_workflow(workflow)
        
        await self.log_success(
            "workflow_submitted",
            description="Workflow submitted successfully",
            workflow_id=workflow.id,
            task_count=len(workflow.tasks)
        )
        
        logger.info(f"Workflow {workflow.id} submitted with {len(workflow.tasks)} tasks")
        
        # Return the workflow ID
        return workflow.id
        
    async def execute_task(self, task: Task) -> TaskResult:
        """
        Execute a single task directly (bypassing queue).
        
        Args:
            task: Task to execute
            
        Returns:
            Task execution result
        """
        await self.log_operation(
            "task_execute_direct",
            task_id=task.id,
            task_name=task.name,
            protocol=task.protocol,
            method=task.method
        )
        
        try:
            result = await self.task_executor.execute_task(task)
            
            await self.log_success(
                "task_execute_direct_complete",
                description="Direct task execution completed",
                task_id=task.id,
                status=result.status.value if result.status else "unknown",
                success=result.success if hasattr(result, 'success') else None
            )
            
            return result
            
        except Exception as e:
            await self.log_error(
                "task_execute_direct_failed",
                f"Direct task execution failed: {str(e)}",
                task_id=task.id,
                error=str(e),
                error_type=type(e).__name__
            )
            raise
        
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """
        Get result for a specific task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task result if available
        """
        await self.log_debug(
            "task_result_query",
            "Querying task result",
            task_id=task_id
        )
        
        if not self.persistence:
            await self.log_debug(
                "task_result_no_persistence",
                "No persistence available for task result query",
                task_id=task_id
            )
            return None
        
        result = await self.persistence.get_task_result(task_id)
        
        await self.log_debug(
            "task_result_retrieved",
            "Task result retrieved",
            task_id=task_id,
            found=bool(result),
            status=result.status.value if result and result.status else None
        )
        
        return result
        
    async def get_workflow_results(self, workflow_id: str) -> List[TaskResult]:
        """
        Get all task results for a workflow.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            List of task results
        """
        if not self.persistence:
            return []
            
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return []
            
        results = []
        for task in workflow.tasks:
            result = await self.persistence.get_task_result(task.id)
            if result:
                results.append(result)
                
        return results
        
    def get_stats(self) -> Dict[str, Any]:
        """Get execution engine statistics."""
        stats = {
            "tasks_processed": self._stats.tasks_processed,
            "tasks_succeeded": self._stats.tasks_succeeded,
            "tasks_failed": self._stats.tasks_failed,
            "workflows_completed": self._stats.workflows_completed,
            "workflows_failed": self._stats.workflows_failed,
            "orchestrator_stats": self.task_orchestrator.get_statistics(),
            "dependency_stats": self.dependency_manager.get_statistics()
        }
        
        if hasattr(self.retry_manager, 'get_retry_stats'):
            stats["retry_stats"] = asyncio.run(self.retry_manager.get_retry_stats())
            
        return stats
        
    async def emit_event(self, event: Union[GleitzeitEvent, str], data: Optional[Dict[str, Any]] = None) -> None:
        """
        Emit an event (for compatibility).
        
        Args:
            event: Event to emit (GleitzeitEvent or event type string)
            data: Optional event data
        """
        if not self.event_bus:
            return
            
        if isinstance(event, str):
            # Convert string to GleitzeitEvent
            event = GleitzeitEvent(
                event_type=EventType(event),
                data=data or {}
            )
            
        await self.event_bus.emit(event)
        
    # Event handlers for statistics
    
    async def _on_task_completed(self, event: GleitzeitEvent):
        """Handle task completion for stats."""
        self._stats.tasks_processed += 1
        self._stats.tasks_succeeded += 1
        
    async def _on_task_failed(self, event: GleitzeitEvent):
        """Handle task failure for stats."""
        self._stats.tasks_processed += 1
        self._stats.tasks_failed += 1
        
    async def _on_workflow_completed(self, event: GleitzeitEvent):
        """Handle workflow completion for stats."""
        self._stats.workflows_completed += 1
        
    async def _on_workflow_failed(self, event: GleitzeitEvent):
        """Handle workflow failure for stats."""
        self._stats.workflows_failed += 1
        
    # Compatibility methods (delegate to components)
    
    async def get_retry_stats(self) -> Dict[str, Any]:
        """Get retry statistics from the retry manager."""
        if hasattr(self.retry_manager, 'get_retry_stats'):
            return await self.retry_manager.get_retry_stats()
        return {}
        
    def is_running(self) -> bool:
        """Check if engine is running."""
        return self._running
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """
        Get task execution result from persistence.
        
        Args:
            task_id: Task ID
            
        Returns:
            TaskResult or None if not found
        """
        if self.persistence:
            return await self.persistence.get_task_result(task_id)
        return None
    
    async def get_workflow_results(self, workflow_id: str) -> List[TaskResult]:
        """
        Get all task results for a workflow.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            List of TaskResult objects
        """
        results = []
        if self.persistence:
            # Get all tasks for the workflow
            tasks = await self.persistence.get_tasks_by_workflow(workflow_id)
            
            # Get result for each task
            for task in tasks:
                result = await self.persistence.get_task_result(task.id)
                if result:
                    results.append(result)
                    
        return results