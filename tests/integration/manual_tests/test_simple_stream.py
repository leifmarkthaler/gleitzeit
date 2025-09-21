#!/usr/bin/env python
"""Simple test to check if streams are working."""

import asyncio
import os

# Enable streams
os.environ["GLEITZEIT_STREAM_MODE"] = "enabled"
os.environ["GLEITZEIT_STREAM_PERCENTAGE"] = "100"

async def main():
    from gleitzeit.client import GleitzeitClient
    
    # Create and initialize client
    client = GleitzeitClient(host="localhost", port=8007)
    await client.initialize()
    
    # Simple workflow definition
    workflow_def = {
        "name": "Test Stream Processing",
        "description": "Simple test of Redis Streams",
        "timeout": 30,
        "tasks": [
            {
                "name": "hello_task",
                "protocol": "python/v1",
                "method": "python/execute_code",
                "params": {
                    "code": "print('Hello from Redis Streams!'); result = 42; result"
                }
            }
        ]
    }
    
    print("📋 Submitting workflow...")
    workflow_id = await client.submit_workflow(workflow_def)
    print(f"📊 Workflow ID: {workflow_id}")
    
    print("⏳ Waiting for completion...")
    await asyncio.sleep(3)
    
    # Get workflow status
    status = await client.get_workflow(workflow_id)
    print(f"✅ Status: {status}")

if __name__ == "__main__":
    asyncio.run(main())