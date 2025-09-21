#!/usr/bin/env python3
"""
Simple test to run a workflow and get results using the running server.
"""

import asyncio
import aiohttp
import json
import sys

async def test_workflow():
    """Test workflow execution with results."""
    
    # Simple workflow that produces results using Python files
    workflow = {
        "workflow": {
            "name": "test-results",
            "tasks": [
                {
                    "id": "task1",
                    "name": "Generate Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "parameters": {
                        "file": "test_task1.py"
                    }
                },
                {
                    "id": "task2",
                    "name": "Process Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "depends_on": ["task1"],
                    "parameters": {
                        "file": "test_task2.py"
                    }
                }
            ]
        }
    }
    
    async with aiohttp.ClientSession() as session:
        # Submit workflow
        print("=" * 60)
        print("WORKFLOW SUBMISSION TEST")
        print("=" * 60)
        
        try:
            url = "http://localhost:8080/workflows/"
            print(f"\n1. Submitting workflow to {url}...")
            
            async with session.post(url, json=workflow) as response:
                if response.status == 200:
                    result = await response.json()
                    workflow_id = result.get('workflow_id')
                    print(f"✅ Workflow submitted: {workflow_id}")
                    
                    # Wait a bit for execution
                    print("\n2. Waiting for execution...")
                    await asyncio.sleep(3)
                    
                    # Get workflow status
                    print("\n3. Getting workflow status...")
                    status_url = f"http://localhost:8080/workflows/{workflow_id}"
                    async with session.get(status_url) as status_resp:
                        if status_resp.status == 200:
                            status_data = await status_resp.json()
                            print(f"✅ Workflow status: {status_data.get('status')}")
                            
                            # Show task statuses
                            tasks = status_data.get('tasks', [])
                            if tasks:
                                print("\nTask statuses:")
                                for task in tasks:
                                    print(f"  - {task.get('name')}: {task.get('status')}")
                        else:
                            print(f"❌ Failed to get status: {status_resp.status}")
                    
                    # Get results
                    print("\n4. Getting workflow results...")
                    results_url = f"http://localhost:8080/workflows/{workflow_id}/results"
                    async with session.get(results_url) as results_resp:
                        if results_resp.status == 200:
                            results = await results_resp.json()
                            print(f"✅ Got results:")
                            print(json.dumps(results, indent=2))
                        else:
                            text = await results_resp.text()
                            print(f"❌ Failed to get results: {results_resp.status}")
                            print(f"Response: {text}")
                    
                    return True
                    
                else:
                    error = await response.text()
                    print(f"❌ Failed to submit: {response.status}")
                    print(f"Error: {error}")
                    return False
                    
        except aiohttp.ClientConnectorError:
            print("❌ Could not connect to server at localhost:8080")
            print("Make sure the server is running: gleitzeit serve --port 8080")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    success = asyncio.run(test_workflow())
    sys.exit(0 if success else 1)