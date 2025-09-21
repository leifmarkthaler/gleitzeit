#!/usr/bin/env python
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient() as client:
        workflow_id = 'workflow-18efaa93'
        
        for i in range(10):
            workflow = await client.get_workflow(workflow_id)
            print(f'Attempt {i+1}: Status = {workflow.status}')
            
            tasks = await client.get_workflow_tasks(workflow_id)
            for task in tasks:
                print(f'  Task {task.name}: {task.status}')
            
            if workflow.status in ['COMPLETED', 'FAILED']:
                break
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())