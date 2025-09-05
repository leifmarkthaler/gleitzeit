"""
Event-driven task mixin for real-time task tracking.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Callable, List, AsyncIterator
from datetime import datetime

from gleitzeit.core.models import Task, TaskResult, TaskStatus
from ..events import ClientEvent, EventType

logger = logging.getLogger(__name__)


class EventTaskMixin:
    """
    Mixin providing event-driven task operations.
    
    This mixin enhances task operations with:
    - Real-time status updates
    - Event-based completion detection
    - Retry notifications
    - Result streaming
    """
    
    async def submit_task_with_tracking(self,
                                       task: Task,
                                       on_start: Optional[Callable] = None,
                                       on_complete: Optional[Callable] = None,
                                       on_error: Optional[Callable] = None,
                                       on_retry: Optional[Callable] = None,
                                       auto_wait: bool = False) -> Dict[str, Any]:
        """
        Submit task with real-time event tracking.
        
        Args:
            task: Task to submit
            on_start: Callback when task starts
            on_complete: Callback when task completes
            on_error: Callback for errors
            on_retry: Callback for retries
            auto_wait: Automatically wait for completion
            
        Returns:
            Submission response with tracking info
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
            
        # Check if adapter supports events
        if not hasattr(self._adapter, 'event_bus') or not self._adapter.event_bus:
            # Fall back to regular submission
            response = await self.submit_task(task)
            if auto_wait:
                result = await self.wait_for_task(task.id)
                response['result'] = result
            return response
            
        # Submit task
        response = await self.submit_task(task)
        task_id = task.id
        
        # Set up tracking
        event_bus = self._adapter.event_bus
        sub_ids = []
        completion_future = asyncio.Future() if auto_wait else None
        
        # Task start handler
        async def handle_start(event: ClientEvent):
            if event.data.get('task_id') != task_id:
                return
                
            logger.info(f"Task {task_id} started")
            
            if on_start:
                try:
                    result = on_start(task_id, event.data)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Error in start callback: {e}")
                    
        # Task completion handler
        async def handle_completion(event: ClientEvent):
            if event.data.get('task_id') != task_id:
                return
                
            result = TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                result=event.data.get('result'),
                error=None,
                completed_at=datetime.utcnow()
            )
            
            logger.info(f"Task {task_id} completed")
            
            if on_complete:
                try:
                    cb_result = on_complete(task_id, result)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception as e:
                    logger.error(f"Error in completion callback: {e}")
                    
            if completion_future and not completion_future.done():
                completion_future.set_result(result)
                
        # Task error handler
        async def handle_error(event: ClientEvent):
            if event.data.get('task_id') != task_id:
                return
                
            is_permanent = event.data.get('is_permanent', False)
            if not is_permanent:
                return  # Will be retried
                
            error = event.data.get('error_message', 'Task failed')
            logger.error(f"Task {task_id} failed: {error}")
            
            if on_error:
                try:
                    cb_result = on_error(task_id, error)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception as e:
                    logger.error(f"Error in error callback: {e}")
                    
            if completion_future and not completion_future.done():
                result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    result=None,
                    error=error,
                    completed_at=datetime.utcnow()
                )
                completion_future.set_result(result)
                
        # Retry handler
        async def handle_retry(event: ClientEvent):
            if event.data.get('task_id') != task_id:
                return
                
            attempt = event.data.get('attempt_number', 0)
            retry_at = event.data.get('retry_at')
            
            logger.info(f"Task {task_id} scheduled for retry #{attempt} at {retry_at}")
            
            if on_retry:
                try:
                    cb_result = on_retry(task_id, attempt, retry_at)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception as e:
                    logger.error(f"Error in retry callback: {e}")
                    
        # Register event handlers
        sub_ids.append(event_bus.register(EventType.TASK_STARTED, handle_start))
        sub_ids.append(event_bus.register(EventType.TASK_COMPLETED, handle_completion))
        sub_ids.append(event_bus.register(EventType.TASK_FAILED, handle_error))
        sub_ids.append(event_bus.register(EventType.RETRY_SCHEDULED, handle_retry))
        sub_ids.append(event_bus.register(EventType.TASK_CANCELLED, handle_error))
        sub_ids.append(event_bus.register(EventType.TASK_TIMEOUT, handle_error))
        
        # Store subscription IDs
        response['event_subscriptions'] = sub_ids
        response['tracking_enabled'] = True
        
        # Wait for completion if requested
        if auto_wait and completion_future:
            try:
                result = await asyncio.wait_for(completion_future, timeout=task.timeout or 300)
                response['result'] = result
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for task {task_id}")
                response['result'] = None
            finally:
                # Cleanup subscriptions
                for sub_id in sub_ids:
                    event_bus.unregister(sub_id)
                    
        return response
        
    async def monitor_task(self,
                         task_id: str,
                         include_logs: bool = True,
                         include_events: bool = True,
                         include_metrics: bool = False) -> AsyncIterator[Dict[str, Any]]:
        """
        Monitor task execution in real-time.
        
        Args:
            task_id: Task ID to monitor
            include_logs: Include log entries
            include_events: Include task events
            include_metrics: Include performance metrics
            
        Yields:
            Stream of monitoring data
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
            
        if not hasattr(self._adapter, 'event_bus') or not self._adapter.event_bus:
            raise RuntimeError("Event monitoring not available")
            
        event_bus = self._adapter.event_bus
        
        # Queue for events
        event_queue = asyncio.Queue()
        
        # Event handler
        async def queue_event(event: ClientEvent):
            if event.data.get('task_id') == task_id:
                await event_queue.put({
                    'type': 'event',
                    'event_type': str(event.event_type),
                    'data': event.data,
                    'timestamp': event.timestamp
                })
                
        # Register for task events
        sub_ids = []
        event_types = [
            EventType.TASK_STARTED,
            EventType.TASK_COMPLETED,
            EventType.TASK_FAILED,
            EventType.TASK_CANCELLED,
            EventType.TASK_TIMEOUT,
            EventType.RETRY_SCHEDULED,
            EventType.TASK_READY_FOR_RETRY,
        ]
        
        for event_type in event_types:
            sub_id = event_bus.register(event_type, queue_event)
            sub_ids.append(sub_id)
            
        try:
            # Start log streaming if requested
            log_task = None
            if include_logs and hasattr(self._adapter, 'stream_task_logs'):
                async def stream_logs():
                    async for log in self._adapter.stream_task_logs(task_id):
                        await event_queue.put({
                            'type': 'log',
                            'level': log.get('level'),
                            'message': log.get('message'),
                            'timestamp': log.get('timestamp')
                        })
                        
                log_task = asyncio.create_task(stream_logs())
                
            # Start metrics streaming if requested
            metrics_task = None
            if include_metrics:
                async def stream_metrics():
                    while True:
                        # Get task metrics (implementation specific)
                        metrics = await self._get_task_metrics(task_id)
                        if metrics:
                            await event_queue.put({
                                'type': 'metrics',
                                'data': metrics,
                                'timestamp': datetime.utcnow()
                            })
                        await asyncio.sleep(1)  # Update every second
                        
                metrics_task = asyncio.create_task(stream_metrics())
                
            # Yield events, logs, and metrics
            while True:
                try:
                    item = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    yield item
                    
                    # Check if task is complete
                    if item.get('type') == 'event' and item.get('event_type') in [
                        str(EventType.TASK_COMPLETED),
                        str(EventType.TASK_FAILED),
                        str(EventType.TASK_CANCELLED)
                    ]:
                        break
                        
                except asyncio.TimeoutError:
                    continue
                    
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
                    
            if metrics_task:
                metrics_task.cancel()
                try:
                    await metrics_task
                except asyncio.CancelledError:
                    pass
                    
    async def wait_for_task_event(self,
                                 task_id: str,
                                 event_type: EventType,
                                 timeout: Optional[float] = None) -> Optional[ClientEvent]:
        """
        Wait for a specific task event.
        
        Args:
            task_id: Task ID to wait for
            event_type: Event type to wait for
            timeout: Optional timeout in seconds
            
        Returns:
            The event when it occurs, or None if timeout
        """
        if not self._adapter or not hasattr(self._adapter, 'event_bus'):
            return None
            
        event_bus = self._adapter.event_bus
        
        # Create filter for this task
        def task_filter(event: ClientEvent) -> bool:
            return event.data.get('task_id') == task_id
            
        # Wait for event
        return await event_bus.wait_for(event_type, filter=task_filter, timeout=timeout)
        
    async def get_task_timeline(self, task_id: str) -> List[Dict[str, Any]]:
        """
        Get timeline of task events.
        
        Args:
            task_id: Task ID
            
        Returns:
            List of events in chronological order
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
            
        # Get events from adapter if it supports it
        if hasattr(self._adapter, 'get_events'):
            events = await self._adapter.get_events(task_id=task_id)
            
            # Sort by timestamp
            events.sort(key=lambda e: e.get('timestamp', ''))
            
            # Create timeline
            timeline = []
            for event in events:
                timeline.append({
                    'timestamp': event.get('timestamp'),
                    'event_type': event.get('event_type'),
                    'description': self._describe_event(event),
                    'data': event.get('data', {})
                })
                
            return timeline
            
        return []
        
    def _describe_event(self, event: Dict[str, Any]) -> str:
        """Generate human-readable description of event."""
        event_type = event.get('event_type', 'unknown')
        
        descriptions = {
            'task:started': 'Task execution started',
            'task:completed': 'Task completed successfully',
            'task:failed': 'Task failed with error',
            'task:cancelled': 'Task was cancelled',
            'task:timeout': 'Task timed out',
            'retry:scheduled': 'Retry scheduled',
            'task:ready_for_retry': 'Ready for retry attempt',
        }
        
        return descriptions.get(event_type, f'Event: {event_type}')
        
    async def _get_task_metrics(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task performance metrics (placeholder for implementation)."""
        # This would be implemented based on your metrics system
        return None
        
    async def subscribe_to_task_events(self,
                                      task_id: str,
                                      event_types: Optional[List[EventType]] = None,
                                      handler: Optional[Callable] = None) -> List[str]:
        """
        Subscribe to specific task events.
        
        Args:
            task_id: Task ID to subscribe to
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
                EventType.TASK_STARTED,
                EventType.TASK_COMPLETED,
                EventType.TASK_FAILED,
                EventType.TASK_CANCELLED,
                EventType.TASK_TIMEOUT,
                EventType.RETRY_SCHEDULED,
            ]
            
        # Create task filter
        def task_filter(event: ClientEvent) -> bool:
            return event.data.get('task_id') == task_id
            
        # Default handler if not provided
        if not handler:
            async def default_handler(event: ClientEvent):
                logger.info(f"Task {task_id} event: {event.event_type}")
                
            handler = default_handler
            
        # Register for each event type
        for event_type in event_types:
            sub_id = event_bus.register(
                event_type,
                handler,
                filter=task_filter
            )
            sub_ids.append(sub_id)
            
        logger.debug(f"Subscribed to {len(sub_ids)} event types for task {task_id}")
        
        return sub_ids
        
    async def unsubscribe_task_events(self, subscription_ids: List[str]) -> int:
        """
        Unsubscribe from task events.
        
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
        
    async def get_retry_info(self, task_id: str) -> Dict[str, Any]:
        """
        Get retry information for a task.
        
        Args:
            task_id: Task ID
            
        Returns:
            Retry information including attempts and schedule
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
            
        # Get task
        task = await self.get_task(task_id)
        if not task:
            return {'error': 'Task not found'}
            
        # Get retry metadata
        metadata = task.metadata if hasattr(task, 'metadata') else {}
        
        return {
            'task_id': task_id,
            'retry_attempt': metadata.get('retry_attempt', 0),
            'max_retries': task.retry_config.max_attempts if hasattr(task, 'retry_config') else 3,
            'last_error': metadata.get('last_error'),
            'retry_at': metadata.get('retry_at'),
            'max_retries_reached': metadata.get('max_retries_reached', False)
        }