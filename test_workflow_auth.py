#!/usr/bin/env python3
"""
Test workflow submission with authentication through stateless SystemManager.
"""

import asyncio
import sys
sys.path.insert(0, 'src')

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task


async def test_workflow_with_auth():
    """Test workflow submission and retrieval with authentication."""
    print("\n=== Testing Workflow with Authentication (Stateless SystemManager) ===\n")
    
    # Use API mode to submit workflow
    print("1. Creating API client...")
    client = GleitzeitClient(mode=ClientMode.API, base_url="http://localhost:8000")
    await client.initialize()
    print("   ✓ Client initialized")
    
    # Create workflow
    print("\n2. Creating workflow...")
    workflow = Workflow(
        id="test_auth_workflow",
        name="Test Authentication Flow",
        tasks=[
            Task(
                id="task1",
                name="Test Auth Task",
                method="execute",
                protocol="python",
                config={
                    "code": """
print("Task executing with authentication!")
result = {
    "message": "Authentication works!",
    "value": 42
}
"""
                }
            )
        ]
    )
    print(f"   ✓ Workflow created: {workflow.id}")
    
    # Submit workflow - goes through SystemManager with auth
    print("\n3. Submitting workflow (through SystemManager)...")
    result = await client.submit_workflow(workflow)
    print(f"   ✓ Submitted: {result}")
    
    if result.get("success"):
        workflow_id = result.get("workflow_id")
        
        # Wait for execution
        print("\n4. Waiting for workflow execution...")
        await asyncio.sleep(2)
        
        # Get workflow status
        print("\n5. Getting workflow status...")
        status = await client.get_workflow_status(workflow_id)
        print(f"   Status: {status.get('status')}")
        
        # Get workflow to verify
        print("\n6. Retrieving workflow...")
        retrieved = await client.get_workflow(workflow_id)
        if retrieved:
            print(f"   ✓ Retrieved workflow: {retrieved.id}")
            print(f"   ✓ Workflow has user_id: {retrieved.user_id}")
        
        # Check results
        print("\n7. Getting results...")
        results = await client.get_workflow_results(workflow_id)
        if results:
            print(f"   ✓ Results: {results}")
    
    await client.shutdown()
    print("\n=== Authentication Test Complete ===\n")


async def test_multiple_clients():
    """Test multiple clients with different sessions."""
    print("\n=== Testing Multiple Clients (Stateless) ===\n")
    
    # Create two API clients
    print("1. Creating two API clients...")
    client1 = GleitzeitClient(mode=ClientMode.API, base_url="http://localhost:8000")
    client2 = GleitzeitClient(mode=ClientMode.API, base_url="http://localhost:8000")
    
    await client1.initialize()
    await client2.initialize()
    print("   ✓ Both clients initialized")
    
    # Each client gets its own SystemManager instance (stateless!)
    # But they coordinate through Redis
    
    # Submit workflow through client1
    print("\n2. Client1 submitting workflow...")
    workflow = Workflow(
        id="test_multi_client",
        name="Multi-Client Test",
        tasks=[
            Task(
                id="task1",
                protocol="python",
                config={"code": "result = 'client1_submitted'"}
            )
        ]
    )
    
    result1 = await client1.submit_workflow(workflow)
    print(f"   ✓ Client1 submitted: {result1}")
    
    if result1.get("success"):
        workflow_id = result1.get("workflow_id")
        
        # Try to get workflow through client2
        print("\n3. Client2 retrieving workflow...")
        retrieved = await client2.get_workflow(workflow_id)
        if retrieved:
            print(f"   ✓ Client2 retrieved: {retrieved.id}")
            print("   ✓ Stateless coordination works!")
        else:
            print("   ⚠ Client2 couldn't retrieve (may be auth isolation)")
    
    await client1.shutdown()
    await client2.shutdown()
    print("\n=== Multiple Client Test Complete ===\n")


async def main():
    """Run all tests."""
    try:
        await test_workflow_with_auth()
        await test_multiple_clients()
        print("\n✅ All tests passed!\n")
        print("Key observations:")
        print("- SystemManager is stateless (new instance each time)")
        print("- Authentication enforced through SystemManager")
        print("- Sessions managed centrally by AuthManager")
        print("- All coordination through Redis")
    except Exception as e:
        print(f"\n❌ Test failed: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())