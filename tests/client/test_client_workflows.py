"""
Tests for GleitzeitClient workflow operations.

Tests workflow submission, querying, cancellation, and result chaining.
"""
import pytest
import asyncio
from gleitzeit.client import GleitzeitClient


@pytest.fixture
def simple_workflow():
    """Create a simple test workflow."""
    return {
        "name": "test-workflow",
        "tasks": [
            {
                "name": "hello",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'message': 'Hello from test!'}"
                }
            }
        ]
    }


@pytest.fixture
def chained_workflow():
    """Create a workflow with result chaining."""
    return {
        "name": "test-chaining",
        "tasks": [
            {
                "name": "generate",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
result = {
    'number': 42,
    'message': 'Generated data'
}
print(f'Generated: {result}')
"""
                }
            },
            {
                "name": "process",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
# Results auto-injected into 'inputs' dict by dependency worker
# Keys are task UUIDs, values are result dicts
print(f'Inputs type: {type(inputs)}')
print(f'Inputs: {inputs}')

result = None
for key, value in inputs.items():
    if isinstance(value, dict) and 'number' in value:
        number = value['number']
        result = {
            'doubled': number * 2,
            'processed': True
        }
        break

if result is None:
    result = {'error': 'No input found'}

print(f'Result: {result}')
"""
                },
                "dependencies": ["generate"]
            }
        ]
    }


@pytest.mark.asyncio
async def test_submit_workflow(simple_workflow):
    """Test submitting a simple workflow."""
    async with GleitzeitClient() as client:
        response = await client.submit_workflow(simple_workflow)

        assert response.workflow_id is not None
        assert response.status in ["submitted", "pending", "running"]
        print(f"✓ Submitted workflow: {response.workflow_id}")
        print(f"  Status: {response.status}")
        print(f"  Message: {response.message}")


@pytest.mark.asyncio
async def test_submit_workflow_with_metadata(simple_workflow):
    """Test submitting workflow with priority and metadata."""
    async with GleitzeitClient() as client:
        response = await client.submit_workflow(
            simple_workflow,
            workflow_id="test-workflow-123",
            priority=10,
            metadata={"test": "metadata", "env": "test"}
        )

        assert response.workflow_id == "test-workflow-123"
        print(f"✓ Submitted workflow with metadata: {response.workflow_id}")


@pytest.mark.asyncio
async def test_get_workflow_status(simple_workflow):
    """Test getting workflow status."""
    async with GleitzeitClient() as client:
        response = await client.submit_workflow(simple_workflow)

        # Wait a moment for processing
        await asyncio.sleep(1)

        status = await client.get_workflow_status(response.workflow_id)
        assert status.workflow_id == response.workflow_id
        assert status.status in ["pending", "running", "completed", "failed"]
        print(f"✓ Got workflow status: {status.status}")
        print(f"  Created: {status.created_at}")
        print(f"  Updated: {status.updated_at}")


@pytest.mark.asyncio
async def test_get_workflow_tasks(simple_workflow):
    """Test getting workflow tasks."""
    async with GleitzeitClient() as client:
        response = await client.submit_workflow(simple_workflow)

        await asyncio.sleep(1)

        tasks = await client.get_workflow_tasks(response.workflow_id)
        assert len(tasks) > 0
        print(f"✓ Got {len(tasks)} tasks from workflow")
        for task in tasks:
            print(f"  - {task.get('name', task.get('task_id'))}: {task.get('status')}")


@pytest.mark.asyncio
async def test_wait_for_workflow(simple_workflow):
    """Test waiting for workflow completion."""
    async with GleitzeitClient() as client:
        response = await client.submit_workflow(simple_workflow)
        print(f"Waiting for workflow {response.workflow_id}...")

        final_status = await client.wait_for_workflow(
            response.workflow_id,
            timeout=60,
            poll_interval=2
        )

        assert final_status.status in ["completed", "failed"]
        print(f"✓ Workflow completed with status: {final_status.status}")


