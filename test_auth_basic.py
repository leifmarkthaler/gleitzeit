#!/usr/bin/env python3
"""
Test that basic auth mode works correctly.
"""

import requests
import json

def test_basic_auth():
    """Test basic auth endpoints."""
    
    base_url = "http://localhost:8000"
    
    print("Testing Basic Auth Mode")
    print("=" * 60)
    
    # Test 1: Health check
    print("\n1. Health Check:")
    response = requests.get(f"{base_url}/health")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"   Backend: {data.get('pool_info', {}).get('backend')}")
    
    # Test 2: Get current user (should return basic user)
    print("\n2. Get Current User (no credentials):")
    response = requests.get(f"{base_url}/auth/me")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    
    if response.status_code == 200:
        user = response.json()
        print(f"   User: {user.get('username')} (role: {user.get('role')})")
        print(f"   ID: {user.get('id')}")
        print(f"   Permissions: {len(user.get('permissions', []))} permissions")
    
    # Test 3: Try with empty auth header
    print("\n3. Get Current User (empty Bearer token):")
    headers = {"Authorization": "Bearer "}
    response = requests.get(f"{base_url}/auth/me", headers=headers)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:100]}")
    
    # Test 4: Try to create a workflow
    print("\n4. Create Workflow (no credentials):")
    workflow = {
        "workflow": {
            "name": "Test Workflow",
            "tasks": []
        }
    }
    response = requests.post(f"{base_url}/workflows", json=workflow)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    
    # Test 5: Check what auth mode is configured
    print("\n5. Check System Configuration:")
    import os
    print(f"   GLEITZEIT_AUTH_MODE: {os.getenv('GLEITZEIT_AUTH_MODE', 'not set (defaults to basic)')}")
    print(f"   Server should be in basic mode by default")
    
    print("\n" + "=" * 60)
    print("Basic auth should allow operations without credentials")
    print("If auth is failing, the system is not properly configured for basic mode")

if __name__ == "__main__":
    test_basic_auth()