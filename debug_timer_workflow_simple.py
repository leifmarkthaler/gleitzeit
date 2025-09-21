#!/usr/bin/env python3
"""
Very simple debug test - just emit a timer completion event directly
and see if the workflow progresses correctly
"""

import asyncio
import json
from gleitzeit.client import GleitzeitClient

async def main():
    client = GleitzeitClient(base_url="http://localhost:8091")
    await client.initialize()
    
    # Submit the simplest possible timer workflow
    workflow = {
        "name": "debug-timer-simple",
        "tasks": [
            {
                "id": "timer_task",
                "name": "Timer task",
                "protocol": "timer/v1",
                "method": "timer/sleep",
                "params": {"seconds": 1}  # Very short timer
            },
            {
                "id": "after_timer",
                "name": "After timer",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"file": "print_after_timer.py"},
                "dependencies": ["timer_task"]
            }
        ]
    }
    
    print(f"Submitting simple timer workflow: {json.dumps(workflow, indent=2)}")
    result = await client.submit_workflow(workflow)
    print(f"\nWorkflow submitted: {result['workflow_id']}")
    
    # Wait just a bit longer than the timer
    await asyncio.sleep(3)
    
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
            print(f"  {task['name']}: {task_data.get('status', 'unknown')}")
            
    except Exception as e:
        print(f"Error checking status: {e}")
    
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())