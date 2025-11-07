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
                    "name": "task_1",
                    "type": "python",
                    "params": {
                        "code": "import time; time.sleep(30); print('Task 1 done')"
                    }
                },
                {
                    "name": "task_2",
                    "type": "python",
                    "params": {
                        "code": "print('Task 2 done')"
                    },
                    "dependencies": ["task_1"]
                },
                {
                    "name": "task_3",
                    "type": "python",
                    "params": {
                        "code": "print('Task 3 done')"
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
        if 'state' in workflow_status:
            print(f"\nInitial workflow status: {workflow_status['state'].get('status', 'unknown')}")
        else:
            print(f"\nInitial workflow status: {workflow_status.get('status', 'unknown')}")

        # Get task statuses
        tasks_response = await client.get_workflow_tasks(workflow_id)
        print("\nInitial task statuses:")
        if isinstance(tasks_response, dict):
            tasks = tasks_response.get('tasks', [])
        else:
            tasks = tasks_response
        for task_info in tasks:
            task_id = task_info.get('task_id', 'unknown')
            status = task_info.get('status', 'unknown')
            print(f"  {task_id}: {status}")

        # Cancel the entire workflow (hard fail policy should cancel all tasks)
        print(f"\n→ Cancelling workflow (hard fail policy)...")
        cancel_result = await client.cancel_workflow(workflow_id)
        print(f"✓ Workflow cancel result: {cancel_result}")

        # Wait for cascade to complete
        await asyncio.sleep(2)

        # Check final status
        workflow_status = await client.get_workflow(workflow_id)
        if 'state' in workflow_status:
            print(f"\nFinal workflow status: {workflow_status['state'].get('status', 'unknown')}")
        else:
            print(f"\nFinal workflow status: {workflow_status.get('status', 'unknown')}")

        # Check task statuses again
        tasks_response = await client.get_workflow_tasks(workflow_id)
        print("\nFinal task statuses (should all be cancelled):")
        if isinstance(tasks_response, dict):
            tasks = tasks_response.get('tasks', [])
        else:
            tasks = tasks_response
        for task_info in tasks:
            task_id = task_info.get('task_id', 'unknown')
            status = task_info.get('status', 'unknown')
            # Task might have completed before cancellation was processed
            if status in ['cancelled', 'completed']:
                print(f"  ✓ {task_id}: {status}")
            else:
                print(f"  ❌ {task_id}: {status} (expected: cancelled or completed)")

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
                    "name": "slow_task",
                    "type": "python",
                    "params": {
                        "code": "import time; time.sleep(60); print('Slow task done')"
                    }
                },
                {
                    "name": "parallel_task",
                    "type": "python",
                    "params": {
                        "code": "import time; time.sleep(5); print('Parallel task done')"
                    }
                },
                {
                    "name": "dependent",
                    "type": "python",
                    "params": {
                        "code": "print('Dependent done')"
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

        # Get the actual task IDs from the workflow
        workflow_info = await client.get_workflow(workflow_id)
        actual_tasks = []
        if 'data' in workflow_info and 'workflow' in workflow_info['data']:
            import json
            workflow_data = workflow_info['data']['workflow']
            # Check if it's already parsed
            if isinstance(workflow_data, str):
                workflow_data = json.loads(workflow_data)
            actual_tasks = workflow_data.get('tasks', [])

        # Find the slow_task ID
        slow_task_id = None
        for task in actual_tasks:
            if task.get('name') == 'slow_task':
                slow_task_id = task['id']
                break

        if slow_task_id:
            print(f"\n→ Cancelling single task: {slow_task_id} (slow_task)")
            print(f"   (Hard fail policy should cancel entire workflow)")
            try:
                cancel_result = await client.cancel_task(slow_task_id)
                print(f"✓ Task cancel result: {cancel_result}")
            except Exception as e:
                print(f"❌ Failed to cancel task: {e}")
                # Continue to check effects anyway
        else:
            print("❌ Could not find slow_task ID")

        # Wait for cascade
        await asyncio.sleep(3)

        # Check workflow status (should be cancelled)
        workflow_status = await client.get_workflow(workflow_id)
        if 'state' in workflow_status:
            final_status = workflow_status['state'].get('status', 'unknown')
        else:
            final_status = workflow_status.get('status', 'unknown')

        if final_status == 'cancelled':
            print(f"\n✓ Workflow status: {final_status} (hard fail triggered)")
        else:
            print(f"\n❌ Workflow status: {final_status} (expected: cancelled)")

        # Check all task statuses
        tasks_response = await client.get_workflow_tasks(workflow_id)
        print("\nTask statuses after single task cancellation:")
        if isinstance(tasks_response, dict):
            tasks = tasks_response.get('tasks', [])
        else:
            tasks = tasks_response
        for task_info in tasks:
            task_id = task_info.get('task_id', 'unknown')
            status = task_info.get('status', 'unknown')

            # Check if this task has the name we're looking for
            task_name = None
            for orig_task in actual_tasks:
                if orig_task['id'] == task_id:
                    task_name = orig_task.get('name', '')
                    break

            if task_name in ['slow_task', 'dependent']:
                # These should definitely be cancelled
                if status == 'cancelled':
                    print(f"  ✓ {task_name} ({task_id}): {status}")
                else:
                    print(f"  ❌ {task_name} ({task_id}): {status} (expected: cancelled)")
            else:
                # parallel_task might have completed or been cancelled
                print(f"  • {task_name or task_id}: {status}")

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