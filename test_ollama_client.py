#!/usr/bin/env python3
"""Test script to submit an Ollama workflow using the Python client."""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient

async def main():
    # Load workflow from YAML file
    with open("test_ollama_workflow.yaml", "r") as f:
        workflow = yaml.safe_load(f)

    # Initialize client (async context manager)
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        print("Submitting Ollama workflow...")

        # Submit workflow
        response = await client.submit_workflow(workflow)

        workflow_id = response.workflow_id
        print(f"✓ Workflow submitted: {workflow_id}")
        print(f"  Status: {response.status}")

        # Wait for workflow to complete (this awaits the result!)
        print("\nWaiting for workflow to complete...")
        final_status = await client.wait_for_workflow(
            workflow_id,
            timeout=120,  # 2 minutes max
            poll_interval=2  # Check every 2 seconds
        )

        print(f"\n✓ Workflow {final_status.status}!")
        print(f"  Completed at: {final_status.completed_at}")

        if final_status.error:
            print(f"  Error: {final_status.error}")

        # Get full workflow details
        workflow_details = await client.get_workflow(workflow_id)
        print(f"\nWorkflow Details:")
        print(f"  Status: {workflow_details.get('state', {}).get('status')}")
        print(f"  Data: {workflow_details.get('data')}")

        # Get task results
        tasks = await client.get_workflow_tasks(workflow_id)
        print(f"\nTask Results ({len(tasks)} tasks):")
        for task in tasks:
            print(f"\n  Task: {task.get('id')}")
            print(f"    Status: {task.get('status')}")
            if task.get('result'):
                print(f"    Result: {task.get('result')}")
            if task.get('error'):
                print(f"    Error: {task.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())
