#!/usr/bin/env python
"""Test workflow with stream transport after Redis cleanup."""

import asyncio
import os
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def test_stream_clean():
    """Test stream transport with clean Redis."""
    
    # Create client
    client = GleitzeitClient(base_url="http://localhost:8050")
    await client.initialize()
    
    # Create workflow with Python tasks (since Python provider is registered)
    workflow = Workflow(
        id="test-clean-stream",
        name="Clean Stream Test",
        tasks=[
            Task(
                id="task1",
                name="Task 1",
                protocol="python/v1",  # Using the registered protocol
                method="python/execute",
                params={
                    "file": "task1.py"
                },
                dependencies=[]
            ),
            Task(
                id="task2",
                name="Task 2",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "task2.py"
                },
                dependencies=["task1"]
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
    max_attempts = 15
    for i in range(max_attempts):
        await asyncio.sleep(2)
        
        # Check workflow status
        workflow_data = await client.get_workflow(workflow_id)
        
        if workflow_data:
            status = workflow_data.status if hasattr(workflow_data, 'status') else workflow_data.get('status')
            print(f"  Status: {status} (attempt {i+1}/{max_attempts})")
            
            if status in ["completed", "failed"]:
                if status == "completed":
                    print("✅ Workflow completed successfully with stream transport!")
                else:
                    print(f"❌ Workflow failed: {status}")
                break
    else:
        print("⏱️ Workflow timed out")

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Stream Transport with Clean Redis")
    print("=" * 60)
    asyncio.run(test_stream_clean())