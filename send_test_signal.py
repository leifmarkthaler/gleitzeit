#!/usr/bin/env python3
"""Send signal to the waiting workflow."""

import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    client = GleitzeitClient()
    await client.initialize()
    
    workflow_id = "workflow-7c4723a0a19249ff99d6d21f3793e11f"
    
    # Check status before signal
    print("=== Before sending signal ===")
    workflow = await client.get_workflow(workflow_id)
    print(f"Workflow status: {workflow.status}")
    for task in workflow.tasks:
        print(f"  - {task.name}: {task.status}")
    
    # Send the signal
    print("\n=== Sending signal 'test_approval' ===")
    result = await client.send_signal("test_approval", {"approved": True})
    print(f"Signal result: {result}")
    
    # Wait for processing
    await asyncio.sleep(3)
    
    # Check status after signal
    print("\n=== After sending signal ===")
    workflow = await client.get_workflow(workflow_id)
    print(f"Workflow status: {workflow.status}")
    for task in workflow.tasks:
        print(f"  - {task.name}: {task.status}")

if __name__ == "__main__":
    asyncio.run(main())