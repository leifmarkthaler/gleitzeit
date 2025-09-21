#!/usr/bin/env python3
"""
Debug script to check timer task status after completion
"""

import asyncio
import json
import redis
from gleitzeit.client import GleitzeitClient

async def main():
    client = GleitzeitClient(base_url="http://localhost:8091")
    await client.initialize()
    
    # Submit a simple timer workflow  
    workflow = {
        "name": "debug-timer-status",
        "tasks": [
            {
                "id": "timer_task",
                "name": "Timer task",
                "protocol": "timer/v1",
                "method": "timer/sleep",
                "params": {"seconds": 2}
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
    
    print("Submitting timer workflow...")
    result = await client.submit_workflow(workflow)
    workflow_id = result['workflow_id']
    print(f"Workflow submitted: {workflow_id}")
    
    # Wait for timer to complete
    await asyncio.sleep(4)
    
    # Check status via direct Redis access
    print("\n=== REDIS STATUS CHECK ===")
    try:
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        
        # Check workflow
        workflow_data = r.hgetall(f"gleitzeit:workflow:{workflow_id}")
        print(f"Workflow status: {workflow_data.get('status', 'unknown')}")
        
        # Check timer task
        timer_task_data = r.hgetall(f"gleitzeit:task:timer_task")
        timer_task_result_data = r.hgetall(f"gleitzeit:task_result:timer_task")
        
        print(f"\nTimer task status: {timer_task_data.get('status', 'unknown')}")
        print(f"Timer task result status: {timer_task_result_data.get('status', 'unknown')}")
        print(f"Timer task result data: {timer_task_result_data}")
        
        # Check dependent task  
        after_task_data = r.hgetall(f"gleitzeit:task:after_timer")
        after_task_result_data = r.hgetall(f"gleitzeit:task_result:after_timer")
        
        print(f"\nAfter task status: {after_task_data.get('status', 'unknown')}")
        print(f"After task result status: {after_task_result_data.get('status', 'unknown')}")
        
    except Exception as e:
        print(f"Error checking Redis: {e}")
    
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())