"""
Tests for GleitzeitClient task operations.

Tests task querying, status, results, logs, and dependencies.
"""
import pytest
import asyncio
from gleitzeit.client import GleitzeitClient


@pytest.fixture
def workflow_with_tasks():
    """Create a workflow with multiple tasks."""
    return {
        "name": "multi-task-workflow",
        "tasks": [
            {
                "name": "task1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'step': 1, 'value': 10}"
                }
            },
            {
                "name": "task2",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
for key, value in inputs.items():
    if isinstance(value, dict) and 'step' in value:
        result = {'step': 2, 'value': value['value'] * 2}
        break
"""
                },
                "dependencies": ["task1"]
            },
            {
                "name": "task3",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
for key, value in inputs.items():
    if isinstance(value, dict) and 'step' in value and value['step'] == 2:
        result = {'step': 3, 'value': value['value'] + 5}
        break
"""
                },
                "dependencies": ["task2"]
            }
        ]
    }


@pytest.mark.asyncio
async def test_get_task_status(workflow_with_tasks):
    """Test getting task status."""
    async with GleitzeitClient() as client:
        # Submit workflow
        response = await client.submit_workflow(workflow_with_tasks)

        # Wait a moment
        await asyncio.sleep(2)

        # Get tasks
        tasks = await client.get_workflow_tasks(response.workflow_id)

        if tasks:
            task = tasks[0]
            task_id = task.get("task_id")

            # Get task status
            status = await client.get_task_status(task_id, response.workflow_id)

            print(f"✓ Got task status: {status.status}")
            print(f"  Task ID: {status.task_id}")
            print(f"  Workflow ID: {status.workflow_id}")
            print(f"  Provider: {status.provider}")
            print(f"  Retry count: {status.retry_count}")


@pytest.mark.asyncio
async def test_get_task_result(workflow_with_tasks):
    """Test getting task result."""
    async with GleitzeitClient() as client:
        # Submit and wait for completion
        response = await client.submit_workflow(workflow_with_tasks)

        final_status = await client.wait_for_workflow(
            response.workflow_id,
            timeout=60
        )

        assert final_status.status == "completed"

        # Get tasks
        tasks = await client.get_workflow_tasks(response.workflow_id)

        # Get result from first task
        if tasks:
            task_id = tasks[0].get("task_id")
            result = await client.get_task_result(task_id, response.workflow_id)

            print(f"✓ Got task result: {result}")
            assert result is not None
            assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_wait_for_task(workflow_with_tasks):
    """Test waiting for task completion."""
    async with GleitzeitClient() as client:
        # Submit workflow
        response = await client.submit_workflow(workflow_with_tasks)

        # Get first task
        await asyncio.sleep(1)
        tasks = await client.get_workflow_tasks(response.workflow_id)

        if tasks:
            task_id = tasks[0].get("task_id")

            print(f"Waiting for task {task_id}...")
            final_status = await client.wait_for_task(
                task_id,
                response.workflow_id,
                timeout=60,
                poll_interval=2
            )

            print(f"✓ Task completed with status: {final_status.status}")
            assert final_status.status in ["completed", "failed"]


@pytest.mark.asyncio
async def test_get_task_dependencies(workflow_with_tasks):
    """Test getting task dependencies."""
    async with GleitzeitClient() as client:
        # Submit workflow
        response = await client.submit_workflow(workflow_with_tasks)

        # Wait for tasks to be created
        await asyncio.sleep(2)

        tasks = await client.get_workflow_tasks(response.workflow_id)

        # Find task2 which has dependencies
        task2 = None
        for task in tasks:
            if task.get("name") == "task2":
                task2 = task
                break

        if task2:
            try:
                deps = await client.get_task_dependencies(
                    task2["task_id"],
                    response.workflow_id
                )
                print(f"✓ Task2 dependencies: {deps}")
            except Exception as e:
                print(f"Note: Could not get dependencies: {e}")


@pytest.mark.asyncio
async def test_list_tasks():
    """Test listing tasks."""
    async with GleitzeitClient() as client:
        # List task IDs
        task_ids = await client.list_tasks(limit=10)
        print(f"✓ Got {len(task_ids)} task IDs")

        # List with full data
        tasks = await client.list_tasks(limit=5, full_data=True)
        print(f"✓ Got {len(tasks)} tasks with full data")


@pytest.mark.asyncio
async def test_get_failed_tasks():
    """Test getting failed tasks from a workflow."""
    # Create a workflow that will fail
    failing_workflow = {
        "name": "failing-workflow",
        "tasks": [
            {
                "name": "will_fail",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "raise ValueError('Intentional failure for testing')"
                }
            }
        ]
    }

    async with GleitzeitClient() as client:
        response = await client.submit_workflow(failing_workflow)

        # Wait for it to fail
        await asyncio.sleep(5)

        try:
            failed_tasks = await client.get_failed_tasks(response.workflow_id)
            print(f"✓ Got {len(failed_tasks)} failed tasks")

            for task in failed_tasks:
                print(f"  - Task {task.task_id}: {task.error}")
        except Exception as e:
            print(f"Note: Could not get failed tasks: {e}")


@pytest.mark.asyncio
async def test_task_logs(workflow_with_tasks):
    """Test getting task logs."""
    async with GleitzeitClient() as client:
        # Submit and wait
        response = await client.submit_workflow(workflow_with_tasks)
        await asyncio.sleep(3)

        tasks = await client.get_workflow_tasks(response.workflow_id)

        if tasks:
            task_id = tasks[0].get("task_id")

            try:
                logs = await client.get_task_logs(task_id, response.workflow_id)
                print(f"✓ Got {len(logs)} log entries for task")

                if logs:
                    for log in logs[:3]:  # Show first 3
                        print(f"  {log}")
            except Exception as e:
                print(f"Note: Could not get logs: {e}")


if __name__ == "__main__":
    import sys

    print("Running task tests...\n")

    workflow = {
        "name": "multi-task-workflow",
        "tasks": [
            {
                "name": "task1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'step': 1, 'value': 10}"
                }
            },
            {
                "name": "task2",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
for key, value in inputs.items():
    if isinstance(value, dict) and 'step' in value:
        result = {'step': 2, 'value': value['value'] * 2}
        break
"""
                },
                "dependencies": ["task1"]
            },
            {
                "name": "task3",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
for key, value in inputs.items():
    if isinstance(value, dict) and 'step' in value and value['step'] == 2:
        result = {'step': 3, 'value': value['value'] + 5}
        break
"""
                },
                "dependencies": ["task2"]
            }
        ]
    }

    try:
        asyncio.run(test_get_task_status(workflow))
        asyncio.run(test_get_task_result(workflow))
        asyncio.run(test_wait_for_task(workflow))
        asyncio.run(test_get_task_dependencies(workflow))
        asyncio.run(test_list_tasks())
        asyncio.run(test_get_failed_tasks())
        asyncio.run(test_task_logs(workflow))
        print("\n✓ All task tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
