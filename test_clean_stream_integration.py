#!/usr/bin/env python3
"""
Test Clean Stream Integration.

Validates the clean stream-only implementation integrates correctly
with all system components.
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
from gleitzeit.core.models import Task, Workflow, TaskStatus
from gleitzeit.core.events import EventType

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_clean_stream_system():
    """Test the clean stream-only system."""
    logger.info("Testing clean stream-only system...")

    try:
        # Create persistence
        persistence = await PersistenceFactory.create()

        # Create StreamSystemManager
        manager = await StreamSystemManager.get_or_create(
            persistence=persistence,
            instance_id="test-clean-stream",
            stream_config={
                "total_shards": 4,
                "consumer_group": "test-clean-processors",
                "monitoring_interval": 5
            }
        )

        assert manager is not None, "StreamSystemManager should be created"
        assert manager.is_stream_based() == True, "Should be stream-based"

        logger.info("✅ Clean stream system created successfully")
        return manager

    except Exception as e:
        logger.error(f"❌ Clean stream system creation failed: {e}")
        raise


async def test_stream_components(manager):
    """Test that all stream components are properly initialized."""
    logger.info("Testing stream components...")

    try:
        # Check stream scheduler
        assert manager.event_scheduler is not None, "StreamEventScheduler should be initialized"
        assert hasattr(manager.event_scheduler, 'get_statistics'), "Should have statistics"

        # Check timer manager
        assert manager.timer_manager is not None, "Timer manager should be initialized"
        assert hasattr(manager.timer_manager, 'create_timer'), "Should have timer creation"

        # Check signal manager
        assert manager.signal_manager is not None, "Signal manager should be initialized"
        assert hasattr(manager.signal_manager, 'send_signal'), "Should have signal sending"

        # Check execution engine
        assert manager.execution_engine is not None, "Execution engine should be initialized"
        assert hasattr(manager.execution_engine, 'submit_task'), "Should have task submission"

        # Check monitoring
        assert manager.stream_monitor is not None, "Stream monitor should be initialized"
        assert manager.consumer_group_manager is not None, "Consumer group manager should be initialized"

        logger.info("✅ All stream components properly initialized")

    except Exception as e:
        logger.error(f"❌ Stream components test failed: {e}")
        raise


async def test_timer_functionality(manager):
    """Test timer functionality in stream system."""
    logger.info("Testing timer functionality...")

    try:
        # Create a timer
        timer = await manager.timer_manager.create_timer(
            workflow_id="test-workflow-timer",
            duration_seconds=2.0,
            timer_type="delay",
            payload={"test": "timer_data"}
        )

        assert timer.timer_id is not None, "Timer should have ID"
        assert timer.workflow_id == "test-workflow-timer", "Timer should have correct workflow ID"

        logger.info(f"Created timer: {timer.timer_id}")

        # Get timer statistics
        stats = manager.timer_manager.get_statistics()
        assert stats["stream_based"] == True, "Should be stream-based"
        assert stats["timers_created"] >= 1, "Should have created timers"

        logger.info("✅ Timer functionality working")

    except Exception as e:
        logger.error(f"❌ Timer functionality test failed: {e}")
        raise


async def test_signal_functionality(manager):
    """Test signal functionality in stream system."""
    logger.info("Testing signal functionality...")

    try:
        # Register a signal handler
        handler = await manager.signal_manager.register_handler(
            workflow_id="test-workflow-signal",
            signal_name="test-signal",
            handler_type="continue"
        )

        assert handler.handler_id is not None, "Handler should have ID"
        logger.info(f"Registered handler: {handler.handler_id}")

        # Send a signal
        signal = await manager.signal_manager.send_signal(
            signal_name="test-signal",
            workflow_id="test-workflow-signal",
            payload={"test": "signal_data"}
        )

        assert signal.signal_id is not None, "Signal should have ID"
        logger.info(f"Sent signal: {signal.signal_id}")

        # Get signal statistics
        stats = manager.signal_manager.get_statistics()
        assert stats["stream_based"] == True, "Should be stream-based"
        assert stats["signals_created"] >= 1, "Should have created signals"

        logger.info("✅ Signal functionality working")

    except Exception as e:
        logger.error(f"❌ Signal functionality test failed: {e}")
        raise


async def test_execution_engine(manager):
    """Test execution engine functionality."""
    logger.info("Testing execution engine...")

    try:
        # Create a simple task
        task = Task(
            task_id="test-task-exec",
            workflow_id="test-workflow-exec",
            protocol_id="python/v1",
            script="print('Hello from stream execution')",
            parameters={"test": "data"}
        )

        # Submit task
        execution_id = await manager.execution_engine.submit_task(task)
        assert execution_id is not None, "Should get execution ID"

        logger.info(f"Submitted task for execution: {execution_id}")

        # Get execution statistics
        stats = manager.execution_engine.get_statistics()
        assert stats["stream_based"] == True, "Should be stream-based"
        assert "statistics" in stats, "Should have statistics"

        logger.info("✅ Execution engine working")

    except Exception as e:
        logger.error(f"❌ Execution engine test failed: {e}")
        raise


async def test_system_health(manager):
    """Test system health monitoring."""
    logger.info("Testing system health...")

    try:
        # Get system health
        health = await manager.get_system_health()

        assert "stream_processing" in health, "Should include stream processing health"

        stream_health = health["stream_processing"]
        assert stream_health["enabled"] == True, "Stream processing should be enabled"
        assert "status" in stream_health, "Should have status"

        logger.info(f"System health: {stream_health['status']}")

        # Get stream statistics
        stream_stats = await manager.get_stream_statistics()
        assert stream_stats["stream_processing"] == True, "Should be using stream processing"

        config = stream_stats["configuration"]
        assert config["total_shards"] == 4, "Should have correct shard count"

        logger.info("✅ System health monitoring working")

    except Exception as e:
        logger.error(f"❌ System health test failed: {e}")
        raise


async def test_stream_monitoring(manager):
    """Test stream monitoring capabilities."""
    logger.info("Testing stream monitoring...")

    try:
        # Get stream info
        if hasattr(manager.timer_manager, 'get_stream_info'):
            timer_streams = await manager.timer_manager.get_stream_info()
            logger.info(f"Timer streams: {timer_streams}")

        if hasattr(manager.signal_manager, 'get_stream_info'):
            signal_streams = await manager.signal_manager.get_stream_info()
            logger.info(f"Signal streams: {signal_streams}")

        # Check monitor status
        if manager.stream_monitor:
            monitor_status = manager.stream_monitor.get_status()
            assert monitor_status["running"] == True, "Monitor should be running"

        logger.info("✅ Stream monitoring working")

    except Exception as e:
        logger.error(f"❌ Stream monitoring test failed: {e}")
        raise


async def test_event_processing_flow(manager):
    """Test end-to-end event processing flow."""
    logger.info("Testing event processing flow...")

    try:
        # Schedule an immediate event
        event_id = await manager.event_scheduler.schedule_immediate(
            event_type="test_flow_event",
            payload={"test": "flow_data"}
        )

        assert event_id is not None, "Should get event ID"
        logger.info(f"Scheduled flow event: {event_id}")

        # Give some time for processing
        await asyncio.sleep(3)

        # Check scheduler statistics
        stats = manager.event_scheduler.get_statistics()
        assert stats["stream_based"] == True, "Should be stream-based"
        assert stats["running"] == True, "Should be running"

        logger.info("✅ Event processing flow working")

    except Exception as e:
        logger.error(f"❌ Event processing flow test failed: {e}")
        raise


async def test_no_legacy_methods(manager):
    """Test that legacy tick-based methods are removed."""
    logger.info("Testing removal of legacy methods...")

    try:
        # Timer manager should not have tick method
        assert not hasattr(manager.timer_manager, 'tick'), "Timer manager should not have tick() method"

        # Signal manager should not have tick method
        assert not hasattr(manager.signal_manager, 'tick'), "Signal manager should not have tick() method"

        # Should be pure stream-based
        assert manager.timer_manager.get_statistics()["tick_based"] == False, "Should not be tick-based"
        assert manager.signal_manager.get_statistics()["tick_based"] == False, "Should not be tick-based"

        logger.info("✅ Legacy methods properly removed")

    except Exception as e:
        logger.error(f"❌ Legacy method removal test failed: {e}")
        raise


async def main():
    """Run all clean stream integration tests."""
    logger.info("Starting clean stream integration tests...")

    manager = None
    try:
        # Test system creation
        manager = await test_clean_stream_system()

        # Test components
        await test_stream_components(manager)

        # Test functionality
        await test_timer_functionality(manager)
        await test_signal_functionality(manager)
        await test_execution_engine(manager)

        # Test monitoring
        await test_system_health(manager)
        await test_stream_monitoring(manager)

        # Test event flow
        await test_event_processing_flow(manager)

        # Test clean architecture
        await test_no_legacy_methods(manager)

        logger.info("🎉 All clean stream integration tests passed!")

    except Exception as e:
        logger.error(f"💥 Clean stream integration tests failed: {e}")
        return 1

    finally:
        # Cleanup
        if manager:
            try:
                await manager.shutdown()
                logger.info("StreamSystemManager shutdown complete")
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)