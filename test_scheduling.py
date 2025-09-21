#!/usr/bin/env python3
"""Test scheduling with timer/wait_until method."""

import asyncio
from datetime import datetime, timedelta
from gleitzeit.client import GleitzeitClient


async def test_scheduling():
    client = GleitzeitClient(base_url='http://localhost:8000')
    await client.initialize()
    
    # Schedule task for 2 seconds from now
    target_time = datetime.utcnow() + timedelta(seconds=2)
    target_iso = target_time.isoformat() + 'Z'
    
    print(f'Current time: {datetime.utcnow().isoformat()}Z')
    print(f'Scheduling for: {target_iso}')
    
    # Create a Python script to execute
    with open('/tmp/scheduled_task.py', 'w') as f:
        f.write('''
import datetime
print(f"Task executed at: {datetime.datetime.utcnow().isoformat()}Z")
result = {"executed_at": datetime.datetime.utcnow().isoformat(), "status": "success"}
''')
    
    # Submit scheduled workflow
    result = await client.submit_workflow({
        'id': 'scheduled-workflow',
        'tasks': [
            {
                'id': 'wait-until-task',
                'protocol': 'timer/v1',
                'method': 'timer/wait_until',
                'params': {'timestamp': target_iso}
            },
            {
                'id': 'after-schedule',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'params': {'file': '/tmp/scheduled_task.py'},
                'dependencies': ['wait-until-task']
            }
        ]
    })
    
    workflow_id = result.get('workflow_id')
    print(f'✅ Submitted workflow: {workflow_id}')
    
    # Wait for scheduled time plus buffer
    print('⏳ Waiting for scheduled execution...')
    await asyncio.sleep(4)
    
    print(f'Current time after wait: {datetime.utcnow().isoformat()}Z')
    print('✅ Task should have executed at scheduled time')


if __name__ == '__main__':
    asyncio.run(test_scheduling())