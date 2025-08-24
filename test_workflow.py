#!/usr/bin/env python3
import asyncio
import yaml
import httpx
import json
import time

async def submit_workflow():
    # Read the workflow YAML file
    with open('examples/test_complex_python.yaml', 'r') as f:
        workflow_config = yaml.safe_load(f)
    
    # Submit workflow via API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            'http://localhost:8041/workflows',
            json=workflow_config,
            timeout=30.0
        )
        
        if response.status_code == 200:
            result = response.json()
            workflow_id = result['id']
            print(f"✅ Workflow submitted: {workflow_id}")
            
            # Monitor workflow status
            for i in range(30):  # Check for up to 30 seconds
                await asyncio.sleep(1)
                status_response = await client.get(f'http://localhost:8041/workflows/{workflow_id}')
                if status_response.status_code == 200:
                    status = status_response.json()
                    print(f"Status: {status['status']}, Tasks: {status.get('tasks_completed', 0)}/{status.get('tasks_total', 0)}")
                    
                    if status['status'] in ['completed', 'failed']:
                        print(f"\n{'✅' if status['status'] == 'completed' else '❌'} Workflow {status['status']}")
                        
                        # Get detailed results
                        results_response = await client.get(f'http://localhost:8041/workflows/{workflow_id}/results')
                        if results_response.status_code == 200:
                            results = results_response.json()
                            print("\nTask Results:")
                            for task_id, task_result in results.get('task_results', {}).items():
                                print(f"  {task_id}: {task_result.get('status')}")
                        break
            else:
                print("⏱️ Workflow still running after 30 seconds")
        else:
            print(f"❌ Failed to submit workflow: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(submit_workflow())