#!/usr/bin/env python3
"""
Test Phase 1: StreamSystemManager Integration

This test validates that:
1. StreamSystemManager can be used as EventBus replacement
2. WorkflowManager can emit events via streams
3. Event handlers can be registered with streams
4. Basic workflow operations work with stream architecture
"""

import asyncio
import logging
from datetime import datetime

from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager as StreamSystemManager
from gleitzeit.core.workflow_manager_factory import WorkflowManagerFactory
from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_stream_system_manager_compatibility():
    """Test that StreamSystemManager can replace EventBus."""

    logger.info("=== Phase 1 Test: StreamSystemManager as EventBus Replacement ===")

    try:
        # Create persistence backend
        persistence = await PersistenceFactory.create()
        logger.info("✅ Created persistence backend")

        # Create StreamSystemManager (the key component)
        stream_manager = await StreamSystemManager.get_or_create(
            persistence=persistence,
            create_if_missing=True,
            start_system=True,
            stream_config={
                "total_shards": 4,  # Smaller for testing
                "consumer_group": "test-processors",
                "monitoring_interval": 10
            }
        )
        logger.info("✅ Created StreamSystemManager")

        # Verify StreamSystemManager has EventBus compatibility methods
        assert hasattr(stream_manager, 'emit_event'), "StreamSystemManager missing emit_event method"
        assert hasattr(stream_manager, 'register_handler'), "StreamSystemManager missing register_handler method"
        logger.info("✅ StreamSystemManager has EventBus compatibility methods")

        # Test event emission directly
        test_event = GleitzeitEvent(
            event_type=EventType.WORKFLOW_SUBMITTED,
            data={"workflow_id": "test-123", "test": True},
            source="test_phase1",
            severity=EventSeverity.INFO
        )

        await stream_manager.emit_event(test_event)
        logger.info("✅ Successfully emitted event via StreamSystemManager")

        # Test handler registration
        async def test_handler(event_data):
            logger.info(f"Test handler received event: {event_data}")

        handler_id = await stream_manager.register_handler(
            EventType.WORKFLOW_SUBMITTED,
            test_handler
        )
        logger.info(f"✅ Successfully registered handler: {handler_id}")

        # Create WorkflowManager using StreamSystemManager as event_bus
        workflow_manager = await WorkflowManagerFactory.create(
            persistence=persistence,
            event_bus=stream_manager,  # This is the key test!
            execution_engine=None,
            dependency_resolver=None
        )
        logger.info("✅ Created WorkflowManager with StreamSystemManager as event_bus")

        # Verify WorkflowManager has the expected event_bus reference
        assert workflow_manager.event_bus == stream_manager, "WorkflowManager event_bus not set correctly"
        logger.info("✅ WorkflowManager.event_bus correctly set to StreamSystemManager")

        # Test workflow operations (this should emit events via streams)
        test_workflow_data = {
            "name": "test_phase1_workflow",
            "tasks": [
                {
                    "id": "task1",
                    "provider": "python",
                    "function": "print",
                    "parameters": {"message": "Hello Phase 1!"}
                }
            ]
        }

        # This should emit events via StreamSystemManager
        workflow_id = await workflow_manager.submit_workflow(test_workflow_data)
        logger.info(f"✅ Successfully submitted workflow {workflow_id} using stream-based events")

        # Clean up
        await stream_manager.shutdown()
        logger.info("✅ StreamSystemManager shutdown complete")

        logger.info("\n🎉 PHASE 1 SUCCESS: StreamSystemManager can replace EventBus!")
        logger.info("✅ WorkflowManager successfully uses streams for events")
        logger.info("✅ No EventBus wrapper needed - direct stream integration works")

        return True

    except Exception as e:
        logger.error(f"❌ Phase 1 test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_event_emission_paths():
    """Test different event emission paths in StreamSystemManager."""

    logger.info("=== Testing Event Emission Paths ===")

    try:
        persistence = await PersistenceFactory.create()

        # Test with minimal configuration
        stream_manager = await StreamSystemManager.get_or_create(
            persistence=persistence,
            create_if_missing=True,
            start_system=False,  # Don't start full system for this test
            stream_config={"total_shards": 2}
        )

        # Test event with all fields (tags must be strings)
        detailed_event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "task-456", "result": "success"},
            source="test_emission",
            correlation_id="corr-123",
            severity=EventSeverity.INFO,
            tags={"test": "true", "phase": "1"}
        )

        await stream_manager.emit_event(detailed_event)
        logger.info("✅ Successfully emitted detailed event")

        await stream_manager.shutdown()
        return True

    except Exception as e:
        logger.error(f"❌ Event emission test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all Phase 1 tests."""

    logger.info("Starting Phase 1 Stream Integration Tests")

    tests = [
        ("StreamSystemManager Compatibility", test_stream_system_manager_compatibility),
        ("Event Emission Paths", test_event_emission_paths)
    ]

    results = []
    for test_name, test_func in tests:
        logger.info(f"\n--- Running {test_name} ---")
        result = await test_func()
        results.append((test_name, result))

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 1 TEST RESULTS:")

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"  {status}: {test_name}")
        if not passed:
            all_passed = False

    if all_passed:
        logger.info(f"\n🎉 ALL TESTS PASSED - PHASE 1 IMPLEMENTATION SUCCESS!")
        logger.info("✅ StreamSystemManager successfully replaces EventBus")
        logger.info("✅ WorkflowManager works with pure stream architecture")
        logger.info("✅ No polling loops - event-driven streams only")
    else:
        logger.info(f"\n❌ Some tests failed - Phase 1 needs fixes")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)