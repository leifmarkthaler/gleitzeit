#!/usr/bin/env python3
"""
Simple test for cancellation functionality in Gleitzeit 0.0.7
Tests the hard fail policy where cancelling a task cancels the entire workflow.
"""

import asyncio
import json
import time
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.client.client import GleitzeitClient


async def test_simple_cancellation():
    """Test cancelling a workflow and verifying cascade effects"""
    print("\n" + "="*60)
    print("SIMPLE CANCELLATION TEST - HARD FAIL POLICY")
    print("="*60)

    async with GleitzeitClient(auto_login=False) as client:
        # Create a simple workflow with a few tasks
        workflow = {
            "name": "Test Hard Fail Cancellation",
            "tasks": [
                {
                    "id": "task_1",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "import time; time.sleep(30); print('Task 1 done')",
                        "capture_output": True
                    }
                },
                {
                    "id": "task_2",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "print('Task 2 done')",
                        "capture_output": True
                    },
                    "dependencies": ["task_1"]
                },
                {
                    "id": "task_3",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "print('Task 3 done')",
                        "capture_output": True
                    },
                    "dependencies": ["task_2"]
                }
            ]
        }

        # Submit workflow
        result = await client.submit_workflow(workflow)
        workflow_id = result.workflow_id
        print(f"✓ Submitted workflow: {workflow_id}")

        # Wait a bit for processing
        await asyncio.sleep(3)

        # Get initial workflow status
        workflow_status = await client.get_workflow(workflow_id)
        print(f"\nInitial workflow status: {workflow_status.get('status')}")

        # Get task statuses
        tasks = await client.get_workflow_tasks(workflow_id)
        print("\nInitial task statuses:")
        if isinstance(tasks, list):
            for task_info in tasks:
                task_id = task_info.get('task_id', 'unknown')
                status = task_info.get('status', 'unknown')
                print(f"  {task_id}: {status}")
        elif isinstance(tasks, dict):
            for task_id, task_info in tasks.items():
                if isinstance(task_info, dict):
                    print(f"  {task_id}: {task_info.get('status', 'unknown')}")

        # Cancel the entire workflow (hard fail policy should cancel all tasks)
        print(f"\n→ Cancelling workflow (hard fail policy)...")
        cancel_result = await client.cancel_workflow(workflow_id)
        print(f"✓ Workflow cancel result: {cancel_result}")

        # Wait for cascade to complete
        await asyncio.sleep(2)

        # Check final status
        workflow_status = await client.get_workflow(workflow_id)
        print(f"\nFinal workflow status: {workflow_status.get('status')}")

        # Check task statuses again
        tasks = await client.get_workflow_tasks(workflow_id)
        print("\nFinal task statuses (should all be cancelled):")
        if isinstance(tasks, list):
            for task_info in tasks:
                task_id = task_info.get('task_id', 'unknown')
                status = task_info.get('status', 'unknown')
                if status == 'cancelled':
                    print(f"  ✓ {task_id}: {status}")
                else:
                    print(f"  ❌ {task_id}: {status} (expected: cancelled)")
        elif isinstance(tasks, dict):
            for task_id, task_info in tasks.items():
                if isinstance(task_info, dict):
                    status = task_info.get('status', 'unknown')
                    if status == 'cancelled':
                        print(f"  ✓ {task_id}: {status}")
                    else:
                        print(f"  ❌ {task_id}: {status} (expected: cancelled)")

        print("\n" + "="*60)
        print("TEST COMPLETED")
        print("="*60)


async def test_task_cancellation_cascade():
    """Test that cancelling a single task cancels the entire workflow"""
    print("\n" + "="*60)
    print("TASK CANCELLATION CASCADE TEST")
    print("="*60)

    async with GleitzeitClient(auto_login=False) as client:
        # Create workflow with parallel branches
        workflow = {
            "name": "Test Task Cancel Cascade",
            "tasks": [
                {
                    "id": "slow_task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "import time; time.sleep(60); print('Slow task done')",
                        "capture_output": True
                    }
                },
                {
                    "id": "parallel_task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "import time; time.sleep(5); print('Parallel task done')",
                        "capture_output": True
                    }
                },
                {
                    "id": "dependent",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "print('Dependent done')",
                        "capture_output": True
                    },
                    "dependencies": ["slow_task"]
                }
            ]
        }

        # Submit workflow
        result = await client.submit_workflow(workflow)
        workflow_id = result.workflow_id
        print(f"✓ Submitted workflow: {workflow_id}")

        # Wait for tasks to start
        await asyncio.sleep(3)

        # Cancel the slow_task - should trigger hard fail policy
        slow_task_id = f"{workflow_id}:slow_task"
        print(f"\n→ Cancelling single task: slow_task")
        print(f"   (Hard fail policy should cancel entire workflow)")

        try:
            cancel_result = await client.cancel_task(slow_task_id)
            print(f"✓ Task cancel result: {cancel_result}")
        except Exception as e:
            print(f"❌ Failed to cancel task: {e}")
            # Continue to check effects anyway

        # Wait for cascade
        await asyncio.sleep(3)

        # Check workflow status (should be cancelled)
        workflow_status = await client.get_workflow(workflow_id)
        final_status = workflow_status.get('status')
        if final_status == 'cancelled':
            print(f"\n✓ Workflow status: {final_status} (hard fail triggered)")
        else:
            print(f"\n❌ Workflow status: {final_status} (expected: cancelled)")

        # Check all task statuses
        tasks = await client.get_workflow_tasks(workflow_id)
        print("\nTask statuses after single task cancellation:")
        if isinstance(tasks, list):
            for task_info in tasks:
                task_id = task_info.get('task_id', 'unknown')
                status = task_info.get('status', 'unknown')
                if 'slow_task' in task_id or 'dependent' in task_id:
                    # These should definitely be cancelled
                    if status == 'cancelled':
                        print(f"  ✓ {task_id}: {status}")
                    else:
                        print(f"  ❌ {task_id}: {status} (expected: cancelled)")
                else:
                    # parallel_task might have completed or been cancelled
                    print(f"  • {task_id}: {status}")
        elif isinstance(tasks, dict):
            for task_id, task_info in tasks.items():
                if isinstance(task_info, dict):
                    status = task_info.get('status', 'unknown')
                    if 'slow_task' in task_id or 'dependent' in task_id:
                        # These should definitely be cancelled
                        if status == 'cancelled':
                            print(f"  ✓ {task_id}: {status}")
                        else:
                            print(f"  ❌ {task_id}: {status} (expected: cancelled)")
                    else:
                        # parallel_task might have completed or been cancelled
                        print(f"  • {task_id}: {status}")

        print("\n" + "="*60)
        print("TEST COMPLETED")
        print("="*60)


async def main():
    """Run all cancellation tests"""
    print("\n" + "="*60)
    print("GLEITZEIT 0.0.7 CANCELLATION TESTS")
    print("Testing Hard Fail Policy Implementation")
    print("="*60)

    try:
        # Test 1: Workflow cancellation
        await test_simple_cancellation()

        # Test 2: Task cancellation cascade
        await test_task_cancellation_cascade()

        print("\n" + "="*60)
        print("ALL TESTS COMPLETED")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())