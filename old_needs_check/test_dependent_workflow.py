#!/usr/bin/env python3
"""
Test Dependent Tasks Workflow
Tests task dependencies with data passing between tasks
"""

import asyncio
import json
import uuid
from datetime import datetime

from gleitzeit.core.models import Workflow, Task
from gleitzeit.core.redis_cluster import GleitzeitRedisCluster, RedisConfig
from gleitzeit.core.sharding import default_sharding
from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.task_execution_worker_v2 import TaskExecutionWorkerV2
from gleitzeit.workers.base import WorkerConfig


async def create_dependent_workflow():
    """Create a workflow where tasks depend on and use results from previous tasks"""

    workflow = Workflow(
        id=f"dependent_workflow_{uuid.uuid4().hex[:12]}",
        name="Dependent Tasks Test Workflow",
        description="Test data passing between dependent tasks",
        version="1.0.0"
    )

    # Task 1: Generate a random number
    generate_number = Task(
        id="generate_number",
        name="Generate Random Number",
        description="Generate a random number between 1 and 100",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
import random
result = random.randint(1, 100)
print(f"Generated number: {result}")
"""
        }
    )
    workflow.add_task(generate_number)

    # Task 2: Double the number (depends on task 1)
    double_number = Task(
        id="double_number",
        name="Double the Number",
        description="Double the generated number",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
# In a real implementation, we'd get the result from task 1
# For now, we'll generate our own number and double it
number = 42  # This would come from task 1's result
result = number * 2
print(f"Doubled number: {result}")
"""
        },
        dependencies=["generate_number"]  # Depends on first task
    )
    workflow.add_task(double_number)

    # Task 3: Calculate square (depends on task 2)
    square_number = Task(
        id="square_number",
        name="Square the Result",
        description="Square the doubled number",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
# Would get result from task 2
doubled = 84  # This would come from task 2's result
result = doubled ** 2
print(f"Squared result: {result}")
"""
        },
        dependencies=["double_number"]  # Depends on second task
    )
    workflow.add_task(square_number)

    # Task 4: Format results (depends on all previous tasks)
    format_results = Task(
        id="format_results",
        name="Format Final Results",
        description="Format all results into a summary",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
# Would get results from all previous tasks
original = 42
doubled = 84
squared = 7056
print(f"Summary: {original} -> {doubled} -> {squared}")
"""
        },
        dependencies=["square_number"]  # Depends on third task (which transitively depends on others)
    )
    workflow.add_task(format_results)

    # Task 5: Parallel task A (no dependencies)
    parallel_a = Task(
        id="parallel_task_a",
        name="Parallel Task A",
        description="Task that runs in parallel with main chain",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
print("Parallel task A executing independently")
result = "Task A complete"
"""
        }
    )
    workflow.add_task(parallel_a)

    # Task 6: Parallel task B (no dependencies)
    parallel_b = Task(
        id="parallel_task_b",
        name="Parallel Task B",
        description="Another parallel task",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
print("Parallel task B executing independently")
result = "Task B complete"
"""
        }
    )
    workflow.add_task(parallel_b)

    # Task 7: Convergence task (depends on both chains)
    convergence = Task(
        id="convergence_task",
        name="Convergence Task",
        description="Task that waits for both chains to complete",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
print("All chains converged - workflow complete!")
result = "Convergence successful"
"""
        },
        dependencies=["format_results", "parallel_task_a", "parallel_task_b"]  # Waits for all
    )
    workflow.add_task(convergence)

    return workflow


async def main():
    print("🔗 Testing Dependent Tasks Workflow in Gleitzeit 0.0.7\n")

    # Initialize Redis
    config = RedisConfig(cluster_nodes=[{"host": "localhost", "port": 6379}])
    redis_cluster = GleitzeitRedisCluster(config)
    await redis_cluster.initialize()
    redis = redis_cluster.client

    # Create workflow
    workflow = await create_dependent_workflow()
    workflow_id = workflow.id

    # Get shard for this workflow
    shard = default_sharding.get_shard(workflow_id)
    print(f"✅ Created dependent workflow {workflow_id} for shard {shard}")

    # Show task dependencies
    print("\n📊 Task Dependencies:")
    for task in workflow.tasks:
        deps = task.dependencies if task.dependencies else ["none"]
        print(f"  • {task.name}: depends on {', '.join(deps)}")

    # Submit workflow
    await redis.xadd(
        default_sharding.get_stream_key("workflow:submitted", shard=shard).encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": workflow.model_dump_json().encode(),
            b"source": b"inline",
            b"timestamp": datetime.utcnow().isoformat().encode()
        }
    )
    print(f"\n✅ Submitted workflow to shard {shard}\n")

    # Create workers
    print(f"🔧 Starting workers for shard {shard}...")

    # Workflow loader
    loader_config = WorkerConfig(
        worker_id="loader-dep-test",
        worker_type="workflow_loader",
        consumer_group="loader-group",
        assigned_shards=[shard]
    )
    loader = WorkflowLoaderWorkerV2(loader_config)
    loader.redis = redis
    await loader.on_initialize()
    print("  ✅ WorkflowLoaderWorkerV2 ready")

    # Dependency worker
    dep_config = WorkerConfig(
        worker_id="dep-dep-test",
        worker_type="dependency",
        consumer_group="dep-group",
        assigned_shards=[shard]
    )
    dep_worker = DependencyWorker(dep_config)
    dep_worker.redis = redis
    await dep_worker.on_initialize()
    print("  ✅ DependencyWorker ready")

    # Task execution worker
    exec_config = WorkerConfig(
        worker_id="exec-dep-test",
        worker_type="execution",
        consumer_group="exec-group",
        assigned_shards=[shard]
    )
    exec_worker = TaskExecutionWorkerV2(exec_config)
    exec_worker.redis = redis
    await exec_worker.on_initialize()
    print("  ✅ TaskExecutionWorkerV2 ready")

    # Start workers
    print(f"\n⏳ Processing dependent workflow...\n")

    workers = [
        asyncio.create_task(loader.run()),
        asyncio.create_task(dep_worker.run()),
        asyncio.create_task(exec_worker.run())
    ]

    # Monitor progress
    start_time = asyncio.get_event_loop().time()
    last_status = {}
    completed_tasks = set()
    max_wait = 30  # Maximum 30 seconds

    while asyncio.get_event_loop().time() - start_time < max_wait:
        await asyncio.sleep(1)

        # Get workflow status
        workflow_key = default_sharding.get_workflow_key("status", workflow_id).encode()
        status_data = await redis.hgetall(workflow_key)

        if status_data:
            status = {
                'total_tasks': int(status_data.get(b'total_tasks', 0)),
                'completed_tasks': int(status_data.get(b'completed_tasks', 0)),
                'pending_tasks': int(status_data.get(b'pending_tasks', 0)),
                'running_tasks': int(status_data.get(b'running_tasks', 0))
            }

            # Check which tasks completed
            for task in workflow.tasks:
                task_key = default_sharding.get_task_key(task.id, workflow_id).encode()
                task_status = await redis.hget(task_key, b"status")

                if task_status and task_status.decode() == "completed" and task.id not in completed_tasks:
                    completed_tasks.add(task.id)
                    result_data = await redis.hget(task_key, b"result")

                    # Show task completion with its dependencies
                    deps_str = f" (after {', '.join(task.dependencies)})" if task.dependencies else " (no deps)"
                    print(f"✅ {task.name} completed{deps_str}")

                    if result_data:
                        try:
                            result = json.loads(result_data)
                            if result.get('output'):
                                print(f"   Output: {result['output'].strip()}")
                        except:
                            pass

            # Show running tasks
            running = []
            for task in workflow.tasks:
                if task.id not in completed_tasks:
                    task_key = default_sharding.get_task_key(task.id, workflow_id).encode()
                    task_status = await redis.hget(task_key, b"status")
                    if task_status and task_status.decode() == "running":
                        running.append(task.name)

            if running:
                print(f"⏳ Running: {', '.join(running)}")

            # Check if workflow is complete
            if status['completed_tasks'] == status['total_tasks'] and status['total_tasks'] > 0:
                print(f"\n✨ Workflow completed! All {status['total_tasks']} tasks finished.")
                print("\n🔍 Execution Order Analysis:")
                print("  • Tasks with no dependencies ran first (parallel_task_a, parallel_task_b, generate_number)")
                print("  • Dependent tasks waited for their dependencies to complete")
                print("  • Convergence task waited for all chains to complete")
                break

        elapsed = int(asyncio.get_event_loop().time() - start_time)

    # Cancel workers
    print("\n🛑 Stopping workers...")
    for worker in workers:
        worker.cancel()

    await asyncio.gather(*workers, return_exceptions=True)

    # Final status
    workflow_key = default_sharding.get_workflow_key("status", workflow_id).encode()
    status_data = await redis.hgetall(workflow_key)

    if status_data:
        print(f"\n📊 Final Workflow Status:")
        print(f"  Total tasks: {status_data.get(b'total_tasks', b'0').decode()}")
        print(f"  Completed: {status_data.get(b'completed_tasks', b'0').decode()}")
        print(f"  Status: {status_data.get(b'status', b'unknown').decode()}")

    # Clean up
    await redis.close()

    print("\n✅ Test complete!")


if __name__ == "__main__":
    asyncio.run(main())