#!/usr/bin/env python3
"""
Basic test for the new ModularStreamSystemManager.
Tests just the core functionality without full system startup.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_mixin_imports():
    """Test that all mixins can be imported correctly."""
    logger.info("Testing mixin imports...")

    try:
        from gleitzeit.system.mixins.base import BaseSystemMixin
        from gleitzeit.system.mixins.stream_core import StreamCoreMixin
        from gleitzeit.system.mixins.stream_events import StreamEventsMixin
        from gleitzeit.system.mixins.stream_timers import StreamTimersMixin
        from gleitzeit.system.mixins.stream_signals import StreamSignalsMixin
        from gleitzeit.system.mixins.stream_execution import StreamExecutionMixin
        from gleitzeit.system.mixins.stream_monitoring import StreamMonitoringMixin
        from gleitzeit.system.mixins.stream_providers import StreamProvidersMixin
        from gleitzeit.system.mixins.stream_auth import StreamAuthMixin

        logger.info("✓ All mixins imported successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to import mixins: {e}")
        return False


async def test_modular_manager_creation():
    """Test creating the modular system manager."""
    logger.info("Testing modular manager creation...")

    try:
        from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
        from gleitzeit.system.models import SystemConfig, DeploymentMode

        # Create minimal config
        config = SystemConfig()
        config.deployment_mode = DeploymentMode.DEVELOPMENT
        config.environment = "test"

        # Create manager instance (don't initialize yet)
        manager = ModularStreamSystemManager(
            config=config,
            stream_config={"total_shards": 8, "consumer_group": "test"}
        )

        # Test basic properties
        assert hasattr(manager, 'instance_id')
        assert hasattr(manager, 'total_shards')
        assert manager.total_shards == 8
        assert manager.is_stream_based() == True
        assert manager.is_modular() == True

        logger.info(f"✓ Created manager with instance_id: {manager.instance_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to create modular manager: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mixin_composition():
    """Test that mixins compose correctly."""
    logger.info("Testing mixin composition...")

    try:
        from gleitzeit.system.mixins.base import BaseSystemMixin
        from gleitzeit.system.mixins.stream_core import StreamCoreMixin

        class TestManager(BaseSystemMixin, StreamCoreMixin):
            def __init__(self):
                super().__init__(
                    stream_config={"total_shards": 4}
                )

        test_manager = TestManager()

        # Test that both mixins are working
        assert hasattr(test_manager, 'instance_id')  # From BaseSystemMixin
        assert hasattr(test_manager, 'total_shards')  # From StreamCoreMixin
        assert test_manager.total_shards == 4

        logger.info("✓ Mixin composition working correctly")
        return True

    except Exception as e:
        logger.error(f"Mixin composition test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all basic tests."""
    logger.info("=== Running Basic Modular System Manager Tests ===")

    tests = [
        test_mixin_imports,
        test_mixin_composition,
        test_modular_manager_creation
    ]

    for test in tests:
        success = await test()
        if not success:
            logger.error(f"Test {test.__name__} failed")
            return 1

    logger.info("🎉 All basic tests passed!")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)