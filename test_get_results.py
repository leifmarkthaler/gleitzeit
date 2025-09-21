#!/usr/bin/env python3
"""
Test retrieving workflow results via API.
"""

import sys
import requests
import json

def test_get_results():
    """Test getting workflow results through API."""
    print("\n=== Testing Result Retrieval via API ===\n")
    
    base_url = "http://localhost:8000"
    workflow_id = "cbb4bfe1-f21f-4e98-996d-f0842f8721fa"
    
    # 1. Try to get workflow status
    print(f"1. Getting workflow status for {workflow_id}...")
    try:
        response = requests.get(f"{base_url}/workflows/{workflow_id}")
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Workflow Status: {data.get('status')}")
            print(f"   Response: {json.dumps(data, indent=2)}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Failed: {e}")
    
    # 2. Try to get workflow results
    print(f"\n2. Getting workflow results...")
    try:
        response = requests.get(f"{base_url}/workflows/{workflow_id}/results")
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Results: {json.dumps(data, indent=2)}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Failed: {e}")
    
    # 3. Try with a session/auth token (simulate basic auth)
    print(f"\n3. Trying with basic auth header...")
    headers = {
        "Authorization": "Basic basic-session"  # This would normally be a real session
    }
    try:
        response = requests.get(f"{base_url}/workflows/{workflow_id}", headers=headers)
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Workflow Status: {data.get('status')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Failed: {e}")
    
    # 4. Try to get task results directly
    task_id = "21541a07-cfe1-4432-aafe-27002cb5eac3"
    print(f"\n4. Getting task results for {task_id}...")
    try:
        response = requests.get(f"{base_url}/tasks/{task_id}/result")
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Task Result: {json.dumps(data, indent=2)}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Failed: {e}")

if __name__ == "__main__":
    test_get_results()