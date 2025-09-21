#!/usr/bin/env python3
"""
Simple workflow test without WebSocket dependency.
"""

import requests
import json
import uuid
import time

def test_simple_workflow():
    """Test simple workflow submission and execution."""
    
    base_url = "http://localhost:8000"
    
    print("SIMPLE WORKFLOW TEST")
    print("=" * 60)
    
    # 1. Check auth
    print("\n1. Checking authentication...")
    response = requests.get(f"{base_url}/auth/me")
    if response.status_code == 200:
        user = response.json()
        print(f"   User: {user.get('username')} (role: {user.get('role')})")
    else:
        print(f"   Auth failed: {response.text}")
        return
    
    # 2. Create workflow
    workflow = {
        "id": str(uuid.uuid4()),
        "name": "Simple Test Workflow",
        "tasks": [
            {
                "id": str(uuid.uuid4()),
                "name": "Add Numbers",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/test_tasks/calculate.py",
                    "function": "add_numbers",
                    "args": [5, 3]
                }
            }
        ]
    }
    
    # 3. Submit workflow
    print("\n2. Submitting workflow...")
    print(f"   Workflow: {workflow['name']}")
    print(f"   Tasks: {len(workflow['tasks'])}")
    
    response = requests.post(
        f"{base_url}/workflows",
        json={"workflow": workflow}
    )
    
    if response.status_code == 200:
        result = response.json()
        workflow_id = result.get("workflow_id", workflow["id"])
        print(f"   ✓ Submitted: {workflow_id}")
        print(f"   Status: {result.get('status')}")
        
        # 4. Wait and check status
        print("\n3. Checking workflow status...")
        for i in range(10):
            time.sleep(2)
            response = requests.get(f"{base_url}/workflows/{workflow_id}")
            if response.status_code == 200:
                workflow_data = response.json()
                status = workflow_data.get("status")
                print(f"   Attempt {i+1}: {status}")
                
                if status in ["completed", "failed"]:
                    print(f"\n4. Final status: {status}")
                    
                    # Check task results
                    if "tasks" in workflow_data:
                        for task in workflow_data["tasks"]:
                            print(f"   Task '{task['name']}': {task.get('status')}")
                            if task.get("result"):
                                print(f"     Result: {task['result']}")
                            if task.get("error"):
                                print(f"     Error: {task['error']}")
                    
                    # Get results
                    print("\n5. Getting workflow results...")
                    response = requests.get(f"{base_url}/workflows/{workflow_id}/results")
                    if response.status_code == 200:
                        results = response.json()
                        print(f"   Results: {json.dumps(results, indent=2)}")
                    else:
                        print(f"   Failed to get results: {response.text}")
                    
                    break
            else:
                print(f"   Failed to get status: {response.text}")
                break
        else:
            print("\n   Timeout: Workflow did not complete in time")
    else:
        print(f"   ✗ Failed: {response.status_code}")
        print(f"   Error: {response.text}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")

if __name__ == "__main__":
    test_simple_workflow()