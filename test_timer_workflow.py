#!/usr/bin/env python
"""Test timer workflow execution"""

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
from gleitzeit.workers.timer_worker import TimerWorker
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.sharding import default_sharding
import redis.asyncio as aioredis

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def submit_timer_workflow(redis):
    """Submit a workflow with timer-based tasks"""
    import uuid
    workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"

    # Workflow with timer delay
    workflow = {
        'name': 'timer-test',
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
                'id': 'wait_task',
                'type': 'timer',
                'timer_type': 'delay',
                'delay': 3,  # 3 second delay
                'dependencies': ['task1']
            },
            {
                'id': 'task2',
                'type': 'python',
                'code': '''
import datetime
result = {"message": "Task 2 after timer", "time": datetime.datetime.now().isoformat()}
print(f"Task 2 executed at {result['time']} (after timer)")
                ''',
                'dependencies': ['wait_task']
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

    print(f"✅ Submitted timer workflow {workflow_id} to shard {shard}")
    return workflow_id, shard

async def check_workflow_status(redis, workflow_id):
    """Check the status of a workflow"""
    shard = default_sharding.get_shard(workflow_id)
    status_data = await redis.hgetall(f"{{shard:{shard}}}:workflow:status:{workflow_id}".encode())

    if status_data:
        print(f"\n📊 Workflow Status for {workflow_id}:")
        for key, value in status_data.items():
            print(f"  {key.decode()}: {value.decode()}")

        # Check task statuses
        print("\n📋 Task Status:")
        for task_id in ['task1', 'wait_task', 'task2']:
            task_status = await redis.hgetall(f"{{shard:{shard}}}:task:status:{task_id}".encode())
            if task_status:
                status = task_status.get(b"status", b"unknown").decode()
                if status == "completed":
                    print(f"  {task_id}: ✅ {status}")
                elif status == "failed":
                    error = task_status.get(b"error", b"").decode()
                    print(f"  {task_id}: ❌ {status} - {error[:100]}")
                else:
                    print(f"  {task_id}: ⏳ {status}")
            else:
                print(f"  {task_id}: No status")
    else:
        print(f"No status found for workflow {workflow_id}")

async def run_timer_test():
    """Run timer workflow test"""
    print("\n🚀 Testing Timer Workflow in Gleitzeit 0.0.7\n")

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379')

    # Submit workflow
    workflow_id, shard = await submit_timer_workflow(redis)

    print(f"\n🔧 Starting workers for shard {shard}...")

    # Create workers
    workers = []

    # Workflow Loader
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="loader-timer-test",
        consumer_group="loader-group-timer",
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
        worker_id="dep-timer-test",
        consumer_group="dep-group-timer",
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
        worker_id="exec-timer-test",
        consumer_group="exec-group-timer",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    exec_worker = TaskExecutionWorkerV2(exec_config)
    await exec_worker.initialize()
    workers.append(exec_worker)
    print("  ✅ TaskExecutionWorkerV2 ready")

    # Timer Worker
    timer_config = WorkerConfig(
        worker_type="timer",
        worker_id="timer-test",
        consumer_group="timer-group",
        redis_url="redis://localhost:6379",
        assigned_shards=list(range(16)),  # Timer worker handles all shards
        block_timeout=500
    )
    timer_worker = TimerWorker(timer_config)
    await timer_worker.initialize()
    workers.append(timer_worker)
    print("  ✅ TimerWorker ready (with leader election)")

    print(f"\n⏳ Processing workflow for 10 seconds (includes 3 second timer delay)...")

    # Create tasks for all workers
    tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.run())
        tasks.append(task)

    # Track progress
    start_time = time.time()
    for i in range(10):
        await asyncio.sleep(1)
        await check_workflow_status(redis, workflow_id)
        elapsed = time.time() - start_time
        print(f"\n⏱️  Elapsed: {elapsed:.1f}s")

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
        print("\n🎉 SUCCESS! Timer workflow completed successfully!")

        # Check timing
        task1_status = await redis.hget(f"task:status:task1".encode(), b"completed_at")
        task2_status = await redis.hget(f"task:status:task2".encode(), b"completed_at")

        if task1_status and task2_status:
            task1_time = datetime.fromisoformat(task1_status.decode())
            task2_time = datetime.fromisoformat(task2_status.decode())
            delay = (task2_time - task1_time).total_seconds()
            print(f"⏱️  Actual delay between task1 and task2: {delay:.2f} seconds")
    else:
        print(f"\n⚠️  Workflow status: {final_status.decode() if final_status else 'not found'}")

    await redis.aclose()
    print("\n✅ Test complete!")

if __name__ == "__main__":
    asyncio.run(run_timer_test())