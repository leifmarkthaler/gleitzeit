#!/usr/bin/env python3
"""
Test the Redis Event-Driven Scheduler.

This test demonstrates true stateless scheduling using Redis events.
"""

import asyncio
import logging
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.scheduler.redis_event_scheduler import RedisEventScheduler, TickScheduler
from gleitzeit.timers.stateless_timer_manager import StatelessTimerManager
from gleitzeit.signals.stateless_signal_manager import StatelessSignalManager
from gleitzeit.persistence.factory import PersistenceFactory

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_redis_event_scheduler():
    """Test the Redis event-driven scheduler."""

    logger.info("Testing Redis event-driven scheduler...")

    try:
        # Initialize persistence
        persistence = await PersistenceFactory.create()
        await persistence.initialize()

        # Initialize Redis event scheduler
        redis_scheduler = RedisEventScheduler(
            persistence=persistence,
            instance_id="test-redis-scheduler"
        )
        await redis_scheduler.initialize()

        # Initialize tick scheduler
        tick_scheduler = TickScheduler(redis_scheduler)

        # Initialize timer and signal managers
        timer_manager = StatelessTimerManager(
            persistence=persistence,
            instance_id="test-timer-manager"
        )
        await timer_manager.initialize()

        signal_manager = StatelessSignalManager(
            persistence=persistence,
            instance_id="test-signal-manager"
        )
        await signal_manager.initialize()

        # Register components with tick scheduler
        await tick_scheduler.register_tick_component(timer_manager)
        await tick_scheduler.register_tick_component(signal_manager)

        logger.info("All components initialized successfully!")

        # Test 1: Schedule some immediate events
        logger.info("=== Test 1: Immediate Events ===")

        async def handle_test_event(event_data):
            logger.info(f"Handled test event: {event_data['event_id']} - {event_data['payload']}")

        await redis_scheduler.register_handler("test_event", handle_test_event)

        # Schedule immediate events
        await redis_scheduler.schedule_immediate("test_event", {"message": "Hello immediate!"})
        await redis_scheduler.schedule_immediate("test_event", {"message": "Another immediate!"})

        # Wait a bit for immediate events to process
        await asyncio.sleep(2)

        # Test 2: Schedule delayed events
        logger.info("=== Test 2: Delayed Events ===")

        await redis_scheduler.schedule_event("test_event", 3, {"message": "Delayed event 1"})
        await redis_scheduler.schedule_event("test_event", 5, {"message": "Delayed event 2"})

        # Test 3: Create some timers and signals
        logger.info("=== Test 3: Create Timers and Signals ===")

        timer = await timer_manager.create_timer(
            workflow_id="test-workflow-scheduler",
            duration_seconds=4,
            timer_type="delay",
            payload={"test": "scheduler_timer"}
        )
        logger.info(f"Created timer: {timer.timer_id}")

        signal = await signal_manager.send_signal(
            signal_name="test_scheduler_signal",
            workflow_id="test-workflow-scheduler",
            payload={"test": "scheduler_signal"}
        )
        logger.info(f"Created signal: {signal.signal_id}")

        # Test 4: Schedule tick events
        logger.info("=== Test 4: Tick Events ===")

        # Schedule a single tick
        await tick_scheduler.schedule_tick(2)

        # Schedule recurring ticks (5 ticks with 1.5 second intervals)
        await tick_scheduler.schedule_recurring_ticks(1.5, 5)

        # Test 5: Event cancellation
        logger.info("=== Test 5: Event Cancellation ===")

        cancel_event_id = await redis_scheduler.schedule_event(
            "test_event", 10, {"message": "This should be cancelled"}
        )
        logger.info(f"Scheduled event to cancel: {cancel_event_id}")

        # Cancel the event
        cancelled = await redis_scheduler.cancel_event(cancel_event_id)
        logger.info(f"Event cancellation result: {cancelled}")

        # Test 6: Let everything run for a while
        logger.info("=== Test 6: Let Events Process ===")
        logger.info("Waiting 15 seconds for all events to process...")

        await asyncio.sleep(15)

        # Get statistics
        scheduler_stats = redis_scheduler.get_statistics()
        timer_stats = timer_manager.get_statistics()
        signal_stats = signal_manager.get_statistics()

        logger.info(f"Redis Scheduler Stats: {scheduler_stats}")
        logger.info(f"Timer Manager Stats: {timer_stats}")
        logger.info(f"Signal Manager Stats: {signal_stats}")

        # Cleanup
        await redis_scheduler.shutdown()
        await signal_manager.shutdown()
        await timer_manager.shutdown()
        await persistence.shutdown()

        logger.info("Test completed successfully!")
        return True

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_redis_event_scheduler())
    sys.exit(0 if result else 1)