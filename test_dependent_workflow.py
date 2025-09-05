#!/usr/bin/env python3
"""
Test running dependent_workflow.yaml using the Gleitzeit client.
"""

import asyncio
import json
from pathlib import Path
from gleitzeit.client import GleitzeitClient

async def main():
    # Create client (uses SystemManager in API mode by default)
    client = GleitzeitClient(api_port=8003)  # Use port 8003 since server is running there
    
    try:
        # Initialize the client
        print("Initializing client...")
        await client.initialize()
        
        # Submit the workflow from YAML file
        workflow_file = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/examples/dependent_workflow.yaml"
        print(f"\nSubmitting workflow from: {workflow_file}")
        
        # Use run_workflow which loads YAML and submits via API
        result = await client.run_workflow(
            workflow_file,
            watch=True  # Wait for the workflow to complete
        )
        
        print(f"\nWorkflow submitted with ID: {result.get('workflow_id')}")
        print(f"Workflow status: {result.get('status')}")
        
        # Get detailed workflow results
        workflow_id = result.get('workflow_id')
        workflow = await client.get_workflow(workflow_id)
        
        print("\n=== Task Results ===")
        
        # Get results for each task
        for task_name in ["generate_topic", "write_outline", "write_essay"]:
            # Find the task by name
            task = next((t for t in workflow.tasks if t.name == task_name), None)
            if task:
                print(f"\n--- {task_name} ---")
                print(f"Status: {task.status}")
                
                # Get task result
                task_result = await client.get_task_result(task.id)
                if task_result and task_result.output:
                    # Parse the response from the LLM output
                    if isinstance(task_result.output, dict) and 'response' in task_result.output:
                        print(f"Response: {task_result.output['response']}")
                    else:
                        print(f"Output: {json.dumps(task_result.output, indent=2)}")
                elif task_result:
                    print(f"Raw Result: {task_result}")
        
        print("\n=== Workflow Complete ===")
        print(f"Final status: {workflow.status}")
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())