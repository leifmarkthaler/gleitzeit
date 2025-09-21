"""
Stream-based Execution Engine for Gleitzeit.

Pure stream-based execution engine that integrates with the stream event system
for scalable, distributed task and workflow execution.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

from .models import Task, Workflow, TaskStatus, TaskResult, WorkflowStatus
from .task_executor import TaskExecutor
from .dependency_manager import UnifiedDependencyManager
from .parameter_resolver import ParameterResolver
from .events import EventType, GleitzeitEvent
from .logging_mixin import LoggingMixin
from .errors import ConfigurationError, ExecutionError
from ..task_queue import QueueManager
from ..persistence.base import PersistenceBackend
from ..events import EventBus
from ..scheduler import StatelessScheduler

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Execution modes for the stream engine."""
    STREAM_DRIVEN = "stream_driven"  # Pure stream-based processing
    EVENT_DRIVEN = "event_driven"   # Event-driven processing
    WORKFLOW_ONLY = "workflow_only"  # Only process complete workflows


@dataclass
class StreamExecutionStats:
    """Statistics for stream execution engine."""
    tasks_processed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    workflows_completed: int = 0
    workflows_failed: int = 0
    events_handled: int = 0
    last_execution_time: Optional[datetime] = None


class StreamExecutionEngine(LoggingMixin):
    """
    Pure stream-based execution engine.

    Features:
    - Stream-based task execution coordination
    - Event-driven workflow processing
    - Integration with StatelessScheduler
    - Horizontal scaling via consumer groups
    - No polling loops - pure event-driven
    """

    def __init__(
        self,
        pooling_adapter: Any,
        queue_manager: QueueManager,
        stream_scheduler: StatelessScheduler,
        dependency_resolver: Any = None,
        persistence: Optional[PersistenceBackend] = None,
        max_concurrent_tasks: int = 10,
        event_bus: Optional[EventBus] = None,
        task_timeout: int = 300,
        instance_id: Optional[str] = None,
        execution_mode: ExecutionMode = ExecutionMode.STREAM_DRIVEN
    ):
        """
        Initialize StreamExecutionEngine.

        Args:
            pooling_adapter: Pooling adapter for provider access
            queue_manager: Queue manager for task management
            stream_scheduler: Stream event scheduler for coordination
            dependency_resolver: Dependency resolver
            persistence: Persistence backend
            max_concurrent_tasks: Maximum concurrent task executions
            event_bus: Event bus for coordination
            task_timeout: Default task timeout in seconds
            instance_id: Instance identifier
            execution_mode: Execution mode
        """
        if not pooling_adapter:
            raise ConfigurationError("StreamExecutionEngine requires a pooling_adapter")
        if not stream_scheduler:
            raise ConfigurationError("StreamExecutionEngine requires a stream_scheduler")

        super().__init__()

        self.pooling_adapter = pooling_adapter
        self.queue_manager = queue_manager
        self.stream_scheduler = stream_scheduler
        self.dependency_resolver = dependency_resolver
        self.persistence = persistence
        self.max_concurrent_tasks = max_concurrent_tasks
        self.event_bus = event_bus
        self.task_timeout = task_timeout
        self.instance_id = instance_id or f"stream-engine-{asyncio.current_task().get_name()}"
        self.execution_mode = execution_mode

        # Task executor
        self.task_executor = TaskExecutor(
            pooling_adapter=pooling_adapter,
            queue_manager=queue_manager,
            persistence=persistence,
            event_bus=event_bus,
            task_timeout=task_timeout,
            max_concurrent_tasks=max_concurrent_tasks
        )

        # Create dependency resolver if not provided
        if not self.dependency_resolver and persistence:
            self.dependency_resolver = UnifiedDependencyManager(persistence)

        # Parameter resolver
        self.parameter_resolver = ParameterResolver()

        # Statistics
        self.stats = StreamExecutionStats()

        # Running state
        self._running = False
        self._execution_task: Optional[asyncio.Task] = None

        logger.info(f"Initialized StreamExecutionEngine (mode: {execution_mode.value})")

    async def initialize(self):
        """Initialize the execution engine."""
        try:
            # Initialize task executor
            await self.task_executor.initialize()

            # Register event handlers with stream scheduler
            await self._register_event_handlers()

            logger.info("StreamExecutionEngine initialized")

        except Exception as e:
            logger.error(f"Failed to initialize StreamExecutionEngine: {e}")
            raise

    async def start(self):
        """Start the execution engine."""
        if self._running:
            logger.warning("StreamExecutionEngine already running")
            return

        self._running = True

        # Start task executor
        await self.task_executor.start()

        logger.info("StreamExecutionEngine started")

    async def stop(self):
        """Stop the execution engine."""
        self._running = False

        # Stop task executor
        if self.task_executor:
            await self.task_executor.stop()

        logger.info("StreamExecutionEngine stopped")

    async def shutdown(self):
        """Shutdown the execution engine."""
        await self.stop()

        if self.task_executor:
            await self.task_executor.shutdown()

        logger.info("StreamExecutionEngine shutdown complete")

    async def _register_event_handlers(self):
        """Register event handlers with the stream scheduler."""
        # Register handlers for execution events
        await self.stream_scheduler.register_handler("task_execute", self._handle_task_execution)
        await self.stream_scheduler.register_handler("workflow_execute", self._handle_workflow_execution)
        await self.stream_scheduler.register_handler("task_retry", self._handle_task_retry)
        await self.stream_scheduler.register_handler("workflow_step", self._handle_workflow_step)

        logger.info("Registered execution event handlers")

    async def submit_task(
        self,
        task: Task,
        priority: int = 0,
        delay_seconds: float = 0
    ) -> str:
        """
        Submit a task for execution via streams.

        Args:
            task: Task to execute
            priority: Task priority
            delay_seconds: Delay before execution

        Returns:
            Task execution ID
        """
        try:
            # Schedule task execution event
            event_id = await self.stream_scheduler.schedule_event(
                event_type="task_execute",
                delay_seconds=delay_seconds,
                payload={
                    "task": task.to_dict(),
                    "priority": priority,
                    "submitted_by": self.instance_id,
                    "submitted_at": datetime.utcnow().isoformat()
                },
                shard_key=task.workflow_id  # Shard by workflow for consistency
            )

            # Store task in queue for tracking
            await self.queue_manager.enqueue_task(task, priority=priority)

            logger.info(f"Submitted task {task.task_id} for execution (event: {event_id})")
            return event_id

        except Exception as e:
            logger.error(f"Failed to submit task {task.task_id}: {e}")
            raise ExecutionError(f"Task submission failed: {e}")

    async def submit_workflow(
        self,
        workflow: Workflow,
        priority: int = 0,
        delay_seconds: float = 0
    ) -> str:
        """
        Submit a workflow for execution via streams.

        Args:
            workflow: Workflow to execute
            priority: Workflow priority
            delay_seconds: Delay before execution

        Returns:
            Workflow execution ID
        """
        try:
            # Schedule workflow execution event
            event_id = await self.stream_scheduler.schedule_event(
                event_type="workflow_execute",
                delay_seconds=delay_seconds,
                payload={
                    "workflow": workflow.to_dict(),
                    "priority": priority,
                    "submitted_by": self.instance_id,
                    "submitted_at": datetime.utcnow().isoformat()
                },
                shard_key=workflow.workflow_id
            )

            logger.info(f"Submitted workflow {workflow.workflow_id} for execution (event: {event_id})")
            return event_id

        except Exception as e:
            logger.error(f"Failed to submit workflow {workflow.workflow_id}: {e}")
            raise ExecutionError(f"Workflow submission failed: {e}")

    async def _handle_task_execution(self, event_data: Dict[str, Any]):
        """Handle task execution event from stream."""
        try:
            payload = event_data.get("payload", {})
            task_data = payload.get("task", {})

            if not task_data:
                logger.warning(f"No task data in execution event: {event_data}")
                return

            # Reconstruct task from data
            task = Task.from_dict(task_data)

            # Check if task is still valid
            if not await self._is_task_valid(task):
                logger.info(f"Task {task.task_id} is no longer valid, skipping")
                return

            # Resolve dependencies if needed
            if self.dependency_resolver and task.depends_on:
                resolved = await self.dependency_resolver.resolve_dependencies(task.task_id)
                if not resolved:
                    logger.info(f"Dependencies not ready for task {task.task_id}, will retry")
                    await self._schedule_task_retry(task, delay_seconds=30)
                    return

            # Execute the task
            result = await self.task_executor.execute_task(task)

            # Update statistics
            self.stats.tasks_processed += 1
            self.stats.last_execution_time = datetime.utcnow()

            if result.status == TaskStatus.COMPLETED:
                self.stats.tasks_succeeded += 1
            elif result.status == TaskStatus.FAILED:
                self.stats.tasks_failed += 1

            # Emit completion event
            if self.event_bus:
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.TASK_COMPLETED if result.status == TaskStatus.COMPLETED else EventType.TASK_FAILED,
                    data={
                        "task_id": task.task_id,
                        "workflow_id": task.workflow_id,
                        "result": result.to_dict() if result else None,
                        "execution_time": result.execution_time if result else None
                    }
                ))

            self.stats.events_handled += 1

        except Exception as e:
            logger.error(f"Error handling task execution event: {e}")
            self.stats.tasks_failed += 1

    async def _handle_workflow_execution(self, event_data: Dict[str, Any]):
        """Handle workflow execution event from stream."""
        try:
            payload = event_data.get("payload", {})
            workflow_data = payload.get("workflow", {})

            if not workflow_data:
                logger.warning(f"No workflow data in execution event: {event_data}")
                return

            # Reconstruct workflow from data
            workflow = Workflow.from_dict(workflow_data)

            # Start workflow execution by submitting first tasks
            await self._start_workflow_execution(workflow)

            self.stats.events_handled += 1

        except Exception as e:
            logger.error(f"Error handling workflow execution event: {e}")
            self.stats.workflows_failed += 1

    async def _handle_task_retry(self, event_data: Dict[str, Any]):
        """Handle task retry event from stream."""
        try:
            payload = event_data.get("payload", {})
            task_data = payload.get("task", {})

            if not task_data:
                logger.warning(f"No task data in retry event: {event_data}")
                return

            task = Task.from_dict(task_data)

            # Re-submit for execution
            await self._handle_task_execution({"payload": {"task": task_data}})

        except Exception as e:
            logger.error(f"Error handling task retry event: {e}")

    async def _handle_workflow_step(self, event_data: Dict[str, Any]):
        """Handle workflow step progression event."""
        try:
            payload = event_data.get("payload", {})
            workflow_id = payload.get("workflow_id")
            completed_task_id = payload.get("completed_task_id")

            if not workflow_id:
                logger.warning(f"No workflow_id in step event: {event_data}")
                return

            # Check if workflow can progress
            await self._check_workflow_progression(workflow_id, completed_task_id)

            self.stats.events_handled += 1

        except Exception as e:
            logger.error(f"Error handling workflow step event: {e}")

    async def _is_task_valid(self, task: Task) -> bool:
        """Check if a task is still valid for execution."""
        try:
            if not self.persistence:
                return True

            # Check if task still exists and is in valid state
            task_data = await self.persistence.get_task(task.task_id)
            if not task_data:
                return False

            # Check if task is not already completed or cancelled
            current_status = task_data.get("status")
            if current_status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]:
                return False

            return True

        except Exception as e:
            logger.warning(f"Error checking task validity for {task.task_id}: {e}")
            return True  # Default to valid if we can't check

    async def _schedule_task_retry(self, task: Task, delay_seconds: float = 60):
        """Schedule a task for retry."""
        try:
            await self.stream_scheduler.schedule_event(
                event_type="task_retry",
                delay_seconds=delay_seconds,
                payload={
                    "task": task.to_dict(),
                    "retry_count": task.retry_count + 1,
                    "retried_by": self.instance_id,
                    "retried_at": datetime.utcnow().isoformat()
                },
                shard_key=task.workflow_id
            )

            logger.info(f"Scheduled retry for task {task.task_id} in {delay_seconds}s")

        except Exception as e:
            logger.error(f"Failed to schedule task retry for {task.task_id}: {e}")

    async def _start_workflow_execution(self, workflow: Workflow):
        """Start workflow execution by identifying and submitting initial tasks."""
        try:
            # Find tasks with no dependencies (initial tasks)
            initial_tasks = []
            for task in workflow.tasks:
                if not task.depends_on:
                    initial_tasks.append(task)

            if not initial_tasks:
                logger.warning(f"No initial tasks found in workflow {workflow.workflow_id}")
                return

            # Submit initial tasks for execution
            for task in initial_tasks:
                await self.submit_task(task, delay_seconds=0)

            logger.info(f"Started workflow {workflow.workflow_id} with {len(initial_tasks)} initial tasks")

        except Exception as e:
            logger.error(f"Failed to start workflow execution for {workflow.workflow_id}: {e}")
            raise

    async def _check_workflow_progression(self, workflow_id: str, completed_task_id: str):
        """Check if workflow can progress after task completion."""
        try:
            if not self.persistence:
                return

            # Get workflow data
            workflow_data = await self.persistence.get_workflow(workflow_id)
            if not workflow_data:
                logger.warning(f"Workflow {workflow_id} not found for progression check")
                return

            workflow = Workflow.from_dict(workflow_data)

            # Find tasks that can now be executed
            ready_tasks = []
            for task in workflow.tasks:
                if task.status == TaskStatus.PENDING and task.depends_on:
                    # Check if all dependencies are completed
                    deps_ready = await self._check_task_dependencies(task, workflow)
                    if deps_ready:
                        ready_tasks.append(task)

            # Submit ready tasks
            for task in ready_tasks:
                await self.submit_task(task, delay_seconds=0)

            if ready_tasks:
                logger.info(f"Submitted {len(ready_tasks)} ready tasks for workflow {workflow_id}")

            # Check if workflow is complete
            await self._check_workflow_completion(workflow)

        except Exception as e:
            logger.error(f"Error checking workflow progression for {workflow_id}: {e}")

    async def _check_task_dependencies(self, task: Task, workflow: Workflow) -> bool:
        """Check if all task dependencies are satisfied."""
        if not task.depends_on:
            return True

        try:
            for dep_task_id in task.depends_on:
                # Find dependency task in workflow
                dep_task = next((t for t in workflow.tasks if t.task_id == dep_task_id), None)
                if not dep_task:
                    logger.warning(f"Dependency task {dep_task_id} not found in workflow")
                    return False

                if dep_task.status != TaskStatus.COMPLETED:
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking dependencies for task {task.task_id}: {e}")
            return False

    async def _check_workflow_completion(self, workflow: Workflow):
        """Check if workflow is complete and update status."""
        try:
            # Check if all tasks are complete
            all_complete = all(task.status == TaskStatus.COMPLETED for task in workflow.tasks)
            any_failed = any(task.status == TaskStatus.FAILED for task in workflow.tasks)

            if all_complete:
                workflow.status = WorkflowStatus.COMPLETED
                self.stats.workflows_completed += 1

                if self.event_bus:
                    await self.event_bus.emit(GleitzeitEvent(
                        event_type=EventType.WORKFLOW_COMPLETED,
                        data={"workflow_id": workflow.workflow_id}
                    ))

                logger.info(f"Workflow {workflow.workflow_id} completed successfully")

            elif any_failed:
                workflow.status = WorkflowStatus.FAILED
                self.stats.workflows_failed += 1

                if self.event_bus:
                    await self.event_bus.emit(GleitzeitEvent(
                        event_type=EventType.WORKFLOW_FAILED,
                        data={"workflow_id": workflow.workflow_id}
                    ))

                logger.info(f"Workflow {workflow.workflow_id} failed")

            # Update workflow status in persistence
            if self.persistence and workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                await self.persistence.update_workflow(workflow.workflow_id, {"status": workflow.status.value})

        except Exception as e:
            logger.error(f"Error checking workflow completion for {workflow.workflow_id}: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get execution engine statistics."""
        return {
            "instance_id": self.instance_id,
            "execution_mode": self.execution_mode.value,
            "running": self._running,
            "stream_based": True,
            "statistics": {
                "tasks_processed": self.stats.tasks_processed,
                "tasks_succeeded": self.stats.tasks_succeeded,
                "tasks_failed": self.stats.tasks_failed,
                "workflows_completed": self.stats.workflows_completed,
                "workflows_failed": self.stats.workflows_failed,
                "events_handled": self.stats.events_handled,
                "last_execution_time": self.stats.last_execution_time.isoformat() if self.stats.last_execution_time else None
            },
            "task_executor": self.task_executor.get_statistics() if hasattr(self.task_executor, 'get_statistics') else {}
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        health = {
            "healthy": True,
            "instance_id": self.instance_id,
            "running": self._running,
            "stream_based": True,
            "components": {
                "task_executor": await self.task_executor.health_check() if hasattr(self.task_executor, 'health_check') else {"status": "unknown"},
                "stream_scheduler": {"status": "connected" if self.stream_scheduler else "missing"},
                "dependency_resolver": {"status": "connected" if self.dependency_resolver else "missing"},
                "persistence": {"status": "connected" if self.persistence else "missing"}
            }
        }

        # Check component health
        for component, status in health["components"].items():
            if status.get("status") == "unhealthy":
                health["healthy"] = False
                break

        return health