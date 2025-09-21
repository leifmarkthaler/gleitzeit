#!/usr/bin/env python
"""Quick timer test"""

import asyncio
from gleitzeit.client import GleitzeitClient

async def test():
    client = await GleitzeitClient.create(mode='api', api_url='http://localhost:8000')
    result = await client.submit_workflow({
        'name': 'Quick timer test',
        'tasks': [{
            'name': 'timer_test',
            'protocol': 'timer/v1',
            'method': 'timer/sleep',
            'params': {'duration': 1}
        }]
    })
    print(f'Timer workflow: {result}')
    workflow_id = result.get('workflow_id')
    
    await asyncio.sleep(2)
    
    workflow = await client.get_workflow(workflow_id)
    print(f'Workflow status: {workflow.status if workflow else "unknown"}')

asyncio.run(test())