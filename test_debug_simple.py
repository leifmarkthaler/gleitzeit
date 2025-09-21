#!/usr/bin/env python3
"""
Very basic test - just check if manager starts.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

async def test_manager_startup():
    """Test just manager startup."""
    print("Creating ModularStreamSystemManager...")

    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    try:
        manager = await ModularStreamSystemManager.create(
            config=config,
            stream_config={'total_shards': 8},
            create_if_missing=True,
            start_system=False  # Don't start the system yet
        )

        if not manager:
            print("❌ Failed to create manager")
            return False

        print(f"✓ Created manager: {manager.instance_id}")

        # Check components
        print("\nChecking components...")
        print(f"  Workflow Manager: {hasattr(manager, 'workflow_manager') and manager.workflow_manager is not None}")
        print(f"  Workflow Loader: {hasattr(manager, 'workflow_loader') and manager.workflow_loader is not None}")
        print(f"  Execution Engine: {hasattr(manager, 'execution_engine') and manager.execution_engine is not None}")
        print(f"  Pooling Adapter: {hasattr(manager, 'pooling_adapter') and manager.pooling_adapter is not None}")

        # Check provider registration
        if manager.pooling_adapter:
            print(f"\nRegistered protocols: {list(manager.pooling_adapter._registered_protocols)}")
            print(f"  timer/v1 available: {manager.pooling_adapter.is_protocol_available('timer/v1')}")
            print(f"  signal/v1 available: {manager.pooling_adapter.is_protocol_available('signal/v1')}")
            print(f"  python/v1 available: {manager.pooling_adapter.is_protocol_available('python/v1')}")

        print("\n✅ Manager created successfully!")

        # Now try starting the system
        print("\nStarting system...")
        started = await manager.start_system()
        if started:
            print("✓ System started")

            # Give it a moment
            await asyncio.sleep(1)

            print("\n✅ System is running!")
        else:
            print("❌ Failed to start system")
            return False

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if 'manager' in locals():
            print("\nShutting down...")
            await manager.shutdown()
            print("✓ Shutdown complete")

if __name__ == "__main__":
    result = asyncio.run(test_manager_startup())
    sys.exit(0 if result else 1)