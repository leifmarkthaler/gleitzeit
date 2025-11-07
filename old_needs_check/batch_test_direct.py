#!/usr/bin/env python3
"""
Performance test - Submit and time 20 workflows
"""

import asyncio
import time
import json
import redis
from datetime import datetime

# Import from correct path
import sys
sys.path.insert(0, 'src')

from gleitzeit.core.models import Workflow, Task

async def submit_workflow_to_redis(workflow_data, workflow_id):
    """Submit workflow directly to loader stream"""
    r = redis.Redis(host='localhost', port=6379, decode_responses=False)

    # Store workflow definition
    r.set(f"workflow:{workflow_id}:definition", json.dumps(workflow_data))

    # Get shard for this workflow
    shard = hash(workflow_id) % 16

    # Submit directly to workflow:load stream (bypassing submission worker)
    loader_data = {
        b'workflow_id': workflow_id.encode(),
        b'workflow_ref': json.dumps(workflow_data).encode(),  # Include full workflow
        b'inputs': json.dumps({}).encode(),
        b'timestamp': datetime.now().isoformat().encode()
    }

    # Submit to the loader stream directly
    stream_key = f"{{shard:{shard}}}:workflow:load"
    r.xadd(stream_key, loader_data)

    return workflow_id

async def submit_20_workflows():
    """Submit 20 workflows and measure execution time"""
    
    print("🚀 Starting batch workflow submission test...")
    start_time = time.time()
    
    # Create workflow data
    workflow_ids = []
    
    for i in range(20):
        workflow_id = f"perf-test-{datetime.now().timestamp()}-{i}"
        
        workflow_data = {
            "id": workflow_id,
            "name": f"Performance Test {i+1}",
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
    'workflow_num': """ + str(i+1) + """,
    'calculation': sum(range(1000)),
    'random': random.random(),
    'timestamp': start
}
print(f'Task for workflow """ + str(i+1) + """ completed in {time.time() - start:.3f}s')
"""
                    }
                }
            ]
        }
        
        # Submit to Redis
        wf_id = await submit_workflow_to_redis(workflow_data, workflow_id)
        workflow_ids.append(wf_id)
        print(f"Submitted workflow {i+1}/20: {wf_id}")
    
    submission_time = time.time() - start_time
    print(f"\n✅ Submitted 20 workflows in {submission_time:.2f}s")
    
    # Monitor completion
    print("\nWaiting for workflows to complete...")
    wait_start = time.time()
    
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    completed = 0
    max_wait = 30  # Maximum 30 seconds wait
    
    while completed < 20 and (time.time() - wait_start) < max_wait:
        await asyncio.sleep(0.5)
        completed = 0
        failed = 0
        
        for wf_id in workflow_ids:
            result_key = f"workflow:{wf_id}:result"
            result = r.get(result_key)
            
            if result:
                result_data = json.loads(result)
                if result_data.get('status') == 'completed':
                    completed += 1
                elif result_data.get('status') == 'failed':
                    failed += 1
        
        print(f"Progress: {completed}/20 completed, {failed} failed", end='\r')
    
    wait_time = time.time() - wait_start
    total_time = time.time() - start_time
    
    print(f"\n\n📊 Performance Summary:")
    print(f"  - Submission time: {submission_time:.2f}s")
    print(f"  - Execution time: {wait_time:.2f}s") 
    print(f"  - Total time: {total_time:.2f}s")
    print(f"  - Average per workflow: {total_time/20:.2f}s")
    
    # Check for any failures and show details
    failures = []
    for wf_id in workflow_ids:
        result = r.get(f"workflow:{wf_id}:result")
        if result:
            result_data = json.loads(result)
            if result_data.get('status') == 'failed':
                failures.append((wf_id, result_data.get('error')))
    
    if not failures:
        print(f"\n✅ All {completed} workflows completed successfully!")
    else:
        print(f"\n⚠️ {len(failures)} workflows failed:")
        for wf_id, error in failures[:3]:  # Show first 3 failures
            print(f"  - {wf_id}: {error}")
    
    if completed < 20:
        print(f"\n⏱️ Only {completed}/20 workflows completed within {max_wait}s timeout")

if __name__ == "__main__":
    asyncio.run(submit_20_workflows())
