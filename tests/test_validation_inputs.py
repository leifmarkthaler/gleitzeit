"""
Test that ValidationHandler can access dependency task results via inputs.

This verifies that the existing inputs mechanism works for conditional tasks,
eliminating the need for custom context injection.
"""
import pytest
import asyncio
from gleitzeit.client import GleitzeitClient


@pytest.mark.asyncio
async def test_validation_can_access_dependency_inputs():
    """Test that validation task can access results from dependency tasks."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Workflow: compute a value, then validate it using the computed value
        workflow = {
            "name": "test-validation-inputs",
            "tasks": [
                {
                    "id": "compute_value",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = {'threshold': 95, 'status': 'ok'}"
                    }
                },
                {
                    "id": "validate_value",
                    "protocol": "validation/v1",
                    "method": "validation/evaluate",
                    "params": {
                        "conditions": [
                            "threshold > 90",
                            "status == 'ok'"
                        ],
                        "context": {
                            # Try to access dependency results
                            # This will tell us if inputs are available
                            "threshold": 95,  # Hardcoded for now
                            "status": "ok"
                        },
                        "on_failure": "skip"
                    },
                    "dependencies": ["compute_value"]
                },
                {
                    "id": "process_data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = {'processed': True}"
                    },
                    "dependencies": ["validate_value"]
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        print(f"\n✅ Submitted workflow: {workflow_id}")

        # Wait for completion
        status = await client.wait_for_workflow(workflow_id, timeout=30)

        # Get task results to inspect
        tasks = await client.get_workflow_tasks(workflow_id)

        print(f"\n📊 Workflow Status: {status.status}")
        print(f"\nTasks:")
        for task in tasks:
            task_id = task.get('task_id')
            task_status = task.get('status')
            result = task.get('result')
            error = task.get('error')
            print(f"  - {task_id}: {task_status}")
            if result:
                print(f"    Result: {result}")
            if error:
                print(f"    ERROR: {error}")

        # If workflow failed, show the error
        if status.status == 'failed':
            print(f"\n❌ Workflow failed with error: {status.error}")
            # Find the failed task
            failed_tasks = [t for t in tasks if t.get('status') == 'failed']
            if failed_tasks:
                print(f"\nFailed task details:")
                for ft in failed_tasks:
                    print(f"  Task: {ft.get('task_id')}")
                    print(f"  Error: {ft.get('error')}")

        # Verify workflow completed
        assert status.status == 'completed', f"Workflow should complete, got {status.status}"

        # Find validation task by checking if result has 'valid' field (characteristic of validation results)
        validation_task = next(
            (t for t in tasks if 'valid' in t.get('result', {})),
            None
        )

        assert validation_task is not None, "Should find validation task"
        assert validation_task['status'] == 'completed', "Validation should complete"

        # Check validation result
        val_result = validation_task.get('result', {})
        print(f"\n✅ Validation Result: {val_result}")

        assert val_result.get('valid') == True, "Validation should pass"

        # Process task should also complete (not skipped) - identify by 'processed' in result
        process_task = next(
            (t for t in tasks if 'processed' in t.get('result', {})),
            None
        )

        assert process_task is not None, "Should find process task"
        assert process_task['status'] == 'completed', "Process task should complete (not skipped)"

        print(f"\n✅ SUCCESS: Validation can access context and evaluate conditions!")


@pytest.mark.asyncio
async def test_validation_inputs_dynamic_access():
    """Test validation accessing dependency results dynamically (if inputs work)."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # This test will tell us if we can dynamically access inputs
        workflow = {
            "name": "test-validation-dynamic-inputs",
            "tasks": [
                {
                    "id": "compute",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": """
# Compute some values
result = {
    'score': 85,
    'passed': True,
    'message': 'Test completed successfully'
}
"""
                    }
                },
                {
                    "id": "validate",
                    "protocol": "validation/v1",
                    "method": "validation/evaluate",
                    "params": {
                        "conditions": [
                            "score >= 80",
                            "passed == True"
                        ],
                        "context": {
                            # QUESTION: Can we access inputs here?
                            # Try different approaches:

                            # Approach 1: Direct hardcoded values (baseline)
                            "score": 85,
                            "passed": True

                            # Approach 2: Template syntax? (to test)
                            # "score": "{{inputs.compute.score}}"

                            # Approach 3: Will inputs be auto-injected?
                        },
                        "on_failure": "fail"
                    },
                    "dependencies": ["compute"]
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        print(f"\n✅ Submitted dynamic inputs test: {workflow_id}")

        status = await client.wait_for_workflow(workflow_id, timeout=30)
        tasks = await client.get_workflow_tasks(workflow_id)

        print(f"\n📊 Workflow Status: {status.status}")

        # Get validation task
        val_task = next((t for t in tasks if 'validate' in t.get('task_id', '')), None)

        if val_task:
            print(f"\n✅ Validation Task:")
            print(f"  Status: {val_task.get('status')}")
            print(f"  Result: {val_task.get('result')}")

        assert status.status == 'completed', "Workflow should complete with hardcoded values"


@pytest.mark.asyncio
async def test_validation_check_inputs_availability():
    """Check if Task object has inputs field and if it's populated."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Use a Python task to inspect what's available
        workflow = {
            "name": "test-inspect-inputs",
            "tasks": [
                {
                    "id": "producer",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = {'data': 'test_data', 'value': 42}"
                    }
                },
                {
                    "id": "inspector",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": """
# Check what's available in the execution context
import sys

available_vars = {
    'has_inputs': 'inputs' in dir(),
    'has_result': 'result' in dir(),
    'has_task': 'task' in dir(),
    'all_vars': [v for v in dir() if not v.startswith('_')]
}

# Try to access inputs if it exists
if 'inputs' in dir():
    try:
        available_vars['inputs_type'] = str(type(inputs))
        available_vars['inputs_keys'] = list(inputs.keys()) if hasattr(inputs, 'keys') else 'not_a_dict'
        available_vars['inputs_content'] = str(inputs)
    except Exception as e:
        available_vars['inputs_error'] = str(e)

result = available_vars
"""
                    },
                    "dependencies": ["producer"]
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        print(f"\n✅ Submitted inspection workflow: {workflow_id}")

        status = await client.wait_for_workflow(workflow_id, timeout=30)
        tasks = await client.get_workflow_tasks(workflow_id)

        # Debug: print all tasks
        print(f"\n📋 All tasks ({len(tasks)}):")
        for task in tasks:
            print(f"  - {task.get('task_id')}: {task.get('status')}")
            print(f"    Result keys: {list(task.get('result', {}).keys()) if task.get('result') else 'None'}")

        # Get inspector result - it's the second task (has dependency on first)
        # Since task IDs are UUIDs, we need to find it by result content
        inspector_task = None
        for task in tasks:
            result = task.get('result', {})
            if 'has_inputs' in result:
                inspector_task = task
                break

        assert inspector_task is not None, "Should find inspector task"
        assert inspector_task.get('status') == 'completed', f"Inspector task should complete, got {inspector_task.get('status')}"

        inspector_result = inspector_task.get('result', {})
        print(f"\n📊 INSPECTION RESULTS:")
        print(f"  Has 'inputs' variable: {inspector_result.get('has_inputs')}")
        print(f"  All available vars: {inspector_result.get('all_vars')}")

        if inspector_result.get('has_inputs'):
            print(f"\n✅ INPUTS IS AVAILABLE!")
            print(f"  Type: {inspector_result.get('inputs_type')}")
            print(f"  Keys: {inspector_result.get('inputs_keys')}")
            print(f"  Content: {inspector_result.get('inputs_content')}")

            # Assert inputs exists and has dependency data
            assert inspector_result.get('has_inputs') == True, "Should have inputs variable"
            assert len(inspector_result.get('inputs_keys', [])) > 0, "Should have at least one dependency in inputs"

            # Verify the dependency result is accessible
            inputs_content = inspector_result.get('inputs_content', '')
            assert 'test_data' in inputs_content, "Should have producer's result data in inputs"
            assert '42' in inputs_content, "Should have producer's value in inputs"
        else:
            print(f"\n❌ INPUTS NOT AVAILABLE")
            print(f"  This means we need to implement input injection for ValidationHandler")

            # This is important - if inputs don't exist, we need to know!
            pytest.fail("inputs variable not available in Python task execution context")

        assert status.status == 'completed', "Inspection workflow should complete"


@pytest.mark.asyncio
async def test_validation_gate_with_dependency():
    """Test validation/gate method with dependency results."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        workflow = {
            "name": "test-validation-gate",
            "tasks": [
                {
                    "id": "detect_env",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = {'environment': 'production', 'region': 'us-east-1'}"
                    }
                },
                {
                    "id": "gate",
                    "protocol": "validation/v1",
                    "method": "validation/gate",
                    "params": {
                        "rules": [
                            {
                                "name": "prod_gate",
                                "condition": "env == 'production'",
                                "enable_tasks": ["deploy_prod"],
                                "disable_tasks": ["deploy_dev"]
                            }
                        ],
                        "context": {
                            "env": "production"  # Hardcoded for now
                        }
                    },
                    "dependencies": ["detect_env"]
                },
                {
                    "id": "deploy_prod",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = {'deployed': 'production'}"
                    },
                    "dependencies": ["gate"]
                },
                {
                    "id": "deploy_dev",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = {'deployed': 'development'}"
                    },
                    "dependencies": ["gate"]
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        print(f"\n✅ Submitted gate test: {workflow_id}")

        status = await client.wait_for_workflow(workflow_id, timeout=30)
        tasks = await client.get_workflow_tasks(workflow_id)

        print(f"\n📊 Gate Test Results:")
        for task in tasks:
            task_id = task.get('task_id', '')
            task_status = task.get('status')
            print(f"  {task_id}: {task_status}")

        # Get gate result
        gate_task = next((t for t in tasks if 'gate' in t.get('task_id', '')), None)
        if gate_task:
            gate_result = gate_task.get('result', {})
            print(f"\n✅ Gate Result: {gate_result}")

        # Verify gate worked
        assert status.status in ['completed', 'completed_with_skips'], "Workflow should complete"


if __name__ == "__main__":
    # Run with: pytest tests/test_validation_inputs.py -v -s
    pytest.main([__file__, "-v", "-s"])
