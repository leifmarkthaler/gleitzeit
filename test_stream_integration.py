#!/usr/bin/env python3
"""
Test Stream Integration with SystemManager.

Validates that the new stream-based components integrate correctly
with the existing SystemManager infrastructure.
"""

import asyncio
import logging
import time
from datetime import datetime
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager as StreamSystemManager
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.events.stateless_bus import StatelessEventBus

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_stream_system_manager_initialization():
    """Test StreamSystemManager initialization."""
    logger.info("Testing StreamSystemManager initialization...")

    try:
        # Create persistence
        persistence = await PersistenceFactory.create()

        # Create StreamSystemManager with streams enabled
        manager = await StreamSystemManager.get_or_create(
            persistence=persistence,
            instance_id="test-stream-manager",
            use_streams=True,
            stream_config={
                "total_shards": 8,
                "consumer_group": "test-processors",
                "monitoring_interval": 10
            }
        )

        assert manager is not None, "StreamSystemManager should be created"
        assert manager.use_streams == True, "Streams should be enabled"
        assert manager.total_shards == 8, "Shards should be configured"

        logger.info("✅ StreamSystemManager initialization successful")
        return manager

    except Exception as e:
        logger.error(f"❌ StreamSystemManager initialization failed: {e}")
        raise


async def test_component_registration(manager):
    """Test that stream components are properly registered."""
    logger.info("Testing component registration...")

    try:
        # Check that stream components are initialized
        assert manager.stream_monitor is not None, "StreamMonitor should be initialized"
        assert manager.consumer_group_manager is not None, "ConsumerGroupManager should be initialized"

        # Check that hybrid scheduler is used
        from gleitzeit.scheduler.hybrid_event_scheduler import HybridEventScheduler
        assert isinstance(manager.event_scheduler, HybridEventScheduler), "Should use HybridEventScheduler"

        # Check component registry
        if manager.component_registry:
            components = await manager.component_registry.list_components()
            component_ids = [c.component_id for c in components]
            logger.info(f"Registered components: {component_ids}")

        logger.info("✅ Component registration successful")

    except Exception as e:
        logger.error(f"❌ Component registration failed: {e}")
        raise


async def test_timer_manager_integration(manager):
    """Test timer manager integration."""
    logger.info("Testing timer manager integration...")

    try:
        # Check timer manager type
        if manager.use_streams:
            from gleitzeit.timers.stream_timer_manager import StreamTimerManager
            if manager.stream_timer_manager:
                assert isinstance(manager.stream_timer_manager, StreamTimerManager), "Should use StreamTimerManager"

                # Test creating a timer
                timer = await manager.stream_timer_manager.create_timer(
                    workflow_id="test-workflow",
                    duration_seconds=1.0,
                    timer_type="delay",
                    payload={"test": "data"}
                )

                assert timer.timer_id is not None, "Timer should have ID"
                assert timer.workflow_id == "test-workflow", "Timer should have correct workflow ID"

                logger.info(f"Created test timer: {timer.timer_id}")

                # Test timer statistics
                stats = manager.stream_timer_manager.get_statistics()
                assert stats["stream_based"] == True, "Should be stream-based"
                assert stats["timers_created"] >= 1, "Should have created timers"

        logger.info("✅ Timer manager integration successful")

    except Exception as e:
        logger.error(f"❌ Timer manager integration failed: {e}")
        raise


async def test_signal_manager_integration(manager):
    """Test signal manager integration."""
    logger.info("Testing signal manager integration...")

    try:
        if manager.use_streams and manager.stream_signal_manager:
            from gleitzeit.signals.stream_signal_manager import StreamSignalManager
            assert isinstance(manager.stream_signal_manager, StreamSignalManager), "Should use StreamSignalManager"

            # Test registering a handler
            handler = await manager.stream_signal_manager.register_handler(
                workflow_id="test-workflow",
                signal_name="test-signal",
                handler_type="continue"
            )

            assert handler.handler_id is not None, "Handler should have ID"
            assert handler.workflow_id == "test-workflow", "Handler should have correct workflow ID"

            logger.info(f"Registered test handler: {handler.handler_id}")

            # Test sending a signal
            signal = await manager.stream_signal_manager.send_signal(
                signal_name="test-signal",
                workflow_id="test-workflow",
                payload={"test": "signal"}
            )

            assert signal.signal_id is not None, "Signal should have ID"
            assert signal.signal_name == "test-signal", "Signal should have correct name"

            logger.info(f"Sent test signal: {signal.signal_id}")

            # Test signal statistics
            stats = manager.stream_signal_manager.get_statistics()
            assert stats["stream_based"] == True, "Should be stream-based"
            assert stats["signals_created"] >= 1, "Should have created signals"

        logger.info("✅ Signal manager integration successful")

    except Exception as e:
        logger.error(f"❌ Signal manager integration failed: {e}")
        raise


