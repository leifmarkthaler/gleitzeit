#!/usr/bin/env python3
import asyncio
import json
import redis.asyncio as aioredis

async def main():
    # Connect to Redis
    client = aioredis.from_url("redis://localhost:6379/0")
    
    # Get all task results for the workflow
    workflow_id = "easy-workflow-534eb51d"
    
    # Scan for task IDs in this workflow
    cursor = b'0'
    task_ids = []
    while cursor:
        cursor, keys = await client.scan(cursor, match=f"gleitzeit:task:{workflow_id}:*", count=100)
        for key in keys:
            task_id = key.decode().split(':')[-1]
            task_ids.append(task_id)
        if cursor == b'0':
            break
    
    print(f"Found {len(task_ids)} tasks in workflow {workflow_id}")
    
    # Get task results
    for task_id in task_ids:
        result_key = f"gleitzeit:task_result:{task_id}"
        result_data = await client.get(result_key)
        if result_data:
            result = json.loads(result_data)
            print(f"\n Task ID: {task_id}")
            print(f"   Status: {result.get('status')}")
            print(f"   Result type: {type(result.get('result'))}")
            print(f"   Result value: {result.get('result')}")
    
    await client.close()

if __name__ == '__main__':
    asyncio.run(main())
