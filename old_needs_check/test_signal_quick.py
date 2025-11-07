#!/usr/bin/env python
"""Quick test for signal send/broadcast functionality"""

import asyncio
import sys
from pathlib import Path
import json
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.handlers.signal import SignalHandler
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.signals.stateless_signal_manager import StatelessSignalManager
import redis.asyncio as aioredis

async def test_signal_handler():
    """Test the signal handler directly"""
    print("\n=== Testing Signal Handler ===\n")

    handler = SignalHandler()

    # Test 1: Send to current workflow (default)
    print("1. Testing send to current workflow...")
    task1 = Task(
        id="test-1",
        name="Send to Self",
        workflow_id="wf-123",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": "self-signal",
            "payload": {"test": "data"}
        }
    )

    result1 = await handler.execute(task1)
    assert result1.status == TaskStatus.COMPLETED
    assert result1.metadata["target_workflows"] == ["wf-123"]
    print("   ✅ Send to current workflow works")

    # Test 2: Send to specific workflows
    print("2. Testing send to specific workflows...")
    task2 = Task(
        id="test-2",
        name="Send to Others",
        workflow_id="wf-123",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": "multi-signal",
            "target_workflows": ["wf-456", "wf-789"],
            "payload": {"multi": True}
        }
    )

    result2 = await handler.execute(task2)
    assert result2.status == TaskStatus.COMPLETED
    assert result2.metadata["target_workflows"] == ["wf-456", "wf-789"]
    print("   ✅ Send to specific workflows works")

    # Test 3: Broadcast
    print("3. Testing broadcast...")
    task3 = Task(
        id="test-3",
        name="Broadcast",
        workflow_id="wf-123",
        protocol="signal/v1",
        method="signal/broadcast",
        params={
            "signal_name": "system-wide",
            "payload": {"broadcast": True}
        }
    )

    result3 = await handler.execute(task3)
    assert result3.status == TaskStatus.COMPLETED
    assert result3.metadata["signal_action"] == "broadcast"
    assert "target_workflows" not in result3.metadata  # Broadcast has no targets
    print("   ✅ Broadcast works")

    print("\n✅ All handler tests passed!\n")

async def test_signal_manager():
    """Test the signal manager with Redis"""
    print("=== Testing Signal Manager with Redis ===\n")

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379')

    try:
        # Clear any old test data
        await redis.delete(b"signals:pending")

        # Test 1: Send to specific workflow
        print("1. Sending signal to specific workflow...")
        signal_id1 = await StatelessSignalManager.send_signal(
            redis=redis,
            signal_name="test-signal-1",
            workflow_id="wf-test-123",
            payload={"message": "Hello workflow"}
        )
        print(f"   Created signal: {signal_id1}")

        # Verify signal was stored
        signal_meta = await redis.hgetall(f"signals:meta:{signal_id1}".encode())
        assert signal_meta[b"signal_name"] == b"test-signal-1"
        assert signal_meta[b"workflow_id"] == b"wf-test-123"
        print("   ✅ Signal stored correctly")

        # Test 2: Broadcast (no workflow)
        print("2. Broadcasting system-wide signal...")
        signal_id2 = await StatelessSignalManager.send_signal(
            redis=redis,
            signal_name="broadcast-signal",
            workflow_id=None,  # Broadcast
            payload={"broadcast": True}
        )
        print(f"   Created broadcast: {signal_id2}")

        # Verify broadcast was stored
        signal_meta2 = await redis.hgetall(f"signals:meta:{signal_id2}".encode())
        assert signal_meta2[b"signal_name"] == b"broadcast-signal"
        assert signal_meta2[b"workflow_id"] == b""  # Empty for broadcast
        print("   ✅ Broadcast stored correctly")

        # Check pending queue
        pending = await redis.lrange(b"signals:pending", 0, -1)
        print(f"3. Pending signals in queue: {len(pending)}")
        assert len(pending) >= 2  # Our two signals
        print("   ✅ Signals queued for processing")

        print("\n✅ All signal manager tests passed!\n")

    finally:
        # Cleanup
        await redis.delete(b"signals:pending")
        await redis.delete(f"signals:meta:{signal_id1}".encode())
        await redis.delete(f"signals:meta:{signal_id2}".encode())
        await redis.aclose()

async def test_end_to_end():
    """Test end-to-end signal flow"""
    print("=== Testing End-to-End Signal Flow ===\n")

    redis = await aioredis.from_url('redis://localhost:6379')

    try:
        # Directly test signal emission logic
        from gleitzeit.signals.stateless_signal_manager import StatelessSignalManager

        async def emit_signal(sender_workflow_id, signal_name, payload, target_workflow=None):
            """Simulate what TaskExecutionWorker does"""
            signal_id = await StatelessSignalManager.send_signal(
                redis=redis,
                signal_name=signal_name,
                workflow_id=target_workflow,
                payload=payload
            )

            if target_workflow is None:
                print(f"   Broadcast '{signal_name}' system-wide (ID: {signal_id})")
            elif target_workflow == sender_workflow_id:
                print(f"   Sent '{signal_name}' within workflow {sender_workflow_id} (ID: {signal_id})")
            else:
                print(f"   Sent '{signal_name}' from {sender_workflow_id} to {target_workflow} (ID: {signal_id})")

            return signal_id

        # Test different signal scenarios
        print("1. Testing internal workflow signal...")
        await emit_signal(
            sender_workflow_id="wf-100",
            signal_name="internal-signal",
            payload={"internal": True},
            target_workflow="wf-100"
        )

        print("2. Testing cross-workflow signal...")
        await emit_signal(
            sender_workflow_id="wf-100",
            signal_name="cross-signal",
            payload={"cross": True},
            target_workflow="wf-200"
        )

        print("3. Testing broadcast signal...")
        await emit_signal(
            sender_workflow_id="wf-100",
            signal_name="broadcast-signal",
            payload={"broadcast": True},
            target_workflow=None
        )

        print("\n✅ All end-to-end tests passed!\n")

    finally:
        # Cleanup
        await redis.flushdb()
        await redis.aclose()

async def main():
    """Run all tests"""
    print("\n🧪 Testing Signal Send/Broadcast Implementation\n")
    print("=" * 50)

    # Test handler without Redis
    await test_signal_handler()

    # Test with Redis
    await test_signal_manager()

    # Test end-to-end flow
    await test_end_to_end()

    print("=" * 50)
    print("\n✨ All tests passed successfully!\n")

if __name__ == "__main__":
    asyncio.run(main())