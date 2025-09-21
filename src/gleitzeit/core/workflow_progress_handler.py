"""
WorkflowProgressHandler - Event-driven workflow progress tracking.

This handler listens to task completion events and maintains incremental
workflow progress, properly updating workflow status in persistence and
emitting progress events for UI/API consumption.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Set, Optional

from ..core.events import GleitzeitEvent, EventType
from ..core.models import WorkflowStatus, TaskStatus
from ..persistence.unified_persistence import UnifiedPersistenceAdapter

logger = logging.getLogger(__name__)


class WorkflowProgressHandler:
    """Event-driven workflow progress tracking handler."""
    
    def __init__(
        self,
        event_bus,
        persistence: UnifiedPersistenceAdapter,
        instance_id: str = "default"
    ):
        self.event_bus = event_bus
        self.persistence = persistence
        self.instance_id = instance_id
        self._running = False
        
        # Track workflow progress in memory for efficiency
        self._workflow_progress: Dict[str, Dict[str, int]] = {}
        self._lock = asyncio.Lock()
        
    async def start(self):
        """Start the workflow progress handler."""
        if self._running:
            return
            
        logger.info(f"Starting WorkflowProgressHandler (instance: {self.instance_id})")
        
        # Register event handlers
        self.event_bus.register(EventType.TASK_COMPLETED, self._handle_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._handle_task_failed)
        
        self._running = True
        logger.info("WorkflowProgressHandler started")
        
    async def stop(self):
        """Stop the workflow progress handler."""
        if not self._running:
            return
            
        logger.info("Stopping WorkflowProgressHandler")
        
        # Unregister event handlers
        if self.event_bus:
            try:
                self.event_bus.unregister(EventType.TASK_COMPLETED, self._handle_task_completed)
                self.event_bus.unregister(EventType.TASK_FAILED, self._handle_task_failed)
            except Exception as e:
                logger.error(f"Error unregistering event handlers: {e}")
        
        self._running = False
        self._workflow_progress.clear()
        logger.info("WorkflowProgressHandler stopped")
        
    async def _handle_task_completed(self, event: GleitzeitEvent):
        """Handle task completion event."""
        task_id = event.data.get("task_id")
        if not task_id:
            logger.warning("Received TASK_COMPLETED event without task_id")
            return
            
        logger.debug(f"Processing task completion: {task_id}")
        
        try:
            # Get task and workflow information
            task = await self.persistence.get_task(task_id)
            if not task or not task.workflow_id:
                logger.warning(f"Task {task_id} not found or missing workflow_id")
                return
                
            # Update workflow progress
            await self._update_workflow_progress(task.workflow_id, completed_task_id=task_id)
            
        except Exception as e:
            logger.error(f"Error handling task completion {task_id}: {e}")
            
    async def _handle_task_failed(self, event: GleitzeitEvent):
        """Handle task failure event."""
        task_id = event.data.get("task_id")
        if not task_id:
            logger.warning("Received TASK_FAILED event without task_id")
            return
            
        logger.debug(f"Processing task failure: {task_id}")
        
        try:
            # Get task and workflow information
            task = await self.persistence.get_task(task_id)
            if not task or not task.workflow_id:
                logger.warning(f"Task {task_id} not found or missing workflow_id")
                return
                
            # Check if this is a permanent failure
            task_result = await self.persistence.get_task_result(task_id)
            if task_result:
                metadata = task_result.metadata or {}
                is_retryable = metadata.get("is_retryable", True)
                is_permanent = metadata.get("is_permanent", False)
                
                # Only update progress for permanent failures
                if is_permanent or not is_retryable:
                    await self._update_workflow_progress(task.workflow_id, failed_task_id=task_id)
            else:
                # If no result yet, treat as temporary failure
                logger.debug(f"Task {task_id} failed but no result available yet - treating as temporary")
                
        except Exception as e:
            logger.error(f"Error handling task failure {task_id}: {e}")
            
    async def _update_workflow_progress(
        self, 
        workflow_id: str, 
        completed_task_id: str = None,
        failed_task_id: str = None
    ):
        """Update workflow progress and status."""
        async with self._lock:
            try:
                # Get workflow from persistence
                workflow = await self.persistence.get_workflow(workflow_id)
                if not workflow:
                    logger.warning(f"Workflow {workflow_id} not found")
                    return
                    
                # Initialize progress tracking for this workflow if needed
                if workflow_id not in self._workflow_progress:
                    self._workflow_progress[workflow_id] = {
                        "total": len(workflow.tasks),
                        "completed": 0,
                        "failed": 0,
                        "completed_tasks": set(),
                        "failed_tasks": set()
                    }
                
                progress = self._workflow_progress[workflow_id]
                
                # Update progress counters
                if completed_task_id:
                    if completed_task_id not in progress["completed_tasks"]:
                        progress["completed_tasks"].add(completed_task_id)
                        progress["completed"] += 1
                        logger.debug(f"Workflow {workflow_id}: task {completed_task_id} completed ({progress['completed']}/{progress['total']})")
                        
                if failed_task_id:
                    if failed_task_id not in progress["failed_tasks"]:
                        progress["failed_tasks"].add(failed_task_id)
                        progress["failed"] += 1
                        logger.debug(f"Workflow {workflow_id}: task {failed_task_id} failed ({progress['failed']} failed, {progress['completed']}/{progress['total']} completed)")
                
                # Determine workflow status (pass workflow for task state checking)
                old_status = workflow.status
                new_status = await self._calculate_workflow_status(progress, workflow)
                
                # Update workflow if status changed or we have progress updates
                if new_status != old_status or completed_task_id or failed_task_id:
                    workflow.status = new_status
                    
                    # Set completion time if workflow is done
                    if new_status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                        workflow.completed_at = datetime.utcnow()
                        
                    # Save workflow to persistence
                    await self.persistence.save_workflow(workflow)
                    
                    # Emit progress event for UI/API consumption
                    await self._emit_progress_event(workflow_id, progress, new_status, old_status)
                    
                    logger.info(f"Workflow {workflow_id} progress updated: {progress['completed']}/{progress['total']} completed, {progress['failed']} failed, status: {new_status}")
                    
            except Exception as e:
                logger.error(f"Error updating workflow progress for {workflow_id}: {e}")
                
    async def _calculate_workflow_status(self, progress: Dict, workflow=None) -> WorkflowStatus:
        """Calculate workflow status based on task progress and states."""
        total = progress["total"]
        completed = progress["completed"]
        failed = progress["failed"]
        finished = completed + failed
        
        if failed > 0 and finished == total:
            # All tasks finished and some failed
            return WorkflowStatus.FAILED
        elif completed == total:
            # All tasks completed successfully
            return WorkflowStatus.COMPLETED
        elif finished == total:
            # This shouldn't happen but handle it
            return WorkflowStatus.COMPLETED if failed == 0 else WorkflowStatus.FAILED
        
        # Check for special waiting states if workflow provided
        if workflow and hasattr(workflow, 'tasks'):
            has_waiting = False
            has_scheduled = False
            has_executing = False
            has_paused = False
            
            for task in workflow.tasks:
                # Skip completed and failed tasks
                if task.id in progress.get("completed_tasks", set()) or task.id in progress.get("failed_tasks", set()):
                    continue
                    
                # Check task status
                if hasattr(task, 'status'):
                    status = task.status
                    if isinstance(status, str):
                        if status == TaskStatus.WAITING.value:
                            has_waiting = True
                        elif status == TaskStatus.SCHEDULED.value:
                            has_scheduled = True
                        elif status == TaskStatus.PAUSED.value:
                            has_paused = True
                        elif status in [TaskStatus.EXECUTING.value, TaskStatus.QUEUED.value]:
                            has_executing = True
                    elif hasattr(status, 'value'):
                        if status == TaskStatus.WAITING:
                            has_waiting = True
                        elif status == TaskStatus.SCHEDULED:
                            has_scheduled = True
                        elif status == TaskStatus.PAUSED:
                            has_paused = True
                        elif status in [TaskStatus.EXECUTING, TaskStatus.QUEUED]:
                            has_executing = True
            
            # Determine status based on task states - prioritize special states
            if has_paused:
                # If any task is paused, workflow is paused
                return WorkflowStatus.PAUSED
            elif has_waiting:
                # If any task is waiting, workflow is waiting
                return WorkflowStatus.WAITING
            elif has_scheduled:
                # If any task is scheduled, workflow is scheduled
                return WorkflowStatus.SCHEDULED
            elif completed > 0 or has_executing:
                return WorkflowStatus.RUNNING
            else:
                return WorkflowStatus.PENDING
        
        # Fallback logic if no workflow provided
        elif failed > 0:
            # Some tasks failed but workflow not finished yet
            return WorkflowStatus.RUNNING
        elif completed > 0:
            # Some tasks completed, none failed
            return WorkflowStatus.RUNNING
        else:
            # No progress yet
            return WorkflowStatus.PENDING
            
    async def _emit_progress_event(
        self, 
        workflow_id: str, 
        progress: Dict, 
        new_status: WorkflowStatus,
        old_status: WorkflowStatus
    ):
        """Emit workflow progress event for UI/API consumption."""
        try:
            event_data = {
                "workflow_id": workflow_id,
                "total_tasks": progress["total"],
                "completed_tasks": progress["completed"],
                "failed_tasks": progress["failed"],
                "status": new_status.value if hasattr(new_status, 'value') else str(new_status),
                "previous_status": old_status.value if hasattr(old_status, 'value') else str(old_status),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.WORKFLOW_PROGRESS,
                data=event_data
            ))
            
            # Also emit completion events for major status changes
            if new_status == WorkflowStatus.COMPLETED and old_status != WorkflowStatus.COMPLETED:
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.WORKFLOW_COMPLETED,
                    data={"workflow_id": workflow_id}
                ))
            elif new_status == WorkflowStatus.FAILED and old_status != WorkflowStatus.FAILED:
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.WORKFLOW_FAILED,
                    data={"workflow_id": workflow_id}
                ))
                
        except Exception as e:
            logger.error(f"Error emitting progress event for workflow {workflow_id}: {e}")
            
    async def get_workflow_progress(self, workflow_id: str) -> Optional[Dict]:
        """Get current progress for a workflow."""
        async with self._lock:
            return self._workflow_progress.get(workflow_id, None)
            
    async def reset_workflow_progress(self, workflow_id: str):
        """Reset progress tracking for a workflow."""
        async with self._lock:
            if workflow_id in self._workflow_progress:
                del self._workflow_progress[workflow_id]
                logger.debug(f"Reset progress tracking for workflow {workflow_id}")