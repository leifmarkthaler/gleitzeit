#!/usr/bin/env python
"""
Test the streamlined event bus directly.
"""

import asyncio
import logging
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.events.streamlined_event_bus import StreamlinedEventBus
from gleitzeit.core.events import GleitzeitEvent, EventType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_streamlined_bus():
    """Test the streamlined event bus."""

    # Create persistence
    persistence = await PersistenceFactory.create()
    redis = persistence.redis

    # Create streamlined event bus
    bus = StreamlinedEventBus(redis, instance_id="test")

    # Register a handler
    handled_events = []

    async def handler(event):
        logger.info(f"Handler received: {event.event_type}")
        handled_events.append(event)

    bus.register_handler(EventType.TASK_READY, handler)

    # Emit an event
    await bus.emit(GleitzeitEvent(
        event_type=EventType.TASK_READY,
        data={"task_id": "test1"}
    ))

    logger.info("Event emitted")

    # Process events
    stats = await bus.process_once()
    logger.info(f"Processing stats: {stats}")

    # Check if handled
    logger.info(f"Handled {len(handled_events)} events")

    return True


if __name__ == "__main__":
    asyncio.run(test_streamlined_bus())