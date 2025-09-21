#!/usr/bin/env python
"""Test centralized workflow ID assignment through WorkflowLoaderV2."""

import asyncio
import aiohttp
import json

async def test_workflow_submission():
    """Test workflow submission with centralized ID management."""
    
    # Workflow definition that will be processed by WorkflowLoaderV2
    workflow_data = {
        "name": "test-centralized-workflow",
        "tasks": [
            {
                "name": "task1",
                "protocol": "python",
                "method": "script",
                "params": {
                    "script": "examples/scripts/hello.py"
                }
            },
            {
                "name": "task2",
                "protocol": "python",
                "method": "script",
                "params": {
                    "script": "examples/scripts/math_ops.py",
                    "args": ["10", "20"]
                },
                "dependencies": ["task1"]
            }
        ]
    }
    
    # Submit workflow through API
    async with aiohttp.ClientSession() as session:
        url = "http://localhost:8004/api/v1/workflows/submit"
        
        print("Submitting workflow with centralized ID management...")
        print(f"Workflow: {json.dumps(workflow_data, indent=2)}")
        
        async with session.post(url, json={"workflow": workflow_data}) as response:
            result = await response.json()
            
            if response.status == 200:
                print(f"\n✅ Workflow submitted successfully!")
                print(f"Workflow ID: {result.get('workflow_id')}")
                print(f"Status: {result.get('status')}")
                print("\nThe workflow ID and task IDs were assigned centrally by WorkflowLoaderV2")
                
                # Wait for workflow to complete
                workflow_id = result.get('workflow_id')
                if workflow_id:
                    await asyncio.sleep(3)
                    
                    # Check workflow status
                    async with session.get(f"http://localhost:8080/api/v1/workflows/{workflow_id}") as status_response:
                        if status_response.status == 200:
                            workflow_status = await status_response.json()
                            print(f"\nWorkflow Status: {workflow_status.get('status')}")
                            print(f"Tasks: {len(workflow_status.get('tasks', []))}")
                            
                            # Verify all tasks have workflow_id set
                            tasks = workflow_status.get('tasks', [])
                            all_have_workflow_id = all(task.get('workflow_id') == workflow_id for task in tasks)
                            
                            if all_have_workflow_id:
                                print("✅ All tasks have workflow_id properly set by WorkflowLoaderV2")
                            else:
                                print("❌ Some tasks missing workflow_id")
                
            else:
                print(f"\n❌ Workflow submission failed!")
                print(f"Status: {response.status}")
                print(f"Error: {result}")

if __name__ == "__main__":
    asyncio.run(test_workflow_submission())