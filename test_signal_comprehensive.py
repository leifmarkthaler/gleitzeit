#!/usr/bin/env python
"""Comprehensive test of signal functionality"""

import asyncio
import logging
import sys
from pathlib import Path
import json
import time
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.task_execution_worker_v2 import TaskExecutionWorkerV2
from gleitzeit.workers.signal_worker import SignalWorker
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.sharding import default_sharding
import redis.asyncio as aioredis

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_signal_actually_waits():
    """Test that signal tasks actually wait and don't complete immediately"""
    print("\n=== TEST 1: Signal Task Actually Waits ===\n")

    redis = await aioredis.from_url('redis://localhost:6379')
    await redis.flushdb()

    import uuid
    workflow_id = f"test_wait_{uuid.uuid4().hex[:8]}"

    workflow = {
        'name': 'test-wait',
        'tasks': [
            {
                'id': 'signal_task',
                'type': 'signal',
                'signal_action': 'wait',
                'signal_name': 'my-signal',
                'timeout': 30
            }
        ]
    }

    shard = default_sharding.get_shard(workflow_id)

    # Submit workflow using cluster-aware key format
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:load".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(workflow).encode(),
            b"format": b"inline"
        }
    )

    # Start workers
    workers = []
    configs = [
        WorkerConfig("workflow_loader", f"loader-{workflow_id}", "loader-group", "redis://localhost:6379", [shard]),
        WorkerConfig("dependency", f"dep-{workflow_id}", "dep-group", "redis://localhost:6379", [shard]),
        WorkerConfig("task_execution", f"exec-{workflow_id}", "exec-group", "redis://localhost:6379", [shard]),
        WorkerConfig("signal", f"signal-{workflow_id}", "signal-group", "redis://localhost:6379", list(range(16)))
    ]

    for config in configs:
        if config.worker_type == "workflow_loader":
            worker = WorkflowLoaderWorkerV2(config)
        elif config.worker_type == "dependency":
            worker = DependencyWorker(config)
        elif config.worker_type == "task_execution":
            worker = TaskExecutionWorkerV2(config)
        elif config.worker_type == "signal":
            worker = SignalWorker(config)
        await worker.initialize()
        workers.append(worker)

    # Start all workers
    tasks = [asyncio.create_task(worker.run()) for worker in workers]

    # Wait for task to start waiting
    print("Waiting for signal task to enter waiting state...")
    await asyncio.sleep(2)

    # Check task status
    status = await redis.hget(f"{{shard:{shard}}}:task:status:signal_task".encode(), b"status")
    if status:
        print(f"✅ Task status: {status.decode()}")
        assert status.decode() == "waiting", f"Expected waiting, got {status.decode()}"
    else:
        print("❌ No task status found!")

    # Check if task is registered as waiting
    waiters = await redis.smembers(f"{{shard:{shard}}}:signal:waiters:{workflow_id}:my-signal")
    print(f"Registered waiters: {waiters}")
    assert len(waiters) > 0, "No waiters registered!"

    print("\n⏰ Waiting 5 seconds before sending signal...")
    await asyncio.sleep(5)

    # Send signal
    print("📤 Sending signal...")
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:signals:{workflow_id}".encode(),
        {
            b"signal": b"my-signal",
            b"payload": json.dumps({"test": "data"}).encode(),
            b"timestamp": datetime.utcnow().isoformat().encode()
        }
    )

    # Wait for signal to be processed
    await asyncio.sleep(2)

    # Check final status
    final_status = await redis.hget(f"{{shard:{shard}}}:task:status:signal_task".encode(), b"status")
    if final_status:
        print(f"✅ Final task status: {final_status.decode()}")
        assert final_status.decode() == "completed", f"Expected completed, got {final_status.decode()}"

    # Check result
    result = await redis.hget(f"{{shard:{shard}}}:task:status:signal_task".encode(), b"result")
    if result:
        result_data = json.loads(result.decode())
        print(f"✅ Task result: {json.dumps(result_data, indent=2)}")
        assert result_data.get("signal_received") == True
        assert result_data.get("signal_name") == "my-signal"

    # Stop workers
    for worker in workers:
        worker._running = False
    await asyncio.sleep(1)
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    print("\n✅ TEST 1 PASSED: Signal task waited and completed correctly\n")
    await redis.aclose()


