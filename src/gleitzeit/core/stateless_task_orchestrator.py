"""
Stateless Task Orchestrator for Gleitzeit

Event-driven orchestrator without persistent loops.
Processing is triggered externally rather than via continuous polling.
"""

import asyncio
import logging
import os
from typing import Optional, Dict, Any, List
from collections import defaultdict
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.core.task_executor import TaskExecutor
from gleitzeit.core.dependency_manager import UnifiedDependencyManager
from gleitzeit.core.parameter_resolver import ParameterResolver
from gleitzeit.core.errors import (
    TaskError, TaskExecutionError, WorkflowError, WorkflowValidationError,
    PersistenceError, QueueError, ConfigurationError
)
from gleitzeit.task_queue import QueueManager
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.events import EventBus
from gleitzeit.core.events import EventType, GleitzeitEvent

logger = logging.getLogger(__name__)


class StatelessTaskOrchestrator:
    """
    Stateless task orchestration coordinator.

    Key differences from the original:
    - NO persistent loops or polling
    - Leader election is single-check, not continuous
    - Processing triggered via events or external calls
    - TTL-based leadership with external refresh

    This orchestrator acts as a thin coordination layer that:
    - Processes tasks on-demand when triggered
    - Checks dependencies
    - Routes to TaskExecutor for execution
    - Handles task completion and workflow progression
    """

    def __init__(
        self,
        queue_manager: QueueManager,
        dependency_manager: UnifiedDependencyManager,
        task_executor: TaskExecutor,
        persistence: Optional[PersistenceBackend] = None,
        event_bus: Optional[EventBus] = None,
        max_concurrent_tasks: int = 10,
        instance_id: Optional[str] = None
    ):
        """
        Initialize StatelessTaskOrchestrator.

        Args:
            queue_manager: Queue manager for task dequeuing
            dependency_manager: Unified dependency manager
            task_executor: Task executor (required)
            persistence: Persistence backend
            event_bus: Event bus for coordination
            max_concurrent_tasks: Maximum concurrent task executions
        """
        if not task_executor:
            raise ConfigurationError("StatelessTaskOrchestrator requires a task_executor")

        self.queue_manager = queue_manager
        self.dependency_manager = dependency_manager
        self.task_executor = task_executor
        self.persistence = persistence
        self.event_bus = event_bus
        self.max_concurrent_tasks = max_concurrent_tasks
        self.instance_id = instance_id or f"stateless-orchestrator-{os.getpid()}"

        # Leader election configuration
        self.enable_distributed = os.getenv("GLEITZEIT_TASK_ORCHESTRATOR_DISTRIBUTED", "true").lower() == "true"
        self.leader_ttl = int(os.getenv("GLEITZEIT_LEADER_TTL", "10"))

        # Track active tasks (but NOT with persistent monitoring)
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)

        # Track recently processed events to prevent duplicates
        self._processed_events = defaultdict(set)

        # Track if we've registered with StreamSystemManager to avoid duplicate registrations
        self._stream_manager_registered = False

        # Setup event handlers - will be skipped if StreamSystemManager registration occurs
        self._setup_event_handlers()

        logger.info(f"Initialized StatelessTaskOrchestrator (instance: {self.instance_id})")

    def _setup_event_handlers(self):
        """Setup event subscriptions - only if not using StreamSystemManager."""
        if not self.event_bus:
            logger.warning("StatelessTaskOrchestrator: No event_bus available")
            return

        # Skip EventBus registration if we're using StreamSystemManager
        # to avoid duplicate event handling
        if self._stream_manager_registered:
            logger.info("StatelessTaskOrchestrator: Skipping EventBus registration (using StreamSystemManager)")
            return

        # Listen for workflow submission to enqueue initial tasks
        self.event_bus.register(EventType.WORKFLOW_SUBMITTED, self._handle_workflow_submitted)

        # Listen for task ready events from queue
        self.event_bus.register(EventType.TASK_READY, self._handle_task_ready)

        # Listen for task completion to check workflow progress
        self.event_bus.register(EventType.TASK_COMPLETED, self._handle_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._handle_task_failed)

        logger.info("StatelessTaskOrchestrator event handlers registered via EventBus")

    def register_with_stream_manager(self, stream_manager):
        """
        Register event handlers with StreamSystemManager.

        This allows the MultiplexedStreamConsumer to route events
        directly to our handlers without going through the event bus.

        Args:
            stream_manager: StreamSystemManager instance
        """
        if not hasattr(stream_manager, 'register_event_handler'):
            logger.warning("StreamSystemManager doesn't support event handler registration")
            return

        # Mark that we're using StreamSystemManager to prevent duplicate EventBus registration
        self._stream_manager_registered = True

        # If EventBus handlers were already registered, unregister them to avoid duplicates
        if self.event_bus:
            try:
                self.event_bus.unregister(EventType.WORKFLOW_SUBMITTED, self._handle_workflow_submitted)
                self.event_bus.unregister(EventType.TASK_READY, self._handle_task_ready)
                self.event_bus.unregister(EventType.TASK_COMPLETED, self._handle_task_completed)
                self.event_bus.unregister(EventType.TASK_FAILED, self._handle_task_failed)
                logger.info("StatelessTaskOrchestrator: Unregistered EventBus handlers to use StreamSystemManager")
            except Exception as e:
                logger.debug(f"Could not unregister EventBus handlers: {e}")

        # Register handlers for stream-based events with component name
        component_name = 'StatelessTaskOrchestrator'
        stream_manager.register_event_handler('workflow:submitted', self._handle_workflow_submitted, component_name)
        stream_manager.register_event_handler('task:ready', self._handle_task_ready, component_name)
        stream_manager.register_event_handler('task:completed', self._handle_task_completed, component_name)
        stream_manager.register_event_handler('task:failed', self._handle_task_failed, component_name)

        logger.info("StatelessTaskOrchestrator registered handlers with StreamSystemManager (EventBus handlers disabled)")

    async def start(self):
        """
        Initialize the orchestrator.

        Note: This does NOT start any loops!
        It only performs initialization tasks.
        """
        logger.info(f"StatelessTaskOrchestrator {self.instance_id} initialized (NO loops started)")

    async def stop(self):
        """Stop the orchestrator and release resources."""
        # Cancel any active tasks
        for task_id, task in list(self._active_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Release leader lock if held
        if self.enable_distributed and self.persistence:
            await self.release_leadership()

        logger.info(f"StatelessTaskOrchestrator {self.instance_id} stopped")

    async def check_leadership(self) -> bool:
        """
        Check if this instance can be leader.

        Single check, not a loop!

        Returns:
            True if this instance is/became leader
        """
        if not self.enable_distributed or not self.persistence:
            # Non-distributed mode, always leader
            return True

        lock_key = "task_orchestrator:leader"

        try:
            # Check current leader
            current_leader = await self.persistence.get(lock_key)
            if current_leader:
                if isinstance(current_leader, bytes):
                    current_leader = current_leader.decode()

            if current_leader == self.instance_id:
                # We're already leader, refresh TTL
                await self.persistence.expire(lock_key, self.leader_ttl)
                return True
            elif not current_leader:
                # No leader, try to become one
                acquired = await self.persistence.set(
                    lock_key,
                    self.instance_id,
                    nx=True,  # Only set if not exists
                    ex=self.leader_ttl
                )
                if acquired:
                    logger.info(f"Instance {self.instance_id} became leader")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking leadership: {e}")
            return False

    async def release_leadership(self):
        """Release leadership if held."""
        if not self.persistence:
            return

        lock_key = "task_orchestrator:leader"
        try:
            current_leader = await self.persistence.get(lock_key)
            if current_leader:
                if isinstance(current_leader, bytes):
                    current_leader = current_leader.decode()
                if current_leader == self.instance_id:
                    await self.persistence.delete(lock_key)
                    logger.info(f"Instance {self.instance_id} released leadership")
        except Exception as e:
            logger.error(f"Error releasing leadership: {e}")

    async def process_once(self) -> Dict[str, Any]:
        """
        Process available tasks once (no loop).

        Can be called by external triggers.

        Returns:
            Processing statistics
        """
        stats = {
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "instance_id": self.instance_id,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Check if we can process (leader check for distributed mode)
        if self.enable_distributed:
            is_leader = await self.check_leadership()
            if not is_leader:
                stats["skipped"] = 1
                stats["reason"] = "not_leader"
                return stats

        # Process available tasks from queue (single batch)
        try:
            tasks = await self.queue_manager.get_ready_tasks(limit=self.max_concurrent_tasks)

            for task in tasks:
                try:
                    await self._process_task(task)
                    stats["processed"] += 1
                except Exception as e:
                    logger.error(f"Error processing task {task.id}: {e}")
                    stats["failed"] += 1

        except Exception as e:
            logger.error(f"Error in process_once: {e}")
            stats["error"] = str(e)

        return stats

    async def _process_task(self, task: Task):
        """Process a single task."""
        # IDEMPOTENCY CHECK: Skip if already executing
        if task.id in self._active_tasks:
            logger.debug(f"Task {task.id} already being executed, skipping duplicate")
            return

        # Check if task is already completed (from persistence)
        if self.persistence:
            current_task = await self.persistence.get_task(task.id)
            if current_task and current_task.status == TaskStatus.COMPLETED:
                logger.info(f"Task {task.id} already completed, skipping")
                return
            logger.info(f"Found task {task.id} in {current_task.status if current_task else 'UNKNOWN'} state, processing...")

        # Check dependencies
        ready = await self.dependency_manager.check_dependencies(task)
        if not ready:
            logger.debug(f"Task {task.id} dependencies not ready")
            return

        # Execute task
        async with self._semaphore:
            # Track as active BEFORE creating the task
            task_future = asyncio.create_task(self._execute_task(task))
            self._active_tasks[task.id] = task_future

            try:
                await task_future
            finally:
                # Remove from active
                self._active_tasks.pop(task.id, None)

    async def _execute_task(self, task: Task):
        """Execute a task through the TaskExecutor."""
        try:
            # Don't update status here - TaskExecutor handles status transitions
            # This avoids duplicate status updates and potential race conditions

            # Execute through TaskExecutor (which will handle status updates and events)
            task_result = await self.task_executor.execute_task(task)

            # TaskExecutor returns a TaskResult and handles all status updates/events
            # We don't need to update anything here - TaskExecutor has already:
            # 1. Updated task status in persistence
            # 2. Emitted appropriate events (TASK_STARTED, TASK_COMPLETED/FAILED)
            # 3. Saved the task result

            logger.info(f"Task {task.id} execution completed with status: {task_result.status}")

        except Exception as e:
            # TaskExecutor should handle all errors internally and return a TaskResult
            # If we get here, it means TaskExecutor itself failed catastrophically
            logger.error(f"TaskExecutor failed catastrophically for task {task.id}: {e}")

            # Since TaskExecutor failed, we need to clean up the task state ourselves
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.utcnow()

            if self.persistence:
                await self.persistence.save_task(task)

            # Emit failure event
            if self.event_bus:
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.TASK_FAILED,
                    data={
                        "task_id": task.id,
                        "workflow_id": task.workflow_id,
                        "error": str(e)
                    }
                ))

    async def submit_workflow(self, workflow):
        """
        Submit a workflow for execution.

        This method is called by ExecutionEngineV2. It directly processes the workflow
        without emitting a workflow:submitted event to avoid duplicate processing.

        Args:
            workflow: The workflow to submit
        """
        # Store workflow in persistence
        if self.persistence:
            await self.persistence.save_workflow(workflow)

        # Directly enqueue initial tasks (don't emit event to avoid self-triggering)
        # This is what _handle_workflow_submitted would do, but we do it directly
        # to avoid duplicate processing from the event handler
        try:
            # Find tasks with no dependencies
            ready_task_count = 0
            for task in workflow.tasks:
                if not task.dependencies:
                    ready_task_count += 1
                    logger.info(f"Enqueueing task {task.id} (no dependencies)")
                    try:
                        await self.queue_manager.enqueue_task(task)
                        logger.info(f"Task {task.id} enqueued successfully")
                    except Exception as e:
                        logger.error(f"Failed to enqueue task {task.id}: {e}")

            logger.info(f"Submitted workflow {workflow.id} - enqueued {ready_task_count} ready tasks")

            # Emit TASK_READY events for initial tasks to trigger processing
            for task in workflow.tasks:
                if not task.dependencies:
                    logger.info(f"Emitting TASK_READY event for initial task {task.id}")
                    await self.event_bus.emit(GleitzeitEvent(
                        event_type=EventType.TASK_READY,
                        data={"task_id": task.id, "workflow_id": workflow.id}
                    ))

            # Note: We do NOT emit a workflow:submitted event here to avoid duplicate processing
            # The workflow submission is already handled directly

        except Exception as e:
            logger.error(f"Failed to process workflow {workflow.id}: {e}")
            raise

    async def _handle_workflow_submitted(self, event: GleitzeitEvent):
        """Handle workflow submission - enqueue initial tasks."""
        workflow_id = event.data.get("workflow_id")
        if not workflow_id:
            logger.warning("No workflow_id in event data")
            return

        # Only process if we're leader (or non-distributed)
        if self.enable_distributed:
            is_leader = await self.check_leadership()
            logger.info(f"Leadership check for workflow {workflow_id}: is_leader={is_leader}, distributed={self.enable_distributed}")
            if not is_leader:
                logger.info(f"Not leader, skipping workflow {workflow_id}")
                return
        else:
            logger.info(f"Non-distributed mode, processing workflow {workflow_id}")

        logger.info(f"Processing workflow submission: {workflow_id}")

        # Get workflow and enqueue ready tasks
        if self.persistence:
            logger.info(f"Fetching workflow {workflow_id} from persistence")
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                logger.info(f"Found workflow {workflow_id} with {len(workflow.tasks)} tasks")
                # Find tasks with no dependencies
                ready_task_count = 0
                for task in workflow.tasks:
                    if not task.dependencies:
                        ready_task_count += 1
                        logger.info(f"Enqueueing task {task.id} (no dependencies)")
                        try:
                            await self.queue_manager.enqueue_task(task)
                            logger.info(f"Task {task.id} enqueued successfully")
                        except Exception as e:
                            logger.error(f"Failed to enqueue task {task.id}: {e}", exc_info=True)

                if ready_task_count == 0:
                    logger.warning(f"No tasks without dependencies found in workflow {workflow_id}")
                else:
                    logger.info(f"Enqueued {ready_task_count} initial tasks for workflow {workflow_id}")
            else:
                logger.error(f"Workflow {workflow_id} not found in persistence")
        else:
            logger.error("No persistence backend available")

    async def _handle_task_ready(self, event: GleitzeitEvent):
        """Handle task ready event."""
        logger.info(f"_handle_task_ready called with event: {event.event_type}, data: {event.data}")
        task_id = event.data.get("task_id")
        if not task_id:
            logger.warning("No task_id in TASK_READY event")
            return

        # IDEMPOTENCY CHECK: Skip if already processing
        if task_id in self._active_tasks:
            logger.info(f"Task {task_id} already being processed, ignoring duplicate TASK_READY event")
            return

        logger.info(f"Processing TASK_READY for task {task_id}")
        # Process the task
        if self.persistence:
            task = await self.persistence.get_task(task_id)
            if task:
                # Only skip if truly completed (EXECUTING status is expected during processing)
                if task.status == TaskStatus.COMPLETED:
                    logger.info(f"Task {task_id} already completed, skipping")
                    return
                logger.info(f"Found task {task_id} in {task.status} state, processing...")
                await self._process_task(task)
            else:
                logger.error(f"Task {task_id} not found in persistence")
        else:
            logger.error("No persistence backend available for task processing")

    async def _handle_task_completed(self, event: GleitzeitEvent):
        """Handle task completion - check for newly ready tasks."""
        # Prevent duplicate processing
        event_id = f"{event.event_type}:{event.data.get('task_id', '')}"
        if event_id in self._processed_events[event.event_type]:
            return
        self._processed_events[event.event_type].add(event_id)

        # Only process if we're leader
        if self.enable_distributed:
            is_leader = await self.check_leadership()
            if not is_leader:
                return

        task_id = event.data.get("task_id")
        workflow_id = event.data.get("workflow_id")

        if not task_id or not workflow_id:
            return

        logger.info(f"Task {task_id} completed, checking dependencies")

        # Check for newly ready tasks
        if self.dependency_manager:
            newly_ready = await self.dependency_manager.get_dependent_tasks(task_id)
            for dependent_task_id in newly_ready:
                # Enqueue newly ready task
                if self.persistence:
                    task = await self.persistence.get_task(dependent_task_id)
                    if task:
                        ready = await self.dependency_manager.check_dependencies(task)
                        if ready:
                            await self.queue_manager.enqueue_task(task)
                            # Emit TASK_READY event to trigger processing
                            logger.info(f"Emitting TASK_READY event for dependent task {task.id}")
                            await self.event_bus.emit(GleitzeitEvent(
                                event_type=EventType.TASK_READY,
                                data={"task_id": task.id, "workflow_id": task.workflow_id}
                            ))

    async def _handle_task_failed(self, event: GleitzeitEvent):
        """Handle task failure."""
        task_id = event.data.get("task_id")
        workflow_id = event.data.get("workflow_id")
        error = event.data.get("error")

        logger.error(f"Task {task_id} failed in workflow {workflow_id}: {error}")

        # Emit workflow error event for handling by WorkflowManager
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.WORKFLOW_ERROR,
                data={
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "error": error
                }
            ))

    def get_statistics(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        return {
            "instance_id": self.instance_id,
            "active_tasks": len(self._active_tasks),
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "distributed_mode": self.enable_distributed
        }