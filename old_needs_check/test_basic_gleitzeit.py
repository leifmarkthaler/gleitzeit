#!/usr/bin/env python3
"""
Test script to verify basic Gleitzeit functionality.
This submits a workflow and monitors its execution.
"""

import asyncio
import json
import yaml
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, 'src')

import redis.asyncio as aioredis
from gleitzeit.core.sharding import default_sharding


async def submit_workflow(redis, workflow_path):
    """Submit a workflow for execution"""

    # Load workflow
    with open(workflow_path, 'r') as f:
        workflow_data = yaml.safe_load(f)

    # Generate workflow ID
    workflow_id = f"wf_{int(time.time() * 1000)}"

    print(f"📤 Submitting workflow: {workflow_id}")
    print(f"   Name: {workflow_data['name']}")
    print(f"   Tasks: {len(workflow_data.get('tasks', []))}")

    # Submit to workflow:load stream
    stream_key = default_sharding.get_global_key("workflow:load")

    await redis.xadd(
        stream_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": yaml.dump(workflow_data).encode(),
            b"source": b"test_script",
            b"timestamp": str(time.time()).encode()
        }
    )

    print(f"✅ Workflow submitted: {workflow_id}")
    return workflow_id


async def monitor_workflow(redis, workflow_id, timeout=30):
    """Monitor workflow execution"""

    print(f"\n📊 Monitoring workflow: {workflow_id}")

    start_time = time.time()
    completed_tasks = set()
    failed_tasks = set()

    while time.time() - start_time < timeout:
        # Check task completion events
        completion_stream = default_sharding.get_global_key("task:completed")

        # Read recent events
        events = await redis.xread(
            {completion_stream.encode(): b"0"},
            count=100,
            block=1000
        )

        for stream, messages in events:
            for msg_id, data in messages:
                if b"workflow_id" in data and data[b"workflow_id"].decode() == workflow_id:
                    task_id = data.get(b"task_id", b"unknown").decode()
                    if task_id not in completed_tasks:
                        completed_tasks.add(task_id)
                        print(f"   ✓ Task completed: {task_id}")

        # Check failure events
        failure_stream = default_sharding.get_global_key("task:failed")

        failure_events = await redis.xread(
            {failure_stream.encode(): b"0"},
            count=100,
            block=1000
        )

        for stream, messages in failure_events:
            for msg_id, data in messages:
                if b"workflow_id" in data and data[b"workflow_id"].decode() == workflow_id:
                    task_id = data.get(b"task_id", b"unknown").decode()
                    error = data.get(b"error", b"unknown error").decode()
                    if task_id not in failed_tasks:
                        failed_tasks.add(task_id)
                        print(f"   ✗ Task failed: {task_id} - {error}")

        # Check if all tasks completed
        if len(completed_tasks) >= 3:  # We expect 3 tasks
            print(f"\n🎉 Workflow completed successfully!")
            print(f"   Completed tasks: {completed_tasks}")
            return True

        if failed_tasks:
            print(f"\n❌ Workflow failed!")
            print(f"   Failed tasks: {failed_tasks}")
            return False

        await asyncio.sleep(1)

    print(f"\n⏱️  Timeout waiting for workflow completion")
    print(f"   Completed tasks: {completed_tasks}")
    return False


async def check_workers_status(redis):
    """Check if workers are healthy"""

    print("\n🔍 Checking worker status...")

    # Check heartbeats
    pattern = "gleitzeit:worker:*:heartbeat"
    cursor = b"0"
    active_workers = []

    while cursor:
        cursor, keys = await redis.scan(
            cursor=cursor,
            match=pattern.encode(),
            count=100
        )

        for key in keys:
            ttl = await redis.ttl(key)
            if ttl > 0:
                worker_id = key.decode().split(":")[2]
                active_workers.append(worker_id)

        if cursor == b"0":
            break

    if active_workers:
        print(f"   ✓ {len(active_workers)} active workers found")
        for worker in active_workers[:5]:  # Show first 5
            print(f"      - {worker}")
        if len(active_workers) > 5:
            print(f"      ... and {len(active_workers) - 5} more")
    else:
        print("   ⚠️  No active workers found")
        print("   Please start the orchestrator with:")
        print("   python -m gleitzeit.orchestrator.component_orchestrator basic_config.yaml")

    return len(active_workers) > 0


async def main():
    """Main test function"""

    print("=" * 60)
    print("GLEITZEIT BASIC FUNCTIONALITY TEST")
    print("=" * 60)

    # Connect to Redis
    redis = await aioredis.from_url("redis://localhost:6379")

    try:
        # Check Redis connectivity
        pong = await redis.ping()
        print(f"✅ Redis connected: {pong}")

        # Check for active workers
        has_workers = await check_workers_status(redis)

        if not has_workers:
            print("\n⚠️  No workers are running!")
            print("\nTo start workers, run in another terminal:")
            print("  python -m gleitzeit.orchestrator.component_orchestrator basic_config.yaml")
            print("\nOr start individual workers with:")
            print("  gleitzeit worker start --config basic_config.yaml")
            return

        # Submit test workflow
        workflow_path = "test_basic_workflow.yaml"

        if not Path(workflow_path).exists():
            print(f"\n❌ Workflow file not found: {workflow_path}")
            return

        workflow_id = await submit_workflow(redis, workflow_path)

        # Monitor execution
        success = await monitor_workflow(redis, workflow_id)

        if success:
            print("\n✅ BASIC FUNCTIONALITY TEST PASSED")
        else:
            print("\n❌ BASIC FUNCTIONALITY TEST FAILED")

    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())