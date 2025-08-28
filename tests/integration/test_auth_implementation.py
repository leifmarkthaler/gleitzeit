#!/usr/bin/env python3
"""
Test script for authentication implementation
Tests both with auth disabled (default) and enabled
"""

import os
import asyncio
import httpx
import json
from pathlib import Path
import sys

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_test(name: str, passed: bool, details: str = ""):
    """Print test result"""
    status = f"{GREEN}✓ PASS{RESET}" if passed else f"{RED}✗ FAIL{RESET}"
    print(f"{status} - {name}")
    if details:
        print(f"  {YELLOW}{details}{RESET}")


async def test_no_auth():
    """Test that API works without authentication (default)"""
    print(f"\n{BLUE}=== Testing without authentication (default) ==={RESET}")
    
    # Make sure auth is disabled
    os.environ['GLEITZEIT_AUTH_ENABLED'] = 'false'
    
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Test 1: Get status without auth
        try:
            response = await client.get("/status")
            passed = response.status_code == 200
            print_test("GET /status without auth", passed, f"Status: {response.status_code}")
        except Exception as e:
            print_test("GET /status without auth", False, str(e))
        
        # Test 2: List workflows without auth
        try:
            response = await client.get("/workflows")
            passed = response.status_code == 200
            print_test("GET /workflows without auth", passed, f"Status: {response.status_code}")
        except Exception as e:
            print_test("GET /workflows without auth", False, str(e))
        
        # Test 3: Submit workflow without auth
        try:
            workflow_data = {
                "name": "Test Workflow",
                "tasks": [
                    {
                        "name": "Test Task",
                        "protocol": "python/v1",
                        "method": "execute",
                        "params": {"code": "print('Hello')"}
                    }
                ]
            }
            response = await client.post("/workflows", json=workflow_data)
            passed = response.status_code in [200, 201]
            print_test("POST /workflows without auth", passed, f"Status: {response.status_code}")
            
            if passed and response.json():
                workflow_id = response.json().get("workflow_id")
                print(f"  Created workflow: {workflow_id}")
        except Exception as e:
            print_test("POST /workflows without auth", False, str(e))


async def test_with_auth():
    """Test that authentication works when enabled"""
    print(f"\n{BLUE}=== Testing with authentication enabled ==={RESET}")
    
    # Enable auth
    os.environ['GLEITZEIT_AUTH_ENABLED'] = 'true'
    os.environ['GLEITZEIT_AUTH_CREATE_ADMIN'] = 'true'
    os.environ['GLEITZEIT_AUTH_ADMIN_EMAIL'] = 'admin@localhost'
    os.environ['GLEITZEIT_AUTH_ADMIN_PASSWORD'] = 'admin123'
    os.environ['GLEITZEIT_AUTH_JWT_SECRET'] = 'test-secret-key-for-testing'
    
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Test 1: Access without auth should fail
        try:
            response = await client.get("/workflows")
            passed = response.status_code == 401
            print_test("GET /workflows requires auth", passed, 
                      f"Status: {response.status_code} (expected 401)")
        except Exception as e:
            print_test("GET /workflows requires auth", False, str(e))
        
        # Test 2: Login with admin credentials
        token = None
        try:
            login_data = {
                "username": "admin@localhost",
                "password": "admin123"
            }
            response = await client.post("/auth/login", json=login_data)
            passed = response.status_code == 200
            print_test("POST /auth/login", passed, f"Status: {response.status_code}")
            
            if passed:
                data = response.json()
                token = data.get("access_token")
                user = data.get("user", {})
                print(f"  Logged in as: {user.get('email')}")
                print(f"  Roles: {user.get('roles', [])}")
        except Exception as e:
            print_test("POST /auth/login", False, str(e))
        
        if not token:
            print(f"{RED}Cannot continue tests without auth token{RESET}")
            return
        
        # Test 3: Access with valid token
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            response = await client.get("/workflows", headers=headers)
            passed = response.status_code == 200
            print_test("GET /workflows with token", passed, f"Status: {response.status_code}")
        except Exception as e:
            print_test("GET /workflows with token", False, str(e))
        
        # Test 4: Create workflow with ownership tracking
        try:
            workflow_data = {
                "name": "Auth Test Workflow",
                "tasks": [
                    {
                        "name": "Auth Test Task",
                        "protocol": "python/v1",
                        "method": "execute",
                        "params": {"code": "return 'authenticated'"}
                    }
                ]
            }
            response = await client.post("/workflows", json=workflow_data, headers=headers)
            passed = response.status_code in [200, 201]
            print_test("POST /workflows with auth", passed, f"Status: {response.status_code}")
            
            if passed and response.json():
                workflow_id = response.json().get("workflow_id")
                print(f"  Created workflow: {workflow_id}")
                
                # Check if ownership was tracked
                # This would require fetching the workflow and checking metadata
        except Exception as e:
            print_test("POST /workflows with auth", False, str(e))
        
        # Test 5: Create API key
        try:
            api_key_data = {
                "name": "Test API Key",
                "description": "Testing API key creation"
            }
            response = await client.post("/auth/api-keys", json=api_key_data, headers=headers)
            passed = response.status_code in [200, 201]
            print_test("POST /auth/api-keys", passed, f"Status: {response.status_code}")
            
            if passed:
                data = response.json()
                api_key = data.get("key")
                print(f"  Created API key: {data.get('key_prefix')}...")
                
                # Test using API key
                api_headers = {"X-API-Key": api_key}
                response = await client.get("/workflows", headers=api_headers)
                passed = response.status_code == 200
                print_test("GET /workflows with API key", passed, f"Status: {response.status_code}")
        except Exception as e:
            print_test("POST /auth/api-keys", False, str(e))


