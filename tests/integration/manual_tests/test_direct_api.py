#!/usr/bin/env python3
"""Direct API test for workflow status"""

import requests
import time
import yaml

# Load workflow
with open("test_workflow.yaml", "r") as f:
    workflow_data = yaml.safe_load(f)

print(f"📋 Submitting workflow: {workflow_data['name']}")

# Submit workflow
response = requests.post(
    "http://localhost:8001/workflows",
    json={"workflow": workflow_data}
)

if response.status_code == 200:
    workflow_id = response.json()["workflow_id"]
    print(f"✅ Workflow submitted: {workflow_id}")
    
    # Monitor workflow
    print("\n⏳ Monitoring workflow (expecting tasks to fail after 3 retries)...")
    
    for i in range(30):
        # Get status
        status_resp = requests.get(f"http://localhost:8001/workflows/{workflow_id}")
        
        if status_resp.status_code == 200:
            workflow = status_resp.json()
            status = workflow.get("status", "unknown")
            
            # Get task statuses
            task_statuses = {}
            if "tasks" in workflow:
                for task in workflow["tasks"]:
                    task_id = task.get("id", "unknown")
                    task_status = task.get("status", "unknown") 
                    task_statuses[task_id] = task_status
            
            print(f"\r[{i+1}s] Workflow: {status} | Tasks: {task_statuses}", end="", flush=True)
            
            if status in ["completed", "failed"]:
                print(f"\n\n🏁 Final workflow status: {status}")
                
                if status == "failed":
                    print("✅ TEST PASSED: Workflow correctly marked as FAILED")
                else:
                    print("❌ TEST FAILED: Workflow should be FAILED when all tasks fail")
                break
        
        time.sleep(1)
else:
    print(f"❌ Failed to submit: {response.status_code}")
    print(response.text)