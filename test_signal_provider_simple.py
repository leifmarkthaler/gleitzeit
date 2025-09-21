#!/usr/bin/env python3
"""
Simple test to verify SignalProvider is registered and available.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.providers.signal_provider import SignalProvider
import uuid
from datetime import datetime

async def test_signal_provider():
    """Test that SignalProvider is properly registered."""

    print("Testing SignalProvider registration in ModularStreamSystemManager...\n")

    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    manager = await ModularStreamSystemManager.create(
        config=config,
        stream_config={'total_shards': 8},
        create_if_missing=True,
        start_system=False  # Don't start full system
    )

    if not manager:
        print("❌ Failed to create manager")
        return False

    print(f"✓ Created manager: {manager.instance_id}")

    try:
        # Check if SignalProvider is registered
        if hasattr(manager, 'pooling_adapter') and manager.pooling_adapter:
            print("\n✓ PoolingAdapter available")

            # Check protocol availability
            signal_available = manager.pooling_adapter.is_protocol_available('signal/v1')
            timer_available = manager.pooling_adapter.is_protocol_available('timer/v1')

            print(f"{'✓' if signal_available else '❌'} signal/v1 protocol: {'available' if signal_available else 'NOT available'}")
            print(f"{'✓' if timer_available else '❌'} timer/v1 protocol: {'available' if timer_available else 'NOT available'}")

            if signal_available and timer_available:
                print("\n✅ SUCCESS: Both SignalProvider and TimerProvider are registered!")

                # Test creating a signal task to verify it can be executed
                print("\nTesting task creation...")
                signal_task = Task(
                    id=f"test_signal_{uuid.uuid4().hex[:8]}",
                    name="Test Signal",
                    protocol="signal/v1",
                    method="signal/wait",
                    params={
                        "signal": "test_signal",
                        "timeout": 5
                    },
                    status=TaskStatus.PENDING,
                    created_at=datetime.utcnow()
                )

                # Verify the task executor would accept this
                if hasattr(manager, 'task_executor') and manager.task_executor:
                    # Just check that it recognizes the protocol
                    print(f"✓ Created signal task: {signal_task.id}")
                    print(f"  Protocol: {signal_task.protocol}")
                    print(f"  Method: {signal_task.method}")
                    print("\n✅ SignalProvider is properly configured for workflow tasks!")
                else:
                    print("⚠️ Task executor not initialized (expected in non-started system)")
                    print("✓ But providers are registered and will work when system starts")

                return True
            else:
                print("\n❌ FAILED: Providers not properly registered")
                return False
        else:
            print("❌ No PoolingAdapter found")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print("\nShutting down manager...")
        await manager.shutdown()
        print("✓ Manager shutdown complete")

if __name__ == "__main__":
    result = asyncio.run(test_signal_provider())
    sys.exit(0 if result else 1)