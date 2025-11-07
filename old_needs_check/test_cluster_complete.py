#!/usr/bin/env python
"""Final comprehensive test to verify all components use cluster-aware keys"""

import asyncio
import sys
from pathlib import Path
import json
import uuid

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.core.redis_cluster import GleitzeitRedisCluster
from gleitzeit.core.sharding import default_sharding
from gleitzeit.workers.base import WorkerConfig
import redis.asyncio as aioredis

async def main():
    print("=" * 80)
    print("COMPLETE REDIS CLUSTER IMPLEMENTATION VERIFICATION")
    print("=" * 80)

    # Initialize Redis
    redis = await aioredis.from_url('redis://localhost:6379')
    await redis.flushdb()

    print("\n✅ Redis cleared for testing")

    # Test workflow with all component types
    workflow_id = f"test_{uuid.uuid4().hex[:8]}"
    shard = default_sharding.get_shard(workflow_id)

    workflow = {
        'name': 'complete-test',
        'tasks': [
            {
                'id': 'python_task',
                'type': 'python',
                'code': 'print("Python task")'
            },
            {
                'id': 'timer_task',
                'type': 'timer',
                'timer_type': 'delay',
                'delay': 1,
                'dependencies': ['python_task']
            },
            {
                'id': 'signal_task',
                'type': 'signal',
                'signal_action': 'wait',
                'signal_name': 'test-signal',
                'timeout': 5,
                'dependencies': ['timer_task']
            }
        ]
    }

    # Submit workflow
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:load".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(workflow).encode(),
            b"format": b"inline"
        }
    )

    print(f"\n✅ Submitted workflow {workflow_id} to shard {shard}")

    # Start all worker types
    print("\nStarting workers...")
    from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
    from gleitzeit.workers.dependency_worker import DependencyWorker
    from gleitzeit.workers.task_execution_worker_v2 import TaskExecutionWorkerV2
    from gleitzeit.workers.timer_worker import TimerWorker
    from gleitzeit.workers.signal_worker import SignalWorker

    workers = []
    configs = [
        WorkerConfig("workflow_loader", "loader-test", "loader-group", assigned_shards=[shard]),
        WorkerConfig("dependency", "dep-test", "dep-group", assigned_shards=[shard]),
        WorkerConfig("task_execution", "exec-test", "exec-group", assigned_shards=[shard]),
        WorkerConfig("timer", "timer-test", "timer-group", assigned_shards=list(range(16))),
        WorkerConfig("signal", "signal-test", "signal-group", assigned_shards=list(range(16)))
    ]

    for config in configs:
        if config.worker_type == "workflow_loader":
            worker = WorkflowLoaderWorkerV2(config)
        elif config.worker_type == "dependency":
            worker = DependencyWorker(config)
        elif config.worker_type == "task_execution":
            worker = TaskExecutionWorkerV2(config)
        elif config.worker_type == "timer":
            worker = TimerWorker(config)
        elif config.worker_type == "signal":
            worker = SignalWorker(config)

        await worker.initialize()
        workers.append(worker)
        print(f"  ✅ {worker.__class__.__name__} started")

    # Run workers
    tasks = [asyncio.create_task(worker.run()) for worker in workers]

    # Let them process
    await asyncio.sleep(3)

    # Send signal to complete workflow
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:signals:{workflow_id}".encode(),
        {
            b"signal": b"test-signal",
            b"payload": b"{}",
            b"timestamp": b"2025-01-01T00:00:00"
        }
    )

    await asyncio.sleep(2)

    # Check all keys created use cluster format
    print("\n" + "=" * 80)
    print("VERIFYING REDIS KEY FORMATS")
    print("=" * 80)

    cursor = b"0"
    all_keys = []
    while True:
        cursor, keys = await redis.scan(cursor)
        all_keys.extend(keys)
        if cursor == b"0":
            break

    print(f"\nTotal keys created: {len(all_keys)}")

    # Check key patterns
    cluster_keys = 0
    non_cluster_keys = []

    for key in all_keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        if key_str.startswith("{shard:"):
            cluster_keys += 1
        else:
            non_cluster_keys.append(key_str)

    print(f"✅ Cluster-aware keys: {cluster_keys}")

    if non_cluster_keys:
        print(f"⚠️  Non-cluster keys found: {len(non_cluster_keys)}")
        for key in non_cluster_keys[:10]:  # Show first 10
            print(f"    - {key}")
    else:
        print("✅ ALL keys use cluster-aware format!")

    # Check specific key patterns
    print("\nKey pattern analysis:")
    patterns = {
        "Workflow data": "{shard:*}:workflow:data:*",
        "Task status": "{shard:*}:task:status:*",
        "Streams": "{shard:*}:*",
        "Worker registry": "{shard:0}:worker:*",
        "Signal waiters": "{shard:*}:signal:*",
        "Timer pending": "{shard:0}:timers:pending"
    }

    for name, pattern in patterns.items():
        cursor = b"0"
        count = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern.encode())
            count += len(keys)
            if cursor == b"0":
                break
        if count > 0:
            print(f"  ✅ {name}: {count} keys found")

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

    # Final verdict
    print("\n" + "=" * 80)
    if cluster_keys > 0 and len(non_cluster_keys) == 0:
        print("🎉 SUCCESS: All components properly use Redis Cluster keys!")
    else:
        print(f"⚠️  PARTIAL: {cluster_keys} cluster keys, {len(non_cluster_keys)} non-cluster keys")
    print("=" * 80)

    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(main())