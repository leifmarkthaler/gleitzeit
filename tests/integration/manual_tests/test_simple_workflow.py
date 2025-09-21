#!/usr/bin/env python
"""Test a simple working workflow."""

import asyncio
import json
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def test_simple_workflow():
    """Test a simple working workflow without LLM calls."""
    
    # Create client
    client = await GleitzeitClient.create(mode="api", api_port=8080)
    
    print("Testing simple workflow submission...")
    
    # Create a simple workflow with Python tasks using existing example scripts
    workflow = Workflow(
        id="test-simple-workflow",
        name="Simple Test Workflow",
        tasks=[
            Task(
                id="task1",
                name="Generate Numbers",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "examples/scripts/generate_numbers.py"
                },
                dependencies=[]
            ),
            Task(
                id="task2", 
                name="Calculate Sum",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "examples/scripts/calculate_sum.py"
                },
                dependencies=["task1"]
            )
        ]
    )
    
    try:
        # Submit workflow
        result = await client.submit_workflow(workflow)
        print(f"✅ Workflow submitted successfully!")
        print(f"Workflow ID: {result}")
        
        # Wait a bit for execution
        await asyncio.sleep(2)
        
        # Try to get workflow status
        try:
            status = await client.get_workflow(result if isinstance(result, str) else result.get('workflow_id'))
            print(f"Workflow status: {json.dumps(status, indent=2)}")
        except Exception as e:
            print(f"Could not get workflow status: {e}")
            
    except Exception as e:
        print(f"❌ Workflow submission failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_simple_workflow())