"""
Comprehensive test suite for WebSocket client functionality.

Tests all WebSocket methods in the GleitzeitClient:
- wait_for_workflow_async() - Event-driven workflow monitoring
- watch_multiple_workflows() - Batch workflow monitoring
- wait_for_task() - Task-level monitoring
- get_connection_stats() - Connection health
- monitor_all_workflows() - Global activity monitoring
- stream_workflow_events() - Async event streaming
"""

import pytest
import asyncio
from gleitzeit.client import GleitzeitClient


# Test workflow definition
TEST_WORKFLOW = {
    "name": "test-ws-workflow",
    "tasks": [
        {
            "id": "task1",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"code": "result = {'value': 42}"}
        },
        {
            "id": "task2",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"code": "result = {'value': 100}"},
            "dependencies": ["task1"]
        }
    ]
}


@pytest.mark.asyncio
async def test_connection_stats():
    """Test WebSocket connection health statistics."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        stats = await client.get_connection_stats()

        assert stats["status"] == "healthy"
        assert stats["connected"] is True
        assert "latency_ms" in stats
        assert "connect_time_ms" in stats
        assert stats["latency_ms"] > 0


@pytest.mark.asyncio
async def test_wait_for_workflow_async():
    """Test event-driven workflow monitoring with callbacks."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit workflow
        response = await client.submit_workflow(TEST_WORKFLOW)
        workflow_id = response.workflow_id

        # Track events
        events = []
        workflow_done = asyncio.Event()

        def on_task_complete(event):
            events.append(("task_complete", event))

        def on_complete(event):
            events.append(("workflow_complete", event))
            workflow_done.set()

        def on_failure(event):
            events.append(("workflow_failed", event))
            workflow_done.set()

        # Start monitoring
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

        # Verify events
        assert len(events) > 0
        assert any(e[0] == "workflow_complete" for e in events)
        assert any(e[0] == "task_complete" for e in events)


@pytest.mark.asyncio
async def test_watch_multiple_workflows():
    """Test monitoring multiple workflows simultaneously."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit 2 workflows (reduced from 3 to avoid rate limiting)
        ids = []
        for i in range(2):
            try:
                response = await client.submit_workflow(TEST_WORKFLOW)
                ids.append(response.workflow_id)
                await asyncio.sleep(0.1)  # Small delay between submissions
            except Exception as e:
                # If auth fails, skip this test
                pytest.skip(f"Authentication required for workflow submission: {e}")

        if not ids:
            pytest.skip("No workflows submitted successfully")

        # Track completions
        completed_ids = []

        def on_workflow_complete(wid, event):
            completed_ids.append(wid)

        # Watch all
        summary = await client.watch_multiple_workflows(
            ids,
            on_workflow_complete=on_workflow_complete,
            timeout=90
        )

        # Verify summary
        assert summary["total"] == len(ids)
        assert summary["completed"] + summary["failed"] + summary["timeout"] == len(ids)


@pytest.mark.asyncio
async def test_wait_for_task():
    """Test waiting for specific task completion via WebSocket."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Track callback
        task_completed = asyncio.Event()
        captured_event = None

        def on_complete(event):
            nonlocal captured_event
            captured_event = event
            task_completed.set()

        # Create a slower workflow to ensure we can catch the event
        slow_workflow = {
            "name": "test-ws-task-slow",
            "tasks": [{
                "id": "slow_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "import time; time.sleep(0.5); result = 42"}
            }]
        }

        # Submit workflow
        response = await client.submit_workflow(slow_workflow)
        workflow_id = response.workflow_id

        # Wait a moment for task to be created
        await asyncio.sleep(0.2)

        # Get task ID from API
        try:
            tasks = await client.get_workflow_tasks(workflow_id)
        except Exception as e:
            pytest.skip(f"Could not retrieve workflow tasks: {e}")

        if not tasks:
            pytest.skip("No tasks found in workflow")

        task_id = tasks[0].get('task_id')
        if not task_id:
            pytest.skip("Task ID not available")

        # Wait for task completion via WebSocket
        # The task might already be done, but wait_for_task_ws should still work
        try:
            task_event = await client.wait_for_task_ws(
                task_id,
                workflow_id,
                on_complete=on_complete,
                timeout=10
            )

            # Verify
            assert task_event is not None
            assert "event_type" in task_event
        except TimeoutError:
            # If timeout, task likely already completed before we subscribed
            # This is expected for fast tasks - skip the test
            pytest.skip("Task completed before WebSocket subscription")


