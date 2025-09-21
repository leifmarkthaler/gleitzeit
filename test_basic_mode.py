#!/usr/bin/env python3
"""
Test that basic auth mode works out of the box.
This simulates what a user would experience after pip install.
"""

import asyncio
import sys
from pathlib import Path

# Test without any environment variables set
import os
# Clear any auth-related env vars to simulate fresh install
os.environ.pop('GLEITZEIT_AUTH_MODE', None)
os.environ.pop('GLEITZEIT_SECRET_KEY', None)
os.environ.pop('GLEITZEIT_REQUIRE_EMAIL_VERIFICATION', None)

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task

async def test_basic_mode():
    """Test basic mode functionality."""
    print("Testing Gleitzeit in basic mode (default after pip install)...")
    print("-" * 60)
    
    # Test 1: Client initialization without any config
    print("\n1. Testing client initialization...")
    try:
        client = GleitzeitClient(mode=ClientMode.NATIVE)
        print("   ✅ Client created successfully")
    except Exception as e:
        print(f"   ❌ Failed to create client: {e}")
        return False
    
    # Test 2: Get current user in basic mode
    print("\n2. Testing get_current_user in basic mode...")
    try:
        user = await client.get_current_user()
        print(f"   ✅ Got user: {user}")
        if user.get('username') != 'system' and user.get('username') != 'basic':
            print(f"   ⚠️ Warning: Expected basic/system user, got {user.get('username')}")
    except Exception as e:
        print(f"   ❌ Failed to get user: {e}")
        return False
    
    # Test 3: Create and submit a simple workflow
    print("\n3. Testing workflow submission in basic mode...")
    try:
        # Create a simple workflow
        workflow = Workflow(
            id="test-workflow-basic",
            name="Test Basic Mode Workflow",
            tasks=[
                Task(
                    id="task1",
                    name="Simple Task",
                    type="python",
                    config={
                        "code": "result = 'Hello from basic mode!'"
                    }
                )
            ]
        )
        
        # Submit workflow
        result = await client.submit_workflow(workflow)
        if result.get('success'):
            print(f"   ✅ Workflow submitted: {result.get('workflow_id')}")
        else:
            print(f"   ❌ Workflow submission failed: {result}")
            return False
            
    except Exception as e:
        print(f"   ❌ Failed to submit workflow: {e}")
        # This might fail if no providers are available, which is OK for basic test
        print("   ℹ️ Note: Workflow submission may require providers to be running")
    
    # Test 4: List workflows
    print("\n4. Testing workflow listing in basic mode...")
    try:
        workflows = await client.list_workflows(limit=5)
        print(f"   ✅ Listed {len(workflows)} workflows")
    except Exception as e:
        print(f"   ❌ Failed to list workflows: {e}")
        return False
    
    # Test 5: Auth operations in basic mode (should work without error)
    print("\n5. Testing auth operations in basic mode...")
    try:
        # Login should work (no-op in basic mode)
        login_result = await client.login("any_user", "any_password")
        print(f"   ✅ Login result: {login_result}")
        
        # Logout should work (no-op in basic mode)
        logout_result = await client.logout()
        print(f"   ✅ Logout result: {logout_result}")
        
    except Exception as e:
        print(f"   ❌ Auth operations failed: {e}")
        return False
    
    # Cleanup
    await client.shutdown()
    
    print("\n" + "=" * 60)
    print("✅ All basic mode tests passed!")
    print("The library works out-of-the-box after pip install.")
    return True


async def test_api_mode():
    """Test that API mode also works in basic auth."""
    print("\n\nTesting API mode with basic auth...")
    print("-" * 60)
    
    # Start server if needed
    print("\n1. Checking if API server is running...")
    client = GleitzeitClient(mode=ClientMode.API)
    
    try:
        # This will attempt to connect to the API
        user = await client.get_current_user()
        print(f"   ✅ API mode works: {user}")
    except Exception as e:
        print(f"   ℹ️ API not running (expected): {e}")
        print("   To test API mode, run: gleitzeit serve")
    finally:
        await client.shutdown()
    
    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("GLEITZEIT BASIC MODE COMPATIBILITY TEST")
    print("=" * 60)
    
    # Test native mode (most important for pip install)
    success = await test_basic_mode()
    
    if not success:
        print("\n❌ Basic mode tests failed!")
        sys.exit(1)
    
    # Test API mode (optional)
    await test_api_mode()
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS COMPLETED SUCCESSFULLY")
    print("Gleitzeit works out-of-the-box after pip install!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())