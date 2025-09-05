#!/usr/bin/env python3
"""Test cascade failure for dependent tasks."""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.workflow_loader import load_workflow_from_dict
import time

async def main():
    """Submit mixed workflow and monitor cascade failures."""
    
    print("Creating API client...")
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_host="localhost",
        api_port=8001,
        auto_start_server=False
    )
    
    await client.initialize()
    print("Client initialized")
    
    # Load mixed workflow
    print("\nLoading mixed workflow...")
    with open("testworkflows/mixed_workflow.yaml", "r") as f:
        workflow_data = yaml.safe_load(f)
    print(f"Loaded workflow: {workflow_data['name']}")
    
    # Convert to proper workflow object
    workflow = load_workflow_from_dict(workflow_data)
    
    # Show task dependencies
    print("\nTask Dependencies:")
    for task in workflow.tasks:
        deps = task.dependencies if task.dependencies else []
        print(f"  {task.name}: depends on {deps}")
    
    # Submit workflow
    print("\nSubmitting workflow...")
    workflow_id = await client.submit_workflow(workflow)
    print(f"✅ Workflow submitted: {workflow_id}")
    
    # Monitor execution
    print("\nMonitoring execution (checking every 2 seconds)...")
    for i in range(10):
        await asyncio.sleep(2)
        
        workflows = await client.list_workflows(limit=20)
        
        for wf in workflows:
            if hasattr(wf, 'id') and wf.id == workflow_id:
                print(f"\n[{i+1}] Workflow status: {wf.status}")
                
                # Check each task
                for task in wf.tasks:
                    status = task.status if hasattr(task, 'status') else 'unknown'
                    print(f"  Task {task.name:25}: {status}")
                    
                    # If task failed, show why
                    if status == 'failed':
                        # Check if it has dependencies
                        if task.dependencies:
                            print(f"    (has dependencies: {task.dependencies})")
                
                # Check if workflow is done
                if wf.status in ['completed', 'failed', 'cancelled']:
                    print(f"\nWorkflow finished with status: {wf.status}")
                    
                    # Show final task statuses
                    print("\nFinal Task Statuses:")
                    for task in wf.tasks:
                        status = task.status if hasattr(task, 'status') else 'unknown'
                        deps_str = f" (deps: {task.dependencies})" if task.dependencies else ""
                        print(f"  {task.name:25}: {status}{deps_str}")
                    
                    if wf.status == 'failed':
                        print("\n✅ CASCADE FAILURE TEST PASSED - Workflow correctly failed due to task failures")
                    
                    await client.shutdown()
                    return
                
                break
    
    print("\n⚠️ Workflow did not complete within timeout")
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
