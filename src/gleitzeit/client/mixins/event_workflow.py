"""
Event-driven workflow mixin for real-time workflow tracking.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Callable, List, AsyncIterator
from datetime import datetime

from gleitzeit.core.models import Workflow, TaskResult, WorkflowStatus, TaskStatus
from gleitzeit.core.errors import SystemError
from ..events import ClientEvent, EventType

logger = logging.getLogger(__name__)


class EventWorkflowMixin:
    """
    Mixin providing event-driven workflow operations.
    
    This mixin enhances workflow operations with:
    - Real-time progress tracking
    - Event-based completion detection
    - Live status updates
    - Progress callbacks
    """
    
    async def submit_workflow_with_tracking(self, 
                                           workflow: Workflow,
                                           on_progress: Optional[Callable] = None,
                                           on_task_complete: Optional[Callable] = None,
                                           on_complete: Optional[Callable] = None,
                                           on_error: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Submit workflow with real-time event tracking.
        
        Args:
            workflow: Workflow to submit
            on_progress: Callback for progress updates (called with percent complete)
            on_task_complete: Callback for each task completion
            on_complete: Callback when workflow completes
            on_error: Callback for errors
            
        Returns:
            Submission response with tracking info
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
            
        # Check if adapter supports events
        if not hasattr(self._adapter, 'event_bus') or not self._adapter.event_bus:
            # Fall back to regular submission
            return await self.submit_workflow(workflow)
            
        # Submit workflow
        response = await self.submit_workflow(workflow)
        workflow_id = response.get('workflow_id')
        
        if not workflow_id:
            return response
            
        # Set up tracking
        total_tasks = len(workflow.tasks)
        completed_tasks = 0
        task_results = {}
        
        # Progress tracker
        async def track_progress(event: ClientEvent):
            nonlocal completed_tasks
            
            task_id = event.data.get('task_id')
            if task_id in [t.id for t in workflow.tasks]:
                completed_tasks += 1
                progress = (completed_tasks / total_tasks) * 100
                
                # Call progress callback
                if on_progress:
                    try:
                        result = on_progress(progress, completed_tasks, total_tasks)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error(f"Error in progress callback: {e}")
                        
        # Task completion tracker
        async def track_task_completion(event: ClientEvent):
            task_id = event.data.get('task_id')
            if task_id not in [t.id for t in workflow.tasks]:
                return
                
            # Store result
            result = TaskResult(
                task_id=task_id,
                status=event.data.get('status', TaskStatus.COMPLETED.value),
                result=event.data.get('result'),
                error=event.data.get('error'),
                completed_at=datetime.utcnow()
            )
            task_results[task_id] = result
            
            # Call task completion callback
            if on_task_complete:
                try:
                    cb_result = on_task_complete(task_id, result)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception as e:
                    logger.error(f"Error in task completion callback: {e}")
                    
            # Track progress
            await track_progress(event)
            
        # Workflow completion tracker
        async def track_workflow_completion(event: ClientEvent):
            wf_id = event.data.get('workflow_id')
            if wf_id != workflow_id:
                return
                
            # Call completion callback
            if on_complete:
                try:
                    cb_result = on_complete(workflow_id, list(task_results.values()))
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception as e:
                    logger.error(f"Error in completion callback: {e}")
                    
        # Error tracker
        async def track_errors(event: ClientEvent):
            wf_id = event.data.get('workflow_id')
            if wf_id != workflow_id:
                return
                
            error = event.data.get('error', 'Workflow failed')
            
            # Call error callback
            if on_error:
                try:
                    cb_result = on_error(workflow_id, error)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception as e:
                    logger.error(f"Error in error callback: {e}")
                    
        # Register event handlers
        event_bus = self._adapter.event_bus
        sub_ids = []
        
        sub_ids.append(event_bus.register(EventType.TASK_COMPLETED, track_task_completion))
        sub_ids.append(event_bus.register(EventType.TASK_FAILED, track_task_completion))
        sub_ids.append(event_bus.register(EventType.WORKFLOW_COMPLETED, track_workflow_completion))
        sub_ids.append(event_bus.register(EventType.WORKFLOW_FAILED, track_errors))
        
        # Store subscription IDs for cleanup
        response['event_subscriptions'] = sub_ids
        response['tracking_enabled'] = True
        
        return response
        
    async def monitor_workflow(self, 
                             workflow_id: str,
                             include_logs: bool = False,
                             include_events: bool = True) -> AsyncIterator[Dict[str, Any]]:
        """
        Monitor workflow execution in real-time.
        
        Args:
            workflow_id: Workflow ID to monitor
            include_logs: Include log entries
            include_events: Include workflow events
            
        Yields:
            Stream of monitoring data
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
            
        if not hasattr(self._adapter, 'event_bus') or not self._adapter.event_bus:
            raise SystemError("Event monitoring not available")
            
        event_bus = self._adapter.event_bus
        
        # Queue for events
        event_queue = asyncio.Queue()
        
        # Event handler
        async def queue_event(event: ClientEvent):
            if event.data.get('workflow_id') == workflow_id:
                await event_queue.put({
                    'type': 'event',
                    'event_type': str(event.event_type),
                    'data': event.data,
                    'timestamp': event.timestamp
                })
                
        # Register for workflow events
        sub_ids = []
        event_types = [
            EventType.WORKFLOW_STARTED,
            EventType.TASK_STARTED,
            EventType.TASK_COMPLETED,
            EventType.TASK_FAILED,
            EventType.TASK_CANCELLED,
            EventType.RETRY_SCHEDULED,
            EventType.WORKFLOW_COMPLETED,
            EventType.WORKFLOW_FAILED,
            EventType.WORKFLOW_CANCELLED,
        ]
        
        for event_type in event_types:
            sub_id = event_bus.register(event_type, queue_event)
            sub_ids.append(sub_id)
            
        try:
            # Start log streaming if requested
            log_task = None
            if include_logs and hasattr(self._adapter, 'stream_workflow_logs'):
                async def stream_logs():
                    async for log in self._adapter.stream_workflow_logs(workflow_id):
                        await event_queue.put({
                            'type': 'log',
                            'level': log.get('level'),
                            'message': log.get('message'),
                            'timestamp': log.get('timestamp')
                        })
                        
                log_task = asyncio.create_task(stream_logs())
                
            # Yield events and logs
            while True:
                try:
                    item = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    yield item
                except asyncio.TimeoutError:
                    # Check if workflow is complete
                    workflow = await self.get_workflow(workflow_id)
                    if workflow and workflow.status in [WorkflowStatus.COMPLETED.value, WorkflowStatus.FAILED.value, WorkflowStatus.CANCELLED.value]:
                        break
                        
        finally:
            # Cleanup
            for sub_id in sub_ids:
                event_bus.unregister(sub_id)
                
            if log_task:
                log_task.cancel()
                try:
                    await log_task
                except asyncio.CancelledError:
                    pass
                    
    async def wait_for_workflow_event(self,
                                     workflow_id: str,
                                     event_type: EventType,
                                     timeout: Optional[float] = None) -> Optional[ClientEvent]:
        """
        Wait for a specific workflow event.
        
        Args:
            workflow_id: Workflow ID to wait for
            event_type: Event type to wait for
            timeout: Optional timeout in seconds
            
        Returns:
            The event when it occurs, or None if timeout
        """
        if not self._adapter or not hasattr(self._adapter, 'event_bus'):
            return None
            
        event_bus = self._adapter.event_bus
        
        # Create filter for this workflow
        def workflow_filter(event: ClientEvent) -> bool:
            return event.data.get('workflow_id') == workflow_id
            
        # Wait for event
        return await event_bus.wait_for(event_type, filter=workflow_filter, timeout=timeout)
        
    async def get_workflow_progress(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get real-time workflow progress.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Progress information
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
            
        # Get workflow
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return {'error': 'Workflow not found'}
            
        # Get task statuses
        total_tasks = len(workflow.tasks)
        completed_tasks = 0
        failed_tasks = 0
        running_tasks = 0
        
        for task in workflow.tasks:
            if hasattr(task, 'status'):
                if task.status == TaskStatus.COMPLETED.value:
                    completed_tasks += 1
                elif task.status == 'failed':
                    failed_tasks += 1
                elif task.status in ['running', 'started']:
                    running_tasks += 1
                    
        progress = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
        
        return {
            'workflow_id': workflow_id,
            'status': workflow.status if hasattr(workflow, 'status') else 'unknown',
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'running_tasks': running_tasks,
            'pending_tasks': total_tasks - completed_tasks - failed_tasks - running_tasks,
            'progress_percent': progress,
            'is_complete': completed_tasks == total_tasks,
            'has_failures': failed_tasks > 0
        }
        
    async def subscribe_to_workflow_events(self,
                                          workflow_id: str,
                                          event_types: Optional[List[EventType]] = None,
                                          handler: Optional[Callable] = None) -> List[str]:
        """
        Subscribe to specific workflow events.
        
        Args:
            workflow_id: Workflow ID to subscribe to
            event_types: Optional list of event types (None = all)
            handler: Optional event handler
            
        Returns:
            List of subscription IDs
        """
        if not self._adapter or not hasattr(self._adapter, 'event_bus'):
            return []
            
        event_bus = self._adapter.event_bus
        sub_ids = []
        
        # Default event types if not specified
        if not event_types:
            event_types = [
                EventType.WORKFLOW_STARTED,
                EventType.TASK_STARTED,
                EventType.TASK_COMPLETED,
                EventType.TASK_FAILED,
                EventType.WORKFLOW_COMPLETED,
                EventType.WORKFLOW_FAILED,
            ]
            
        # Create workflow filter
        def workflow_filter(event: ClientEvent) -> bool:
            return event.data.get('workflow_id') == workflow_id
            
        # Default handler if not provided
        if not handler:
            async def default_handler(event: ClientEvent):
                logger.info(f"Workflow {workflow_id} event: {event.event_type}")
                
            handler = default_handler
            
        # Register for each event type
        for event_type in event_types:
            sub_id = event_bus.register(
                event_type,
                handler,
                filter=workflow_filter
            )
            sub_ids.append(sub_id)
            
        logger.debug(f"Subscribed to {len(sub_ids)} event types for workflow {workflow_id}")
        
        return sub_ids
        
    async def unsubscribe_workflow_events(self, subscription_ids: List[str]) -> int:
        """
        Unsubscribe from workflow events.
        
        Args:
            subscription_ids: List of subscription IDs to unsubscribe
            
        Returns:
            Number of subscriptions removed
        """
        if not self._adapter or not hasattr(self._adapter, 'event_bus'):
            return 0
            
        event_bus = self._adapter.event_bus
        removed = 0
        
        for sub_id in subscription_ids:
            if event_bus.unregister(sub_id):
                removed += 1
                
        return removed