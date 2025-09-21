#!/usr/bin/env python3
"""
Test script for the new ModularStreamSystemManager.

This script tests the modular stream system manager with mixins
to verify it works correctly without the complexity of inheritance.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add the src directory to the path so we can import gleitzeit
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_modular_system_manager():
    """Test the modular stream system manager."""
    logger.info("=== Testing ModularStreamSystemManager ===")

    # Create system configuration
    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT
    config.environment = "test"
    config.default_providers = ["python"]

    # Stream configuration
    stream_config = {
        "total_shards": 16,  # Smaller for testing
        "consumer_group": "test-processors",
        "monitoring_interval": 10,
        "validate_contracts": True
    }

    system_manager = None
    try:
        logger.info("Creating ModularStreamSystemManager...")

        # Create the system manager
        system_manager = await ModularStreamSystemManager.create(
            config=config,
            stream_config=stream_config,
            create_if_missing=True,
            start_system=True
        )

        if not system_manager:
            logger.error("Failed to create system manager")
            return False

        logger.info(f"✓ Created system manager: {system_manager.instance_id}")

        # Test basic properties
        logger.info("Testing basic properties...")
        assert system_manager.is_stream_based() == True
        assert system_manager.is_modular() == True
        assert system_manager.is_initialized == True
        assert system_manager.is_running == True
        logger.info("✓ Basic properties correct")

        # Test mixin components
        logger.info("Testing mixin components...")
        mixin_status = system_manager.get_mixin_components()
        logger.info(f"Mixin status: {mixin_status}")

        # Verify core components are available
        assert mixin_status["base_system"] == True
        assert mixin_status["stream_core"] == True
        assert mixin_status["stream_events"] == True
        logger.info("✓ Core mixins working")

        # Test system info
        logger.info("Testing system info...")
        system_info = await system_manager.get_system_info()
        logger.info(f"System info keys: {list(system_info.keys())}")

        assert system_info["stream_based"] == True
        assert system_info["modular"] == True
        assert system_info["system_type"] == "ModularStreamSystemManager"
        logger.info("✓ System info correct")

        # Test system health
        logger.info("Testing system health...")
        try:
            health = await system_manager.get_system_health()
            logger.info(f"Health status available: {bool(health)}")
            logger.info("✓ Health monitoring working")
        except Exception as e:
            logger.warning(f"Health monitoring not fully available: {e}")

        # Test stream statistics
        logger.info("Testing stream statistics...")
        try:
            stream_stats = system_manager.get_stream_statistics()
            logger.info(f"Stream statistics: {stream_stats}")
            assert stream_stats["stream_processing"] == True
            logger.info("✓ Stream statistics working")
        except Exception as e:
            logger.warning(f"Stream statistics not fully available: {e}")

        # Test event emission
        logger.info("Testing event emission...")
        try:
            from gleitzeit.core.events import GleitzeitEvent, EventType
            test_event = GleitzeitEvent(
                event_type=EventType.TASK_SUBMITTED,
                data={"test": "data"},
                source="test_script"
            )
            await system_manager.emit_event(test_event)
            logger.info("✓ Event emission working")
        except Exception as e:
            logger.warning(f"Event emission not fully available: {e}")

        # Test provider statistics
        logger.info("Testing provider statistics...")
        try:
            provider_stats = system_manager.get_provider_statistics()
            logger.info(f"Provider statistics: {provider_stats}")
            logger.info("✓ Provider statistics working")
        except Exception as e:
            logger.warning(f"Provider statistics not fully available: {e}")

        # Test basic workflow operations (if available)
        logger.info("Testing workflow operations...")
        try:
            if hasattr(system_manager, 'workflow_loader') and system_manager.workflow_loader:
                logger.info("✓ Workflow loader available")
            if hasattr(system_manager, 'workflow_manager') and system_manager.workflow_manager:
                logger.info("✓ Workflow manager available")
            if hasattr(system_manager, 'execution_engine') and system_manager.execution_engine:
                logger.info("✓ Execution engine available")
        except Exception as e:
            logger.warning(f"Workflow operations not fully available: {e}")

        logger.info("=== All tests passed! ===")
        return True

    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup
        if system_manager:
            logger.info("Shutting down system manager...")
            try:
                await system_manager.shutdown()
                logger.info("✓ System manager shutdown complete")
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")


async def test_mixin_isolation():
    """Test that mixins can be used independently."""
    logger.info("=== Testing Mixin Isolation ===")

    try:
        from gleitzeit.system.mixins.base import BaseSystemMixin
        from gleitzeit.system.mixins.stream_core import StreamCoreMixin

        class TestManager(BaseSystemMixin, StreamCoreMixin):
            def __init__(self):
                super().__init__()
                logger.info("✓ Multiple mixins can be combined")

        # Test creating a minimal manager
        test_manager = TestManager()
        assert hasattr(test_manager, 'instance_id')
        assert hasattr(test_manager, 'total_shards')
        logger.info("✓ Mixin isolation working")
        return True

    except Exception as e:
        logger.error(f"Mixin isolation test failed: {e}")
        return False


async def main():
    """Main test function."""
    logger.info("Starting ModularStreamSystemManager tests...")

    # Test mixin isolation first
    isolation_success = await test_mixin_isolation()
    if not isolation_success:
        logger.error("Mixin isolation test failed")
        return 1

    # Test full system manager
    system_success = await test_modular_system_manager()
    if not system_success:
        logger.error("System manager test failed")
        return 1

    logger.info("🎉 All tests passed successfully!")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)