#!/usr/bin/env python
"""Test signal workflow execution"""

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
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def submit_signal_workflow(redis):
    """Submit a workflow with signal-based tasks"""
    import uuid
    workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"

    # Workflow with signal wait
    workflow = {
        'name': 'signal-test',
        'tasks': [
            {
                'id': 'task1',
                'type': 'python',
                'code': '''
import datetime
result = {"message": "Task 1 started", "time": datetime.datetime.now().isoformat()}
print(f"Task 1 executed at {result['time']}")
                '''
            },
            {
                'id': 'signal_wait',
                'type': 'signal',
                'signal_action': 'wait',
                'signal_name': 'test-signal',
                'timeout': 30,
                'dependencies': ['task1']
            },
            {
                'id': 'task2',
                'type': 'python',
                'code': '''
import datetime
result = {"message": "Task 2 after signal", "time": datetime.datetime.now().isoformat()}
print(f"Task 2 executed at {result['time']} (after signal)")
                ''',
                'dependencies': ['signal_wait']
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

    print(f"✅ Submitted signal workflow {workflow_id} to shard {shard}")
    return workflow_id, shard

async def send_signal(redis, workflow_id, signal_name, payload=None):
    """Send a signal to a workflow"""
    if payload is None:
        payload = {"data": "test signal payload"}

    # Create workflow signal stream key
    signal_stream = f"workflow:signals:{workflow_id}"

    # Send signal to workflow stream
    await redis.xadd(
        signal_stream.encode(),
        {
            b"signal": signal_name.encode(),
            b"payload": json.dumps(payload).encode(),
            b"timestamp": datetime.utcnow().isoformat().encode()
        }
    )

    print(f"📨 Sent signal '{signal_name}' to workflow {workflow_id}")

async def check_workflow_status(redis, workflow_id):
    """Check the status of a workflow"""
    status_data = await redis.hgetall(f"workflow:status:{workflow_id}".encode())

    if status_data:
        print(f"\n📊 Workflow Status for {workflow_id}:")
        for key, value in status_data.items():
            print(f"  {key.decode()}: {value.decode()}")

        # Check task statuses
        print("\n📋 Task Status:")
        for task_id in ['task1', 'signal_wait', 'task2']:
            task_status = await redis.hgetall(f"task:status:{task_id}".encode())
            if task_status:
                status = task_status.get(b"status", b"unknown").decode()
                if status == "completed":
                    print(f"  {task_id}: ✅ {status}")
                elif status == "failed":
                    error = task_status.get(b"error", b"").decode()
                    print(f"  {task_id}: ❌ {status} - {error[:100]}")
                elif status == "waiting":
                    print(f"  {task_id}: ⏳ {status} (waiting for signal)")
                else:
                    print(f"  {task_id}: ⏳ {status}")
            else:
                print(f"  {task_id}: No status")
    else:
        print(f"No status found for workflow {workflow_id}")

async def run_signal_test():
    """Run signal workflow test"""
    print("\n🚀 Testing Signal Workflow in Gleitzeit 0.0.7\n")

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379')

    # Submit workflow
    workflow_id, shard = await submit_signal_workflow(redis)

    print(f"\n🔧 Starting workers for shard {shard}...")

    # Create workers
    workers = []

    # Workflow Loader
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="loader-signal-test",
        consumer_group="loader-group-signal",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    loader = WorkflowLoaderWorkerV2(loader_config)
    await loader.initialize()
    workers.append(loader)
    print("  ✅ WorkflowLoaderWorkerV2 ready")

    # Dependency Worker
    dep_config = WorkerConfig(
        worker_type="dependency",
        worker_id="dep-signal-test",
        consumer_group="dep-group-signal",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    dep = DependencyWorker(dep_config)
    await dep.initialize()
    workers.append(dep)
    print("  ✅ DependencyWorker ready")

    # Task Execution Worker
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="exec-signal-test",
        consumer_group="exec-group-signal",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    exec_worker = TaskExecutionWorkerV2(exec_config)
    await exec_worker.initialize()
    workers.append(exec_worker)
    print("  ✅ TaskExecutionWorkerV2 ready")

    # Signal Worker
    signal_config = WorkerConfig(
        worker_type="signal",
        worker_id="signal-test",
        consumer_group="signal-group",
        redis_url="redis://localhost:6379",
        assigned_shards=list(range(16)),  # Signal worker handles all shards
        block_timeout=500
    )
    signal_worker = SignalWorker(signal_config)
    await signal_worker.initialize()
    workers.append(signal_worker)
    print("  ✅ SignalWorker ready (with leader election)")

    print(f"\n⏳ Processing workflow...")

    # Create tasks for all workers
    tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.run())
        tasks.append(task)

    # Track progress
    start_time = time.time()

    # Wait for workflow to reach signal wait state
    print("\n⏰ Waiting for workflow to reach signal wait state...")
    for i in range(5):
        await asyncio.sleep(1)
        await check_workflow_status(redis, workflow_id)

        # Check if signal_wait task is waiting
        signal_task_status = await redis.hget(f"task:status:signal_wait".encode(), b"status")
        if signal_task_status and signal_task_status.decode() == "waiting":
            print("\n✅ Signal task is waiting for signal!")
            break

    # Send the signal after a short delay
    await asyncio.sleep(2)
    print("\n📤 Sending signal to workflow...")
    await send_signal(redis, workflow_id, "test-signal", {"message": "Hello from test!"})

    # Wait for signal to be processed
    print("\n⏰ Waiting for signal to be processed...")
    for i in range(5):
        await asyncio.sleep(1)
        await check_workflow_status(redis, workflow_id)
        elapsed = time.time() - start_time
        print(f"\n⏱️  Elapsed: {elapsed:.1f}s")

        # Check if workflow completed
        workflow_status = await redis.hget(f"workflow:status:{workflow_id}".encode(), b"status")
        if workflow_status and workflow_status.decode() == "completed":
            print("\n✅ Workflow completed!")
            break

    print("\n🛑 Stopping workers...")

    # Stop workers
    for worker in workers:
        worker._running = False

    await asyncio.sleep(1)

    # Cancel tasks
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Check final status
    await check_workflow_status(redis, workflow_id)

    print("\n📈 Worker Statistics:")
    for worker in workers:
        print(f"  {worker.config.worker_id}: {worker.messages_processed} processed, {worker.messages_failed} failed")

    # Check if workflow completed
    final_status = await redis.hget(f"workflow:status:{workflow_id}".encode(), b"status")
    if final_status and final_status.decode() == "completed":
        print("\n🎉 SUCCESS! Signal workflow completed successfully!")

        # Check signal task result
        signal_task_result = await redis.hget(f"task:status:signal_wait".encode(), b"result")
        if signal_task_result:
            result = json.loads(signal_task_result.decode())
            print(f"\n📦 Signal task result: {json.dumps(result, indent=2)}")
    else:
        print(f"\n⚠️  Workflow status: {final_status.decode() if final_status else 'not found'}")

    await redis.aclose()
    print("\n✅ Test complete!")

if __name__ == "__main__":
    asyncio.run(run_signal_test())