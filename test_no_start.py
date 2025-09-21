#!/usr/bin/env python3
"""
Test without starting the system.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

async def test_no_start():
    """Test manager without starting."""
    print("Creating ModularStreamSystemManager (no start)...")

    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    try:
        manager = await ModularStreamSystemManager.create(
            config=config,
            stream_config={'total_shards': 8},
            create_if_missing=True,
            start_system=False  # Don't start
        )

        if not manager:
            print("❌ Failed to create manager")
            return False

        print(f"✓ Created manager: {manager.instance_id}")

        # Check components
        print("\nChecking components...")
        print(f"  Workflow Manager: {manager.workflow_manager is not None}")
        print(f"  Workflow Loader: {manager.workflow_loader is not None}")
        print(f"  Execution Engine: {manager.execution_engine is not None}")
        print(f"  Pooling Adapter: {manager.pooling_adapter is not None}")

        # Check protocols
        if manager.pooling_adapter:
            protocols = list(manager.pooling_adapter._registered_protocols)
            print(f"\nRegistered protocols: {protocols}")
            for proto in ['python/v1', 'timer/v1', 'signal/v1']:
                available = manager.pooling_adapter.is_protocol_available(proto)
                print(f"  {proto}: {'✓' if available else '❌'}")

        print("\n✅ Manager initialized successfully without starting!")
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
    result = asyncio.run(test_no_start())
    print(f"\nTest {'passed' if result else 'failed'}")
    sys.exit(0 if result else 1)