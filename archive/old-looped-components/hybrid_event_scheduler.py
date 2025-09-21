"""
Hybrid Event Scheduler - Backwards compatible wrapper for migration.

Provides the same interface as RedisEventScheduler but uses StatelessScheduler
internally for better scalability. Allows gradual migration from keyspace
notifications to stream-based processing.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Awaitable

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent, EventType
from ..events import EventBus
from .stateless_scheduler import StatelessScheduler

logger = logging.getLogger(__name__)


class HybridEventScheduler:
    """
    Hybrid scheduler that maintains RedisEventScheduler interface
    but uses StatelessScheduler internally.

    This provides a migration path from keyspace notifications to streams
    while maintaining backwards compatibility.
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[EventBus] = None,
        instance_id: Optional[str] = None,
        use_streams: bool = True
    ):
        """
        Initialize Hybrid Event Scheduler.

        Args:
            persistence: Redis persistence adapter
            event_bus: Optional event bus for notifications
            instance_id: Instance identifier
            use_streams: If True, use stream-based scheduling (recommended)
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.instance_id = instance_id or f"hybrid-scheduler-{uuid.uuid4().hex[:8]}"
        self.use_streams = use_streams

        # Initialize the appropriate scheduler
        if use_streams:
            self.scheduler = StatelessScheduler(
                persistence=persistence,
                event_bus=event_bus,
                instance_id=instance_id
            )
        else:
            # Fallback to original Redis scheduler if needed
            from .redis_event_scheduler import RedisEventScheduler
            self.scheduler = RedisEventScheduler(
                persistence=persistence,
                event_bus=event_bus,
                instance_id=instance_id
            )

        logger.info(f"Initialized HybridEventScheduler (streams: {use_streams}, instance: {self.instance_id})")

    async def initialize(self):
        """Initialize the underlying scheduler."""
        await self.scheduler.initialize()

        if self.use_streams:
            # Start stream processing
            await self.scheduler.start_processing()

        logger.info(f"HybridEventScheduler initialized (streams: {self.use_streams})")

    async def shutdown(self):
        """Shutdown the scheduler."""
        await self.scheduler.shutdown()
        logger.info("HybridEventScheduler shutdown")

    async def schedule_event(
        self,
        event_type: str,
        delay_seconds: float,
        payload: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None
    ) -> str:
        """
        Schedule an event to fire after a delay.

        Interface compatible with RedisEventScheduler.
        """
        return await self.scheduler.schedule_event(
            event_type=event_type,
            delay_seconds=delay_seconds,
            payload=payload,
            event_id=event_id
        )

    async def schedule_immediate(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Schedule an event to fire immediately.

        Interface compatible with RedisEventScheduler.
        """
        return await self.scheduler.schedule_immediate(
            event_type=event_type,
            payload=payload
        )

    async def register_handler(
        self,
        event_type: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ):
        """
        Register a handler for scheduled events.

        Interface compatible with RedisEventScheduler.
        """
        await self.scheduler.register_handler(event_type, handler)

    async def cancel_event(self, event_id: str) -> bool:
        """
        Cancel a scheduled event.

        Note: For stream-based scheduler, this is more complex
        as events may already be in the stream.
        """
        if hasattr(self.scheduler, 'cancel_event'):
            return await self.scheduler.cancel_event(event_id)
        else:
            # For stream scheduler, we would need to implement cancellation
            # by adding a cancellation event to a separate stream
            logger.warning(f"Event cancellation not implemented for stream scheduler: {event_id}")
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        stats = self.scheduler.get_statistics()
        stats.update({
            "hybrid": True,
            "use_streams": self.use_streams,
            "scheduler_type": "stream" if self.use_streams else "keyspace"
        })
        return stats

    # Stream-specific methods (only available when using streams)
    async def get_stream_info(self) -> Optional[Dict[str, Any]]:
        """Get stream information (only for stream-based scheduler)."""
        if hasattr(self.scheduler, 'get_stream_info'):
            return await self.scheduler.get_stream_info()
        return None

    async def force_process_events(self) -> int:
        """Force processing of pending events (useful for testing)."""
        if hasattr(self.scheduler, '_process_events_loop'):
            # For stream scheduler, trigger a processing cycle
            return await self.scheduler._process_stream_events(self.scheduler.scheduled_stream)
        return 0