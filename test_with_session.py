#!/usr/bin/env python3
"""
Test workflow submission and retrieval with proper session handling.
"""

import requests
import json
import uuid

def test_with_session():
    """Test workflow submission and retrieval using session cookies."""
    
    base_url = "http://localhost:8000"
    
    # Use a session to maintain cookies
    session = requests.Session()
    
    print("WORKFLOW TEST WITH SESSION")
    print("=" * 60)
    
    # 1. Get current user (this will create/get basic session)
    print("\n1. Getting current user...")
    response = session.get(f"{base_url}/auth/me")
    if response.status_code == 200:
        user = response.json()
        print(f"   User: {user.get('username')} (id: {user.get('id')})")
        print(f"   Role: {user.get('role')}")
    else:
        print(f"   Failed: {response.text}")
        return
    
    # 2. Submit workflow
    workflow_id = str(uuid.uuid4())
    workflow = {
        "id": workflow_id,
        "name": "Test Workflow with Session",
        "tasks": [
            {
                "id": str(uuid.uuid4()),
                "name": "Add Numbers",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/test_tasks/calculate.py",
                    "function": "add_numbers",
                    "args": [10, 20]
                }
            }
        ]
    }
    
    print("\n2. Submitting workflow...")
    print(f"   Workflow ID: {workflow_id}")
    response = session.post(
        f"{base_url}/workflows",
        json={"workflow": workflow}
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"   ✓ Submitted successfully")
        submitted_id = result.get("workflow_id", workflow_id)
    else:
        print(f"   ✗ Failed: {response.text}")
        return
    
    # 3. Get workflow back (using same session)
    print("\n3. Retrieving workflow...")
    response = session.get(f"{base_url}/workflows/{submitted_id}")
    
    if response.status_code == 200:
        workflow_data = response.json()
        print(f"   ✓ Retrieved successfully")
        print(f"   Status: {workflow_data.get('status')}")
        print(f"   User ID: {workflow_data.get('user_id')}")
        print(f"   Tasks: {len(workflow_data.get('tasks', []))}")
        
        # Check if it's the same user
        if workflow_data.get('user_id') == user.get('id'):
            print(f"   ✓ User ID matches!")
        else:
            print(f"   ✗ User ID mismatch: {workflow_data.get('user_id')} != {user.get('id')}")
    else:
        print(f"   ✗ Failed: {response.status_code}")
        print(f"   Error: {response.text}")
    
    # 4. Check session cookie
    print("\n4. Session info...")
    if 'session_id' in session.cookies:
        print(f"   Session ID: {session.cookies['session_id']}")
    else:
        print("   No session cookie found")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")

if __name__ == "__main__":
    test_with_session()