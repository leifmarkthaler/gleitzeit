#!/usr/bin/env python3
"""Test simple task execution directly without events."""

import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    # Create client using factory method
    client = await GleitzeitClient.create(mode="api", base_url="http://localhost:8082", enable_events=False)
    
    try:
        # Submit a simple task
        task_data = {
            "name": "test_redis_streams",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": """
print("Testing Redis Streams implementation!")
result = 42 * 2
print(f"Calculation result: {result}")
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
        
        # Check if status is properly saved as string value, not enum string
        task_check = await client.get_task(task_id)
        print(f"\n✅ Status verification:")
        print(f"   Task status value: {task_check.status}")
        
        # Check if it's the proper value
        if hasattr(task_check.status, 'value'):
            print(f"   ❌ Status is still an enum object!")
        elif "TaskStatus." in str(task_check.status):
            print(f"   ❌ Status saved as enum string: {task_check.status}")
        else:
            print(f"   ✅ Status properly saved as: {task_check.status}")
            
    finally:
        # Cleanup if needed
        pass

if __name__ == "__main__":
    asyncio.run(main())