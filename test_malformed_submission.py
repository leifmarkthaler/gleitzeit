#!/usr/bin/env python3
"""Test submitting a malformed workflow"""

import asyncio
import time
import sys
import uuid

sys.path.insert(0, 'src')

import redis.asyncio as aioredis
from gleitzeit.core.sharding import default_sharding


async def submit_malformed_workflow():
    """Submit a malformed workflow and observe handling"""
    redis = await aioredis.from_url('redis://localhost:6379')

    # Submit the malformed workflow
    workflow_id = f"malformed_{int(time.time() * 1000)}"
    shard = default_sharding.get_shard(workflow_id)

    print(f"Submitting malformed workflow: {workflow_id}")
    print(f"Target shard: {shard}")

    # Submit to workflow:load stream
    stream_key = default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id)

    await redis.xadd(
        stream_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"path": b"test_malformed_workflow.yaml",
            b"format": b"yaml"
        }
    )

    print(f"✓ Workflow submitted to stream: {stream_key}")

    # Monitor for 10 seconds
    print("\nMonitoring workflow processing...")
    start_time = time.time()

    while time.time() - start_time < 10:
        # Check workflow status
        status_key = default_sharding.get_workflow_key('status', workflow_id)
        status = await redis.hget(status_key.encode(), b'status')

        if status:
            print(f"  Workflow status: {status.decode()}")

        # Check workflow data for error
        data_key = default_sharding.get_workflow_key('data', workflow_id)
        error = await redis.hget(data_key.encode(), b'error')

        if error:
            print(f"  ERROR: {error.decode()}")
            break

        # Check failed stream
        failed_stream = default_sharding.get_global_key('workflow:load:failed')
        try:
            msgs = await redis.xread({failed_stream.encode(): b'$'}, count=10, block=100)
            for stream, messages in msgs:
                for msg_id, data in messages:
                    if data.get(b'workflow_id', b'').decode() == workflow_id:
                        print(f"  Found in failed stream!")
                        print(f"  Error: {data.get(b'error', b'').decode()}")
                        print(f"  Error type: {data.get(b'error_type', b'').decode()}")
                        await redis.aclose()
                        return
        except:
            pass

        await asyncio.sleep(1)

    print("\n✓ Test completed")
    await redis.aclose()


if __name__ == "__main__":
    print("Testing malformed workflow submission...")
    print("-" * 40)

    asyncio.run(submit_malformed_workflow())