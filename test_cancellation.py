#!/usr/bin/env python3
"""
Test cancellation functionality for Gleitzeit 0.0.7
Tests both task and workflow cancellation for non-running tasks.
"""

import asyncio
import json
import time
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.client.client import GleitzeitClient


async def test_task_cancellation():
    """Test cancelling a single task before it starts"""
    print("\n" + "="*60)
    print("TEST 1: Cancel a single pending task")
    print("="*60)

    client = GleitzeitClient()

    # Create workflow with dependencies to keep tasks pending
    workflow = {
        "name": "Test Task Cancellation",
        "tasks": [
            {
                "id": "blocker_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "import time; time.sleep(10); print('Blocker done')",
                    "capture_output": True
                }
            },
            {
                "id": "pending_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('This should not execute')",
                    "capture_output": True
                },
                "dependencies": ["blocker_task"]
            },
            {
                "id": "dependent_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('This should be blocked')",
                    "capture_output": True
                },
                "dependencies": ["pending_task"]
            }
        ]
    }

    # Submit workflow
    result = await client.submit_workflow(workflow)
    workflow_id = result.workflow_id if hasattr(result, 'workflow_id') else result['workflow_id']
    print(f"✓ Submitted workflow: {workflow_id}")

    # Wait a bit for tasks to be processed
    await asyncio.sleep(2)

    # Cancel the pending task (use full task ID with workflow prefix)
    pending_task_id = f"{workflow_id}:pending_task"
    print(f"→ Cancelling {pending_task_id}...")
    cancel_result = await client.cancel_task(pending_task_id)
    print(f"✓ Cancel result: {cancel_result}")

    # Check task statuses
    await asyncio.sleep(2)

    # Get workflow status
    workflow_status = await client.get_workflow(workflow_id)
    print(f"\nWorkflow status: {workflow_status.get('status')}")

    # Check each task
    for task_name in ["blocker_task", "pending_task", "dependent_task"]:
        task_id = f"{workflow_id}:{task_name}"
        try:
            task_status = await client.get_task(task_id)
            print(f"  {task_name}: {task_status.state.get('status')} - {task_status.state.get('blocked_reason', '')}")
        except Exception as e:
            print(f"  {task_name}: Error getting status - {e}")

    # Let blocker finish
    print("\n→ Waiting for blocker task to complete...")
    await asyncio.sleep(10)

    # Final status check
    workflow_status = await client.get_workflow(workflow_id)
    print(f"\nFinal workflow status: {workflow_status.get('status')}")

    for task_name in ["blocker_task", "pending_task", "dependent_task"]:
        task_id = f"{workflow_id}:{task_name}"
        try:
            task_status = await client.get_task(task_id)
            status = task_status.state.get('status')
            if status == 'blocked':
                reason = task_status.state.get('blocked_reason', 'unknown')
                print(f"  {task_name}: {status} ({reason})")
            elif status == 'cancelled':
                reason = task_status.state.get('cancelled_reason', 'user_requested')
                print(f"  {task_name}: {status} ({reason})")
            else:
                print(f"  {task_name}: {status}")
        except Exception as e:
            print(f"  {task_name}: Error getting status - {e}")


async def test_workflow_cancellation():
    """Test cancelling an entire workflow"""
    print("\n" + "="*60)
    print("TEST 2: Cancel an entire workflow")
    print("="*60)

    client = GleitzeitClient()

    # Create workflow with multiple tasks
    workflow = {
        "name": "Test Workflow Cancellation",
        "tasks": [
            {
                "id": f"task_{i}",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": f"import time; time.sleep({i}); print('Task {i} done')",
                    "capture_output": True
                }
            }
            for i in range(1, 6)
        ]
    }

    # Add dependencies to create a chain
    for i in range(1, 5):
        workflow["tasks"][i]["dependencies"] = [f"task_{i}"]

    # Submit workflow
    result = await client.submit_workflow(workflow)
    workflow_id = result.workflow_id if hasattr(result, 'workflow_id') else result['workflow_id']
    print(f"✓ Submitted workflow: {workflow_id}")

    # Wait for first task to start
    await asyncio.sleep(2)

    # Cancel the workflow
    print(f"→ Cancelling workflow...")
    cancel_result = await client.cancel_workflow(workflow_id)
    print(f"✓ Cancel result: {cancel_result}")

    # Check workflow and task statuses
    await asyncio.sleep(2)

    workflow_status = await client.get_workflow(workflow_id)
    print(f"\nWorkflow status: {workflow_status.get('status')}")

    # Check each task
    for i in range(1, 6):
        task_id = f"task_{i}"
        task_status = await client.get_task(task_id)
        status = task_status.get('status')
        if status == 'blocked':
            reason = task_status.get('blocked_reason', 'unknown')
            print(f"  {task_id}: {status} ({reason})")
        else:
            print(f"  {task_id}: {status}")


