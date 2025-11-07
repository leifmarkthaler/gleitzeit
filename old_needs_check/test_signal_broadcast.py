#!/usr/bin/env python
"""Test signal broadcast functionality"""

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
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.workers.signal_worker import SignalWorker
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.sharding import default_sharding
import redis.asyncio as aioredis

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def create_broadcast_workflows(redis):
    """Create a broadcaster and multiple listener workflows"""
    import uuid

    # Create multiple listener workflows
    listener_ids = []
    for i in range(3):
        listener_id = f"listener_{uuid.uuid4().hex[:8]}"
        listener_ids.append(listener_id)

        listener = {
            'name': f'listener-{i+1}',
            'tasks': [
                {
                    'id': 'wait_broadcast',
                    'type': 'signal',
                    'signal_action': 'wait',
                    'signal_name': 'system-announcement',
                    'timeout': 60
                },
                {
                    'id': 'process_broadcast',
                    'type': 'python',
                    'code': f'''
print(f"Listener {i+1} received broadcast!")
result = {{"listener": {i+1}, "received": True}}
                    ''',
                    'dependencies': ['wait_broadcast']
                }
            ]
        }

        shard = default_sharding.get_shard(listener_id)
        await redis.xadd(
            f"workflow:load:{shard}".encode(),
            {
                b"workflow_id": listener_id.encode(),
                b"workflow": json.dumps(listener).encode(),
                b"format": b"inline"
            }
        )
        print(f"✅ Created listener workflow {i+1}: {listener_id}")

    # Create broadcaster workflow
    broadcaster_id = f"broadcaster_{uuid.uuid4().hex[:8]}"
    broadcaster = {
        'name': 'broadcaster',
        'tasks': [
            {
                'id': 'prepare_message',
                'type': 'python',
                'code': '''
import datetime
print("Preparing broadcast message...")
result = {"prepared": True, "time": datetime.datetime.now().isoformat()}
                '''
            },
            {
                'id': 'broadcast_signal',
                'type': 'signal',
                'signal_action': 'broadcast',  # System-wide broadcast
                'signal_name': 'system-announcement',
                'payload': {
                    'message': 'System-wide announcement!',
                    'priority': 'high',
                    'timestamp': datetime.utcnow().isoformat()
                },
                'dependencies': ['prepare_message']
            },
            {
                'id': 'confirm_broadcast',
                'type': 'python',
                'code': '''
print("Broadcast sent to all workflows!")
result = {"broadcast_complete": True}
                ''',
                'dependencies': ['broadcast_signal']
            }
        ]
    }

    shard = default_sharding.get_shard(broadcaster_id)
    await redis.xadd(
        f"workflow:load:{shard}".encode(),
        {
            b"workflow_id": broadcaster_id.encode(),
            b"workflow": json.dumps(broadcaster).encode(),
            b"format": b"inline"
        }
    )
    print(f"✅ Created broadcaster workflow: {broadcaster_id}")

    return broadcaster_id, listener_ids

async def check_workflow_status(redis, workflow_id, label=""):
    """Check the status of a workflow"""
    status_data = await redis.hgetall(f"workflow:status:{workflow_id}".encode())

    if status_data:
        status = status_data.get(b"status", b"unknown").decode()
        completed = status_data.get(b"completed_tasks", b"0").decode()
        total = status_data.get(b"total_tasks", b"0").decode()

        if status == "completed":
            print(f"  {label}{workflow_id}: ✅ {status} ({completed}/{total} tasks)")
        elif status == "failed":
            error = status_data.get(b"error", b"").decode()
            print(f"  {label}{workflow_id}: ❌ {status} - {error[:50]}")
        else:
            print(f"  {label}{workflow_id}: ⏳ {status} ({completed}/{total} tasks)")

        return status
    else:
        print(f"  {label}{workflow_id}: No status yet")
        return None

async def run_broadcast_test():
    """Test signal broadcast functionality"""
    print("\n🚀 Testing Signal Broadcast in Gleitzeit\n")
    print("This test demonstrates:")
    print("1. signal/send - sends to current or specific workflows")
    print("2. signal/broadcast - sends system-wide to all workflows")
    print("\n" + "=" * 60)

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379')

    # Create workflows
    broadcaster_id, listener_ids = await create_broadcast_workflows(redis)

    print(f"\n📊 Created 1 broadcaster and {len(listener_ids)} listeners")
    print("Broadcasting will send signal to ALL listening workflows\n")

    # Start workers for all shards
    workers = []
    shards = set()

    # Get all unique shards
    shards.add(default_sharding.get_shard(broadcaster_id))
    for listener_id in listener_ids:
        shards.add(default_sharding.get_shard(listener_id))

    print(f"🔧 Starting workers for {len(shards)} shard(s)...")

    for shard in shards:
        # Workflow Loader
        loader_config = WorkerConfig(
            worker_type="workflow_loader",
            worker_id=f"loader-broadcast-{shard}",
            shard=shard
        )
        loader = WorkflowLoaderWorkerV2(loader_config, redis)
        workers.append(asyncio.create_task(loader.start()))

        # Dependency Worker
        dep_config = WorkerConfig(
            worker_type="dependency",
            worker_id=f"dep-broadcast-{shard}",
            shard=shard
        )
        dep = DependencyWorker(dep_config, redis)
        workers.append(asyncio.create_task(dep.start()))

        # Task Execution Worker
        exec_config = WorkerConfig(
            worker_type="task_execution",
            worker_id=f"exec-broadcast-{shard}",
            shard=shard
        )
        exec_config.__dict__['enabled_task_types'] = ['signal', 'python']
        exec_worker = TaskExecutionWorker(exec_config, redis)
        workers.append(asyncio.create_task(exec_worker.start()))

        # Signal Worker
        signal_config = WorkerConfig(
            worker_type="signal",
            worker_id=f"signal-broadcast-{shard}",
            shard=shard
        )
        signal_worker = SignalWorker(signal_config, redis)
        workers.append(asyncio.create_task(signal_worker.start()))

    # Monitor progress
    print("\n📡 Monitoring broadcast progress...\n")

    all_completed = False
    for i in range(15):
        await asyncio.sleep(2)

        print(f"\n--- Check {i+1} ---")

        # Check broadcaster
        broadcaster_status = await check_workflow_status(redis, broadcaster_id, "Broadcaster: ")

        # Check listeners
        completed_listeners = 0
        for idx, listener_id in enumerate(listener_ids):
            status = await check_workflow_status(redis, listener_id, f"Listener {idx+1}: ")
            if status == "completed":
                completed_listeners += 1

        # Check if all completed
        if broadcaster_status == "completed" and completed_listeners == len(listener_ids):
            print(f"\n✅ SUCCESS! Broadcaster sent signal and all {len(listener_ids)} listeners received it!")
            all_completed = True
            break

    if not all_completed:
        print("\n⚠️  Test timed out - not all workflows completed")

    # Cleanup
    print("\n🧹 Cleaning up workers...")
    for worker in workers:
        worker.cancel()

    await redis.close()
    print("\n✨ Broadcast test complete!")

if __name__ == "__main__":
    asyncio.run(run_broadcast_test())