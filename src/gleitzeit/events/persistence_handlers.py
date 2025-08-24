"""Persistence event handlers for event-driven architecture."""

import asyncio
import logging
from typing import TYPE_CHECKING
from ..events.base import EventHandler
from ..core.events import GleitzeitEvent, EventType
from ..core.models import TaskStatus

if TYPE_CHECKING:
    from ..persistence.base import UnifiedPersistence

logger = logging.getLogger(__name__)


class PersistenceTaskHandler(EventHandler):
    """Handles all task-related events by updating persistence layer."""
    
    def __init__(self, persistence: "UnifiedPersistence"):
        self.persistence = persistence
    
    async def handle(self, event: GleitzeitEvent) -> None:
        """Handle task events by updating persistence."""
        logger.info(f"PERSISTENCE HANDLER DEBUG: Received event {event.event_type} for task {event.data.get('task_id')}")
        
        if event.event_type == EventType.TASK_COMPLETED:
            logger.info(f"PERSISTENCE HANDLER DEBUG: Processing TASK_COMPLETED event")
            await self._handle_task_completed(event)
        elif event.event_type == EventType.TASK_FAILED:
            logger.info(f"PERSISTENCE HANDLER DEBUG: Processing TASK_FAILED event")
            await self._handle_task_failed(event)
        elif event.event_type == EventType.TASK_STARTED:
            logger.info(f"PERSISTENCE HANDLER DEBUG: Processing TASK_STARTED event")
            await self._handle_task_started(event)
        else:
            logger.warning(f"PERSISTENCE HANDLER DEBUG: Unknown event type {event.event_type}")
    
    async def _handle_task_completed(self, event: GleitzeitEvent) -> None:
        """Handle task completion by updating task status and saving result."""
        task_id = event.data.get("task_id")
        workflow_id = event.data.get("workflow_id")
        
        if not task_id:
            logger.error("TaskCompletedEvent missing task_id in data")
            return
        
        try:
            # Get the task from persistence
            task = await self.persistence.get_task(task_id)
            if not task:
                logger.error(f"Task {task_id} not found in persistence for completion")
                return
            
            # Update task status to completed
            logger.info(f"PERSISTENCE DEBUG: Task {task_id} current status: {task.status}")
            task.status = TaskStatus.COMPLETED
            if not task.completed_at:
                from datetime import datetime
                task.completed_at = datetime.utcnow()
            
            logger.info(f"PERSISTENCE DEBUG: Task {task_id} setting status to COMPLETED, completed_at: {task.completed_at}")
            
            # Save the updated task
            try:
                await self.persistence.save_task(task)
                logger.info(f"PERSISTENCE DEBUG: Task {task_id} save_task() completed successfully")
            except Exception as save_error:
                logger.error(f"PERSISTENCE DEBUG: Task {task_id} save_task() failed: {save_error}")
                raise
            
            # Verify the save by reading it back
            saved_task = await self.persistence.get_task(task_id)
            if saved_task:
                logger.info(f"PERSISTENCE DEBUG: Task {task_id} read back status: {saved_task.status}")
            else:
                logger.error(f"PERSISTENCE DEBUG: Task {task_id} not found after save!")
            
            # Update workflow's completed_tasks list if task belongs to a workflow
            if workflow_id:
                workflow = await self.persistence.get_workflow(workflow_id)
                if workflow and task_id not in workflow.completed_tasks:
                    workflow.completed_tasks.append(task_id)
                    await self.persistence.save_workflow(workflow)
                    logger.debug(f"Added task {task_id} to workflow {workflow_id} completed_tasks")
            
            logger.info(f"Task {task_id} completion persisted successfully")
            
        except Exception as e:
            logger.error(f"Failed to persist task completion for {task_id}: {e}")
            raise
    
    async def _handle_task_failed(self, event: GleitzeitEvent) -> None:
        """Handle task failure by updating task status."""
        task_id = event.data.get("task_id")
        error_message = event.data.get("error")
        
        if not task_id:
            logger.error("TaskFailedEvent missing task_id in data")
            return
        
        try:
            # Get the task from persistence
            task = await self.persistence.get_task(task_id)
            if not task:
                logger.error(f"Task {task_id} not found in persistence for failure")
                return
            
            # Update task status to failed
            task.status = TaskStatus.FAILED
            task.error_message = error_message
            if not task.completed_at:
                from datetime import datetime
                task.completed_at = datetime.utcnow()
            
            # Save the updated task
            await self.persistence.save_task(task)
            logger.debug(f"Task {task_id} status updated to FAILED in persistence")
            
            logger.info(f"Task {task_id} failure persisted successfully")
            
        except Exception as e:
            logger.error(f"Failed to persist task failure for {task_id}: {e}")
            raise
    
    async def _handle_task_started(self, event: GleitzeitEvent) -> None:
        """Handle task start by updating task status."""
        task_id = event.data.get("task_id")
        
        if not task_id:
            logger.error("TaskStartedEvent missing task_id in data")
            return
        
        try:
            # Get the task from persistence
            task = await self.persistence.get_task(task_id)
            if not task:
                logger.error(f"Task {task_id} not found in persistence for start")
                return
            
            # Update task status to executing
            task.status = TaskStatus.EXECUTING
            if not task.started_at:
                from datetime import datetime
                task.started_at = datetime.utcnow()
            
            # Save the updated task
            await self.persistence.save_task(task)
            logger.debug(f"Task {task_id} status updated to EXECUTING in persistence")
            
            logger.info(f"Task {task_id} start persisted successfully")
            
        except Exception as e:
            logger.error(f"Failed to persist task start for {task_id}: {e}")
            raise


class PersistenceResultHandler(EventHandler):
    """Handles task result storage events."""
    
    def __init__(self, persistence: "UnifiedPersistence"):
        self.persistence = persistence
    
    async def handle(self, event: GleitzeitEvent) -> None:
        """Handle task result events by saving results to persistence."""
        if event.event_type == EventType.TASK_COMPLETED:
            await self._save_task_result(event)
    
    async def _save_task_result(self, event: GleitzeitEvent) -> None:
        """Save task result to persistence."""
        task_id = event.data.get("task_id")
        
        if not task_id:
            logger.error("TaskCompletedEvent missing task_id for result storage")
            return
        
        try:
            # Check if we already have a result stored
            existing_result = await self.persistence.get_task_result(task_id)
            if existing_result:
                logger.debug(f"Task result for {task_id} already exists, skipping")
                return
            
            # For now, we'll need to get the result from somewhere
            # In a full implementation, the result would be passed in the event data
            logger.debug(f"Task result storage handled for {task_id}")
            
        except Exception as e:
            logger.error(f"Failed to store task result for {task_id}: {e}")
            # Don't raise here as result storage is less critical than status updates