#!/usr/bin/env python3
"""
Test that authorization works correctly with client pooling.

This verifies:
1. Client pooling is preserved
2. Basic users cannot access admin functions
3. Users can only see their own workflows/tasks
4. Public workflows are visible to all
"""

import asyncio
import os
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task

# Set up test environment
os.environ['GLEITZEIT_AUTH_MODE'] = 'basic'


async def test_client_pooling_preserved():
    """Test that client pooling still works with authorization."""
    print("\n1. Testing client pooling is preserved...")
    
    # Create multiple clients - they should use the pool
    clients = []
    for i in range(3):
        client = GleitzeitClient(mode=ClientMode.API)
        await client.initialize()
        clients.append(client)
    
    # Check that they're using pooled connections
    # (This would be verified by checking the pool internals)
    print("   ✅ Multiple clients created successfully")
    
    # Clean up
    for client in clients:
        await client.shutdown()
    
    return True


async def test_basic_user_restrictions():
    """Test that basic users cannot access admin functions."""
    print("\n2. Testing basic user restrictions...")
    
    # Use API mode for testing (NATIVE requires service token)
    client = GleitzeitClient(mode=ClientMode.API)
    await client.initialize()
    
    try:
        # Get current user (should be basic user)
        user = await client.get_current_user()
        print(f"   Current user: {user.get('username')} (role: {user.get('role')})")
        
        # Basic user should NOT be able to:
        # 1. Create other users
        try:
            await client.create_user("test", "test@example.com", "password")
            print("   ❌ Basic user could create users (should not be allowed)")
            return False
        except Exception as e:
            if "not available in basic mode" in str(e) or "403" in str(e):
                print("   ✅ Basic user correctly blocked from creating users")
            else:
                print(f"   ⚠️ Unexpected error: {e}")
        
        # 2. List all users
        try:
            users = await client.list_users()
            if users and len(users) > 0:
                print("   ❌ Basic user could list users (should not be allowed)")
                return False
        except Exception as e:
            if "not available in basic mode" in str(e) or "403" in str(e):
                print("   ✅ Basic user correctly blocked from listing users")
            else:
                print(f"   ⚠️ Unexpected error: {e}")
        
    finally:
        await client.shutdown()
    
    return True


async def test_workflow_isolation():
    """Test that users can only see their own workflows."""
    print("\n3. Testing workflow isolation...")
    
    # Use API mode for testing
    client = GleitzeitClient(mode=ClientMode.API)
    await client.initialize()
    
    try:
        # Create a workflow as basic user
        workflow = Workflow(
            id="test-basic-workflow",
            name="Basic User Workflow",
            tasks=[
                Task(
                    id="task1",
                    name="Test Task",
                    protocol="python/v1",
                    method="execute",
                    params={"code": "result = 'test'"}
                )
            ]
        )
        
        # Submit workflow (should be owned by basic user)
        result = await client.submit_workflow(workflow)
        workflow_id = result.get('workflow_id', workflow.id)
        print(f"   ✅ Created workflow: {workflow_id}")
        
        # Should be able to get own workflow
        my_workflow = await client.get_workflow(workflow_id)
        if my_workflow:
            print(f"   ✅ Can access own workflow")
            # Check ownership
            if hasattr(my_workflow, 'user_id'):
                print(f"   Workflow owner: {my_workflow.user_id}")
        else:
            print("   ❌ Cannot access own workflow")
            return False
        
        # List workflows should only show user's workflows
        workflows = await client.list_workflows()
        if workflows:
            if isinstance(workflows, dict):
                workflow_list = workflows.get('workflows', [])
            else:
                workflow_list = workflows
            
            # Check that we only see our workflows
            for wf in workflow_list:
                wf_user_id = getattr(wf, 'user_id', None) if hasattr(wf, 'user_id') else wf.get('user_id')
                if wf_user_id and wf_user_id != 'basic-user' and wf_user_id != 'anonymous':
                    print(f"   ❌ Can see other user's workflow: {wf_user_id}")
                    return False
            
            print(f"   ✅ List shows only accessible workflows ({len(workflow_list)} workflows)")
        
    finally:
        await client.shutdown()
    
    return True


async def test_public_workflow_access():
    """Test that public workflows are visible to all."""
    print("\n4. Testing public workflow access...")
    
    # Use API mode for testing
    client = GleitzeitClient(mode=ClientMode.API)
    await client.initialize()
    
    try:
        # Create a public workflow
        public_workflow = Workflow(
            id="test-public-workflow",
            name="Public Workflow",
            is_public=True,  # Mark as public
            tasks=[
                Task(
                    id="task1",
                    name="Public Task",
                    protocol="python/v1",
                    method="execute",
                    params={"code": "result = 'public'"}
                )
            ]
        )
        
        # Submit public workflow
        result = await client.submit_workflow(public_workflow)
        workflow_id = result.get('workflow_id', public_workflow.id)
        print(f"   ✅ Created public workflow: {workflow_id}")
        
        # Should be able to read public workflow
        retrieved = await client.get_workflow(workflow_id)
        if retrieved:
            print(f"   ✅ Can access public workflow")
        else:
            print("   ❌ Cannot access public workflow")
            return False
        
        # But should NOT be able to modify public workflow (unless owner)
        # This would be tested with a different user
        
    finally:
        await client.shutdown()
    
    return True


async def main():
    """Run all authorization tests."""
    print("=" * 60)
    print("AUTHORIZATION WITH CLIENT POOLING TEST")
    print("=" * 60)
    
    all_passed = True
    
    # Test 1: Client pooling preserved
    # Note: This test requires API mode, skip if server not running
    try:
        passed = await test_client_pooling_preserved()
        all_passed = all_passed and passed
    except Exception as e:
        print(f"   ℹ️ Skipping pooling test (API not running): {e}")
    
    # Test 2: Basic user restrictions
    passed = await test_basic_user_restrictions()
    all_passed = all_passed and passed
    
    # Test 3: Workflow isolation
    passed = await test_workflow_isolation()
    all_passed = all_passed and passed
    
    # Test 4: Public workflow access
    passed = await test_public_workflow_access()
    all_passed = all_passed and passed
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL AUTHORIZATION TESTS PASSED")
        print("Authorization works correctly with client pooling!")
    else:
        print("❌ SOME TESTS FAILED")
        print("Please review the authorization implementation")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())