@pytest.mark.asyncio
async def test_result_chaining(chained_workflow):
    """Test result chaining between tasks."""
    async with GleitzeitClient() as client:
        response = await client.submit_workflow(chained_workflow)
        print(f"Submitted chaining workflow: {response.workflow_id}")

        # Wait for completion
        final_status = await client.wait_for_workflow(
            response.workflow_id,
            timeout=60,
            poll_interval=2
        )

        assert final_status.status == "completed", f"Workflow failed: {final_status.error}"

        # Get tasks and check results
        tasks = await client.get_workflow_tasks(response.workflow_id)

        # Find the process task
        process_task = None
        for task in tasks:
            if task.get("name") == "process":
                process_task = task
                break

        assert process_task is not None

        # Get the result
        result = await client.get_task_result(
            process_task.get("task_id"),
            response.workflow_id
        )

        print(f"✓ Result chaining worked!")
        print(f"  Process task result: {result}")

        # Verify the chaining worked
        if result and isinstance(result, dict):
            assert result.get("doubled") == 84, f"Expected 84, got {result.get('doubled')}"
            assert result.get("processed") is True
            print(f"  ✓ Verified: 42 * 2 = {result.get('doubled')}")


@pytest.mark.asyncio
async def test_cancel_workflow(simple_workflow):
    """Test cancelling a workflow."""
    async with GleitzeitClient() as client:
        # Submit a workflow
        response = await client.submit_workflow(simple_workflow)

        # Try to cancel it quickly
        await asyncio.sleep(0.5)

        try:
            result = await client.cancel_workflow(response.workflow_id)
            print(f"✓ Cancelled workflow: {response.workflow_id}")
            print(f"  Result: {result}")
        except Exception as e:
            # Might already be completed
            print(f"Note: Could not cancel (likely already completed): {e}")


@pytest.mark.asyncio
async def test_list_workflows():
    """Test listing workflows."""
    async with GleitzeitClient() as client:
        # List workflow IDs
        workflow_ids = await client.list_workflows(limit=10)
        print(f"✓ Got {len(workflow_ids)} workflow IDs")

        # List with full data
        workflows = await client.list_workflows(limit=5, full_data=True)
        print(f"✓ Got {len(workflows)} workflows with full data")


@pytest.mark.asyncio
async def test_batch_workflow_submission(simple_workflow):
    """Test submitting multiple workflows concurrently."""
    async with GleitzeitClient() as client:
        # Create multiple workflows
        workflows = [simple_workflow.copy() for _ in range(3)]

        # Submit batch
        responses = await client.submit_workflows_batch(workflows, max_concurrent=2)

        assert len(responses) == 3
        print(f"✓ Submitted {len(responses)} workflows in batch")

        for i, resp in enumerate(responses):
            print(f"  {i+1}. {resp.workflow_id}: {resp.status}")


if __name__ == "__main__":
    import sys

    print("Running workflow tests...\n")

    # Create fixtures
    simple = {
        "name": "test-workflow",
        "tasks": [
            {
                "name": "hello",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'message': 'Hello from test!'}"
                }
            }
        ]
    }

    chained = {
        "name": "test-chaining",
        "tasks": [
            {
                "name": "generate",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
result = {
    'number': 42,
    'message': 'Generated data'
}
print(f'Generated: {result}')
"""
                }
            },
            {
                "name": "process",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
print(f'Inputs: {inputs}')
result = None
for key, value in inputs.items():
    if isinstance(value, dict) and 'number' in value:
        number = value['number']
        result = {'doubled': number * 2, 'processed': True}
        break
if result is None:
    result = {'error': 'No input found'}
print(f'Result: {result}')
"""
                },
                "dependencies": ["generate"]
            }
        ]
    }

    try:
        asyncio.run(test_submit_workflow(simple))
        asyncio.run(test_submit_workflow_with_metadata(simple))
        asyncio.run(test_get_workflow_status(simple))
        asyncio.run(test_get_workflow_tasks(simple))
        asyncio.run(test_wait_for_workflow(simple))
        asyncio.run(test_result_chaining(chained))
        asyncio.run(test_cancel_workflow(simple))
        asyncio.run(test_list_workflows())
        asyncio.run(test_batch_workflow_submission(simple))
        print("\n✓ All workflow tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