async def test_dependency_blocking():
    """Test that dependent tasks are blocked when a dependency is cancelled"""
    print("\n" + "="*60)
    print("TEST 3: Verify dependency blocking on cancellation")
    print("="*60)

    client = GleitzeitClient()

    # Create workflow with complex dependencies
    workflow = {
        "name": "Test Dependency Blocking",
        "tasks": [
            {
                "id": "root",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Root task')",
                    "capture_output": True
                }
            },
            {
                "id": "branch_a",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "import time; time.sleep(5); print('Branch A')",
                    "capture_output": True
                },
                "dependencies": ["root"]
            },
            {
                "id": "branch_b",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Branch B')",
                    "capture_output": True
                },
                "dependencies": ["root"]
            },
            {
                "id": "leaf_a",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Leaf A')",
                    "capture_output": True
                },
                "dependencies": ["branch_a"]
            },
            {
                "id": "leaf_b",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Leaf B')",
                    "capture_output": True
                },
                "dependencies": ["branch_b"]
            },
            {
                "id": "final",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Final task')",
                    "capture_output": True
                },
                "dependencies": ["leaf_a", "leaf_b"]
            }
        ]
    }

    # Submit workflow
    result = await client.submit_workflow(workflow)
    workflow_id = result.workflow_id if hasattr(result, 'workflow_id') else result['workflow_id']
    print(f"✓ Submitted workflow: {workflow_id}")

    # Wait for root to complete and branches to start
    await asyncio.sleep(2)

    # Cancel branch_a (which is running with sleep)
    branch_a_id = f"{workflow_id}:branch_a"
    print(f"→ Cancelling branch_a...")
    await client.cancel_task(branch_a_id)

    # Let other tasks process
    await asyncio.sleep(3)

    # Check task statuses
    print("\nTask statuses after cancellation:")
    for task_name in ["root", "branch_a", "branch_b", "leaf_a", "leaf_b", "final"]:
        task_id = f"{workflow_id}:{task_name}"
        task_status = await client.get_task(task_id)
        status = task_status.get('status')
        if status == 'blocked':
            blocked_by = task_status.get('blocked_by', 'unknown')
            reason = task_status.get('blocked_reason', 'unknown')
            print(f"  {task_name}: {status} (by {blocked_by}: {reason})")
        else:
            print(f"  {task_name}: {status}")

    # Verify the expected blocking chain
    expected_blocked = ["leaf_a", "final"]
    for task_name in expected_blocked:
        task_id = f"{workflow_id}:{task_name}"
        task_status = await client.get_task(task_id)
        if task_status.get('status') != 'blocked':
            print(f"❌ ERROR: {task_name} should be blocked but is {task_status.get('status')}")
        else:
            print(f"✓ {task_name} correctly blocked")


async def main():
    """Run all cancellation tests"""
    print("\n" + "="*60)
    print("GLEITZEIT 0.0.7 CANCELLATION TESTS")
    print("="*60)

    try:
        # Test 1: Single task cancellation
        await test_task_cancellation()

        # Test 2: Workflow cancellation
        await test_workflow_cancellation()

        # Test 3: Dependency blocking
        await test_dependency_blocking()

        print("\n" + "="*60)
        print("ALL TESTS COMPLETED")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())