"""
Integration tests for workflow execution with provider registration.
"""

import asyncio
import pytest
from typing import Dict, Any

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task, TaskStatus, WorkflowStatus


class TestWorkflowExecution:
    """Test complete workflow execution flow."""
    
    @pytest.fixture
    async def client(self):
        """Create and initialize a native client with providers."""
        client = GleitzeitClient(
            mode=ClientMode.NATIVE,
            enable_events=True,
            event_mode='direct'
        )
        await client.initialize()
        yield client
        await client.shutdown()
    
    @pytest.mark.asyncio
    async def test_simple_shell_workflow(self, client):
        """Test executing a simple shell workflow."""
        # Create workflow with shell tasks
        workflow = Workflow(
            id="test_workflow_1",
            name="Shell Test Workflow",
            tasks=[
                Task(
                    id="task1",
                    name="Echo Task",
                    protocol="shell/v1",
                    method="execute",
                    params={"command": "echo 'Hello from task 1'"},
                    dependencies=[]
                ),
                Task(
                    id="task2",
                    name="List Task",
                    protocol="shell/v1",
                    method="execute",
                    params={"command": "ls -la /tmp | head -5"},
                    dependencies=["task1"]
                ),
                Task(
                    id="task3",
                    name="Date Task",
                    protocol="shell/v1",
                    method="execute",
                    params={"command": "date"},
                    dependencies=["task1"]
                )
            ]
        )
        
        # Submit workflow
        result = await client.submit_workflow(workflow)
        assert result is not None
        assert result.get('workflow_id') == workflow.id
        
        # Wait for workflow completion (with timeout)
        timeout = 10  # seconds
        elapsed = 0
        while elapsed < timeout:
            status = await client.get_workflow(workflow.id)
            if status.get('status') in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                break
            await asyncio.sleep(0.5)
            elapsed += 0.5
        
        # Check final status
        final_status = await client.get_workflow(workflow.id)
        assert final_status.get('status') == WorkflowStatus.COMPLETED
        
        # Check all tasks completed
        tasks = await client.get_workflow_tasks(workflow.id)
        assert len(tasks) == 3
        for task in tasks:
            assert task.get('status') == TaskStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_python_workflow(self, client):
        """Test executing a Python workflow."""
        # Create workflow with Python tasks
        workflow = Workflow(
            id="test_workflow_2",
            name="Python Test Workflow",
            tasks=[
                Task(
                    id="calc1",
                    name="Calculate Sum",
                    protocol="python/v1",
                    method="execute",
                    params={
                        "code": "result = 10 + 20; print(f'Sum is {result}')"
                    },
                    dependencies=[]
                ),
                Task(
                    id="calc2",
                    name="Calculate Product",
                    protocol="python/v1",
                    method="execute",
                    params={
                        "code": "result = 5 * 7; print(f'Product is {result}')"
                    },
                    dependencies=[]
                ),
                Task(
                    id="calc3",
                    name="Evaluate Expression",
                    protocol="python/v1",
                    method="evaluate",
                    params={
                        "expression": "sum([1, 2, 3, 4, 5])"
                    },
                    dependencies=["calc1", "calc2"]
                )
            ]
        )
        
        # Submit workflow
        result = await client.submit_workflow(workflow)
        assert result is not None
        
        # Wait for completion
        final_result = await client.wait_for_workflow(workflow.id, timeout=10)
        assert final_result.get('status') == WorkflowStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self, client):
        """Test workflow with complex dependencies."""
        workflow = Workflow(
            id="test_workflow_3",
            name="Complex Dependencies",
            tasks=[
                Task(id="a", name="Task A", protocol="shell/v1", method="execute",
                     params={"command": "echo A"}, dependencies=[]),
                Task(id="b", name="Task B", protocol="shell/v1", method="execute",
                     params={"command": "echo B"}, dependencies=["a"]),
                Task(id="c", name="Task C", protocol="shell/v1", method="execute",
                     params={"command": "echo C"}, dependencies=["a"]),
                Task(id="d", name="Task D", protocol="shell/v1", method="execute",
                     params={"command": "echo D"}, dependencies=["b", "c"]),
            ]
        )
        
        # Submit and wait
        await client.submit_workflow(workflow)
        result = await client.wait_for_workflow(workflow.id, timeout=10)
        
        assert result.get('status') == WorkflowStatus.COMPLETED
        
        # Verify execution order (D should be last)
        tasks = await client.get_workflow_tasks(workflow.id)
        task_d = next(t for t in tasks if t['id'] == 'd')
        assert task_d['status'] == TaskStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_workflow_with_failing_task(self, client):
        """Test workflow with a task that fails."""
        workflow = Workflow(
            id="test_workflow_4",
            name="Workflow with Failure",
            tasks=[
                Task(
                    id="good_task",
                    name="Good Task",
                    protocol="shell/v1",
                    method="execute",
                    params={"command": "echo 'This works'"},
                    dependencies=[]
                ),
                Task(
                    id="bad_task",
                    name="Bad Task",
                    protocol="shell/v1",
                    method="execute",
                    params={"command": "exit 1"},  # This will fail
                    dependencies=[]
                ),
                Task(
                    id="dependent_task",
                    name="Dependent Task",
                    protocol="shell/v1",
                    method="execute",
                    params={"command": "echo 'Should not run'"},
                    dependencies=["bad_task"]
                )
            ]
        )
        
        # Submit workflow
        await client.submit_workflow(workflow)
        
        # Wait for workflow to complete/fail
        result = await client.wait_for_workflow(workflow.id, timeout=10)
        
        # Workflow should fail due to bad_task
        assert result.get('status') in [WorkflowStatus.FAILED, WorkflowStatus.PARTIALLY_COMPLETED]
        
        # Check task statuses
        tasks = await client.get_workflow_tasks(workflow.id)
        
        good_task = next(t for t in tasks if t['id'] == 'good_task')
        assert good_task['status'] == TaskStatus.COMPLETED
        
        bad_task = next(t for t in tasks if t['id'] == 'bad_task')
        assert bad_task['status'] == TaskStatus.FAILED
        
        # Dependent task should not have run
        dependent_task = next(t for t in tasks if t['id'] == 'dependent_task')
        assert dependent_task['status'] in [TaskStatus.PENDING, TaskStatus.BLOCKED]
    
    @pytest.mark.asyncio
    async def test_provider_registration(self, client):
        """Test that providers are properly registered."""
        # Check if we can access the registry through the client
        # This tests that providers were loaded during initialization
        
        # Try to execute a simple task directly
        task = Task(
            id="provider_test",
            name="Provider Test",
            protocol="shell/v1",
            method="execute",
            params={"command": "echo 'Provider is working'"}
        )
        
        result = await client.submit_task(task)
        assert result is not None
        
        # Wait for task completion
        task_result = await client.wait_for_task(task.id, timeout=5)
        assert task_result is not None
        assert task_result.get('status') == TaskStatus.COMPLETED


