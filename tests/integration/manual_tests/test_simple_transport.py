#!/usr/bin/env python3
"""Test workflow for simplified stream transport."""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task


async def main():
    """Run test workflow with stream transport."""
    
    # Create client
    client = GleitzeitClient(api_host="localhost", api_port=8030)
    await client.initialize()
    
    # Define workflow
    workflow_def = Workflow(
        name="test-stream-transport",
        tasks=[
            Task(
                id="task1",
                name="task1",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "task1.py"
                },
                dependencies=[]
            ),
            Task(
                id="task2",
                name="task2",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "task2.py"
                },
                dependencies=["task1"]
            ),
            Task(
                id="task3",
                name="task3",
                protocol="python/v1",
                method="python/execute",
                params={
                    "file": "task3.py"
                },
                dependencies=["task2"]
            )
        ]
    )
    
    # Submit workflow
    print("Submitting workflow with stream transport enabled...")
    response = await client.submit_workflow(workflow_def)
    print(f"Workflow submitted: {response}")
    
    # Extract workflow_id from response
    if isinstance(response, dict):
        workflow_id = response.get('workflow_id')
    else:
        workflow_id = response
    
    # Wait for completion
    print("Waiting for workflow to complete...")
    result = await client.wait_for_workflow(workflow_id, timeout=30)
    
    # Display results
    if isinstance(result, dict):
        print(f"\nWorkflow Status: {result.get('status', 'unknown')}")
        print("\nTask Results:")
        task_results = result.get('task_results', {})
        for task_id, task_result in task_results.items():
            if task_result:
                if isinstance(task_result, dict):
                    print(f"  {task_id}: {task_result.get('status', 'unknown')}")
                    if task_result.get('result'):
                        print(f"    Result: {task_result['result']}")
                else:
                    print(f"  {task_id}: {task_result.status}")
                    if task_result.result:
                        print(f"    Result: {task_result.result}")
    else:
        print(f"\nWorkflow Status: {result.status}")
        print("\nTask Results:")
        for task_id, task_result in result.task_results.items():
            if task_result:
                print(f"  {task_id}: {task_result.status}")
                if task_result.result:
                    print(f"    Result: {task_result.result}")
    
    print("\nStream transport test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())