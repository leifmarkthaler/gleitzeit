#!/usr/bin/env python
"""Submit and monitor a workflow with results."""

import asyncio
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow
import json

async def main():
    # Create client connected to local server on correct port
    client = GleitzeitClient(
        base_url="http://localhost:8080",
        mode=ClientMode.API
    )
    
    # Initialize the client
    await client.initialize()
    
    print("=" * 60)
    print("SUBMITTING WORKFLOW WITH PYTHON FILES")
    print("=" * 60)
    
    # Create workflow with two tasks using example scripts
    workflow_dict = {
        "name": "test-workflow-with-results",
        "tasks": [
            {
                "name": "hello_task",
                "protocol": "python",
                "method": "script",
                "params": {
                    "script": "examples/scripts/hello.py"
                }
            },
            {
                "name": "math_task",
                "protocol": "python",
                "method": "script",
                "params": {
                    "script": "examples/scripts/math_ops.py",
                    "args": ["25", "17"]
                },
                "dependencies": ["hello_task"]
            }
        ]
    }
    
    print(f"\nWorkflow definition:\n{json.dumps(workflow_dict, indent=2)}")
    
    # Create Workflow object
    workflow = Workflow(**workflow_dict)
    
    # Submit workflow
    try:
        result = await client.submit_workflow(workflow)
        workflow_id = result.get("workflow_id")
        print(f"\n✅ Workflow submitted successfully!")
        print(f"   Workflow ID: {workflow_id}")
        print(f"   Status: {result.get('status')}")
        
        # Monitor workflow execution
        print("\n" + "=" * 60)
        print("MONITORING WORKFLOW EXECUTION")
        print("=" * 60)
        
        # Wait for workflow to complete
        final_status = await client.wait_for_workflow(
            workflow_id, 
            timeout=30,
            poll_interval=1
        )
        
        print(f"\n✅ Workflow completed with status: {final_status.get('status')}")
        
        # Get workflow details
        workflow_data = await client.get_workflow(workflow_id)
        if workflow_data:
            print(f"\nWorkflow tasks:")
            for task in workflow_data.get("tasks", []):
                print(f"  - {task.get('name')}: {task.get('status')}")
                if task.get('workflow_id'):
                    print(f"    workflow_id: {task.get('workflow_id')}")
        
        # Get results
        print("\n" + "=" * 60)
        print("FETCHING RESULTS")
        print("=" * 60)
        
        results = await client.get_workflow_results(workflow_id)
        if results:
            print(f"\nTask Results:")
            for task_id, result in results.items():
                print(f"\n  Task: {task_id}")
                print(f"  Status: {result.get('status')}")
                if result.get('result'):
                    print(f"  Output: {result.get('result')}")
                if result.get('error'):
                    print(f"  Error: {result.get('error')}")
        
        print("\n" + "=" * 60)
        print("✅ WORKFLOW EXECUTION COMPLETE!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())