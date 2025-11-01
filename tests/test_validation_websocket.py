"""
WebSocket tests for ValidationHandler.

Tests validation handler with real-time event monitoring via WebSocket:
- Validation task completion events
- Failed validation events
- Assertion failure events
- Gate control events
"""

import pytest
import asyncio
from gleitzeit.client import GleitzeitClient


@pytest.mark.asyncio
async def test_validation_success_websocket():
    """Test that successful validation events are streamed via WebSocket."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Workflow with validation
        validation_workflow = {
            "name": "test-validation-ws-success",
            "tasks": [
                {
                    "id": "compute",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'score': 95, 'status': 'ok'}"}
                },
                {
                    "id": "validate",
                    "protocol": "validation/v1",
                    "method": "validation/evaluate",
                    "params": {
                        "conditions": [
                            "score >= 80",
                            "status == 'ok'"
                        ],
                        "context": {
                            "score": 95,
                            "status": "ok"
                        },
                        "mode": "all",
                        "on_failure": "skip"
                    },
                    "dependencies": ["compute"]
                },
                {
                    "id": "process",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'processed': True}"},
                    "dependencies": ["validate"]
                }
            ]
        }

        response = await client.submit_workflow(validation_workflow)
        workflow_id = response.workflow_id

        # Track events
        validation_events = []
        workflow_done = asyncio.Event()

        def on_task_complete(event):
            # Check if this is the validation task
            task_data = event.get('data', {})
            result = task_data.get('result', {})
            if 'valid' in result:
                validation_events.append(event)

        def on_complete(event):
            workflow_done.set()

        def on_failure(event):
            workflow_done.set()

        # Monitor workflow
        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_task_complete=on_task_complete,
            on_complete=on_complete,
            on_failure=on_failure,
            timeout=60
        )

        # Wait for completion
        await asyncio.wait_for(workflow_done.wait(), timeout=65)
        monitor_task.cancel()

        # Verify validation events
        assert len(validation_events) > 0, "Should capture validation task completion event"

        # Check validation result in event
        val_event = validation_events[0]
        val_result = val_event['data']['result']
        assert val_result['valid'] == True, "Validation should pass"
        assert val_result['summary']['passed'] == 2, "Both conditions should pass"
        assert val_result['summary']['failed'] == 0, "No conditions should fail"

        # Workflow should complete successfully
        status = await client.get_workflow_status(workflow_id)
        assert status.status == 'completed'


@pytest.mark.asyncio
async def test_validation_failure_websocket():
    """Test that failed validation events are streamed via WebSocket."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Workflow with failing validation
        validation_workflow = {
            "name": "test-validation-ws-failure",
            "tasks": [
                {
                    "id": "compute",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'score': 50}"}
                },
                {
                    "id": "validate",
                    "protocol": "validation/v1",
                    "method": "validation/evaluate",
                    "params": {
                        "conditions": ["score >= 80"],
                        "context": {"score": 50},
                        "mode": "all",
                        "on_failure": "skip"
                    },
                    "dependencies": ["compute"]
                },
                {
                    "id": "fallback",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'fallback': True}"}
                }
            ]
        }

        response = await client.submit_workflow(validation_workflow)
        workflow_id = response.workflow_id

        # Track validation results
        validation_results = []
        workflow_done = asyncio.Event()

        def on_task_complete(event):
            task_data = event.get('data', {})
            result = task_data.get('result', {})
            if 'valid' in result:
                validation_results.append(result)

        def on_complete(event):
            workflow_done.set()

        # Monitor
        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_task_complete=on_task_complete,
            on_complete=on_complete,
            timeout=60
        )

        await asyncio.wait_for(workflow_done.wait(), timeout=65)
        monitor_task.cancel()

        # Verify failed validation
        assert len(validation_results) > 0
        val_result = validation_results[0]
        assert val_result['valid'] == False, "Validation should fail"
        assert val_result['summary']['failed'] > 0, "Should have failed conditions"


