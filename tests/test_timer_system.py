#!/usr/bin/env python3
"""
Test timer system functionality.

Tests the complete timer flow:
1. Timer handler creates sleep timers
2. TimerWorker scans and fires expired timers
3. Retry timers are created and processed
4. Atomic deletion prevents duplicate firing
5. Full audit trail is maintained
"""

import asyncio
import json
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from gleitzeit.handlers import handler_loader, HandlerRegistry
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.workers.timer_worker import TimerWorker
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.sharding import default_sharding
from gleitzeit.core.events import EventType
from gleitzeit.core.event_store import EventLevel

# Load handlers
_ = handler_loader.get_all_capabilities()


class MockRedis:
    """Mock Redis with timer-specific operations"""

    def __init__(self):
        self.data = {}  # Hash storage: key -> {field: value}
        self.sets = {}  # Set storage: key -> set()
        self.streams = {}  # Stream storage: key -> [(id, data)]
        self.scripts = {}  # Loaded Lua scripts
        self.script_counter = 0

    async def hset(self, key, mapping):
        """Set hash fields"""
        if isinstance(key, bytes):
            key = key.decode()
        if key not in self.data:
            self.data[key] = {}
        self.data[key].update(mapping)
        return len(mapping)

    async def hgetall(self, key):
        """Get all hash fields"""
        if isinstance(key, bytes):
            key = key.decode()
        return self.data.get(key, {})

    async def hget(self, key, field):
        """Get single hash field"""
        if isinstance(key, bytes):
            key = key.decode()
        if isinstance(field, bytes):
            field = field.decode()
        return self.data.get(key, {}).get(field)

    async def delete(self, key):
        """Delete key"""
        if isinstance(key, bytes):
            key = key.decode()
        if key in self.data:
            del self.data[key]
            return 1
        return 0

    async def exists(self, key):
        """Check if key exists"""
        if isinstance(key, bytes):
            key = key.decode()
        return 1 if key in self.data else 0

    async def set(self, key, value, ex=None, px=None, nx=False, xx=False):
        """Set string value"""
        if isinstance(key, bytes):
            key = key.decode()
        if isinstance(value, bytes):
            value = value.decode()

        # Handle nx (only set if not exists) and xx (only set if exists)
        if nx and key in self.data:
            return False
        if xx and key not in self.data:
            return False

        self.data[key] = {b"value": value.encode() if isinstance(value, str) else value}
        # Note: ex/px (expiration) not implemented in this mock
        return True

    async def get(self, key):
        """Get string value"""
        if isinstance(key, bytes):
            key = key.decode()
        if key in self.data and b"value" in self.data[key]:
            return self.data[key][b"value"]
        return None

    async def publish(self, channel, message):
        """Publish message to channel (no-op for mock)"""
        # We don't test pub/sub in these tests, so just no-op
        return 0

    async def sadd(self, key, *values):
        """Add to set"""
        if isinstance(key, bytes):
            key = key.decode()
        if key not in self.sets:
            self.sets[key] = set()
        for value in values:
            if isinstance(value, bytes):
                value = value.decode()
            self.sets[key].add(value)
        return len(values)

    async def srem(self, key, *values):
        """Remove from set"""
        if isinstance(key, bytes):
            key = key.decode()
        if key in self.sets:
            for value in values:
                if isinstance(value, bytes):
                    value = value.decode()
                self.sets[key].discard(value)
        return len(values)

    async def smembers(self, key):
        """Get set members"""
        if isinstance(key, bytes):
            key = key.decode()
        return self.sets.get(key, set())

    async def scan(self, cursor, match=None, count=100):
        """Scan for keys"""
        # Simple implementation: return all matching keys on first call
        if cursor != 0:
            return (0, [])

        matching_keys = []
        if match:
            import fnmatch
            # Decode match pattern if bytes
            if isinstance(match, bytes):
                match = match.decode()

            # Convert Redis pattern to Python fnmatch pattern
            matching_keys = [
                k.encode() if isinstance(k, str) else k
                for k in self.data.keys()
                if fnmatch.fnmatch(k, match)
            ]
        else:
            matching_keys = [
                k.encode() if isinstance(k, str) else k
                for k in self.data.keys()
            ]

        return (0, matching_keys)

    async def xadd(self, stream, fields, id='*', maxlen=None, approximate=True):
        """Add to stream"""
        if isinstance(stream, bytes):
            stream = stream.decode()
        if stream not in self.streams:
            self.streams[stream] = []

        # Generate simple ID if needed
        if id == '*':
            id = f"{int(time.time() * 1000)}-{len(self.streams[stream])}"

        self.streams[stream].append((id, fields))

        # Apply maxlen if specified
        if maxlen and len(self.streams[stream]) > maxlen:
            self.streams[stream] = self.streams[stream][-maxlen:]

        return id.encode()

    async def xrange(self, stream, start='-', end='+', count=None):
        """Read from stream"""
        if isinstance(stream, bytes):
            stream = stream.decode()

        if stream not in self.streams:
            return []

        results = []
        for entry_id, data in self.streams[stream]:
            results.append([entry_id.encode(), list(data.items())])

        if count:
            results = results[:count]

        return results

    async def script_load(self, script):
        """Load Lua script"""
        if isinstance(script, bytes):
            script = script.decode()

        # Generate simple SHA hash
        sha = f"sha_{self.script_counter:040x}"
        self.script_counter += 1
        self.scripts[sha] = script

        return sha.encode()

    async def evalsha(self, sha, num_keys, *args):
        """Execute Lua script"""
        if isinstance(sha, bytes):
            sha = sha.decode()

        # For timer script: atomically check and delete if expired
        # args[0] = key, args[1] = current_time
        key = args[0]
        if isinstance(key, bytes):
            key = key.decode()

        current_time = float(args[1].decode() if isinstance(args[1], bytes) else args[1])

        # Get metadata
        metadata = self.data.get(key, {})
        if not metadata:
            return None

        # Check wake_time
        wake_time_bytes = metadata.get(b'wake_time') or metadata.get('wake_time')
        if not wake_time_bytes:
            return None

        wake_time = float(wake_time_bytes.decode() if isinstance(wake_time_bytes, bytes) else wake_time_bytes)

        # If expired, delete and return metadata
        if wake_time <= current_time:
            del self.data[key]

            # Convert to Lua-style return (list of alternating keys/values)
            result = []
            for k, v in metadata.items():
                result.append(k)
                result.append(v)
            return result

        return None


