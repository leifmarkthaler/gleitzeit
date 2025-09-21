#!/usr/bin/env python3
"""
Test that ModularStreamSystemManager is now the default.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

async def test_default_manager():
    """Test the default manager creation."""
    print("Testing default manager creation...")

    # Test 1: Import and check what SystemManager is
    from gleitzeit.system import get_system_manager, create_system_manager

    # Create a manager using the default function
    try:
        manager = await create_system_manager()
        print(f"✓ Created manager: {manager.__class__.__name__}")
        print(f"  Instance ID: {manager.instance_id}")

        # Check if it's ModularStreamSystemManager
        from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
        if isinstance(manager, ModularStreamSystemManager):
            print("✅ SUCCESS: ModularStreamSystemManager is the default!")
        else:
            print(f"❌ FAILED: Got {type(manager)} instead of ModularStreamSystemManager")
            return False

        # Check components
        print("\nChecking components...")
        print(f"  Workflow Manager: {hasattr(manager, 'workflow_manager') and manager.workflow_manager is not None}")
        print(f"  Workflow Loader: {hasattr(manager, 'workflow_loader') and manager.workflow_loader is not None}")
        print(f"  Pooling Adapter: {hasattr(manager, 'pooling_adapter') and manager.pooling_adapter is not None}")

        # Check provider registration
        if manager.pooling_adapter:
            protocols = list(manager.pooling_adapter._registered_protocols)
            print(f"\nRegistered protocols: {protocols}")
            for proto in ['python/v1', 'timer/v1', 'signal/v1']:
                available = manager.pooling_adapter.is_protocol_available(proto)
                print(f"  {proto}: {'✓' if available else '❌'}")

        # Cleanup
        print("\nShutting down...")
        await manager.shutdown()
        print("✓ Shutdown complete")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_default_manager())
    print(f"\n{'='*50}")
    print(f"Test {'PASSED' if result else 'FAILED'}")
    sys.exit(0 if result else 1)