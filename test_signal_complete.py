#!/usr/bin/env python3
"""Test signal workflow completion with the fix."""

import asyncio
import time
from gleitzeit.client import GleitzeitClient

async def test_signal_workflow():
    # Create client
    client = GleitzeitClient(base_url="http://localhost:8000")
    
    # Submit the signal workflow
    print("Submitting signal workflow...")
    result = await client.run_workflow("test_signal_simple.yaml")
    workflow_id = result["workflow_id"]
    print(f"Workflow ID: {workflow_id}")
    
    # Wait a moment for task to start
    await asyncio.sleep(2)
    
    # Check workflow status - should be WAITING
    status = await client.get_workflow_status(workflow_id)
    print(f"Workflow status before signal: {status['status']}")
    
    # Check task statuses
    tasks = await client.get_workflow_tasks(workflow_id)
    for task in tasks:
        print(f"  Task {task['name']}: {task['status']}")
    
    # Send the signal
    print("\nSending test_approval signal...")
    signal_result = await client.send_signal(
        workflow_id=workflow_id,
        signal_name="test_approval",
        payload={"approved": True, "timestamp": time.time()}
    )
    print(f"Signal sent: {signal_result}")
    
    # Wait for signal to be processed
    await asyncio.sleep(3)
    
    # Check workflow status again - should be COMPLETED
    status = await client.get_workflow_status(workflow_id)
    print(f"\nWorkflow status after signal: {status['status']}")
    
    # Check task statuses again
    tasks = await client.get_workflow_tasks(workflow_id)
    for task in tasks:
        print(f"  Task {task['name']}: {task['status']}")
        if task['status'] == 'completed' and task.get('result'):
            print(f"    Result: {task['result']}")
    
    # Get final workflow result
    if status['status'] == 'completed':
        print("\n✅ SUCCESS: Signal workflow completed after receiving signal!")
    else:
        print(f"\n❌ FAILED: Workflow status is {status['status']}, expected 'completed'")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(test_signal_workflow())