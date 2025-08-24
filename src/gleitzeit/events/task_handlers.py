"""Event handlers for task-related events."""

import asyncio
import logging
from typing import TYPE_CHECKING
from ..events.base import EventHandler
from ..core.events import GleitzeitEvent, EventType
from ..core.models import TaskStatus

if TYPE_CHECKING:
    from ..persistence.base import UnifiedPersistence
    from ..task_queue.task_queue import QueueManager

logger = logging.getLogger(__name__)


class TaskCompletedHandler(EventHandler):
    """Handles task completion events by updating persistence and triggering dependency resolution."""
    
    def __init__(self, persistence: "UnifiedPersistence", queue_manager: "QueueManager"):
        self.persistence = persistence
        self.queue_manager = queue_manager
    
    async def handle(self, event: GleitzeitEvent) -> None:
        """Handle task completion by updating persistence and resolving dependencies."""
        if event.event_type != EventType.TASK_COMPLETED:
            return
        
        task_id = event.data.get("task_id")
        workflow_id = event.data.get("workflow_id")
        
        if not task_id:
            logger.error("TaskCompletedEvent missing task_id in data")
            return
        
        try:
            # Only handle dependency resolution - persistence is handled by PersistenceTaskHandler
            if self.queue_manager:
                await self.queue_manager.mark_task_completed(task_id)
                logger.debug(f"Task {task_id} dependency resolution triggered in queue manager")
            
            logger.info(f"Task {task_id} completion handled successfully")
            
        except Exception as e:
            logger.error(f"Failed to handle task completion for {task_id}: {e}")
            raise


# TaskFailedHandler removed for now - focusing on completion events only