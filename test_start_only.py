#!/usr/bin/env python3
"""
Test just starting the system.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

async def test_start():
    """Test starting the system."""
    print("Creating and starting ModularStreamSystemManager...")

    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    manager = await ModularStreamSystemManager.create(
        config=config,
        stream_config={'total_shards': 8},
        create_if_missing=True,
        start_system=True  # Start immediately
    )

    if not manager:
        print("❌ Failed to create manager")
        return False

    print(f"✓ Manager created and started: {manager.instance_id}")
    print("✓ System is running!")

    # Keep alive for a moment
    await asyncio.sleep(2)

    print("\nShutting down...")
    await manager.shutdown()
    print("✓ Shutdown complete")

    return True

if __name__ == "__main__":
    result = asyncio.run(test_start())
    print(f"\nTest {'passed' if result else 'failed'}")
    sys.exit(0 if result else 1)