#!/usr/bin/env python3
"""
Test script to validate authentication mode behavior
"""

import asyncio
import os
import httpx
import json
from pathlib import Path

# Test configuration
BASE_URL = "http://localhost:8000"

async def test_basic_mode():
    """Test basic mode behavior"""
    print("\n=== Testing Basic Mode ===")
    os.environ["GLEITZEIT_AUTH_MODE"] = "basic"
    
    async with httpx.AsyncClient() as client:
        # Test auth status
        print("\n1. Testing auth status...")
        resp = await client.get(f"{BASE_URL}/auth/status")
        if resp.status_code == 200:
            data = resp.json()
            assert data["mode"] == "basic", f"Expected basic mode, got {data['mode']}"
            assert data["requires_login"] == False, "Basic mode should not require login"
            assert data["basic_user"] == "basic@localhost", "Should have basic user"
            print("✅ Auth status correct for basic mode")
        else:
            print(f"❌ Auth status failed: {resp.status_code}")
        
        # Test current user
        print("\n2. Testing current user...")
        resp = await client.get(f"{BASE_URL}/auth/me")
        if resp.status_code == 200:
            user = resp.json()
            assert user["id"] == "basic-user", "Should be basic user"
            assert user["email"] == "basic@localhost", "Should have basic email"
            assert user["is_superuser"] == False, "Basic user should not be superuser"
            print("✅ Current user is basic user")
        else:
            print(f"❌ Current user failed: {resp.status_code}")
        
        # Test workflow creation (should work)
        print("\n3. Testing workflow creation...")
        workflow_data = {
            "name": "Test Workflow",
            "tasks": [
                {
                    "name": "test_task",
                    "type": "test",
                    "params": {"test": "data"}
                }
            ]
        }
        resp = await client.post(f"{BASE_URL}/workflows", json=workflow_data)
        if resp.status_code in [200, 201]:
            print("✅ Workflow creation allowed in basic mode")
        else:
            print(f"❌ Workflow creation failed: {resp.status_code}")
        
        # Test API key creation (should fail)
        print("\n4. Testing API key creation (should be blocked)...")
        api_key_data = {
            "name": "Test Key",
            "description": "Should not work in basic mode"
        }
        resp = await client.post(f"{BASE_URL}/auth/api-keys", json=api_key_data)
        if resp.status_code == 403:
            data = resp.json()
            assert "admin mode" in data["detail"].lower(), "Should mention admin mode requirement"
            print("✅ API key creation correctly blocked in basic mode")
        else:
            print(f"❌ API key creation not blocked: {resp.status_code}")
        
        # Test user registration (should fail)
        print("\n5. Testing user registration (should be blocked)...")
        register_data = {
            "email": "test@example.com",
            "password": "testpass123",
            "username": "testuser"
        }
        resp = await client.post(f"{BASE_URL}/auth/register", json=register_data)
        if resp.status_code == 403:
            data = resp.json()
            assert "admin mode" in data["detail"].lower(), "Should mention admin mode requirement"
            print("✅ User registration correctly blocked in basic mode")
        else:
            print(f"❌ User registration not blocked: {resp.status_code}")
        
        # Test role listing (should fail)
        print("\n6. Testing role listing (should be blocked)...")
        resp = await client.get(f"{BASE_URL}/auth/roles")
        if resp.status_code == 403:
            data = resp.json()
            assert "admin mode" in data["detail"].lower(), "Should mention admin mode requirement"
            print("✅ Role listing correctly blocked in basic mode")
        else:
            print(f"❌ Role listing not blocked: {resp.status_code}")
        
        # Test user listing (should fail)
        print("\n7. Testing user listing (should be blocked)...")
        resp = await client.get(f"{BASE_URL}/auth/users")
        if resp.status_code == 403:
            data = resp.json()
            assert "admin mode" in data["detail"].lower(), "Should mention admin mode requirement"
            print("✅ User listing correctly blocked in basic mode")
        else:
            print(f"❌ User listing not blocked: {resp.status_code}")

async def test_admin_mode():
    """Test admin mode behavior"""
    print("\n=== Testing Admin Mode ===")
    os.environ["GLEITZEIT_AUTH_MODE"] = "admin"
    
    async with httpx.AsyncClient() as client:
        # Test auth status
        print("\n1. Testing auth status...")
        resp = await client.get(f"{BASE_URL}/auth/status")
        if resp.status_code == 200:
            data = resp.json()
            assert data["mode"] == "admin", f"Expected admin mode, got {data['mode']}"
            assert data["requires_login"] == True, "Admin mode should require login"
            assert data["basic_user"] is None, "Should not have basic user"
            print("✅ Auth status correct for admin mode")
        else:
            print(f"❌ Auth status failed: {resp.status_code}")
        
        # Test current user (should fail without auth)
        print("\n2. Testing current user without auth...")
        resp = await client.get(f"{BASE_URL}/auth/me")
        if resp.status_code == 401:
            print("✅ Current user correctly requires auth in admin mode")
        else:
            print(f"❌ Current user should require auth: {resp.status_code}")
        
        # Test workflow creation without auth (should fail)
        print("\n3. Testing workflow creation without auth...")
        workflow_data = {
            "name": "Test Workflow",
            "tasks": [
                {
                    "name": "test_task",
                    "type": "test",
                    "params": {"test": "data"}
                }
            ]
        }
        resp = await client.post(f"{BASE_URL}/workflows", json=workflow_data)
        if resp.status_code == 401:
            print("✅ Workflow creation requires auth in admin mode")
        else:
            print(f"❌ Workflow creation should require auth: {resp.status_code}")

def main():
    """Run tests"""
    print("Testing Gleitzeit Authentication Modes")
    print("=" * 50)
    print("\nNote: This test assumes the API server is running on localhost:8000")
    print("Start it with: python -m gleitzeit.api.app")
    print("\nPress Ctrl+C to skip if the server is not running.\n")
    
    loop = asyncio.get_event_loop()
    
    try:
        # Test basic mode
        loop.run_until_complete(test_basic_mode())
        
        # Test admin mode
        loop.run_until_complete(test_admin_mode())
        
        print("\n" + "=" * 50)
        print("✅ All tests completed!")
        
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")

if __name__ == "__main__":
    main()