async def test_timer_handler_creates_sleep_timer():
    """
    Test that the timer handler correctly creates a sleep timer.
    """
    print("\n=== Testing Timer Handler Sleep ===")

    # Get timer handler
    handler_class = HandlerRegistry.get_handler('timer/v1')
    timer_handler = handler_class(config={})

    # Create sleep task
    task = Task(
        id="task-sleep-123",
        name="Sleep for 5 seconds",
        workflow_id="wf-timer-test",
        protocol="timer/v1",
        method="timer/sleep",
        params={'duration': 5}
    )

    print(f"\n1. Executing sleep task with 5 second duration...")
    start_time = time.time()

    # Execute task - should return SCHEDULED status
    result = await timer_handler.execute(task)

    assert result.status == TaskStatus.SCHEDULED
    assert 'wake_time' in result.metadata
    assert result.metadata.get('timer_type') == 'sleep'

    wake_time = result.metadata['wake_time']
    expected_wake_time = start_time + 5

    # Allow 0.1s tolerance for execution time
    assert abs(wake_time - expected_wake_time) < 0.1

    print(f"   ✓ Task status: {result.status}")
    print(f"   ✓ Wake time: {wake_time}")
    print(f"   ✓ Timer type: {result.metadata.get('timer_type')}")
    print(f"   ✓ Duration: {wake_time - start_time:.2f}s")

    return True