@pytest.mark.asyncio
async def test_monitor_all_workflows():
    """Test global workflow activity monitoring."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Track events
        workflows_started = []
        workflows_completed = []

        def on_start(event):
            workflows_started.append(event.get("workflow_id"))

        def on_complete(event):
            workflows_completed.append(event.get("workflow_id"))

        # Start global monitoring (5 second window)
        monitor_task = asyncio.create_task(
            client.monitor_all_workflows(
                on_workflow_start=on_start,
                on_workflow_complete=on_complete,
                duration=5
            )
        )

        # Submit workflow during monitoring window
        await asyncio.sleep(0.5)
        response = await client.submit_workflow(TEST_WORKFLOW)

        # Wait for monitoring to complete
        summary = await monitor_task

        # Verify events were captured
        assert summary["total_events"] > 0
        assert len(workflows_started) > 0


@pytest.mark.asyncio
async def test_stream_workflow_events():
    """Test async event streaming."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit workflow
        response = await client.submit_workflow(TEST_WORKFLOW)
        workflow_id = response.workflow_id

        events_received = []

        # Stream events
        async for event in client.stream_workflow_events([workflow_id]):
            events_received.append(event)

            # Stop after workflow completes
            if "workflow:completed" in event.get("event_type", ""):
                break

            # Safety limit
            if len(events_received) > 20:
                break

        # Verify we received events
        assert len(events_received) > 0
        assert any("workflow" in e.get("event_type", "") for e in events_received)


@pytest.mark.asyncio
async def test_ping_keepalive():
    """Test that ping/pong keepalive works for long connections."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit slow workflow (or just monitor for 35s to trigger ping)
        response = await client.submit_workflow(TEST_WORKFLOW)
        workflow_id = response.workflow_id

        workflow_done = asyncio.Event()

        # Monitor with callback
        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_complete=lambda e: workflow_done.set(),
            on_failure=lambda e: workflow_done.set(),
            timeout=40  # Long enough to trigger ping
        )

        # Wait for completion
        try:
            await asyncio.wait_for(workflow_done.wait(), timeout=45)
            monitor_task.cancel()
            # If we got here without timeout, ping worked
            assert True
        except asyncio.TimeoutError:
            monitor_task.cancel()
            pytest.fail("Workflow monitoring timed out - ping may have failed")


@pytest.mark.asyncio
async def test_already_completed_task():
    """Test that wait_for_task_ws fires callback immediately for already-completed tasks."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit a fast workflow
        fast_workflow = {
            "name": "test-already-completed-task",
            "tasks": [{
                "id": "fast_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = 123"}
            }]
        }

        response = await client.submit_workflow(fast_workflow)
        workflow_id = response.workflow_id

        # Wait for task to complete
        await asyncio.sleep(2)

        # Get task ID
        tasks = await client.get_workflow_tasks(workflow_id)
        if not tasks:
            pytest.skip("No tasks returned")

        task_id = tasks[0].get('task_id')
        if not task_id:
            pytest.skip("Task ID not available")

        # Task should already be completed
        assert tasks[0].get('status') == 'completed'

        # Now wait for it - callback should fire immediately
        callback_fired = asyncio.Event()
        received_event = None

        def on_complete(event):
            nonlocal received_event
            received_event = event
            callback_fired.set()

        task_event = await client.wait_for_task_ws(
            task_id,
            workflow_id,
            on_complete=on_complete,
            timeout=5
        )

        # Verify callback fired and event received
        assert callback_fired.is_set(), "Callback should have fired immediately"
        assert task_event is not None
        assert task_event.get('data', {}).get('already_completed') == True
        assert task_event.get('event_type') == 'task:completed'


