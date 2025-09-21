#!/usr/bin/env python3
"""
Test if system properly starts.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system import create_system_manager

async def test_system_running():
    """Test if system starts and runs."""
    print("Creating system manager...")

    manager = await create_system_manager()
    print(f"✓ Created: {manager.__class__.__name__}")
    print(f"  Instance: {manager.instance_id}")
    print(f"  Running: {manager._running}")

    # Try to start the system
    print("\nStarting system...")
    result = await manager.start_system()
    print(f"  Start result: {result}")
    print(f"  Running: {manager._running}")

    if manager._running:
        print("✅ System is running!")

        # Check if consumer is running
        if hasattr(manager, 'stream_consumer') and manager.stream_consumer:
            print(f"  Consumer started: {manager.consumer_started}")
            if hasattr(manager.stream_consumer, '_consumer_task'):
                print(f"  Consumer task: {manager.stream_consumer._consumer_task}")
                print(f"  Task done: {manager.stream_consumer._consumer_task.done()}")

        # Let it run for a moment
        print("\nLetting system run for 2 seconds...")
        await asyncio.sleep(2)
        print("Still running!")

        # Shutdown
        print("\nShutting down...")
        await manager.shutdown()
        print("✓ Shutdown complete")

        return True
    else:
        print("❌ System failed to start")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_system_running())
    sys.exit(0 if result else 1)