import asyncio
import time
import json
import sys
import os

# Add src to path
sys.path.insert(0, 'src')

from gleitzeit.client.client import GleitzeitClient

async def submit_workflows():
    """Submit 20 workflows and measure execution time"""
    client = GleitzeitClient("http://localhost:8000")
    
    # Create a simple workflow
    workflow = {
        "name": "Performance Test",
        "version": "1.0.0",
        "tasks": [
            {
                "id": f"task_1",
                "name": "Calculate",
                "type": "python",
                "method": "python/execute",
                "params": {
                    "code": """
import time
import random

# Simulate some work
start = time.time()
result = {
    'calculation': sum(range(1000)),
    'random': random.random(),
    'timestamp': start
}
print(f'Task completed in {time.time() - start:.3f}s')
"""
                }
            }
        ]
    }
    
    print("Starting batch workflow submission...")
    start_time = time.time()
    
    # Submit 20 workflows
    workflow_ids = []
    for i in range(20):
        workflow["name"] = f"Performance Test {i+1}"
        workflow_id = await client.submit_workflow(workflow)
        workflow_ids.append(workflow_id)
        print(f"Submitted workflow {i+1}/20: {workflow_id}")
    
    submission_time = time.time() - start_time
    print(f"\n✅ Submitted 20 workflows in {submission_time:.2f}s")
    
    # Wait for all workflows to complete
    print("\nWaiting for workflows to complete...")
    wait_start = time.time()
    
    completed = 0
    while completed < 20:
        await asyncio.sleep(0.5)
        completed = 0
        for wf_id in workflow_ids:
            # Extract workflow_id from WorkflowResponse object
            actual_id = wf_id.workflow_id if hasattr(wf_id, 'workflow_id') else wf_id
            status = await client.get_workflow_status(actual_id)
            if status and status.status in ['completed', 'failed']:
                completed += 1
        print(f"Progress: {completed}/20 workflows completed", end='\r')
    
    wait_time = time.time() - wait_start
    total_time = time.time() - start_time
    
    print(f"\n\n📊 Performance Summary:")
    print(f"  - Submission time: {submission_time:.2f}s")
    print(f"  - Execution time: {wait_time:.2f}s")
    print(f"  - Total time: {total_time:.2f}s")
    print(f"  - Average per workflow: {total_time/20:.2f}s")
    
    # Check for any failures
    failures = 0
    for wf_id in workflow_ids:
        actual_id = wf_id.workflow_id if hasattr(wf_id, 'workflow_id') else wf_id
        status = await client.get_workflow_status(actual_id)
        if status.status == 'failed':
            failures += 1
            print(f"❌ Workflow {actual_id} failed")
    
    if failures == 0:
        print(f"✅ All 20 workflows completed successfully!")
    else:
        print(f"⚠️ {failures} workflows failed")

if __name__ == "__main__":
    asyncio.run(submit_workflows())
