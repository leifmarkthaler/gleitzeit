#!/usr/bin/env python
"""Test reconciliation with failing workflow"""

import asyncio
from gleitzeit.client.client import GleitzeitClient
import time

async def main():
    # Connect to running server
    client = GleitzeitClient(api_url="http://localhost:8001")
    
    print("📋 Submitting workflow with invalid model...")
    
    # Submit workflow
    workflow_id = await client.submit_workflow("test_workflow.yaml")
    print(f"✅ Workflow submitted: {workflow_id}")
    
    # Monitor progress
    print("\n⏳ Monitoring workflow execution...")
    for i in range(30):  # Check for 30 seconds
        status = await client.get_workflow_status(workflow_id)
        print(f"  Status: {status.get('status')} - Tasks: {status.get('task_summary')}")
        
        # Check if workflow is done
        if status.get('status') in ['completed', 'failed', 'error']:
            break
        
        await asyncio.sleep(1)
    
    # Final status
    print(f"\n📊 Final workflow status: {status.get('status')}")
    print(f"   Task summary: {status.get('task_summary')}")
    
    # Check individual tasks
    if 'tasks' in status:
        for task_id, task_status in status['tasks'].items():
            print(f"   Task {task_id}: {task_status}")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())