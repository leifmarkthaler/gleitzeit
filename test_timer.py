#!/usr/bin/env python3
"""Test timer functionality"""

import asyncio
import time
from gleitzeit.client import GleitzeitClient


async def test_timer_workflow():
    """Test timer workflow execution"""
    
    # Create and initialize client
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()
    
    # Login
    await client.login("basic", "basic123")
    print("✓ Logged in")
    
    # Submit workflow
    workflow_path = "test_timer_workflow.yaml"
    print(f"\nSubmitting workflow: {workflow_path}")
    
    result = await client.submit_workflow_from_file(workflow_path)
    workflow_id = result["workflow_id"]
    print(f"✓ Workflow submitted: {workflow_id}")
    
    # Monitor workflow status
    print("\nMonitoring workflow execution...")
    start_time = time.time()
    
    while True:
        status = await client.get_workflow_status(workflow_id)
        
        # Print task statuses
        print(f"\rWorkflow: {status['status']} | ", end="")
        task_states = {}
        for task in status.get("tasks", []):
            state = task["status"]
            task_states[task["name"]] = state
            
        print(f"Tasks: {task_states} | Time: {time.time() - start_time:.1f}s", end="")
        
        if status["status"] in ["COMPLETED", "FAILED"]:
            print()  # New line
            break
            
        await asyncio.sleep(0.5)
    
    # Get final results
    print(f"\n✓ Workflow {status['status']}")
    
    if status["status"] == "COMPLETED":
        results = await client.get_workflow_results(workflow_id)
        print("\nTask results:")
        for task_id, result in results.items():
            if "result" in result:
                print(f"  {task_id}: {result['result']}")
    
    await client.close()


if __name__ == "__main__":
    asyncio.run(test_timer_workflow())