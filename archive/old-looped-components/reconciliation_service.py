"""
Reconciliation service for recovering stuck workflows and tasks.

This service runs independently and periodically checks for stuck workflows
and tasks, ensuring the system remains in a consistent state. It can be run
on startup and/or periodically to handle failures and recover work.

The service is designed to be stateless and scalable - multiple instances
can run reconciliation without conflicts due to atomic operations.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

from ..core.models import WorkflowStatus, TaskStatus
from ..persistence.base import PersistenceBackend
from ..events import EventBus, GleitzeitEvent
from ..core.events import EventType

logger = logging.getLogger(__name__)


class ReconciliationMode(Enum):
    """Reconciliation execution modes."""
    STARTUP = "startup"      # Run once on startup
    PERIODIC = "periodic"     # Run periodically
    MANUAL = "manual"        # Run on demand


class ReconciliationService:
    """
    Independent service for reconciling workflow and task states.
    
    Can run in different modes:
    - STARTUP: Run once when system starts
    - PERIODIC: Run continuously at intervals
    - MANUAL: Run on demand
    
    Handles:
    - Checking stuck workflows and marking them complete if all tasks are done
    - Re-queuing pending tasks from running workflows
    - Detecting and handling stuck running tasks
    - Cleaning up orphaned resources
    
    Designed for distributed operation - multiple instances can run safely
    using atomic operations to avoid conflicts.
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        event_bus: Optional[EventBus] = None,
        atomic_ops: Optional[Any] = None,
        task_timeout: int = 3600,  # Default 1 hour for stuck tasks
        reconciliation_interval: int = 300,  # Default 5 minutes for periodic mode
        mode: ReconciliationMode = ReconciliationMode.STARTUP,
        scheduler: Optional[Any] = None
    ):
        """
        Initialize the reconciliation service.

        Args:
            persistence: Persistence backend for data access
            event_bus: Event bus for emitting recovery events
            atomic_ops: Atomic operations handler for workflow completion
            task_timeout: Seconds before considering a running task stuck
            reconciliation_interval: Seconds between reconciliation runs in periodic mode
            mode: Service execution mode
            scheduler: Event scheduler for stateless reconciliation (when provided, enables event-driven mode)
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.atomic_ops = atomic_ops
        self.task_timeout = task_timeout
        self.reconciliation_interval = reconciliation_interval
        self.mode = mode
        self.scheduler = scheduler
        
        self._running = False
        self._reconciliation_task = None
        self._last_reconciliation = None
        self._reconciliation_count = 0
        
    async def reconcile(self) -> Dict[str, int]:
        """
        Perform full reconciliation of workflows and tasks.
        
        Returns:
            Statistics about reconciliation actions taken
        """
        logger.info("Starting workflow/task reconciliation...")
        
        stats = {
            "workflows_checked": 0,
            "workflows_completed": 0,
            "workflows_failed": 0,
            "tasks_requeued": 0,
            "tasks_marked_failed": 0,
            "tasks_already_complete": 0
        }
        
        try:
            # Reconcile running workflows
            workflow_stats = await self._reconcile_workflows()
            stats.update(workflow_stats)
            
            # Reconcile stuck tasks
            task_stats = await self._reconcile_stuck_tasks()
            stats.update(task_stats)
            
            # Reconcile stuck pending tasks
            pending_stats = await self._reconcile_pending_tasks()
            for key, value in pending_stats.items():
                stats[f"pending_{key}"] = value
            
            # Reconcile RETRY_PENDING tasks
            retry_pending_stats = await self._reconcile_retry_pending_tasks()
            for key, value in retry_pending_stats.items():
                stats[f"retry_{key}"] = value
            
            # Reconcile recently failed tasks
            failed_task_stats = await self._reconcile_failed_tasks()
            for key, value in failed_task_stats.items():
                stats[f"failed_{key}"] = value
            
            logger.info(f"Reconciliation complete: {stats}")
                
        except Exception as e:
            logger.error(f"Reconciliation failed: {e}", exc_info=True)
            stats["error"] = str(e)
            
        return stats
    
    async def _reconcile_workflows(self) -> Dict[str, int]:
        """
        Reconcile all running workflows.
        
        Returns:
            Statistics about workflow reconciliation
        """
        stats = {
            "workflows_checked": 0,
            "workflows_completed": 0,
            "workflows_failed": 0,
            "tasks_requeued": 0,
            "tasks_already_complete": 0
        }
        
        try:
            # Get all running workflows
            result = await self.persistence.list_workflows(
                status=WorkflowStatus.RUNNING.value,
                limit=1000  # Process in batches if needed
            )
            
            if isinstance(result, dict):
                workflows = result.get("workflows", [])
            else:
                workflows = result or []
            
            logger.info(f"Found {len(workflows)} running workflows to reconcile")
            
            for workflow in workflows:
                stats["workflows_checked"] += 1
                
                # Get all tasks for this workflow
                task_result = await self.persistence.list_tasks(
                    workflow_id=workflow.id if hasattr(workflow, 'id') else workflow.get('id'),
                    limit=1000
                )
                
                if isinstance(task_result, dict):
                    tasks = task_result.get("tasks", [])
                else:
                    tasks = task_result or []
                
                # Check task statuses
                all_complete = True
                has_failed = False
                pending_tasks = []
                running_tasks = []
                
                for task in tasks:
                    task_status = task.status if hasattr(task, 'status') else task.get('status')
                    task_id = task.id if hasattr(task, 'id') else task.get('id')
                    
                    if task_status == TaskStatus.COMPLETED.value:
                        stats["tasks_already_complete"] += 1
                    elif task_status == TaskStatus.FAILED.value:
                        has_failed = True
                        all_complete = False
                    elif task_status == TaskStatus.PENDING.value:
                        all_complete = False
                        pending_tasks.append(task_id)
                    elif task_status == TaskStatus.EXECUTING.value:
                        all_complete = False
                        running_tasks.append(task)
                    else:
                        all_complete = False
                
                workflow_id = workflow.id if hasattr(workflow, 'id') else workflow.get('id')
                
                # Handle workflow based on task states
                if all_complete and not has_failed:
                    # All tasks complete - mark workflow complete
                    logger.info(f"Marking workflow {workflow_id} as completed (all tasks done)")
                    
                    if self.atomic_ops:
                        # Use atomic operation if available
                        success = await self.atomic_ops.check_and_complete_workflow(workflow_id)
                        if success:
                            stats["workflows_completed"] += 1
                    else:
                        # Manual update
                        workflow_obj = await self.persistence.get_workflow(workflow_id)
                        if workflow_obj:
                            if hasattr(workflow_obj, 'status'):
                                workflow_obj.status = WorkflowStatus.COMPLETED.value
                            else:
                                workflow_obj['status'] = WorkflowStatus.COMPLETED.value
                            
                            if hasattr(workflow_obj, 'completed_at'):
                                workflow_obj.completed_at = datetime.utcnow().isoformat()
                            else:
                                workflow_obj['completed_at'] = datetime.utcnow().isoformat()
                                
                            await self.persistence.update_workflow(workflow_obj)
                            stats["workflows_completed"] += 1
                            
                elif has_failed:
                    # Has failed tasks - mark workflow failed
                    logger.info(f"Marking workflow {workflow_id} as failed (has failed tasks)")
                    
                    workflow_obj = await self.persistence.get_workflow(workflow_id)
                    if workflow_obj:
                        if hasattr(workflow_obj, 'status'):
                            workflow_obj.status = WorkflowStatus.FAILED.value
                        else:
                            workflow_obj['status'] = WorkflowStatus.FAILED.value
                            
                        await self.persistence.update_workflow(workflow_obj)
                        stats["workflows_failed"] += 1
                        
                else:
                    # Workflow still has work to do
                    # Re-queue pending tasks
                    for task_id in pending_tasks:
                        logger.info(f"Re-queuing pending task {task_id}")
                        if self.event_bus:
                            await self.event_bus.emit(GleitzeitEvent(
                                event_type=EventType.TASK_READY,
                                data={"task_id": task_id, "workflow_id": workflow_id}
                            ))
                            stats["tasks_requeued"] += 1
                    
                    # Check running tasks for being stuck
                    for task in running_tasks:
                        await self._check_stuck_task(task, stats)
                        
        except Exception as e:
            logger.error(f"Workflow reconciliation error: {e}", exc_info=True)
            
        return stats
    
    async def _reconcile_stuck_tasks(self) -> Dict[str, int]:
        """
        Find and handle tasks stuck in running state.
        
        Returns:
            Statistics about stuck task handling
        """
        stats = {
            "stuck_tasks_found": 0,
            "tasks_marked_failed": 0,
            "tasks_retried": 0
        }
        
        try:
            # Get all running tasks (using EXECUTING status for running tasks)
            result = await self.persistence.list_tasks(
                status=TaskStatus.EXECUTING.value,
                limit=1000
            )
            
            if isinstance(result, dict):
                tasks = result.get("tasks", [])
            else:
                tasks = result or []
            
            logger.info(f"Checking {len(tasks)} running tasks for stuck state")
            
            for task in tasks:
                is_stuck = await self._check_stuck_task(task, stats)
                if is_stuck:
                    stats["stuck_tasks_found"] += 1
                    
        except Exception as e:
            logger.error(f"Stuck task reconciliation error: {e}", exc_info=True)
            
        return stats
    
    async def _check_stuck_task(self, task: Any, stats: Dict[str, int]) -> bool:
        """
        Check if a task is stuck and handle it.
        
        Args:
            task: Task to check
            stats: Statistics dictionary to update
            
        Returns:
            True if task was stuck, False otherwise
        """
        try:
            # Get task timestamps
            started_at = task.started_at if hasattr(task, 'started_at') else task.get('started_at')
            task_id = task.id if hasattr(task, 'id') else task.get('id')
            workflow_id = task.workflow_id if hasattr(task, 'workflow_id') else task.get('workflow_id')
            
            if started_at:
                # Parse timestamp
                if isinstance(started_at, str):
                    started_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                else:
                    started_time = started_at
                    
                # Check if task has been running too long
                elapsed = datetime.utcnow() - started_time
                if elapsed.total_seconds() > self.task_timeout:
                    logger.warning(f"Task {task_id} stuck (running for {elapsed})")
                    
                    # Get retry config
                    retry_config = task.retry_config if hasattr(task, 'retry_config') else task.get('retry_config', {})
                    attempt_count = task.attempt_count if hasattr(task, 'attempt_count') else task.get('attempt_count', 0)
                    max_attempts = retry_config.get('max_attempts', 3) if retry_config else 3
                    
                    if attempt_count < max_attempts:
                        # Retry the task
                        logger.info(f"Retrying stuck task {task_id} (attempt {attempt_count + 1}/{max_attempts})")
                        
                        # Mark task as pending for retry
                        task_obj = await self.persistence.get_task(task_id)
                        if task_obj:
                            if hasattr(task_obj, 'status'):
                                task_obj.status = TaskStatus.PENDING.value
                            else:
                                task_obj['status'] = TaskStatus.PENDING.value
                                
                            await self.persistence.update_task(task_obj)
                            
                            # Emit retry event
                            if self.event_bus:
                                await self.event_bus.emit(GleitzeitEvent(
                                    event_type=EventType.TASK_READY_FOR_RETRY,
                                    data={"task_id": task_id, "workflow_id": workflow_id}
                                ))
                                
                            stats["tasks_retried"] = stats.get("tasks_retried", 0) + 1
                    else:
                        # Mark task as failed
                        logger.error(f"Marking stuck task {task_id} as failed (max retries exceeded)")
                        
                        task_obj = await self.persistence.get_task(task_id)
                        if task_obj:
                            if hasattr(task_obj, 'status'):
                                task_obj.status = TaskStatus.FAILED.value
                                task_obj.error_message = f"Task timeout after {elapsed}"
                            else:
                                task_obj['status'] = TaskStatus.FAILED.value
                                task_obj['error_message'] = f"Task timeout after {elapsed}"
                                
                            await self.persistence.update_task(task_obj)
                            stats["tasks_marked_failed"] = stats.get("tasks_marked_failed", 0) + 1
                            
                    return True
                    
        except Exception as e:
            logger.error(f"Error checking stuck task: {e}", exc_info=True)
            
        return False
    
    async def _reconcile_retry_pending_tasks(self) -> Dict[str, int]:
        """
        Reconcile tasks stuck in RETRY_PENDING state.
        
        Checks for tasks that should have been retried but missed their
        scheduled retry time (e.g., due to system restart).
        
        Returns:
            Statistics about retry pending reconciliation
        """
        stats = {
            "retry_pending_checked": 0,
            "retries_triggered": 0,
            "permanently_failed": 0
        }
        
        try:
            # Get all RETRY_PENDING tasks
            result = await self.persistence.list_tasks(
                status=TaskStatus.RETRY_PENDING.value,
                limit=1000
            )
            
            if isinstance(result, dict):
                tasks = result.get("tasks", [])
            else:
                tasks = result or []
            
            logger.info(f"Checking {len(tasks)} RETRY_PENDING tasks for missed retries")
            
            for task in tasks:
                stats["retry_pending_checked"] += 1
                
                task_id = task.id if hasattr(task, 'id') else task.get('id')
                workflow_id = task.workflow_id if hasattr(task, 'workflow_id') else task.get('workflow_id')
                task_metadata = task.metadata if hasattr(task, 'metadata') else task.get('metadata', {})
                
                # Check if retry time has passed
                retry_at = task_metadata.get('retry_at') if task_metadata else None
                
                if retry_at:
                    # Parse retry timestamp
                    if isinstance(retry_at, str):
                        retry_time = datetime.fromisoformat(retry_at.replace('Z', '+00:00'))
                    else:
                        retry_time = retry_at
                    
                    # Check if we've passed the retry time
                    if datetime.utcnow() >= retry_time:
                        logger.info(f"Task {task_id} missed its retry window (should have retried at {retry_at})")
                        
                        # Update task to QUEUED for re-execution
                        task_obj = await self.persistence.get_task(task_id)
                        if task_obj:
                            if hasattr(task_obj, 'status'):
                                task_obj.status = TaskStatus.QUEUED.value
                            else:
                                task_obj['status'] = TaskStatus.QUEUED.value
                            
                            await self.persistence.update_task(task_obj)
                            
                            # Emit retry event
                            if self.event_bus:
                                await self.event_bus.emit(GleitzeitEvent(
                                    event_type=EventType.TASK_READY_FOR_RETRY,
                                    data={
                                        'task_id': task_id,
                                        'workflow_id': workflow_id,
                                        'reason': 'missed_retry_window',
                                        'original_retry_at': retry_at
                                    }
                                ))
                            
                            stats["retries_triggered"] += 1
                else:
                    # No retry_at timestamp - this shouldn't happen, but handle it
                    logger.warning(f"RETRY_PENDING task {task_id} has no retry_at timestamp")
                    
                    # Check if we have max attempts info
                    retry_attempt = task_metadata.get('retry_attempt', 0) if task_metadata else 0
                    retry_config = task.retry_config if hasattr(task, 'retry_config') else task.get('retry_config', {})
                    max_attempts = retry_config.get('max_attempts', 3) if retry_config else 3
                    
                    if retry_attempt < max_attempts:
                        # Still has attempts - queue for retry
                        task_obj = await self.persistence.get_task(task_id)
                        if task_obj:
                            if hasattr(task_obj, 'status'):
                                task_obj.status = TaskStatus.QUEUED.value
                            else:
                                task_obj['status'] = TaskStatus.QUEUED.value
                            
                            await self.persistence.update_task(task_obj)
                            
                            if self.event_bus:
                                await self.event_bus.emit(GleitzeitEvent(
                                    event_type=EventType.TASK_READY_FOR_RETRY,
                                    data={
                                        'task_id': task_id,
                                        'workflow_id': workflow_id,
                                        'reason': 'retry_pending_no_timestamp'
                                    }
                                ))
                            
                            stats["retries_triggered"] += 1
                    else:
                        # Max attempts reached - mark as failed
                        logger.info(f"Task {task_id} in RETRY_PENDING but max attempts reached")
                        
                        task_obj = await self.persistence.get_task(task_id)
                        if task_obj:
                            if hasattr(task_obj, 'status'):
                                task_obj.status = TaskStatus.FAILED.value
                                task_obj.error_message = "Max retry attempts exceeded"
                            else:
                                task_obj['status'] = TaskStatus.FAILED.value
                                task_obj['error_message'] = "Max retry attempts exceeded"
                            
                            await self.persistence.update_task(task_obj)
                            stats["permanently_failed"] += 1
                            
        except Exception as e:
            logger.error(f"Retry pending reconciliation error: {e}", exc_info=True)
        
        return stats
    
    async def _reconcile_failed_tasks(self) -> Dict[str, int]:
        """
        Check recently failed tasks that might still have retry attempts.
        
        This handles cases where the retry manager failed to process
        a task failure event.
        
        Returns:
            Statistics about failed task reconciliation
        """
        stats = {
            "failed_tasks_checked": 0,
            "retries_scheduled": 0,
            "already_exceeded_max": 0
        }
        
        try:
            # Get recently failed tasks (last hour by default)
            result = await self.persistence.list_tasks(
                status=TaskStatus.FAILED.value,
                limit=1000
            )
            
            if isinstance(result, dict):
                tasks = result.get("tasks", [])
            else:
                tasks = result or []
            
            # Filter to recent failures (last hour)
            lookback_time = datetime.utcnow() - timedelta(hours=1)
            recent_tasks = []
            
            for task in tasks:
                completed_at = task.completed_at if hasattr(task, 'completed_at') else task.get('completed_at')
                if completed_at:
                    if isinstance(completed_at, str):
                        completed_time = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                    else:
                        completed_time = completed_at
                    
                    if completed_time >= lookback_time:
                        recent_tasks.append(task)
            
            logger.info(f"Checking {len(recent_tasks)} recently failed tasks for retry eligibility")
            
            for task in recent_tasks:
                stats["failed_tasks_checked"] += 1
                
                task_id = task.id if hasattr(task, 'id') else task.get('id')
                workflow_id = task.workflow_id if hasattr(task, 'workflow_id') else task.get('workflow_id')
                task_metadata = task.metadata if hasattr(task, 'metadata') else task.get('metadata', {})
                
                # Check if already marked as max retries reached
                if task_metadata and task_metadata.get('max_retries_reached'):
                    stats["already_exceeded_max"] += 1
                    continue
                
                # Check retry configuration
                retry_config = task.retry_config if hasattr(task, 'retry_config') else task.get('retry_config', {})
                if not retry_config:
                    continue  # No retry config, skip
                
                max_attempts = retry_config.get('max_attempts', 3)
                retry_attempt = task_metadata.get('retry_attempt', 0) if task_metadata else 0
                
                if retry_attempt < max_attempts:
                    logger.info(f"Failed task {task_id} has attempts remaining ({retry_attempt}/{max_attempts})")
                    
                    # Calculate retry delay
                    base_delay = retry_config.get('base_delay', 1.0)
                    backoff_strategy = retry_config.get('backoff_strategy', 'exponential')
                    
                    if backoff_strategy == 'exponential':
                        delay = base_delay * (2 ** retry_attempt)
                    elif backoff_strategy == 'linear':
                        delay = base_delay * (retry_attempt + 1)
                    else:
                        delay = base_delay
                    
                    # Cap at max delay
                    max_delay = retry_config.get('max_delay', 300.0)
                    delay = min(delay, max_delay)
                    
                    # Update task for retry
                    task_obj = await self.persistence.get_task(task_id)
                    if task_obj:
                        if hasattr(task_obj, 'status'):
                            task_obj.status = TaskStatus.RETRY_PENDING.value
                            task_obj.metadata = task_obj.metadata or {}
                            task_obj.metadata['retry_attempt'] = retry_attempt + 1
                            task_obj.metadata['retry_at'] = (datetime.utcnow() + timedelta(seconds=delay)).isoformat()
                            task_obj.metadata['retry_reason'] = 'reconciliation'
                        else:
                            task_obj['status'] = TaskStatus.RETRY_PENDING.value
                            task_obj['metadata'] = task_obj.get('metadata', {})
                            task_obj['metadata']['retry_attempt'] = retry_attempt + 1
                            task_obj['metadata']['retry_at'] = (datetime.utcnow() + timedelta(seconds=delay)).isoformat()
                            task_obj['metadata']['retry_reason'] = 'reconciliation'
                        
                        await self.persistence.update_task(task_obj)
                        
                        # Emit retry scheduled event
                        if self.event_bus:
                            await self.event_bus.emit(GleitzeitEvent(
                                event_type=EventType.RETRY_SCHEDULED,
                                data={
                                    'task_id': task_id,
                                    'workflow_id': workflow_id,
                                    'retry_at': task_obj.metadata['retry_at'] if hasattr(task_obj, 'metadata') else task_obj['metadata']['retry_at'],
                                    'attempt_number': retry_attempt + 1,
                                    'reason': 'failed_task_reconciliation'
                                }
                            ))
                        
                        stats["retries_scheduled"] += 1
                else:
                    stats["already_exceeded_max"] += 1
                    
        except Exception as e:
            logger.error(f"Failed task reconciliation error: {e}", exc_info=True)
        
        return stats
    
    # Service lifecycle methods
    
    async def start(self) -> None:
        """
        Start the reconciliation service.
        
        Behavior depends on mode:
        - STARTUP: Run once immediately
        - PERIODIC: Start periodic reconciliation loop
        - MANUAL: Do nothing (wait for manual trigger)
        """
        if self._running:
            logger.warning("ReconciliationService already running")
            return
            
        self._running = True
        logger.info(f"Starting ReconciliationService in {self.mode.value} mode")
        
        if self.mode == ReconciliationMode.STARTUP:
            # Run once on startup
            try:
                stats = await self.reconcile()
                logger.info(f"Startup reconciliation complete: {stats}")
            except Exception as e:
                logger.error(f"Startup reconciliation failed: {e}", exc_info=True)
                
        elif self.mode == ReconciliationMode.PERIODIC:
            # Start periodic reconciliation
            if self.scheduler:
                # Use stateless scheduler-based reconciliation
                await self._start_stateless_reconciliation_loop()
                logger.info(f"Started stateless reconciliation with scheduler (interval: {self.reconciliation_interval}s)")
            else:
                # Fallback to traditional loop-based reconciliation
                self._reconciliation_task = asyncio.create_task(
                    self._periodic_reconciliation_loop()
                )
                logger.info(f"Started periodic reconciliation (interval: {self.reconciliation_interval}s)")
            
        elif self.mode == ReconciliationMode.MANUAL:
            logger.info("ReconciliationService ready for manual triggers")
            
    async def stop(self) -> None:
        """Stop the reconciliation service."""
        if not self._running:
            logger.warning("ReconciliationService not running")
            return
            
        logger.info("Stopping ReconciliationService...")
        self._running = False
        
        # Cancel periodic task if running
        if self._reconciliation_task:
            self._reconciliation_task.cancel()
            try:
                await self._reconciliation_task
            except asyncio.CancelledError:
                pass
            self._reconciliation_task = None
            
        logger.info("ReconciliationService stopped")
        
    async def _periodic_reconciliation_loop(self) -> None:
        """Run reconciliation periodically."""
        while self._running:
            try:
                # Wait for interval
                await asyncio.sleep(self.reconciliation_interval)
                
                if not self._running:
                    break
                    
                # Run reconciliation
                logger.info("Starting periodic reconciliation...")
                stats = await self.reconcile()
                
                self._reconciliation_count += 1
                self._last_reconciliation = datetime.utcnow()
                
                logger.info(f"Periodic reconciliation #{self._reconciliation_count} complete: {stats}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic reconciliation error: {e}", exc_info=True)
                # Continue running despite errors

    async def _start_stateless_reconciliation_loop(self) -> None:
        """
        Start stateless reconciliation using scheduler events.

        This method replaces persistent loops with event-driven scheduling.
        """
        if not self.scheduler:
            logger.error("Cannot start stateless reconciliation: no scheduler provided")
            return

        # Register event handler for reconciliation events
        await self.scheduler.register_handler(
            "reconciliation.process",
            self._handle_reconciliation_event
        )

        # Schedule the first reconciliation event
        await self.scheduler.schedule_event(
            "reconciliation.process",
            self.reconciliation_interval
        )

        logger.info("Started stateless reconciliation with scheduler")

    async def _handle_reconciliation_event(self, event_data: Dict) -> Dict[str, Any]:
        """
        Handle scheduled reconciliation event.

        This method processes one reconciliation cycle and reschedules itself.
        """
        try:
            # Run reconciliation
            logger.info("Starting scheduled reconciliation...")
            stats = await self.reconcile()

            self._reconciliation_count += 1
            self._last_reconciliation = datetime.utcnow()

            logger.info(f"Scheduled reconciliation #{self._reconciliation_count} complete: {stats}")

            # Self-reschedule for next reconciliation (only if still running)
            if self._running and self.scheduler:
                await self.scheduler.schedule_event(
                    "reconciliation.process",
                    self.reconciliation_interval
                )

            return {
                "status": "success",
                "stats": stats,
                "reconciliation_count": self._reconciliation_count
            }

        except Exception as e:
            logger.error(f"Scheduled reconciliation error: {e}", exc_info=True)

            # Still reschedule despite errors (with longer interval for backoff)
            if self._running and self.scheduler:
                await self.scheduler.schedule_event(
                    "reconciliation.process",
                    self.reconciliation_interval * 2  # Backoff on error
                )

            return {
                "status": "error",
                "error": str(e),
                "reconciliation_count": self._reconciliation_count
            }

    async def trigger_reconciliation(self) -> Dict[str, int]:
        """
        Manually trigger reconciliation.
        
        Can be called in any mode to force immediate reconciliation.
        
        Returns:
            Reconciliation statistics
        """
        logger.info("Manual reconciliation triggered")
        return await self.reconcile()
    
    async def _reconcile_pending_tasks(self) -> Dict[str, int]:
        """
        Reconcile stuck pending tasks.
        
        Finds PENDING tasks that are old and have no dependencies,
        then emits TASK_READY events to trigger processing.
        
        Returns:
            Statistics about pending task reconciliation
        """
        stats = {
            "tasks_checked": 0,
            "tasks_requeued": 0,
            "tasks_skipped": 0
        }
        
        try:
            # Get all pending tasks
            pending_tasks = await self.persistence.get_tasks_by_status(TaskStatus.PENDING.value)
            stats["tasks_checked"] = len(pending_tasks)
            
            if not pending_tasks:
                logger.debug("No pending tasks found for reconciliation")
                return stats
            
            # Define cutoff time for "stuck" tasks (5 minutes)
            cutoff_time = datetime.utcnow() - timedelta(minutes=5)
            
            logger.info(f"Checking {len(pending_tasks)} pending tasks for requeue")
            
            for task in pending_tasks:
                try:
                    # Skip if task is recent
                    if not task.created_at or task.created_at > cutoff_time:
                        stats["tasks_skipped"] += 1
                        continue
                    
                    # Skip if task has dependencies (may be legitimately waiting)
                    if task.dependencies:
                        stats["tasks_skipped"] += 1
                        continue
                    
                    # Task is old and has no dependencies - should be requeued
                    age_minutes = (datetime.utcnow() - task.created_at).total_seconds() / 60
                    logger.warning(f"Requeuing stuck pending task {task.id} (age: {age_minutes:.1f} minutes)")
                    
                    # Emit TASK_READY event to trigger processing
                    if self.event_bus:
                        await self.event_bus.emit(GleitzeitEvent(
                            event_type=EventType.TASK_READY,
                            data={
                                "task_id": task.id,
                                "workflow_id": task.workflow_id,
                                "requeue_reason": "stuck_pending_reconciliation"
                            }
                        ))
                        
                        # Also emit workflow event to ensure workflow processing
                        await self.event_bus.emit(GleitzeitEvent(
                            event_type=EventType.WORKFLOW_SUBMITTED,
                            data={
                                "workflow_id": task.workflow_id,
                                "requeue_reason": "pending_task_reconciliation"
                            }
                        ))
                        
                        stats["tasks_requeued"] += 1
                        logger.info(f"Emitted requeue events for task {task.id}")
                    else:
                        logger.warning(f"No event bus available to requeue task {task.id}")
                        
                except Exception as e:
                    logger.error(f"Error processing pending task {task.id}: {e}")
                    continue
            
            if stats["tasks_requeued"] > 0:
                logger.info(f"Requeued {stats['tasks_requeued']} stuck pending tasks")
                
        except Exception as e:
            logger.error(f"Error reconciling pending tasks: {e}", exc_info=True)
            
        return stats
        
    def get_status(self) -> Dict[str, Any]:
        """
        Get service status information.
        
        Returns:
            Status dictionary with service information
        """
        return {
            "running": self._running,
            "mode": self.mode.value,
            "last_reconciliation": self._last_reconciliation.isoformat() if self._last_reconciliation else None,
            "reconciliation_count": self._reconciliation_count,
            "task_timeout": self.task_timeout,
            "reconciliation_interval": self.reconciliation_interval if self.mode == ReconciliationMode.PERIODIC else None
        }