#!/usr/bin/env python
"""Test workflow execution with stream transport enabled."""

import asyncio
import os
import json
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def test_stream_workflow():
    """Test workflow with stream transport."""
    
    # Ensure stream mode is enabled
    os.environ["GLEITZEIT_STREAM_MODE"] = "enabled"
    
    # Create client
    client = GleitzeitClient(base_url="http://localhost:8060")
    await client.initialize()
    
    # Create simple workflow
    workflow = Workflow(
        id="test-stream-workflow",
        name="Stream Transport Test",
        tasks=[
            Task(
                id="echo1",
                name="Echo Task 1",
                protocol="shell",
                method="shell/execute",
                params={
                    "command": "echo 'Task 1 executed via stream transport'"
                },
                dependencies=[]
            ),
            Task(
                id="echo2",
                name="Echo Task 2",
                protocol="shell",
                method="shell/execute",
                params={
                    "command": "echo 'Task 2 executed via stream transport'"
                },
                dependencies=["echo1"]
            ),
            Task(
                id="echo3",
                name="Echo Task 3",
                protocol="shell",
                method="shell/execute",
                params={
                    "command": "echo 'Task 3 executed via stream transport'"
                },
                dependencies=["echo2"]
            )
        ]
    )
    
    print(f"Submitting workflow: {workflow.id}")
    
    # Submit workflow
    result = await client.submit_workflow(workflow)
    
    if isinstance(result, dict):
        workflow_id = result.get("workflow_id")
    else:
        workflow_id = result
    
    print(f"Workflow submitted: {workflow_id}")
    
    # Wait for completion
    max_attempts = 30
    for i in range(max_attempts):
        await asyncio.sleep(2)
        
        # Check workflow status
        workflow_data = await client.get_workflow(workflow_id)
        
        if workflow_data:
            status = workflow_data.status if hasattr(workflow_data, 'status') else workflow_data.get('status')
            print(f"Workflow status: {status}")
            
            if status in ["completed", "failed"]:
                if status == "completed":
                    print("✅ Workflow completed successfully!")
                    
                    # Get results
                    results = await client.get_workflow_results(workflow_id)
                    print(f"Results: {json.dumps(results, indent=2)}")
                else:
                    print("❌ Workflow failed")
                break
    else:
        print("⏱️ Workflow timed out")
    
    # await client.close()  # TODO: Add close method to client

if __name__ == "__main__":
    asyncio.run(test_stream_workflow())