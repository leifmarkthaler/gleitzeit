#!/usr/bin/env python3
"""Submit timer workflow for testing."""

import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    """Submit timer workflow."""
    client = GleitzeitClient(host="localhost", port=8000)
    await client.initialize()
    
    # Load workflow from file
    import yaml
    with open("test_timer_workflow.yaml", "r") as f:
        workflow_data = yaml.safe_load(f)
    
    # Submit workflow
    workflow_id = await client.submit_workflow(workflow_data)
    print(f"Submitted workflow: {workflow_id}")
    
    # Give it a moment to process
    await asyncio.sleep(2)
    
    # Check status
    status = await client.get_workflow_status(workflow_id)
    print(f"Status: {status}")
    
    # Check detailed workflow info
    workflow = await client.get_workflow(workflow_id)
    print(f"Workflow status: {workflow['status']}")
    
    for task in workflow.get('tasks', []):
        print(f"  Task {task['id']}: {task['status']}")

if __name__ == "__main__":
    asyncio.run(main())