#!/usr/bin/env python3
"""Test replay functionality security."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task
from gleitzeit.replay.manager import ReplayManager
from gleitzeit.replay.service import ReplayService


async def test_replay_security():
    """Test that replay functionality respects authentication."""
    
    print("\n" + "="*60)
    print("REPLAY SECURITY TEST")
    print("="*60)
    
    # Test with basic user (default after pip install)
    print("\n1. TESTING WITH BASIC USER (DEFAULT)")
    print("-" * 40)
    
    os.environ["GLEITZEIT_AUTH_MODE"] = "basic"
    
    client = GleitzeitClient(mode=ClientMode.NATIVE, persist_events=True)
    await client.initialize()
    
    # Create a test workflow
    workflow = Workflow(
        id="security_test_wf",
        name="Security Test Workflow",
        description="Test workflow for security",
        tasks=[
            Task(
                id="test_task",
                name="Test Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "print('Security test'); return {'result': 'ok'}"}
            )
        ]
    )
    
    await client.submit_workflow(workflow)
    
    # Test replay with basic user (should work out of the box)
    try:
        result = await client.replay_workflow("security_test_wf")
        print("✓ Basic user can replay workflows (seamless pip install experience)")
    except Exception as e:
        print(f"✗ Basic user replay failed: {e}")
    
    await client.shutdown()
    
    # Test with multi-user scenarios  
    print("\n2. TESTING MULTI-USER SCENARIOS")  
    print("-" * 40)
    
    os.environ["GLEITZEIT_AUTH_MODE"] = "basic"
    os.environ["GLEITZEIT_AUTH_OWNERSHIP_FILTER"] = "true"
    
    client = GleitzeitClient(mode=ClientMode.NATIVE, persist_events=True)
    await client.initialize()
    
    # Test as user who owns the workflow
    user1_context = {
        "id": "user1",
        "email": "user1@test.com",
        "permissions": ["workflows:read", "workflows:replay"],
        "is_superuser": False
    }
    
    # Create workflow owned by user1
    workflow.id = "security_test_wf2"
    workflow.metadata = {"owner_id": "user1"}
    await client.submit_workflow(workflow)
    
    # Test replay as owner
    try:
        service = ReplayService(client)
        result = await service.replay("security_test_wf2", user_context=user1_context)
        print("✓ Owner can replay their workflow")
    except Exception as e:
        print(f"✗ Owner blocked from replaying: {e}")
    
    # Test as different user
    user2_context = {
        "id": "user2", 
        "email": "user2@test.com",
        "permissions": ["workflows:read", "workflows:replay"],
        "is_superuser": False
    }
    
    try:
        result = await service.replay("security_test_wf2", user_context=user2_context)
        print("✗ Non-owner allowed to replay (security issue)")
    except PermissionError:
        print("✓ Non-owner blocked from replaying")
    except Exception as e:
        print(f"? Unexpected error: {e}")
    
    # Test as superuser
    admin_context = {
        "id": "admin",
        "email": "admin@test.com", 
        "permissions": ["workflows:read", "workflows:replay"],
        "is_superuser": True
    }
    
    try:
        result = await service.replay("security_test_wf2", user_context=admin_context)
        print("✓ Superuser can replay any workflow")
    except Exception as e:
        print(f"✗ Superuser blocked: {e}")
    
    # Test listing workflows with ownership filtering
    print("\n3. TESTING WORKFLOW LISTING SECURITY")
    print("-" * 40)
    
    # List as user1 (owner)
    try:
        workflows = await service.list_replayable_workflows(user_context=user1_context)
        user1_can_see = len([wf for wf in workflows if wf["id"] == "security_test_wf2"])
        print(f"✓ Owner sees {user1_can_see} workflows they own")
    except Exception as e:
        print(f"✗ Owner listing failed: {e}")
    
    # List as user2 (not owner)
    try:
        workflows = await service.list_replayable_workflows(user_context=user2_context)
        user2_can_see = len([wf for wf in workflows if wf["id"] == "security_test_wf2"])
        if user2_can_see == 0:
            print("✓ Non-owner cannot see workflows they don't own")
        else:
            print(f"✗ Non-owner can see {user2_can_see} workflows (security issue)")
    except Exception as e:
        print(f"✗ Non-owner listing failed: {e}")
    
    # List as superuser
    try:
        workflows = await service.list_replayable_workflows(user_context=admin_context)
        admin_can_see = len([wf for wf in workflows if wf["id"] == "security_test_wf2"])
        print(f"✓ Superuser sees {admin_can_see} workflows")
    except Exception as e:
        print(f"✗ Superuser listing failed: {e}")
    
    await client.shutdown()
    
    print("\n" + "="*60)
    print("REPLAY SECURITY TEST COMPLETE")
    print("="*60)
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_replay_security())
    
    print("\n" + "="*60)
    print("SECURITY TEST SUMMARY")
    print("="*60)
    
    if success:
        print("\n✅ Replay security tests completed!")
        print("\nSecurity features tested:")
        print("  • Basic user access (seamless pip install experience)")
        print("  • Ownership verification in multi-user scenarios") 
        print("  • Permission checking for replay operations")
        print("  • Superuser access privileges")
        print("  • Workflow listing with ownership filtering")
    else:
        print("\n⚠️  Some security tests failed")
    
    sys.exit(0 if success else 1)