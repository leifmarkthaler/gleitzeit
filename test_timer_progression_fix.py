#!/usr/bin/env python3

"""
Test timer workflow progression issue fix.
"""

import asyncio
import time
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.client.client import GleitzeitClient

async def test_timer_workflow():
    # Connect to server in API mode
    client = GleitzeitClient(mode="api", api_host="localhost", api_port=8101)
    await client.initialize()
    
    try:
        # Login
        login_resp = await client.login("basic", "password")
        print(f"Login: {login_resp}")
        
        # Submit timer workflow
        workflow_resp = await client.submit_workflow_file("test_timer_workflow.yaml")
        print(f"Workflow submitted: {workflow_resp}")
        workflow_id = workflow_resp['workflow_id']
        
        # Monitor workflow progression
        print("Monitoring workflow progression...")
        for i in range(20):  # Monitor for 20 seconds
            status = await client.get_workflow_status(workflow_id)
            print(f"Workflow status ({i+1}s): {status}")
            
            if status.get('status') in ['completed', 'failed']:
                break
                
            await asyncio.sleep(1)
        
        # Get final results
        final_status = await client.get_workflow_status(workflow_id)
        print(f"Final workflow status: {final_status}")
        
        # Get individual task statuses
        tasks = await client.list_tasks(workflow_id)
        print(f"Task statuses:")
        for task in tasks:
            print(f"  - {task.get('name', task.get('id'))}: {task.get('status')}")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if hasattr(client, 'shutdown'):
            await client.shutdown()
        elif hasattr(client, 'close'):
            await client.close()

if __name__ == "__main__":
    asyncio.run(test_timer_workflow())