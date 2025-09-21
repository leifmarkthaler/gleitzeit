#!/usr/bin/env python3
"""
Trace where system hangs during startup.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def test_trace_startup():
    """Trace system startup."""
    print("\n" + "="*50)
    print("TRACING SYSTEM STARTUP")
    print("="*50 + "\n")

    from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
    from gleitzeit.system.models import SystemConfig, DeploymentMode

    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    print("1. Creating ModularStreamSystemManager...")
    manager = await ModularStreamSystemManager.create(
        config=config,
        create_if_missing=True,
        start_system=False  # Don't auto-start
    )

    if not manager:
        print("❌ Failed to create manager")
        return False

    print(f"\n2. ✓ Manager created: {manager.instance_id}")
    print(f"   Initialized: {manager._initialized}")
    print(f"   Running: {manager._running}")

    print("\n3. Starting system...")
    started = await manager.start_system()

    print(f"\n4. Start result: {started}")
    print(f"   Running: {manager._running}")

    if manager._running:
        print("\n✅ System started successfully!")

        # Keep alive briefly
        print("5. Keeping alive for 2 seconds...")
        await asyncio.sleep(2)
        print("6. Still alive!")

        # Shutdown
        print("\n7. Shutting down...")
        await manager.shutdown()
        print("8. ✓ Shutdown complete")

        return True
    else:
        print("\n❌ System failed to start")
        return False

if __name__ == "__main__":
    # Run with timeout
    try:
        loop = asyncio.get_event_loop()
        task = loop.create_task(test_trace_startup())
        loop.run_until_complete(asyncio.wait_for(task, timeout=30))
        result = task.result()
        print(f"\nTest {'PASSED' if result else 'FAILED'}")
        sys.exit(0 if result else 1)
    except asyncio.TimeoutError:
        print("\n❌ Test timed out after 30 seconds!")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)