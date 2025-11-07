#!/usr/bin/env python3
"""Test complete workflow execution"""

import asyncio
import time
import sys
import json
import yaml

sys.path.insert(0, 'src')

import redis.asyncio as aioredis
from gleitzeit.core.sharding import default_sharding


async def monitor_workflow():
    """Submit and monitor a workflow"""
    redis = await aioredis.from_url('redis://localhost:6379')

    # Submit a new workflow
    workflow_id = f"test_wf_{int(time.time() * 1000)}"
    shard = default_sharding.get_shard(workflow_id)

    print(f"Submitting workflow: {workflow_id}")
    print(f"Target shard: {shard}")

    # Load workflow file
    with open('test_basic_workflow.yaml', 'r') as f:
        workflow_data = yaml.safe_load(f)

    # Submit to workflow:load stream
    stream_key = default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id)

    await redis.xadd(
        stream_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": yaml.dump(workflow_data).encode(),
            b"source": b"test_script"
        }
    )

    print(f"✓ Workflow submitted to stream: {stream_key}")

    # Monitor for 30 seconds
    print("\nMonitoring workflow execution...")
    start_time = time.time()

    while time.time() - start_time < 30:
        # Check workflow status
        status_key = default_sharding.get_workflow_key('status', workflow_id)
        status = await redis.hget(status_key.encode(), b'status')

        if status:
            print(f"  Workflow status: {status.decode()}")

            # Check task statuses
            task_pattern = f"{{shard:{shard}}}:task:status:*"
            cursor = b"0"
            while cursor:
                cursor, keys = await redis.scan(
                    cursor=cursor,
                    match=task_pattern.encode(),
                    count=10
                )

                for key in keys:
                    task_status = await redis.hget(key, b'status')
                    if task_status:
                        task_id = key.decode().split(':')[-1]
                        print(f"    Task {task_id}: {task_status.decode()}")

                if cursor == b"0":
                    break

        # Check if workflow completed
        completed_stream = default_sharding.get_stream_key('workflow:completed', workflow_id=workflow_id)
        try:
            msgs = await redis.xread({completed_stream.encode(): b'0'}, count=1, block=100)
            if msgs:
                print("\n✅ WORKFLOW COMPLETED!")
                for stream, messages in msgs:
                    for msg_id, data in messages:
                        if b'result' in data:
                            result = json.loads(data[b'result'].decode())
                            print(f"Result: {json.dumps(result, indent=2)}")
                break
        except:
            pass

        await asyncio.sleep(2)

    else:
        print("\n⏱️  Timeout - workflow did not complete in 30 seconds")

        # Check what's in the stream
        msgs = await redis.xread({stream_key.encode(): b'0'}, count=10)
        if msgs:
            print(f"Workflow still in load stream: {stream_key}")

    await redis.aclose()


if __name__ == "__main__":
    # First, ensure orchestrator is running
    print("Starting workflow execution test...")
    print("Make sure orchestrator is running!")
    print("-" * 40)

    asyncio.run(monitor_workflow())