async def test_health_monitoring(manager):
    """Test health monitoring integration."""
    logger.info("Testing health monitoring...")

    try:
        # Get system health
        health = await manager.get_system_health()

        assert "stream_processing" in health, "Should include stream processing health"

        if manager.use_streams:
            stream_health = health["stream_processing"]
            assert stream_health["enabled"] == True, "Stream processing should be enabled"
            assert "status" in stream_health, "Should have status"
            assert "total_streams" in stream_health, "Should have stream count"

            logger.info(f"Stream health status: {stream_health.get('status')}")
            logger.info(f"Total streams: {stream_health.get('total_streams')}")

        # Get stream statistics
        stream_stats = await manager.get_stream_statistics()
        assert stream_stats["stream_processing"] == True, "Should be using stream processing"
        assert "configuration" in stream_stats, "Should have configuration"

        config = stream_stats["configuration"]
        assert config["total_shards"] == 8, "Should have correct shard count"
        assert config["consumer_group"] == "test-processors", "Should have correct consumer group"

        logger.info("✅ Health monitoring successful")

    except Exception as e:
        logger.error(f"❌ Health monitoring failed: {e}")
        raise


async def test_legacy_compatibility(manager):
    """Test backwards compatibility with legacy interfaces."""
    logger.info("Testing legacy compatibility...")

    try:
        # Test that legacy timer_manager attribute exists
        assert hasattr(manager, 'timer_manager'), "Should have timer_manager attribute"
        assert hasattr(manager, 'signal_manager'), "Should have signal_manager attribute"

        # Test legacy tick() method still works
        if manager.timer_manager and hasattr(manager.timer_manager, 'tick'):
            tick_result = await manager.timer_manager.tick()
            assert isinstance(tick_result, dict), "tick() should return dict"
            logger.info(f"Legacy tick result: {tick_result}")

        if manager.signal_manager and hasattr(manager.signal_manager, 'tick'):
            tick_result = await manager.signal_manager.tick()
            assert isinstance(tick_result, dict), "tick() should return dict"
            logger.info(f"Legacy signal tick result: {tick_result}")

        # Test that event scheduler maintains interface
        assert hasattr(manager.event_scheduler, 'schedule_event'), "Should have schedule_event method"
        assert hasattr(manager.event_scheduler, 'schedule_immediate'), "Should have schedule_immediate method"

        logger.info("✅ Legacy compatibility successful")

    except Exception as e:
        logger.error(f"❌ Legacy compatibility failed: {e}")
        raise


async def test_migration_features(manager):
    """Test migration features."""
    logger.info("Testing migration features...")

    try:
        # Get migration status
        migration_status = manager.get_migration_status()

        assert "use_streams" in migration_status, "Should have use_streams status"
        assert "components" in migration_status, "Should have components status"
        assert "configuration" in migration_status, "Should have configuration"

        components = migration_status["components"]
        if manager.use_streams:
            assert components["stream_monitor"] == True, "StreamMonitor should be initialized"
            assert components["consumer_group_manager"] == True, "ConsumerGroupManager should be initialized"
            assert components["hybrid_scheduler"] == True, "HybridScheduler should be used"

        logger.info(f"Migration status: {migration_status}")
        logger.info("✅ Migration features successful")

    except Exception as e:
        logger.error(f"❌ Migration features failed: {e}")
        raise


async def test_event_processing_flow(manager):
    """Test end-to-end event processing flow."""
    logger.info("Testing event processing flow...")

    try:
        if not manager.use_streams or not manager.event_scheduler:
            logger.info("Skipping event processing test (streams not enabled)")
            return

        # Test scheduling an event
        event_id = await manager.event_scheduler.schedule_immediate(
            event_type="test_event",
            payload={"test": "flow"}
        )

        assert event_id is not None, "Should get event ID"
        logger.info(f"Scheduled test event: {event_id}")

        # Give some time for processing
        await asyncio.sleep(2)

        # Check scheduler statistics
        if hasattr(manager.event_scheduler, 'get_statistics'):
            stats = manager.event_scheduler.get_statistics()
            logger.info(f"Scheduler stats: {stats}")

        logger.info("✅ Event processing flow successful")

    except Exception as e:
        logger.error(f"❌ Event processing flow failed: {e}")
        raise


async def main():
    """Run all integration tests."""
    logger.info("Starting StreamSystemManager integration tests...")

    manager = None
    try:
        # Test initialization
        manager = await test_stream_system_manager_initialization()

        # Test component registration
        await test_component_registration(manager)

        # Test timer manager integration
        await test_timer_manager_integration(manager)

        # Test signal manager integration
        await test_signal_manager_integration(manager)

        # Test health monitoring
        await test_health_monitoring(manager)

        # Test legacy compatibility
        await test_legacy_compatibility(manager)

        # Test migration features
        await test_migration_features(manager)

        # Test event processing flow
        await test_event_processing_flow(manager)

        logger.info("🎉 All StreamSystemManager integration tests passed!")

    except Exception as e:
        logger.error(f"💥 Integration tests failed: {e}")
        return 1

    finally:
        # Cleanup
        if manager:
            try:
                await manager.shutdown()
                logger.info("SystemManager shutdown complete")
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)