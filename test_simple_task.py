#!/usr/bin/env python3
"""Test simple task execution with Redis Streams and fixed enum serialization."""

import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    # Create and initialize client
    client = GleitzeitClient(base_url="http://localhost:8082")
    await client.initialize()
    
    # Submit a simple task
    task_data = {
        "protocol": "python/v1",
        "method": "python/execute",
        "params": {
            "code": """
print("Hello from Redis Streams!")
result = 42 * 2
print(f"Result: {result}")
return {"answer": result, "status": "success"}
"""
        }
    }
    
    result = await client.submit_task(task_data)
    
    task_id = result.get('task_id') or result.get('id')
    print(f"✅ Task submitted: {task_id}")
    print(f"   Response: {result}")
    
    # Wait for completion
    task_result = await client.wait_for_task(task_id, timeout=30)
    
    print(f"\n✅ Task completed!")
    print(f"   Final status: {task_result.status}")
    print(f"   Result: {task_result.result}")
    
    # Check if status is properly saved
    task_check = await client.get_task(task_id)
    print(f"\n✅ Status verification:")
    print(f"   Task status in Redis: {task_check.status}")
    print(f"   Status type: {type(task_check.status)}")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())