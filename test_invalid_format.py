#!/usr/bin/env python3
"""Test submitting workflows with various format errors"""

import asyncio
import time
import sys

sys.path.insert(0, 'src')

import redis.asyncio as aioredis
from gleitzeit.core.sharding import default_sharding


async def test_format_errors():
    """Test various format errors"""
    redis = await aioredis.from_url('redis://localhost:6379')

    tests = [
        {
            "name": "Invalid JSON file",
            "workflow_id": f"invalid_json_{int(time.time() * 1000)}",
            "path": "test_invalid_json.json",
            "format": "json"
        },
        {
            "name": "Non-existent file",
            "workflow_id": f"missing_file_{int(time.time() * 1000)}",
            "path": "nonexistent.yaml",
            "format": "yaml"
        },
        {
            "name": "Invalid inline content",
            "workflow_id": f"invalid_inline_{int(time.time() * 1000)}",
            "workflow": "{{invalid json and yaml}}",
            "format": None
        },
        {
            "name": "Empty workflow",
            "workflow_id": f"empty_{int(time.time() * 1000)}",
            "workflow": "{}",
            "format": None
        }
    ]

    for test in tests:
        print(f"\n{'='*50}")
        print(f"Testing: {test['name']}")
        print(f"Workflow ID: {test['workflow_id']}")

        # Submit to workflow:load stream
        stream_key = default_sharding.get_stream_key("workflow:load", workflow_id=test['workflow_id'])

        # Build message
        msg_data = {b"workflow_id": test['workflow_id'].encode()}

        if 'path' in test:
            msg_data[b"path"] = test['path'].encode()
        if 'workflow' in test:
            msg_data[b"workflow"] = test['workflow'].encode()
        if test.get('format'):
            msg_data[b"format"] = test['format'].encode()

        await redis.xadd(stream_key.encode(), msg_data)
        print(f"Submitted to: {stream_key}")

        # Wait and check for errors
        await asyncio.sleep(2)

        # Check workflow data for error
        data_key = default_sharding.get_workflow_key('data', test['workflow_id'])
        error = await redis.hget(data_key.encode(), b'error')
        status = await redis.hget(data_key.encode(), b'status')

        if error:
            print(f"✓ Error captured: {error.decode()[:100]}...")
        if status:
            print(f"  Status: {status.decode()}")

        # Check failed stream
        failed_stream = default_sharding.get_global_key('workflow:load:failed')
        try:
            msgs = await redis.xrange(failed_stream.encode(), b'-', b'+', count=100)
            for msg_id, data in msgs:
                if data.get(b'workflow_id', b'').decode() == test['workflow_id']:
                    error_type = data.get(b'error_type', b'').decode()
                    if error_type:
                        print(f"  Error type: {error_type}")
                    break
        except:
            pass

    await redis.aclose()
    print(f"\n{'='*50}")
    print("All error handling tests completed")


if __name__ == "__main__":
    print("Testing workflow format error handling...")
    asyncio.run(test_format_errors())