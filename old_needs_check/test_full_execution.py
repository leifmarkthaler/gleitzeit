#!/usr/bin/env python
"""Test full workflow execution with actual workers"""

import asyncio
import logging
import sys
from pathlib import Path
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.task_execution_worker_v2 import TaskExecutionWorkerV2
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.sharding import default_sharding
import redis.asyncio as aioredis

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def submit_test_workflow(redis):
    """Submit a simple test workflow"""
    import uuid
    workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"

    # Simple workflow that should actually execute and return values
    workflow = {
        'name': 'test-execution',
        'tasks': [
            {
                'id': 'task1',
                'type': 'python',
                'code': '''
import json
def calculate():
    x = 10
    y = 20
    return {"sum": x + y, "product": x * y, "message": "Task 1 calculations complete"}
result = calculate()
print(json.dumps(result))
                ''',
                'function': 'exec'
            },
            {
                'id': 'task2',
                'type': 'python',
                'code': '''
import json
import datetime
import sys

# The task1 result should be passed as an argument
print(f"Debug: sys.argv = {sys.argv}", file=sys.stderr)
if len(sys.argv) > 1:
    print(f"Debug: sys.argv[1] = {repr(sys.argv[1])}", file=sys.stderr)
    task1_result = json.loads(sys.argv[1])
else:
    task1_result = {}

def process_data(input_data):
    # Use the sum and product from task1
    sum_value = input_data.get('sum', 0)
    product_value = input_data.get('product', 0)

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "values": [1, 2, 3, 4, 5],
        "calculated_total": sum(range(1, 6)) * sum_value,  # Use task1's sum
        "scaled_product": product_value * 2,  # Use task1's product
        "status": "processed",
        "metadata": {
            "task": "task2",
            "version": "1.0",
            "input_from_task1": input_data
        }
    }

result = process_data(task1_result)
print(json.dumps(result))
                ''',
                'function': 'exec',
                'dependencies': ['task1'],
                'args': ['${task1.result}']  # Pass task1's result as argument
            },
            {
                'id': 'task3',
                'type': 'shell',
                'command': 'echo "Task 3 complete: $(date)"',
                'dependencies': ['task1', 'task2']
            }
        ]
    }

    shard = default_sharding.get_shard(workflow_id)

    # Submit directly as inline workflow using cluster-aware key
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:load".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(workflow).encode(),
            b"format": b"inline"
        }
    )

    print(f"✅ Submitted workflow {workflow_id} to shard {shard}")
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
        for task_id in ['task1', 'task2', 'task3']:
            task_status = await redis.hgetall(f"task:status:{task_id}".encode())
            if task_status:
                status = task_status.get(b"status", b"unknown").decode()
                result = task_status.get(b"result", b"").decode()
                error = task_status.get(b"error", b"").decode()

                if status == "completed":
                    print(f"  {task_id}: ✅ {status} - Result: {result[:50] if result else 'None'}")
                elif status == "failed":
                    print(f"  {task_id}: ❌ {status} - Error: {error[:100]}")
                else:
                    print(f"  {task_id}: ⏳ {status}")
    else:
        print(f"No status found for workflow {workflow_id}")

async def run_full_test():
    """Run full workflow execution test"""
    print("\n🚀 Testing Full Workflow Execution in Gleitzeit 0.0.7\n")

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379')

    # Submit workflow
    workflow_id, shard = await submit_test_workflow(redis)

    print(f"\n🔧 Starting workers for shard {shard}...")

    # Create workers for the specific shard
    workers = []

    # Workflow Loader
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="loader-test",
        consumer_group="loader-group-test",
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
        worker_id="dep-test",
        consumer_group="dep-group-test",
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
        worker_id="exec-test",
        consumer_group="exec-group-test",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    exec_worker = TaskExecutionWorkerV2(exec_config)
    await exec_worker.initialize()
    workers.append(exec_worker)
    print("  ✅ TaskExecutionWorkerV2 ready")

    print("\n⏳ Processing workflow for 10 seconds...")

    # Create tasks for all workers
    tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.run())
        tasks.append(task)

    # Let them process
    await asyncio.sleep(10)

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
        print("\n🎉 SUCCESS! Workflow completed successfully!")
    else:
        print(f"\n⚠️  Workflow status: {final_status.decode() if final_status else 'not found'}")

    await redis.aclose()
    print("\n✅ Test complete!")

if __name__ == "__main__":
    asyncio.run(run_full_test())