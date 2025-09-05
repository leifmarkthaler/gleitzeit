#!/usr/bin/env python
"""Test mixed workflow with cascade failure."""

import asyncio
import yaml
import sys
import os
import time

sys.path.insert(0, 'src')

from gleitzeit.client import GleitzeitClient


async def main():
    # Create client
    print("Creating API client...")
    async with GleitzeitClient(api_url="http://localhost:8001", mode="api") as client:
        
        # Load workflow
        print("Loading mixed workflow...")
        with open('testworkflows/mixed_workflow.yaml', 'r') as f:
            workflow_config = yaml.safe_load(f)
        
        # Submit workflow
        print("Submitting mixed workflow...")
        result = await client.submit_workflow(workflow_config)
        workflow_id = result.get('workflow_id')
        print(f"Workflow submitted: {workflow_id}")
        
        # Monitor for a while
        print("\nMonitoring workflow execution...")
        for i in range(5):
            await asyncio.sleep(3)
            
            # Get workflow status
            workflows = await client.list_workflows()
            for wf in workflows:
                if wf.get('id') == workflow_id:
                    print(f"\n[{i+1}] Workflow status: {wf.get('status')}")
                    
                    # Get tasks
                    tasks = wf.get('tasks', [])
                    for task in tasks:
                        print(f"  Task {task.get('name'):20} ({task.get('id')}): {task.get('status')}")
                        if task.get('dependencies'):
                            print(f"    Dependencies: {task.get('dependencies')}")
                    break
        
        print("\n=== Final Check ===")
        workflows = await client.list_workflows()
        for wf in workflows:
            if wf.get('id') == workflow_id:
                print(f"Workflow: {wf.get('status')}")
                tasks = wf.get('tasks', [])
                for task in tasks:
                    print(f"  {task.get('name'):20}: {task.get('status')}")
                    if task.get('status') == 'failed':
                        # Try to get error details
                        print(f"    Error info available in task metadata")
                break
        
        print("\nTest complete!")


if __name__ == "__main__":
    asyncio.run(main())