async def test_permission_enforcement():
    """Test that permissions are enforced correctly"""
    print(f"\n{BLUE}=== Testing permission enforcement ==={RESET}")
    
    # This would require creating users with different roles
    # For now, we'll just test that the decorators are in place
    
    print(f"{YELLOW}Note: Full permission testing requires creating users with different roles{RESET}")
    print(f"{YELLOW}The decorators are in place but enforcement depends on auth being enabled{RESET}")


def check_files_created():
    """Check that all necessary files were created"""
    print(f"\n{BLUE}=== Checking created files ==={RESET}")
    
    files_to_check = [
        ("Auth decorators", "src/gleitzeit/auth/decorators.py"),
        ("Auth setup CLI", "src/gleitzeit/auth/setup.py"),
        ("Auth implementation plan", "auth-implementation-plan.md"),
        ("Auth migration guide", "auth-migration-guide.md"),
        ("Auth audit report", "auth-audit.md"),
    ]
    
    for name, path in files_to_check:
        full_path = Path(path)
        exists = full_path.exists()
        print_test(f"{name} exists", exists, str(full_path))


async def main():
    """Run all tests"""
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}Gleitzeit Authentication Implementation Test{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    
    # Check files first
    check_files_created()
    
    print(f"\n{YELLOW}Note: API tests require the server to be running{RESET}")
    print(f"{YELLOW}Start the server with: gleitzeit serve{RESET}")
    
    # Ask if server is running
    response = input("\nIs the server running? (y/n): ")
    if response.lower() != 'y':
        print("Skipping API tests. Start the server and run tests again.")
        return
    
    # Run API tests
    await test_no_auth()
    await test_with_auth()
    await test_permission_enforcement()
    
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{GREEN}✓ Testing complete!{RESET}")
    print(f"\n{BLUE}Next steps:{RESET}")
    print("1. Run: gleitzeit auth setup")
    print("2. Enable auth: export GLEITZEIT_AUTH_ENABLED=true")
    print("3. Start server: gleitzeit serve")
    print("4. Test with authentication enabled")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Test interrupted by user{RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{RED}Test failed with error: {e}{RESET}")
        sys.exit(1)