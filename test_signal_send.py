#!/usr/bin/env python
"""Test signal send functionality"""

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

async def submit_signal_send_workflow(redis):
    """Submit a workflow that sends and receives signals"""
    import uuid
    workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"

    # Workflow that sends a signal then waits for it
    workflow = {
        'name': 'signal-send-test',
        'tasks': [
            {
                'id': 'send_signal',
                'type': 'signal',
                'signal_action': 'send',
                'signal_name': 'test-signal',
                'payload': {
                    'message': 'Hello from signal sender!',
                    'timestamp': datetime.utcnow().isoformat()
                }
                # No target_workflows - will send to current workflow
            },
            {
                'id': 'wait_signal',
                'type': 'signal',
                'signal_action': 'wait',
                'signal_name': 'test-signal',
                'timeout': 30,
                'dependencies': ['send_signal']
            },
            {
                'id': 'process_result',
                'type': 'python',
                'code': '''
import json
# The signal payload should be available
print(f"Signal received! Processing complete.")
result = {"status": "completed", "signal_received": True}
                ''',
                'dependencies': ['wait_signal']
            }
        ]
    }

    shard = default_sharding.get_shard(workflow_id)

    # Submit workflow
    await redis.xadd(
        f"workflow:load:{shard}".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(workflow).encode(),
            b"format": b"inline"
        }
    )

    print(f"✅ Submitted signal send/receive workflow {workflow_id} to shard {shard}")
    return workflow_id, shard

async def submit_cross_workflow_signal(redis):
    """Submit two workflows - one sends signal, other receives"""
    import uuid

    # Receiver workflow
    receiver_id = f"workflow_{uuid.uuid4().hex[:12]}"
    receiver = {
        'name': 'signal-receiver',
        'tasks': [
            {
                'id': 'wait_external',
                'type': 'signal',
                'signal_action': 'wait',
                'signal_name': 'external-signal',
                'timeout': 60
            },
            {
                'id': 'process_external',
                'type': 'python',
                'code': '''
print("External signal received! Processing...")
result = {"status": "processed_external_signal"}
                ''',
                'dependencies': ['wait_external']
            }
        ]
    }

    # Sender workflow
    sender_id = f"workflow_{uuid.uuid4().hex[:12]}"
    sender = {
        'name': 'signal-sender',
        'tasks': [
            {
                'id': 'send_to_other',
                'type': 'signal',
                'signal_action': 'send',
                'signal_name': 'external-signal',
                'target_workflows': [receiver_id],  # Send to specific workflow
                'payload': {
                    'source': 'sender_workflow',
                    'data': 'Cross-workflow communication!'
                }
            },
            {
                'id': 'confirm_sent',
                'type': 'python',
                'code': f'''
print("Signal sent to workflow {receiver_id}")
result = {{"signal_sent_to": "{receiver_id}"}}
                ''',
                'dependencies': ['send_to_other']
            }
        ]
    }

    # Submit receiver first
    shard_r = default_sharding.get_shard(receiver_id)
    await redis.xadd(
        f"workflow:load:{shard_r}".encode(),
        {
            b"workflow_id": receiver_id.encode(),
            b"workflow": json.dumps(receiver).encode(),
            b"format": b"inline"
        }
    )
    print(f"✅ Submitted receiver workflow {receiver_id}")

    # Submit sender
    shard_s = default_sharding.get_shard(sender_id)
    await redis.xadd(
        f"workflow:load:{shard_s}".encode(),
        {
            b"workflow_id": sender_id.encode(),
            b"workflow": json.dumps(sender).encode(),
            b"format": b"inline"
        }
    )
    print(f"✅ Submitted sender workflow {sender_id}")

    return receiver_id, sender_id

async def check_workflow_status(redis, workflow_id):
    """Check the status of a workflow"""
    status_data = await redis.hgetall(f"workflow:status:{workflow_id}".encode())

    if status_data:
        status = status_data.get(b"status", b"unknown").decode()
        if status == "completed":
            print(f"  {workflow_id}: ✅ {status}")
        elif status == "failed":
            error = status_data.get(b"error", b"").decode()
            print(f"  {workflow_id}: ❌ {status} - {error[:100]}")
        else:
            print(f"  {workflow_id}: ⏳ {status}")

        # Check for completed tasks count
        completed = status_data.get(b"completed_tasks", b"0").decode()
        total = status_data.get(b"total_tasks", b"0").decode()
        print(f"    Progress: {completed}/{total} tasks")
    else:
        print(f"  {workflow_id}: No status yet")

async def run_signal_send_test():
    """Run signal send/receive tests"""
    print("\n🚀 Testing Signal Send/Receive in Gleitzeit\n")

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379')

    # Test 1: Same workflow signal send/receive
    print("=" * 60)
    print("TEST 1: Same Workflow Signal Send/Receive")
    print("=" * 60)

    workflow_id, shard = await submit_signal_send_workflow(redis)

    print(f"\n🔧 Starting workers...")

    # Create workers
    workers = []

    # Workflow Loader
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="loader-signal-send-test",
        shard=shard
    )
    loader = WorkflowLoaderWorkerV2(loader_config, redis)
    workers.append(asyncio.create_task(loader.start()))

    # Dependency Worker
    dep_config = WorkerConfig(
        worker_type="dependency",
        worker_id="dep-signal-send-test",
        shard=shard
    )
    dep = DependencyWorker(dep_config, redis)
    workers.append(asyncio.create_task(dep.start()))

    # Task Execution Worker with signal handler enabled
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="exec-signal-send-test",
        shard=shard
    )
    exec_config.__dict__['enabled_task_types'] = ['signal', 'python']
    exec_worker = TaskExecutionWorker(exec_config, redis)
    workers.append(asyncio.create_task(exec_worker.start()))

    # Signal Worker
    signal_config = WorkerConfig(
        worker_type="signal",
        worker_id="signal-send-test",
        shard=shard
    )
    signal_worker = SignalWorker(signal_config, redis)
    workers.append(asyncio.create_task(signal_worker.start()))

    # Monitor progress
    print("\n📊 Monitoring workflow progress...")
    for _ in range(10):
        await asyncio.sleep(2)
        await check_workflow_status(redis, workflow_id)

    # Test 2: Cross-workflow signal communication
    print("\n" + "=" * 60)
    print("TEST 2: Cross-Workflow Signal Communication")
    print("=" * 60)

    receiver_id, sender_id = await submit_cross_workflow_signal(redis)

    print("\n📊 Monitoring cross-workflow communication...")
    for _ in range(10):
        await asyncio.sleep(2)
        print("\nReceiver workflow:")
        await check_workflow_status(redis, receiver_id)
        print("\nSender workflow:")
        await check_workflow_status(redis, sender_id)

        # Check if both completed
        receiver_status = await redis.hget(f"workflow:status:{receiver_id}".encode(), b"status")
        sender_status = await redis.hget(f"workflow:status:{sender_id}".encode(), b"status")

        if receiver_status and sender_status:
            if receiver_status.decode() == "completed" and sender_status.decode() == "completed":
                print("\n✅ Both workflows completed successfully!")
                break

    # Cleanup
    print("\n🧹 Cleaning up workers...")
    for worker in workers:
        worker.cancel()

    await redis.close()
    print("\n✨ Signal send/receive test complete!")

if __name__ == "__main__":
    asyncio.run(run_signal_send_test())