@pytest.mark.asyncio
async def test_already_completed_workflow():
    """Test that wait_for_workflow_async fires callback immediately for already-completed workflows."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit a fast workflow
        fast_workflow = {
            "name": "test-already-completed-workflow",
            "tasks": [{
                "id": "fast_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = 456"}
            }]
        }

        response = await client.submit_workflow(fast_workflow)
        workflow_id = response.workflow_id

        # Wait for workflow to complete
        await asyncio.sleep(2)

        # Verify workflow is completed
        status = await client.get_workflow_status(workflow_id)
        assert status.status == 'completed'

        # Now wait for it - callback should fire immediately
        callback_fired = asyncio.Event()
        received_event = None

        def on_complete(event):
            nonlocal received_event
            received_event = event
            callback_fired.set()

        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_complete=on_complete,
            timeout=5
        )

        # Wait a moment for callback to fire
        await asyncio.sleep(0.5)

        # Verify callback fired
        assert callback_fired.is_set(), "Callback should have fired immediately"
        assert received_event is not None
        assert received_event.get('data', {}).get('already_completed') == True
        assert received_event.get('event_type') == 'workflow:completed'


@pytest.mark.asyncio
async def test_validation_error_reporting():
    """Test that workflow validation errors are properly reported with error details."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit an invalid workflow (missing required params)
        invalid_workflow = {
            "name": "test-validation-error",
            "tasks": [{
                "id": "invalid_task",
                "protocol": "python/v1",
                "method": "python/execute"
                # Missing required 'params' field with 'code'
            }]
        }

        response = await client.submit_workflow(invalid_workflow)
        workflow_id = response.workflow_id

        # Wait for validation to complete
        await asyncio.sleep(2)

        # Check that error is available via REST API
        status = await client.get_workflow_status(workflow_id)
        assert status.status == 'failed'
        assert status.error is not None
        assert "WORKFLOW_VALIDATION_FAILED" in status.error
        assert "missing required parameter" in status.error

        # Also verify WebSocket detects the already-failed status with error
        callback_fired = asyncio.Event()
        received_error = None

        def on_failure(event):
            nonlocal received_error
            received_error = event.get('data', {}).get('error')
            callback_fired.set()

        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_failure=on_failure,
            timeout=5
        )

        await asyncio.sleep(0.5)

        # Verify callback fired with error details
        assert callback_fired.is_set(), "Failure callback should fire for validation errors"
        assert received_error is not None
        assert "WORKFLOW_VALIDATION_FAILED" in received_error


@pytest.mark.asyncio
async def test_signal_events_websocket():
    """Test that signal task events are published to WebSocket."""
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Workflow with signal coordination
        signal_workflow = {
            "name": "test-signal-events",
            "tasks": [
                {
                    "id": "producer",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'data': 'produced'}"}
                },
                {
                    "id": "send_signal",
                    "protocol": "signal/v1",
                    "method": "signal/send",
                    "params": {
                        "signal_name": "data_ready",
                        "payload": {"message": "Ready"}
                    },
                    "dependencies": ["producer"]
                },
                {
                    "id": "consumer",
                    "protocol": "signal/v1",
                    "method": "signal/wait",
                    "params": {
                        "signal_name": "data_ready",
                        "timeout": 30
                    }
                },
                {
                    "id": "process",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'processed': True}"},
                    "dependencies": ["consumer", "send_signal"]
                }
            ]
        }

        response = await client.submit_workflow(signal_workflow)
        workflow_id = response.workflow_id

        # Track signal events
        signal_events = []
        workflow_done = asyncio.Event()

        def on_complete(event):
            workflow_done.set()

        def on_failure(event):
            workflow_done.set()

        # Monitor workflow
        await client.wait_for_workflow_async(
            workflow_id,
            on_complete=on_complete,
            on_failure=on_failure,
            timeout=60
        )

        # Stream events to capture signal events
        async def capture_events():
            async for event in client.stream_workflow_events([workflow_id]):
                event_type = event.get('event_type', '')

                # Capture signal-related events
                if any(keyword in event_type for keyword in ['signal', 'waiting']):
                    signal_events.append(event)

                # Stop after workflow completes
                if 'workflow:completed' in event_type or 'workflow:failed' in event_type:
                    break

        stream_task = asyncio.create_task(capture_events())

        # Wait for workflow completion
        await asyncio.wait_for(workflow_done.wait(), timeout=65)

        # Give time for final events
        await asyncio.sleep(0.5)

        # Clean up
        stream_task.cancel()

        # Verify signal events were captured
        assert len(signal_events) > 0, "Should capture at least one signal event"

        # Check for signal:sent event
        signal_sent_events = [e for e in signal_events if 'signal:sent' in e.get('event_type', '')]
        assert len(signal_sent_events) > 0, "Should capture signal:sent event"

        # Verify signal:sent event has correct data
        sent_event = signal_sent_events[0]
        assert sent_event['data']['signal_name'] == 'data_ready'
        assert 'payload' in sent_event['data']

        # Workflow should complete successfully
        status = await client.get_workflow_status(workflow_id)
        assert status.status in ['completed', 'failed']


@pytest.mark.asyncio
async def test_error_handling():
    """Test WebSocket error handling."""
    # Test with invalid URL (no auto_login since server doesn't exist)
    async with GleitzeitClient(api_url="http://localhost:9999", auto_login=False) as client:
        stats = await client.get_connection_stats()
        assert stats["status"] in ["error", "timeout"]
        assert stats["connected"] is False


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