async def test_timer_worker_scans_and_fires():
    """
    Test that TimerWorker scans for expired timers and fires them.
    """
    print("\n=== Testing TimerWorker Scan and Fire ===")

    mock_redis = MockRedis()

    # Step 1: Create timer metadata (simulating what TaskExecutionWorker does)
    print("\n1. Creating timer metadata...")

    workflow_id = "wf-scan-test"
    task_id = "task-scan-123"
    shard = default_sharding.get_shard(workflow_id)

    current_time = time.time()
    wake_time = current_time - 1  # Already expired (1 second ago)

    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await mock_redis.hset(
        metadata_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"shard": str(shard).encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": b"sleep",
            b"created_at": datetime.utcnow().isoformat().encode()
        }
    )

    pending_key = default_sharding.get_timer_key("pending", workflow_id)
    await mock_redis.sadd(pending_key, task_id)

    print(f"   ✓ Created timer metadata: {metadata_key}")
    print(f"   ✓ Wake time: {wake_time} (already expired)")

    # Step 2: Create TimerWorker
    print("\n2. Creating TimerWorker...")

    config = WorkerConfig(
        worker_id="timer-test-worker",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    worker = TimerWorker(config)
    worker.redis = mock_redis

    # Initialize worker (loads Lua script)
    await worker.on_initialize()

    print("   ✓ TimerWorker initialized")
    print(f"   ✓ Scan interval: {worker.scan_interval}s")

    # Step 3: Manually trigger one scan cycle
    print("\n3. Scanning for expired timers...")

    fired_before = worker.timers_fired
    await worker._scan_all_shards_for_expired_timers(current_time)
    fired_after = worker.timers_fired

    print(f"   ✓ Scan completed")
    print(f"   ✓ Timers fired: {fired_after - fired_before}")

    # Step 4: Verify timer was fired and cleaned up
    print("\n4. Verifying timer cleanup...")

    assert fired_after == fired_before + 1, "Timer should have been fired"

    # Check metadata deleted
    exists = await mock_redis.exists(metadata_key.encode())
    assert exists == 0, "Timer metadata should be deleted"

    print("   ✓ Timer metadata deleted")
    print("   ✓ Timer successfully fired and cleaned up")

    return True


async def test_timer_atomic_deletion_prevents_duplicates():
    """
    Test that the Lua script prevents duplicate timer firing.
    """
    print("\n=== Testing Atomic Timer Deletion ===")

    mock_redis = MockRedis()

    # Create timer metadata
    workflow_id = "wf-atomic-test"
    task_id = "task-atomic-123"
    shard = default_sharding.get_shard(workflow_id)

    current_time = time.time()
    wake_time = current_time - 1

    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await mock_redis.hset(
        metadata_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": b"sleep"
        }
    )

    print(f"\n1. Created timer metadata")

    # Create two workers (simulating horizontal scaling)
    config1 = WorkerConfig(
        worker_id="timer-worker-1",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    config2 = WorkerConfig(
        worker_id="timer-worker-2",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    worker1 = TimerWorker(config1)
    worker1.redis = mock_redis
    await worker1.on_initialize()

    worker2 = TimerWorker(config2)
    worker2.redis = mock_redis
    await worker2.on_initialize()

    print("2. Created two TimerWorkers (simulating horizontal scaling)")

    # Both workers try to fire the timer
    print("\n3. Both workers scanning for expired timers...")

    result1 = await worker1._try_fire_timer(metadata_key.encode(), current_time)
    result2 = await worker2._try_fire_timer(metadata_key.encode(), current_time)

    # Only one should succeed
    fired_count = sum([1 for r in [result1, result2] if r is not None])

    assert fired_count == 1, "Only one worker should fire the timer"
    print(f"   ✓ Only one worker fired the timer (atomic deletion worked)")

    # Verify metadata is gone
    exists = await mock_redis.exists(metadata_key.encode())
    assert exists == 0, "Timer metadata should be deleted"

    print("   ✓ Timer metadata deleted atomically")

    return True


async def test_timer_with_future_wake_time():
    """
    Test that timers with future wake times are not fired.
    """
    print("\n=== Testing Future Timer Not Fired ===")

    mock_redis = MockRedis()

    # Create timer metadata with future wake time
    workflow_id = "wf-future-test"
    task_id = "task-future-123"

    current_time = time.time()
    wake_time = current_time + 3600  # 1 hour in the future

    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await mock_redis.hset(
        metadata_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": b"sleep"
        }
    )

    print(f"\n1. Created timer with wake_time in 1 hour")

    # Create worker
    config = WorkerConfig(
        worker_id="timer-test-worker",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    worker = TimerWorker(config)
    worker.redis = mock_redis
    await worker.on_initialize()

    print("2. Created TimerWorker")

    # Scan for expired timers
    print("\n3. Scanning for expired timers...")

    fired_before = worker.timers_fired
    await worker._scan_all_shards_for_expired_timers(current_time)
    fired_after = worker.timers_fired

    # Should not fire
    assert fired_after == fired_before, "Future timer should not fire"
    print("   ✓ Future timer not fired (correct)")

    # Verify metadata still exists
    exists = await mock_redis.exists(metadata_key.encode())
    assert exists == 1, "Timer metadata should still exist"
    print("   ✓ Timer metadata preserved")

    return True


async def test_retry_timer_requeues_task():
    """
    Test that retry timers are detected and fired.

    Note: Full retry re-queueing is an integration test that requires
    complete workflow state. This test validates that retry timers are
    detected, fired, and metadata is cleaned up.
    """
    print("\n=== Testing Retry Timer Detection ===")

    mock_redis = MockRedis()

    # Create retry timer metadata
    workflow_id = "wf-retry-test"
    task_id = "task-retry-123"
    shard = default_sharding.get_shard(workflow_id)

    current_time = time.time()
    wake_time = current_time - 1  # Already expired

    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await mock_redis.hset(
        metadata_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"shard": str(shard).encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": b"retry",  # Retry timer
            b"retry_attempt": b"2",
            b"last_error": b"Connection timeout"
        }
    )

    pending_key = default_sharding.get_timer_key("pending", workflow_id)
    await mock_redis.sadd(pending_key, task_id)

    print(f"\n1. Created retry timer (attempt 2)")

    # Create worker
    config = WorkerConfig(
        worker_id="timer-test-worker",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    worker = TimerWorker(config)
    worker.redis = mock_redis
    await worker.on_initialize()

    print("2. Created TimerWorker")

    # Scan and detect retry timer
    print("\n3. Scanning for retry timer...")

    fired_before = worker.timers_fired
    await worker._scan_all_shards_for_expired_timers(current_time)
    fired_after = worker.timers_fired

    # Should have attempted to fire the retry timer
    assert fired_after == fired_before + 1, "Retry timer should have been detected and fired"
    print("   ✓ Retry timer detected and processed")

    # Verify metadata deleted (even if re-queue fails due to missing workflow data)
    exists = await mock_redis.exists(metadata_key.encode())
    assert exists == 0, "Timer metadata should be deleted"
    print("   ✓ Timer metadata cleaned up")

    return True


async def test_multiple_timers_in_workflow():
    """
    Test scanning and firing multiple timers in a single workflow.
    """
    print("\n=== Testing Multiple Timers ===")

    mock_redis = MockRedis()

    workflow_id = "wf-multi-test"
    current_time = time.time()

    # Create 5 timers: 3 expired, 2 future
    timers = []
    for i in range(5):
        task_id = f"task-multi-{i}"
        wake_time = current_time - 1 if i < 3 else current_time + 3600

        metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
        await mock_redis.hset(
            metadata_key.encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"wake_time": str(wake_time).encode(),
                b"timer_type": b"sleep"
            }
        )

        timers.append({
            'task_id': task_id,
            'wake_time': wake_time,
            'should_fire': i < 3
        })

    print(f"\n1. Created 5 timers: 3 expired, 2 future")

    # Create worker
    config = WorkerConfig(
        worker_id="timer-test-worker",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    worker = TimerWorker(config)
    worker.redis = mock_redis
    await worker.on_initialize()

    print("2. Created TimerWorker")

    # Scan and fire
    print("\n3. Scanning for expired timers...")

    await worker._scan_all_shards_for_expired_timers(current_time)

    # Verify correct timers fired
    print(f"   ✓ Fired {worker.timers_fired} timers")
    assert worker.timers_fired == 3, "Should fire exactly 3 expired timers"

    # Verify metadata states
    for timer in timers:
        task_id = timer['task_id']
        metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
        exists = await mock_redis.exists(metadata_key.encode())

        if timer['should_fire']:
            assert exists == 0, f"Expired timer {task_id} should be deleted"
        else:
            assert exists == 1, f"Future timer {task_id} should still exist"

    print("   ✓ All expired timers deleted")
    print("   ✓ All future timers preserved")

    return True


async def test_timer_event_audit_trail():
    """
    Test that timer firing creates proper audit trail events.
    """
    print("\n=== Testing Timer Audit Trail ===")

    mock_redis = MockRedis()

    workflow_id = "wf-audit-test"
    task_id = "task-audit-123"

    current_time = time.time()
    wake_time = current_time - 1

    # Create timer metadata
    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await mock_redis.hset(
        metadata_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": b"sleep",
            b"created_at": datetime.utcnow().isoformat().encode()
        }
    )

    pending_key = default_sharding.get_timer_key("pending", workflow_id)
    await mock_redis.sadd(pending_key, task_id)

    print("\n1. Created timer metadata")

    # Create worker
    config = WorkerConfig(
        worker_id="timer-test-worker",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    worker = TimerWorker(config)
    worker.redis = mock_redis
    await worker.on_initialize()

    print("2. Created TimerWorker with EventStore")

    # Fire timer
    print("\n3. Firing timer...")

    await worker._scan_all_shards_for_expired_timers(current_time)

    # Check events were published
    shard = default_sharding.get_shard(workflow_id)
    events_key = f"{{shard:{shard}}}:events:{workflow_id}"
    events = await mock_redis.xrange(events_key)

    print(f"   ✓ Published {len(events)} events")

    # Should have timer:fired event
    event_types = []
    for event_id, event_data in events:
        event_dict = dict(event_data)
        if b'event_type' in event_dict:
            event_types.append(event_dict[b'event_type'].decode())
        elif 'event_type' in event_dict:
            event_types.append(event_dict['event_type'])

    assert 'timer:fired' in event_types, "Should have timer:fired event"
    print("   ✓ timer:fired event published")
    print(f"   ✓ Event types: {event_types}")

    return True


async def test_timer_scan_performance():
    """
    Test timer scanning performance with many timers.
    """
    print("\n=== Testing Timer Scan Performance ===")

    mock_redis = MockRedis()

    # Create 100 timers across different workflows
    num_timers = 100
    current_time = time.time()

    print(f"\n1. Creating {num_timers} timers...")

    for i in range(num_timers):
        workflow_id = f"wf-perf-{i % 10}"  # 10 workflows
        task_id = f"task-perf-{i}"

        # 50% expired, 50% future
        wake_time = current_time - 1 if i % 2 == 0 else current_time + 3600

        metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
        await mock_redis.hset(
            metadata_key.encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"wake_time": str(wake_time).encode(),
                b"timer_type": b"sleep"
            }
        )

    print(f"   ✓ Created {num_timers} timers (50 expired, 50 future)")

    # Create worker
    config = WorkerConfig(
        worker_id="timer-test-worker",
        worker_type="timer",
        consumer_group="timer-group",
        max_concurrent=10,
        batch_size=10,
        block_timeout=1000
    )

    worker = TimerWorker(config)
    worker.redis = mock_redis
    await worker.on_initialize()

    print("2. Created TimerWorker")

    # Measure scan time
    print("\n3. Scanning all shards...")

    start = time.time()
    await worker._scan_all_shards_for_expired_timers(current_time)
    duration = time.time() - start

    print(f"   ✓ Scan completed in {duration*1000:.2f}ms")
    print(f"   ✓ Fired {worker.timers_fired} timers")
    print(f"   ✓ Performance: {duration/num_timers*1000:.2f}ms per timer")

    assert worker.timers_fired == 50, "Should fire exactly 50 expired timers"
    assert duration < 1.0, "Scan should complete in under 1 second"

    return True


# Main test runner
async def run_all_tests():
    """Run all timer system tests"""
    tests = [
        test_timer_handler_creates_sleep_timer,
        test_timer_worker_scans_and_fires,
        test_timer_atomic_deletion_prevents_duplicates,
        test_timer_with_future_wake_time,
        test_retry_timer_requeues_task,
        test_multiple_timers_in_workflow,
        test_timer_event_audit_trail,
        test_timer_scan_performance,
    ]

    print("\n" + "="*60)
    print("TIMER SYSTEM TEST SUITE")
    print("="*60)

    passed = 0
    failed = 0

    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
                print(f"\n✓ {test.__name__} PASSED")
            else:
                failed += 1
                print(f"\n✗ {test.__name__} FAILED")
        except Exception as e:
            failed += 1
            print(f"\n✗ {test.__name__} FAILED with exception:")
            print(f"   {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("="*60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
