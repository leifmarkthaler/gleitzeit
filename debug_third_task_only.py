#!/usr/bin/env python3
"""
Test just the third task by itself - no dependencies, no timer
This will tell us if the task execution is working or if there's an issue with the task itself
"""

import asyncio
import json
from gleitzeit.client import GleitzeitClient

async def main():
    client = GleitzeitClient(base_url="http://localhost:8090")
    await client.initialize()
    
    # Test just the third task alone
    workflow = {
        "name": "test-third-task-only",
        "tasks": [
            {
                "id": "standalone_task",
                "name": "Standalone task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"file": "print_after_timer.py"}
                # NO dependencies - should execute immediately
            }
        ]
    }
    
    print(f"Submitting standalone task: {json.dumps(workflow, indent=2)}")
    result = await client.submit_workflow(workflow)
    print(f"\nWorkflow submitted: {result['workflow_id']}")
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Check status
    print("\nChecking workflow status...")
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        
        workflow_data = r.hgetall(f"gleitzeit:workflow:{result['workflow_id']}")
        print(f"Workflow status: {workflow_data.get('status', 'unknown')}")
        
        tasks_json = workflow_data.get('tasks', '[]')
        tasks = json.loads(tasks_json)
        print("\nTask statuses:")
        for task in tasks:
            task_id = task['id']
            task_data = r.hgetall(f"gleitzeit:task:{task_id}")
            task_result_data = r.hgetall(f"gleitzeit:task_result:{task_id}")
            print(f"  {task['name']}: {task_data.get('status', 'unknown')}")
            if task_result_data:
                print(f"    Result: {task_result_data}")
            
    except Exception as e:
        print(f"Error checking status: {e}")
    
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())