#!/usr/bin/env python3
"""Test workflow with runtime failures"""

import asyncio
import time
import sys
import json

sys.path.insert(0, 'src')

import redis.asyncio as aioredis
from gleitzeit.core.sharding import default_sharding


async def test_runtime_failure():
    """Submit and monitor a workflow with runtime failures"""
    redis = await aioredis.from_url('redis://localhost:6379')

    workflow_id = f"runtime_error_{int(time.time() * 1000)}"
    shard = default_sharding.get_shard(workflow_id)

    print(f"Submitting workflow with runtime error: {workflow_id}")
    print(f"Target shard: {shard}")

    # Submit to workflow:load stream
    stream_key = default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id)

    await redis.xadd(
        stream_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"path": b"test_runtime_error.yaml",
            b"format": b"yaml"
        }
    )

    print(f"✓ Workflow submitted to stream: {stream_key}")

    # Monitor for 20 seconds
    print("\nMonitoring workflow execution...")
    start_time = time.time()
    last_status = None

    while time.time() - start_time < 20:
        # Check workflow status
        status_key = default_sharding.get_workflow_key('status', workflow_id)
        status_data = await redis.hgetall(status_key.encode())

        if status_data:
            status = status_data.get(b'status', b'').decode()
            if status != last_status:
                print(f"\nWorkflow status: {status}")
                last_status = status

            # Check task statuses
            for i in range(1, 4):
                task_id = f"task{i}"
                task_key = f"{{shard:{shard}}}:task:status:{task_id}"
                task_data = await redis.hgetall(task_key.encode())

                if task_data:
                    task_status = task_data.get(b'status', b'').decode()
                    print(f"  Task {task_id}: {task_status}")

                    # Check for error details
                    if task_status == 'failed':
                        error = task_data.get(b'error', b'').decode()
                        if error:
                            print(f"    Error: {error[:100]}...")

            # Check if workflow failed
            if status in ['failed', 'completed']:
                if status == 'failed':
                    error = status_data.get(b'error', b'').decode()
                    if error:
                        print(f"\nWorkflow error: {error}")
                break

        await asyncio.sleep(2)

    # Check final results
    print("\n" + "="*50)
    print("Final Check:")

    # Check dead letter queue
    dlq_pattern = f"{{shard:{shard}}}:dlq:*"
    cursor = b"0"
    dlq_found = False

    while cursor:
        cursor, keys = await redis.scan(
            cursor=cursor,
            match=dlq_pattern.encode(),
            count=10
        )

        for key in keys:
            msgs = await redis.xrange(key, b'-', b'+')
            for msg_id, data in msgs:
                if data.get(b'workflow_id', b'').decode() == workflow_id:
                    print(f"Found in DLQ: {key.decode()}")
                    dlq_found = True

        if cursor == b"0":
            break

    if not dlq_found:
        print("No messages in dead letter queue")

    await redis.aclose()
    print("\n✓ Test completed")


if __name__ == "__main__":
    print("Testing workflow with runtime failures...")
    print("-" * 40)

    asyncio.run(test_runtime_failure())