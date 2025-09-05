#!/usr/bin/env python3
"""Test task submission and retrieval."""

import asyncio
import aiohttp
import json
from datetime import datetime

async def test_task_api():
    """Test the task API endpoints."""
    base_url = "http://localhost:8000"
    
    # Create a simple workflow with a task
    workflow = {
        "id": f"test-workflow-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "name": "Test Workflow",
        "tasks": [
            {
                "id": f"test-task-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "name": "Test Task",
                "type": "python",
                "config": {
                    "file": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/test_hello.py",
                    "function": "main"
                }
            }
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        # Submit workflow
        print("Submitting workflow...")
        async with session.post(f"{base_url}/workflows/submit", json={"workflow": workflow}) as resp:
            result = await resp.json()
            print(f"Workflow submission: {result}")
            workflow_id = workflow["id"]
        
        # List tasks
        print("\nListing tasks...")
        async with session.get(f"{base_url}/tasks/?limit=10") as resp:
            tasks = await resp.json()
            print(f"Tasks found: {json.dumps(tasks, indent=2)}")
            
            # Check if we have tasks with IDs
            if tasks and "tasks" in tasks and len(tasks["tasks"]) > 0:
                task_id = tasks["tasks"][0].get("id")
                print(f"\nFirst task ID: {task_id}")
                
                if task_id:
                    # Get specific task
                    print(f"\nGetting task {task_id}...")
                    async with session.get(f"{base_url}/tasks/{task_id}") as resp:
                        task = await resp.json()
                        print(f"Task details: {json.dumps(task, indent=2)}")
                    
                    # Try to get task result
                    print(f"\nGetting task result for {task_id}...")
                    async with session.get(f"{base_url}/tasks/{task_id}/result") as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            print(f"Task result: {json.dumps(result, indent=2)}")
                        else:
                            print(f"Task result not available (status {resp.status})")
            else:
                print("No tasks found in response")

if __name__ == "__main__":
    asyncio.run(test_task_api())