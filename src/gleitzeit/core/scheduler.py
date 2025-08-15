"""
Event Scheduler for Gleitzeit V4

Schedules delayed events (like task retries) to flow through the event-driven
Socket.IO coordination system rather than using separate background processes.
"""

import asyncio
import heapq
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ScheduledEventType(str, Enum):
    """Types of events that can be scheduled"""
    TASK_RETRY = "task:retry"
    WORKFLOW_TIMEOUT = "workflow:timeout"
    HEALTH_CHECK = "health:check"
    CLEANUP = "cleanup"


@dataclass
class ScheduledEvent:
    """A scheduled event to be executed later"""
    event_type: ScheduledEventType
    scheduled_at: datetime
    event_data: Dict[str, Any] = field(default_factory=dict)
    event_id: Optional[str] = None
    
    def __lt__(self, other):
        """For heapq ordering"""
        return self.scheduled_at < other.scheduled_at


class EventScheduler:
    """
    Event scheduler that integrates with Socket.IO event system
    
    Instead of running separate background processes, this scheduler
    emits events through the main event coordination system when
    their scheduled time arrives.
    """
    
    def __init__(self, emit_callback: Callable[[str, Dict[str, Any]], Any]):
        """
        Initialize scheduler with event emission callback
        
        Args:
            emit_callback: Function to call when emitting scheduled events
                          Should be async: emit_callback(event_type, data)
        """
        self.emit_callback = emit_callback
        self._scheduled_events: List[ScheduledEvent] = []
        self._event_lookup: Dict[str, ScheduledEvent] = {}
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        
        logger.info("Initialized EventScheduler")
    
    async def start(self) -> None:
        """Start the scheduler"""
        if self._running:
            return
        
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("EventScheduler started")
    
    async def stop(self) -> None:
        """Stop the scheduler"""
        self._running = False
        
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        
        logger.info("EventScheduler stopped")
    
    async def schedule_event(self, 
                           event_type: ScheduledEventType,
                           delay: timedelta,
                           event_data: Dict[str, Any],
                           event_id: Optional[str] = None) -> str:
        """
        Schedule an event to be emitted after a delay
        
        Args:
            event_type: Type of event to schedule
            delay: How long to wait before emitting
            event_data: Data to include with the event
            event_id: Optional unique ID for the event
            
        Returns:
            Event ID (generated if not provided)
        """
        if not event_id:
            event_id = f"{event_type}_{datetime.utcnow().timestamp()}"
        
        scheduled_at = datetime.utcnow() + delay
        
        event = ScheduledEvent(
            event_type=event_type,
            scheduled_at=scheduled_at,
            event_data=event_data.copy(),
            event_id=event_id
        )
        
        async with self._lock:
            heapq.heappush(self._scheduled_events, event)
            self._event_lookup[event_id] = event
        
        logger.debug(f"Scheduled {event_type} event {event_id} for {scheduled_at}")
        return event_id
    
    async def cancel_event(self, event_id: str) -> bool:
        """
        Cancel a scheduled event
        
        Args:
            event_id: ID of event to cancel
            
        Returns:
            True if event was cancelled, False if not found
        """
        async with self._lock:
            if event_id in self._event_lookup:
                # Remove from lookup (heap entry will be ignored)
                del self._event_lookup[event_id]
                logger.debug(f"Cancelled scheduled event: {event_id}")
                return True
        
        return False
    
    async def schedule_task_retry(self, 
                                task_id: str,
                                retry_delay: timedelta,
                                attempt_count: int,
                                error_message: str) -> str:
        """
        Schedule a task retry event
        
        Args:
            task_id: ID of task to retry
            retry_delay: How long to wait before retry
            attempt_count: Current attempt number
            error_message: Error that caused the retry
            
        Returns:
            Event ID
        """
        event_data = {
            "task_id": task_id,
            "attempt_count": attempt_count,
            "error_message": error_message,
            "scheduled_by": "scheduler",
            "retry_reason": "task_failure"
        }
        
        event_id = f"retry_{task_id}_{attempt_count}"
        
        return await self.schedule_event(
            event_type=ScheduledEventType.TASK_RETRY,
            delay=retry_delay,
            event_data=event_data,
            event_id=event_id
        )
    
    async def get_pending_events(self) -> List[Dict[str, Any]]:
        """Get list of pending scheduled events"""
        async with self._lock:
            pending = []
            for event in self._scheduled_events:
                if event.event_id in self._event_lookup:
                    pending.append({
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "scheduled_at": event.scheduled_at.isoformat(),
                        "data": event.event_data
                    })
            
            return sorted(pending, key=lambda x: x["scheduled_at"])
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics"""
        async with self._lock:
            total_scheduled = len(self._scheduled_events)
            active_events = len(self._event_lookup)
            
            # Count by event type
            type_counts = {}
            for event in self._scheduled_events:
                if event.event_id in self._event_lookup:
                    event_type = event.event_type
                    type_counts[event_type] = type_counts.get(event_type, 0) + 1
            
            return {
                "total_scheduled": total_scheduled,
                "active_events": active_events,
                "type_breakdown": type_counts,
                "running": self._running
            }
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop that processes due events"""
        while self._running:
            try:
                await self._process_due_events()
                await asyncio.sleep(0.01)  # Check every 10ms for better precision
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(0.1)  # Shorter sleep on error
    
    async def _process_due_events(self) -> None:
        """Process events that are due for emission"""
        now = datetime.utcnow()
        due_events = []
        
        async with self._lock:
            # Find all due events
            while self._scheduled_events:
                if self._scheduled_events[0].scheduled_at <= now:
                    event = heapq.heappop(self._scheduled_events)
                    
                    # Only process if event hasn't been cancelled
                    if event.event_id in self._event_lookup:
                        due_events.append(event)
                        del self._event_lookup[event.event_id]
                else:
                    break
        
        # Emit due events (outside of lock to avoid blocking)
        for event in due_events:
            try:
                await self._emit_scheduled_event(event)
            except Exception as e:
                logger.error(f"Failed to emit scheduled event {event.event_id}: {e}")
                # Continue processing other events even if one fails
    
    async def _emit_scheduled_event(self, event: ScheduledEvent) -> None:
        """Emit a scheduled event through the callback"""
        logger.debug(f"Emitting scheduled event: {event.event_type} ({event.event_id})")
        
        # Add scheduler metadata
        event_data = event.event_data.copy()
        event_data.update({
            "scheduled_event": True,
            "scheduled_at": event.scheduled_at.isoformat(),
            "emitted_at": datetime.utcnow().isoformat(),
            "event_id": event.event_id
        })
        
        # Emit through the callback (should be execution engine's emit_event)
        try:
            if asyncio.iscoroutinefunction(self.emit_callback):
                await self.emit_callback(event.event_type.value, event_data)
            else:
                # Handle sync callbacks
                result = self.emit_callback(event.event_type.value, event_data)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.error(f"Failed to emit event {event.event_id}: {e}")
            raise