#!/usr/bin/env python3
"""
Test the new stateless timer and signal system.
"""

import asyncio
import logging
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.timers.stateless_timer_manager import StatelessTimerManager
from gleitzeit.signals.stateless_signal_manager import StatelessSignalManager
from gleitzeit.system.tick_coordinator import AdaptiveTickCoordinator
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.events.stateless_event_bus_adapter import StatelessEventBusAdapter

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_stateless_system():
    """Test the stateless timer and signal system."""

    logger.info("Testing stateless timer and signal system...")

    try:
        # Initialize persistence using factory
        persistence = await PersistenceFactory.create()
        await persistence.initialize()

        # For now, skip event bus to simplify test
        event_bus = None

        # Initialize timer manager
        timer_manager = StatelessTimerManager(
            persistence=persistence,
            event_bus=event_bus,
            instance_id="test-timer-manager"
        )
        await timer_manager.initialize()

        # Initialize signal manager
        signal_manager = StatelessSignalManager(
            persistence=persistence,
            event_bus=event_bus,
            instance_id="test-signal-manager"
        )
        await signal_manager.initialize()

        # Initialize tick coordinator
        tick_coordinator = AdaptiveTickCoordinator(
            min_interval=0.5,
            max_interval=2.0,
            initial_interval=1.0,
            instance_id="test-coordinator"
        )

        # Register components
        tick_coordinator.register_component(timer_manager)
        tick_coordinator.register_component(signal_manager)

        logger.info("All components initialized successfully!")

        # Test timer creation
        logger.info("Creating test timer...")
        timer = await timer_manager.create_timer(
            workflow_id="test-workflow-1",
            duration_seconds=3,
            timer_type="delay",
            payload={"test": "timer_payload"}
        )
        logger.info(f"Created timer: {timer.timer_id}")

        # Test signal creation
        logger.info("Creating test signal...")
        signal = await signal_manager.send_signal(
            signal_name="test_signal",
            workflow_id="test-workflow-1",
            payload={"test": "signal_payload"}
        )
        logger.info(f"Created signal: {signal.signal_id}")

        # Test manual tick
        logger.info("Testing manual tick...")
        results = await tick_coordinator.manual_tick()
        logger.info(f"Tick results: {results}")

        # Start tick coordinator
        logger.info("Starting tick coordinator for 10 seconds...")
        await tick_coordinator.start()

        # Let it run for a bit
        await asyncio.sleep(10)

        # Stop tick coordinator
        await tick_coordinator.stop()

        # Get statistics
        timer_stats = timer_manager.get_statistics()
        signal_stats = signal_manager.get_statistics()
        coordinator_stats = tick_coordinator.get_statistics()

        logger.info(f"Timer Manager Stats: {timer_stats}")
        logger.info(f"Signal Manager Stats: {signal_stats}")
        logger.info(f"Coordinator Stats: {coordinator_stats}")

        # Cleanup
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
    result = asyncio.run(test_stateless_system())
    sys.exit(0 if result else 1)