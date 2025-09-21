#!/usr/bin/env python3
"""
Test event stream to audit for misalignments in event emission and consumption.
"""

import asyncio
import json
from datetime import datetime
from gleitzeit.client import GleitzeitClient


async def test_event_stream():
    """Test complete event stream flow from submission to completion."""
    client = GleitzeitClient(base_url='http://localhost:8000')
    await client.initialize()
    
    # Create test files for execution
    with open('/tmp/task1.py', 'w') as f:
        f.write('''
print("Task 1 starting")
result = {"task": 1, "status": "success", "timestamp": __import__("datetime").datetime.utcnow().isoformat()}
print(f"Task 1 result: {result}")
''')
    
    with open('/tmp/task2.py', 'w') as f:
        f.write('''
print("Task 2 starting")
result = {"task": 2, "status": "success", "timestamp": __import__("datetime").datetime.utcnow().isoformat()}
print(f"Task 2 result: {result}")
''')
    
    with open('/tmp/task3.py', 'w') as f:
        f.write('''
print("Task 3 starting - dependent on task 1 and 2")
result = {"task": 3, "status": "success", "timestamp": __import__("datetime").datetime.utcnow().isoformat()}
print(f"Task 3 result: {result}")
''')
    
    # Submit workflow with dependencies
    workflow = {
        'id': f'event-audit-{datetime.utcnow().isoformat()}',
        'name': 'Event Stream Audit Workflow',
        'tasks': [
            {
                'id': 'task-1',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'params': {'file': '/tmp/task1.py'}
            },
            {
                'id': 'task-2',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'params': {'file': '/tmp/task2.py'}
            },
            {
                'id': 'task-3',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'params': {'file': '/tmp/task3.py'},
                'dependencies': ['task-1', 'task-2']
            }
        ]
    }
    
    print(f"Submitting workflow at {datetime.utcnow().isoformat()}")
    result = await client.submit_workflow(workflow)
    workflow_id = result.get('workflow_id')
    print(f"✅ Workflow submitted: {workflow_id}")
    
    # Poll for status
    print("\n⏳ Monitoring workflow execution...")
    max_polls = 30
    for i in range(max_polls):
        await asyncio.sleep(1)
        
        # Get workflow status
        try:
            status = await client.get_workflow_status(workflow_id)
            print(f"Poll {i+1}: Status = {status.get('status')}")
            
            # Check task statuses
            tasks = status.get('tasks', {})
            for task_id, task_info in tasks.items():
                print(f"  - {task_id}: {task_info.get('status')}")
            
            # Check if completed
            if status.get('status') in ['COMPLETED', 'FAILED']:
                print(f"\n✅ Workflow {status.get('status')}")
                
                # Get results
                for task_id in ['task-1', 'task-2', 'task-3']:
                    try:
                        result = await client.get_task_result(workflow_id, task_id)
                        print(f"  - {task_id} result: {json.dumps(result, indent=2)}")
                    except Exception as e:
                        print(f"  - {task_id} error: {e}")
                break
                
        except Exception as e:
            print(f"Poll {i+1}: Error getting status - {e}")
    
    else:
        print("❌ Workflow did not complete within timeout")
    
    print("\n📊 Event stream audit complete")
    await client.close()


if __name__ == '__main__':
    asyncio.run(test_event_stream())