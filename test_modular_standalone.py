#!/usr/bin/env python3
"""
Standalone test for ModularStreamSystemManager that tests only the mixin structure
without requiring all the complex dependencies to be initialized.
"""

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


async def test_mixin_structure():
    """Test that the mixin structure works correctly without full initialization."""
    logger.info("=== Testing Mixin Structure ===")

    # Create mock persistence
    mock_persistence = MagicMock()
    mock_persistence.redis = MagicMock()
    mock_persistence.keys = AsyncMock(return_value=[])

    try:
        # Import the modular system manager
        from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
        from gleitzeit.system.models import SystemConfig, DeploymentMode

        # Create minimal config
        config = SystemConfig()
        config.deployment_mode = DeploymentMode.DEVELOPMENT

        # Create instance without initialization
        manager = ModularStreamSystemManager(
            config=config,
            persistence=mock_persistence,
            stream_config={"total_shards": 8}
        )

        # Test that mixin attributes are available
        assert hasattr(manager, 'instance_id'), "Missing instance_id from BaseSystemMixin"
        assert hasattr(manager, 'total_shards'), "Missing total_shards from StreamCoreMixin"
        assert hasattr(manager, 'event_handlers'), "Missing event_handlers from StreamCoreMixin"

        # Test that methods are available
        assert hasattr(manager, 'initialize_base'), "Missing initialize_base from BaseSystemMixin"
        assert hasattr(manager, 'initialize_stream_core'), "Missing initialize_stream_core from StreamCoreMixin"
        assert hasattr(manager, 'initialize_stream_timers'), "Missing initialize_stream_timers from StreamTimersMixin"
        assert hasattr(manager, 'initialize_stream_signals'), "Missing initialize_stream_signals from StreamSignalsMixin"
        assert hasattr(manager, 'initialize_stream_execution'), "Missing initialize_stream_execution from StreamExecutionMixin"
        assert hasattr(manager, 'initialize_stream_monitoring'), "Missing initialize_stream_monitoring from StreamMonitoringMixin"
        assert hasattr(manager, 'initialize_stream_providers'), "Missing initialize_stream_providers from StreamProvidersMixin"
        assert hasattr(manager, 'initialize_stream_auth'), "Missing initialize_stream_auth from StreamAuthMixin"

        # Test properties
        assert manager.is_stream_based() == True
        assert manager.is_modular() == True
        assert manager.total_shards == 8

        logger.info("✓ Mixin structure is correct")
        logger.info(f"✓ Instance ID: {manager.instance_id}")
        logger.info(f"✓ Total shards: {manager.total_shards}")

        # Test mixin components status
        components = manager.get_mixin_components()
        logger.info(f"✓ Mixin components: {list(components.keys())}")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_partial_initialization():
    """Test partial initialization with mocked dependencies."""
    logger.info("\n=== Testing Partial Initialization ===")

    # Create comprehensive mocks
    mock_persistence = MagicMock()
    mock_persistence.redis = MagicMock()
    mock_persistence.keys = AsyncMock(return_value=[])

    # Mock event bus
    mock_event_bus = MagicMock()
    mock_event_bus.start = AsyncMock()
    mock_event_bus.emit = AsyncMock()

    try:
        from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
        from gleitzeit.system.models import SystemConfig, DeploymentMode

        config = SystemConfig()
        config.deployment_mode = DeploymentMode.DEVELOPMENT
        config.environment = "test"

        manager = ModularStreamSystemManager(
            config=config,
            persistence=mock_persistence,
            event_bus=mock_event_bus,
            stream_config={"total_shards": 16}
        )

        # Test that we can call initialization methods (they will fail but shouldn't crash)
        logger.info("Testing base initialization with mocks...")

        # Mock the service registry creation to prevent errors
        from unittest.mock import patch

        with patch('gleitzeit.system.mixins.base.ServiceRegistry') as MockServiceRegistry:
            MockServiceRegistry.return_value = MagicMock()
            MockServiceRegistry.return_value.initialize = AsyncMock()
            MockServiceRegistry.return_value.register_service = AsyncMock()

            with patch('gleitzeit.system.mixins.base.HealthMonitor') as MockHealthMonitor:
                MockHealthMonitor.return_value = MagicMock()
                MockHealthMonitor.return_value.initialize = AsyncMock()

                with patch('gleitzeit.system.mixins.base.DistributedComponentRegistry') as MockComponentRegistry:
                    MockComponentRegistry.return_value = MagicMock()
                    MockComponentRegistry.return_value.register_component = AsyncMock()

                    # Now try to initialize base
                    await manager.initialize_base()
                    logger.info("✓ Base initialization completed with mocks")

                    # Verify state
                    assert manager._initialized == True
                    assert manager.service_registry is not None
                    assert manager.health_monitor is not None
                    assert manager.component_registry is not None

                    logger.info("✓ Core components initialized")

        return True

    except Exception as e:
        logger.error(f"❌ Partial initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mixin_interfaces():
    """Test that mixin interfaces are properly exposed."""
    logger.info("\n=== Testing Mixin Interfaces ===")

    try:
        from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager

        # Create minimal instance
        manager = ModularStreamSystemManager()

        # Test StreamExecutionMixin interface
        assert hasattr(manager, 'submit_workflow'), "Missing submit_workflow from StreamExecutionMixin"
        assert hasattr(manager, 'get_workflow'), "Missing get_workflow from StreamExecutionMixin"
        assert hasattr(manager, 'submit_task'), "Missing submit_task from StreamExecutionMixin"

        # Test StreamTimersMixin interface
        assert hasattr(manager, 'schedule_timer'), "Missing schedule_timer from StreamTimersMixin"
        assert hasattr(manager, 'cancel_timer'), "Missing cancel_timer from StreamTimersMixin"

        # Test StreamSignalsMixin interface
        assert hasattr(manager, 'send_signal'), "Missing send_signal from StreamSignalsMixin"
        assert hasattr(manager, 'broadcast_signal'), "Missing broadcast_signal from StreamSignalsMixin"
        assert hasattr(manager, 'wait_for_signal'), "Missing wait_for_signal from StreamSignalsMixin"

        # Test StreamEventsMixin interface (EventBus compatibility)
        assert hasattr(manager, 'emit_event'), "Missing emit_event from StreamEventsMixin"
        assert hasattr(manager, 'register_handler'), "Missing register_handler from StreamEventsMixin"
        assert hasattr(manager, 'emit'), "Missing emit alias from StreamEventsMixin"

        # Test StreamAuthMixin interface
        assert hasattr(manager, 'authenticate_user'), "Missing authenticate_user from StreamAuthMixin"
        assert hasattr(manager, 'get_current_user'), "Missing get_current_user from StreamAuthMixin"
        assert hasattr(manager, 'submit_workflow_authenticated'), "Missing submit_workflow_authenticated from StreamAuthMixin"

        # Test StreamMonitoringMixin interface
        assert hasattr(manager, 'get_system_health'), "Missing get_system_health from StreamMonitoringMixin"
        assert hasattr(manager, 'get_system_status'), "Missing get_system_status from StreamMonitoringMixin"

        logger.info("✓ All mixin interfaces are properly exposed")

        return True

    except Exception as e:
        logger.error(f"❌ Interface test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all standalone tests."""
    logger.info("🚀 Starting Modular Stream System Manager Standalone Tests")
    logger.info("=" * 60)

    tests = [
        test_mixin_structure,
        test_partial_initialization,
        test_mixin_interfaces
    ]

    all_passed = True
    for test_func in tests:
        passed = await test_func()
        if not passed:
            all_passed = False
            logger.error(f"❌ Test {test_func.__name__} failed")

    if all_passed:
        logger.info("\n" + "=" * 60)
        logger.info("🎉 All standalone tests passed!")
        logger.info("The modular system manager structure is working correctly.")
        logger.info("Full integration testing would require all dependencies.")
        return 0
    else:
        logger.error("\n" + "=" * 60)
        logger.error("❌ Some tests failed. See errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)