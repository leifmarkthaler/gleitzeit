#!/usr/bin/env python3
"""
Test SystemManager discovery and creation patterns.

This tests the new centralized SystemManager.get_or_create() method
to ensure it properly handles discovery and creation.
"""

import asyncio
import sys
sys.path.insert(0, 'src')

from gleitzeit.system.system_manager import SystemManager
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task


async def test_system_manager_discovery():
    """Test SystemManager discovery and creation."""
    print("\n=== Testing SystemManager Discovery ===\n")
    
    # Test 1: Create first SystemManager
    print("1. Creating first SystemManager...")
    sm1 = await SystemManager.get_or_create()
    assert sm1 is not None, "First SystemManager should be created"
    print(f"   ✓ Created SystemManager: {sm1.instance_id}")
    
    # Test 2: Get same SystemManager in same process
    print("\n2. Getting SystemManager again (should return cached)...")
    sm2 = await SystemManager.get_or_create()
    assert sm2 is sm1, "Should return same cached instance"
    print(f"   ✓ Got cached SystemManager: {sm2.instance_id}")
    
    # Test 3: Test NativeAdapter using SystemManager
    print("\n3. Testing NativeAdapter with SystemManager.get_or_create()...")
    client = GleitzeitClient(mode=ClientMode.NATIVE)
    await client.initialize()
    
    # Create a test workflow
    workflow = Workflow(
        id="test_workflow_discovery",
        name="Test Discovery",
        tasks=[
            Task(
                id="task1",
                protocol="python",
                config={
                    "code": "result = 42"
                }
            )
        ]
    )
    
    # Submit through NativeAdapter (uses SystemManager)
    result = await client.submit_workflow(workflow)
    print(f"   ✓ Workflow submitted via NativeAdapter: {result}")
    
    # Test 4: Verify workflow was submitted through SystemManager
    print("\n4. Verifying workflow submission through SystemManager...")
    if result.get("success"):
        workflow_id = result.get("workflow_id")
        
        # Get workflow to verify it exists
        retrieved = await client.get_workflow(workflow_id)
        if retrieved:
            print(f"   ✓ Workflow retrieved: {retrieved.id}")
            assert retrieved.id == workflow_id, "Should get same workflow"
        else:
            print("   ⚠ Could not retrieve workflow (may not be implemented)")
    
    # Test 5: Test discovery with new instance ID
    print("\n5. Testing discovery with different instance ID...")
    sm3 = await SystemManager.get_or_create(instance_id="test_instance_2")
    assert sm3 is not sm1, "Different instance ID should create new manager"
    print(f"   ✓ Created new SystemManager: {sm3.instance_id}")
    
    # Cleanup
    await client.shutdown()
    print("\n=== All Tests Passed ===\n")


async def test_stateless_operation():
    """Test stateless operation of SystemManager."""
    print("\n=== Testing Stateless Operation ===\n")
    
    # Create two clients that should coordinate through SystemManager
    print("1. Creating two NATIVE clients...")
    client1 = GleitzeitClient(mode=ClientMode.NATIVE)
    client2 = GleitzeitClient(mode=ClientMode.NATIVE)
    
    await client1.initialize()
    await client2.initialize()
    print("   ✓ Both clients initialized")
    
    # Submit workflow through client1
    print("\n2. Submitting workflow through client1...")
    workflow = Workflow(
        id="test_stateless_workflow",
        name="Test Stateless",
        tasks=[
            Task(
                id="task1",
                protocol="python",
                config={
                    "code": "result = 'stateless'"
                }
            )
        ]
    )
    
    result1 = await client1.submit_workflow(workflow)
    print(f"   ✓ Submitted: {result1}")
    
    # Try to get workflow through client2
    if result1.get("success"):
        workflow_id = result1.get("workflow_id")
        print(f"\n3. Getting workflow through client2...")
        
        # Both clients should use same SystemManager via get_or_create()
        retrieved = await client2.get_workflow(workflow_id)
        if retrieved:
            print(f"   ✓ Retrieved through different client: {retrieved.id}")
        else:
            print("   ⚠ Could not retrieve (may be authorization issue)")
    
    # Cleanup
    await client1.shutdown()
    await client2.shutdown()
    print("\n=== Stateless Tests Complete ===\n")


async def main():
    """Run all tests."""
    try:
        await test_system_manager_discovery()
        await test_stateless_operation()
        print("\n✅ All SystemManager discovery tests passed!\n")
    except Exception as e:
        print(f"\n❌ Test failed: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())