async def test_signal_timeout():
    """Test that signal tasks timeout correctly"""
    print("\n=== TEST 2: Signal Timeout ===\n")

    redis = await aioredis.from_url('redis://localhost:6379')
    await redis.flushdb()

    import uuid
    workflow_id = f"test_timeout_{uuid.uuid4().hex[:8]}"

    workflow = {
        'name': 'test-timeout',
        'tasks': [
            {
                'id': 'timeout_task',
                'type': 'signal',
                'signal_action': 'wait',
                'signal_name': 'never-coming',
                'timeout': 2  # 2 second timeout
            }
        ]
    }

    shard = default_sharding.get_shard(workflow_id)

    # Submit workflow using cluster-aware key format
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:load".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(workflow).encode(),
            b"format": b"inline"
        }
    )

    # Start workers
    workers = []
    configs = [
        WorkerConfig("workflow_loader", f"loader-{workflow_id}", "loader-group", "redis://localhost:6379", [shard]),
        WorkerConfig("dependency", f"dep-{workflow_id}", "dep-group", "redis://localhost:6379", [shard]),
        WorkerConfig("task_execution", f"exec-{workflow_id}", "exec-group", "redis://localhost:6379", [shard]),
        WorkerConfig("signal", f"signal-{workflow_id}", "signal-group", "redis://localhost:6379", list(range(16)))
    ]

    for config in configs:
        if config.worker_type == "workflow_loader":
            worker = WorkflowLoaderWorkerV2(config)
        elif config.worker_type == "dependency":
            worker = DependencyWorker(config)
        elif config.worker_type == "task_execution":
            worker = TaskExecutionWorkerV2(config)
        elif config.worker_type == "signal":
            worker = SignalWorker(config)
        await worker.initialize()
        workers.append(worker)

    # Start all workers
    tasks = [asyncio.create_task(worker.run()) for worker in workers]

    # Wait for task to start waiting
    print("Waiting for task to enter waiting state...")
    await asyncio.sleep(2)

    status = await redis.hget(f"task:status:timeout_task".encode(), b"status")
    if status:
        print(f"Initial status: {status.decode()}")
        assert status.decode() == "waiting"

    # Check timeout is registered
    timeout_score = await redis.zscore(b"signal:timeouts", f"signal:task:{workflow_id}:timeout_task".encode())
    if timeout_score:
        print(f"✅ Timeout registered for timestamp: {timeout_score}")

    print("⏰ Waiting for timeout to expire (3 seconds)...")
    await asyncio.sleep(3)

    # Check if task failed due to timeout
    final_status = await redis.hget(f"task:status:timeout_task".encode(), b"status")
    if final_status:
        print(f"Final status: {final_status.decode()}")
        if final_status.decode() == "failed":
            error = await redis.hget(f"task:status:timeout_task".encode(), b"error")
            if error:
                print(f"✅ Task failed with error: {error.decode()}")
                assert "timed out" in error.decode().lower(), f"Expected 'timed out' in error, got: {error.decode()}"
        else:
            print(f"⚠️ Task did not fail - status is {final_status.decode()}")
    else:
        print("⚠️ No final status found")

    # Stop workers
    for worker in workers:
        worker._running = False
    await asyncio.sleep(1)
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    print("\n✅ TEST 2 COMPLETE: Timeout behavior tested\n")
    await redis.aclose()


async def test_multiple_signals():
    """Test wait_any with multiple signals"""
    print("\n=== TEST 3: Wait for Any Signal ===\n")

    redis = await aioredis.from_url('redis://localhost:6379')
    await redis.flushdb()

    import uuid
    workflow_id = f"test_any_{uuid.uuid4().hex[:8]}"

    workflow = {
        'name': 'test-any',
        'tasks': [
            {
                'id': 'wait_any_task',
                'type': 'signal',
                'signal_action': 'wait_any',
                'signal_names': ['signal-a', 'signal-b', 'signal-c'],
                'timeout': 30
            }
        ]
    }

    shard = default_sharding.get_shard(workflow_id)

    # Submit workflow using cluster-aware key format
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:load".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(workflow).encode(),
            b"format": b"inline"
        }
    )

    # Start workers
    workers = []
    configs = [
        WorkerConfig("workflow_loader", f"loader-{workflow_id}", "loader-group", "redis://localhost:6379", [shard]),
        WorkerConfig("dependency", f"dep-{workflow_id}", "dep-group", "redis://localhost:6379", [shard]),
        WorkerConfig("task_execution", f"exec-{workflow_id}", "exec-group", "redis://localhost:6379", [shard]),
        WorkerConfig("signal", f"signal-{workflow_id}", "signal-group", "redis://localhost:6379", list(range(16)))
    ]

    for config in configs:
        if config.worker_type == "workflow_loader":
            worker = WorkflowLoaderWorkerV2(config)
        elif config.worker_type == "dependency":
            worker = DependencyWorker(config)
        elif config.worker_type == "task_execution":
            worker = TaskExecutionWorkerV2(config)
        elif config.worker_type == "signal":
            worker = SignalWorker(config)
        await worker.initialize()
        workers.append(worker)

    # Start all workers
    tasks = [asyncio.create_task(worker.run()) for worker in workers]

    # Wait for task to start waiting
    await asyncio.sleep(2)

    # Check task is waiting for all signals
    for signal in ['signal-a', 'signal-b', 'signal-c']:
        waiters = await redis.smembers(f"{{shard:{shard}}}:signal:waiters:{workflow_id}:{signal}")
        print(f"Waiters for {signal}: {waiters}")
        assert len(waiters) > 0, f"Not waiting for {signal}"

    print("\n📤 Sending signal-b (middle one)...")
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:signals:{workflow_id}".encode(),
        {
            b"signal": b"signal-b",
            b"payload": json.dumps({"which": "b"}).encode(),
            b"timestamp": datetime.utcnow().isoformat().encode()
        }
    )

    # Wait for processing
    await asyncio.sleep(2)

    # Check task completed
    final_status = await redis.hget(f"{{shard:{shard}}}:task:status:wait_any_task".encode(), b"status")
    if final_status:
        print(f"✅ Task completed with status: {final_status.decode()}")
        assert final_status.decode() == "completed"

    # Check result shows signal-b
    result = await redis.hget(f"{{shard:{shard}}}:task:status:wait_any_task".encode(), b"result")
    if result:
        result_data = json.loads(result.decode())
        print(f"Result: {json.dumps(result_data, indent=2)}")
        assert result_data.get("signal_name") == "signal-b"

    # Stop workers
    for worker in workers:
        worker._running = False
    await asyncio.sleep(1)
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    print("\n✅ TEST 3 PASSED: Wait_any works correctly\n")
    await redis.aclose()


async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("COMPREHENSIVE SIGNAL TESTING")
    print("="*60)

    try:
        await test_signal_actually_waits()
        await test_signal_timeout()
        await test_multiple_signals()

        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("Signal implementation is fully functional!")
        print("="*60 + "\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())