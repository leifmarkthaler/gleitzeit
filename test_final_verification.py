#!/usr/bin/env python3
"""
Final verification - check if timer workflow is now fully working
"""

import asyncio
import time
from gleitzeit.client import GleitzeitClient

async def main():
    client = GleitzeitClient()
    await client.initialize()
    
    # Check the last workflow status
    workflows = await client.list_workflows(limit=1)
    
    if not workflows:
        print("No workflows found")
        return
        
    workflow = workflows[0]
    print(f"Workflow: {workflow.id} - Status: {workflow.status}")
    
    # Get task details
    for task in workflow.tasks:
        print(f"  Task: {task.name} ({task.id}) - Status: {task.status}")
        
        # Try to get task result
        try:
            result = await client.get_task_result(task.id)
            if result:
                print(f"    Result: {result}")
        except Exception as e:
            print(f"    No result available: {e}")
            
if __name__ == "__main__":
    asyncio.run(main())