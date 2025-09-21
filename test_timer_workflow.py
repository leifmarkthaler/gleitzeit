#!/usr/bin/env python3
"""Test timer workflow functionality."""

import asyncio
import json
from datetime import datetime
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def main():
    # Connect to the API
    client = GleitzeitClient(mode="api", api_url="http://localhost:8080")
    await client.initialize()
    
    print("Testing timer workflow...")
    
    # Create a workflow with timer tasks
    workflow = Workflow(
        id=f"timer-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        name="Timer Test Workflow",
        tasks=[
            Task(
                id="start",
                name="Start Task",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "timer_start_task.py"
                }
            ),
            Task(
                id="wait",
                name="Wait 3 seconds",
                protocol="timer/v1",
                method="timer/sleep",
                params={"seconds": 3},
                dependencies=["start"]
            ),
            Task(
                id="done",
                name="Completion Task",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "timer_end_task.py"
                },
                dependencies=["wait"]
            )
        ]
    )
    
    # Submit the workflow - convert to dict and clean up fields
    print(f"\nSubmitting workflow: {workflow.id}")
    workflow_dict = workflow.model_dump(exclude_none=True)
    # Remove fields that aren't accepted by the API
    for field in ['workflow_id', 'resource_requirements', 'execution_node', 'status', 
                  'description', 'created_at', 'error_message', 'completed_at', 
                  'started_at', 'assigned_provider', 'tags', 'attempt_count']:
        workflow_dict.pop(field, None)
        for task in workflow_dict.get('tasks', []):
            task.pop(field, None)
    
    result = await client._adapter._request('POST', '/workflows', json_data={'workflow': workflow_dict})
    print(f"Workflow submitted: {result}")
    
    # Poll for status
    for i in range(10):
        await asyncio.sleep(1)
        status = await client.get_workflow_status(workflow.id)
        print(f"Status after {i+1}s: {status}")
        
        if status.get("status") == "COMPLETED":
            print("\n✅ Workflow completed successfully!")
            
            # Get task results
            results = await client.get_workflow_results(workflow.id)
            print(f"\nTask results:")
            for task_id, task_result in results.items():
                print(f"  {task_id}: {task_result}")
            break
        elif status.get("status") == "FAILED":
            print(f"\n❌ Workflow failed: {status}")
            break
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())