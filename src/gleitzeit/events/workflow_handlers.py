"""Event handlers for workflow-related events."""

import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Any
from ..events.base import EventHandler
from ..core.events import GleitzeitEvent, EventType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WorkflowCompletedHandler(EventHandler):
    """Handles workflow completion events and stores results."""
    
    def __init__(self):
        self.completed_workflows: Dict[str, Any] = {}
        self._completion_futures: Dict[str, asyncio.Future] = {}
    
    async def handle(self, event: GleitzeitEvent) -> None:
        """Handle workflow completion by storing results and resolving futures."""
        logger.debug(f"WorkflowCompletedHandler received event type: {event.event_type}")
        if event.event_type != EventType.WORKFLOW_COMPLETED:
            return
        
        workflow_id = event.data.get("workflow_id")
        if not workflow_id:
            logger.error("WorkflowCompletedEvent missing workflow_id in data")
            return
        
        logger.debug(f"WorkflowCompletedHandler processing workflow {workflow_id}")
        
        # Store the workflow results
        self.completed_workflows[workflow_id] = event.data
        
        # Resolve any waiting futures
        if workflow_id in self._completion_futures:
            future = self._completion_futures[workflow_id]
            if not future.done():
                future.set_result(event.data)
            del self._completion_futures[workflow_id]
        
        logger.info(f"Workflow {workflow_id} completion event handled with status: {event.data.get('status')}")
    
    async def wait_for_workflow(self, workflow_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        """Wait for a workflow to complete and return its results."""
        # Check if already completed
        if workflow_id in self.completed_workflows:
            return self.completed_workflows[workflow_id]
        
        # Create a future to wait for completion
        future = asyncio.Future()
        self._completion_futures[workflow_id] = future
        
        try:
            # Wait for the workflow to complete with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            # Clean up the future if timeout
            if workflow_id in self._completion_futures:
                del self._completion_futures[workflow_id]
            raise TimeoutError(f"Workflow {workflow_id} did not complete within {timeout} seconds")