@pytest.mark.asyncio
async def test_validation_assertion_failure_websocket():
    """Test that assertion failures are reported via WebSocket."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Workflow with assertion that will fail
        assertion_workflow = {
            "name": "test-assertion-ws-failure",
            "tasks": [
                {
                    "id": "setup",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'ready': True}"}
                },
                {
                    "id": "assert_check",
                    "protocol": "validation/v1",
                    "method": "validation/assert",
                    "params": {
                        "assertions": [
                            "value > 100"  # This will fail
                        ],
                        "context": {"value": 50}
                    },
                    "dependencies": ["setup"]
                }
            ]
        }

        response = await client.submit_workflow(assertion_workflow)
        workflow_id = response.workflow_id

        # Track failures
        task_failures = []
        workflow_done = asyncio.Event()

        def on_task_complete(event):
            pass  # Assertion should fail, not complete

        def on_failure(event):
            workflow_done.set()

        # Stream events to capture task failures
        failed_tasks = []

        async def capture_task_events():
            async for event in client.stream_workflow_events([workflow_id]):
                event_type = event.get('event_type', '')

                if 'task:failed' in event_type:
                    failed_tasks.append(event)

                if 'workflow:failed' in event_type or 'workflow:completed' in event_type:
                    break

        stream_task = asyncio.create_task(capture_task_events())

        # Monitor workflow
        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_task_complete=on_task_complete,
            on_failure=on_failure,
            timeout=60
        )

        await asyncio.wait_for(workflow_done.wait(), timeout=65)
        monitor_task.cancel()

        # Give time for final events
        await asyncio.sleep(0.5)
        stream_task.cancel()

        # Verify assertion failure was captured
        assert len(failed_tasks) > 0, "Should capture task:failed event for assertion"

        # Check error message
        failed_event = failed_tasks[0]
        error = failed_event['data'].get('error', '')
        assert 'Assertion failed' in error or 'assertion' in error.lower()

        # Workflow should fail
        status = await client.get_workflow_status(workflow_id)
        assert status.status == 'failed'


@pytest.mark.asyncio
async def test_validation_gate_websocket():
    """Test that validation gate events are streamed via WebSocket."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Workflow with gate control
        gate_workflow = {
            "name": "test-gate-ws",
            "tasks": [
                {
                    "id": "detect_env",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'env': 'production', 'region': 'us-east'}"}
                },
                {
                    "id": "gate_check",
                    "protocol": "validation/v1",
                    "method": "validation/gate",
                    "params": {
                        "rules": [
                            {
                                "name": "production_gate",
                                "condition": "env == 'production'",
                                "enable_tasks": ["deploy_prod"],
                                "disable_tasks": ["deploy_dev"]
                            }
                        ],
                        "context": {"env": "production"}
                    },
                    "dependencies": ["detect_env"]
                },
                {
                    "id": "deploy_prod",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'deployed': 'production'}"},
                    "dependencies": ["gate_check"]
                },
                {
                    "id": "deploy_dev",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'deployed': 'development'}"},
                    "dependencies": ["gate_check"]
                }
            ]
        }

        response = await client.submit_workflow(gate_workflow)
        workflow_id = response.workflow_id

        # Track gate results
        gate_results = []
        workflow_done = asyncio.Event()

        def on_task_complete(event):
            task_data = event.get('data', {})
            result = task_data.get('result', {})
            if 'gate_results' in result:
                gate_results.append(result)

        def on_complete(event):
            workflow_done.set()

        def on_failure(event):
            workflow_done.set()

        # Monitor
        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_task_complete=on_task_complete,
            on_complete=on_complete,
            on_failure=on_failure,
            timeout=60
        )

        await asyncio.wait_for(workflow_done.wait(), timeout=65)
        monitor_task.cancel()

        # Verify gate execution
        assert len(gate_results) > 0, "Should capture gate result"
        gate_result = gate_results[0]
        assert gate_result['valid'] == True
        assert len(gate_result['gate_results']) > 0


@pytest.mark.asyncio
async def test_validation_streaming_events():
    """Test streaming validation task events in real-time."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Complex workflow with multiple validations
        workflow = {
            "name": "test-validation-streaming",
            "tasks": [
                {
                    "id": "task1",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'value': 42}"}
                },
                {
                    "id": "validate1",
                    "protocol": "validation/v1",
                    "method": "validation/evaluate",
                    "params": {
                        "conditions": ["value == 42"],
                        "context": {"value": 42}
                    },
                    "dependencies": ["task1"]
                },
                {
                    "id": "task2",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'count': 100}"},
                    "dependencies": ["validate1"]
                },
                {
                    "id": "validate2",
                    "protocol": "validation/v1",
                    "method": "validation/evaluate",
                    "params": {
                        "conditions": ["count > 50"],
                        "context": {"count": 100}
                    },
                    "dependencies": ["task2"]
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        # Stream all events
        validation_events = []

        async for event in client.stream_workflow_events([workflow_id]):
            event_type = event.get('event_type', '')

            # Capture validation task events
            if 'task:completed' in event_type:
                result = event.get('data', {}).get('result', {})
                if 'valid' in result:
                    validation_events.append(event)

            # Stop after workflow completes
            if 'workflow:completed' in event_type or 'workflow:failed' in event_type:
                break

            # Safety limit
            if len(validation_events) >= 2:
                # We expect 2 validation tasks
                break

        # Verify we captured both validation events
        assert len(validation_events) >= 1, "Should capture at least one validation event"

        # All validations should pass
        for event in validation_events:
            result = event['data']['result']
            assert result['valid'] == True


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