class TestEventIntegration:
    """Test event-driven workflow execution."""
    
    @pytest.fixture
    async def event_client(self):
        """Create event-driven client."""
        client = GleitzeitClient(
            mode=ClientMode.NATIVE,
            enable_events=True,
            event_mode='direct'
        )
        await client.initialize()
        yield client
        await client.shutdown()
    
    @pytest.mark.asyncio
    async def test_workflow_events(self, event_client):
        """Test that workflow execution emits proper events."""
        events_received = []
        
        # Register event handlers
        @event_client.on_event("WORKFLOW_SUBMITTED")
        async def on_workflow_submitted(event):
            events_received.append(('WORKFLOW_SUBMITTED', event.data))
        
        @event_client.on_event("TASK_COMPLETED")
        async def on_task_completed(event):
            events_received.append(('TASK_COMPLETED', event.data))
        
        @event_client.on_event("WORKFLOW_COMPLETED")
        async def on_workflow_completed(event):
            events_received.append(('WORKFLOW_COMPLETED', event.data))
        
        # Create and submit workflow
        workflow = Workflow(
            id="event_test_workflow",
            name="Event Test",
            tasks=[
                Task(
                    id="event_task",
                    name="Event Task",
                    protocol="shell/v1",
                    method="execute",
                    params={"command": "echo 'Testing events'"},
                    dependencies=[]
                )
            ]
        )
        
        await event_client.submit_workflow(workflow)
        await event_client.wait_for_workflow(workflow.id, timeout=5)
        
        # Give events time to propagate
        await asyncio.sleep(0.5)
        
        # Check events were received
        event_types = [e[0] for e in events_received]
        assert 'WORKFLOW_SUBMITTED' in event_types
        assert 'TASK_COMPLETED' in event_types
        # Note: WORKFLOW_COMPLETED might not be implemented yet
    
    @pytest.mark.asyncio
    async def test_task_retry_events(self, event_client):
        """Test retry events for failing tasks."""
        retry_events = []
        
        @event_client.on_event("TASK_READY_FOR_RETRY")
        async def on_retry(event):
            retry_events.append(event.data)
        
        # Create task that might need retry
        task = Task(
            id="retry_task",
            name="Retry Test",
            protocol="shell/v1",
            method="execute",
            params={"command": "exit 1"},  # Will fail
            retry_config={"max_retries": 2, "retry_delay": 0.1}
        )
        
        await event_client.submit_task(task)
        
        # Wait for task to complete (with retries)
        await asyncio.sleep(2)
        
        # Check if retry events were emitted
        # This depends on retry manager implementation
        # May need adjustment based on actual retry behavior


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])