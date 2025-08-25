"""
Test Event-Driven Workflow Manager

Tests the workflow management functionality with the new event-driven architecture.
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from gleitzeit.core.models import Task, TaskStatus, Workflow, WorkflowStatus
from gleitzeit.core.events import EventType, create_workflow_submitted_event, create_task_started_event, create_task_completed_event, create_task_failed_event, create_custom_event
from gleitzeit.core.event_driven_workflow_manager import EventDrivenWorkflowManager
from gleitzeit.events.base import EventBus
from gleitzeit.persistence.base import InMemoryBackend


@pytest.fixture
async def setup_workflow_manager():
    """Set up workflow manager with event bus and persistence"""
    persistence = InMemoryBackend()
    event_bus = EventBus()
    
    workflow_manager = EventDrivenWorkflowManager(
        persistence=persistence,
        event_bus=event_bus
    )
    
    return workflow_manager, persistence, event_bus


@pytest.mark.asyncio
async def test_workflow_start_on_first_task(setup_workflow_manager):
    """Test that workflow starts when first task starts"""
    workflow_manager, persistence, event_bus = setup_workflow_manager
    
    # Create and save a workflow
    workflow = Workflow(
        id="workflow-1",
        name="Test Workflow",
        status=WorkflowStatus.PENDING,
        tasks=[
            Task(id="task-1", name="Task 1", protocol="test", method="test"),
            Task(id="task-2", name="Task 2", protocol="test", method="test")
        ]
    )
    await persistence.save_workflow(workflow)
    
    # Track emitted events
    started_events = []
    async def capture_started(event):
        started_events.append(event)
    
    event_bus.register(EventType.WORKFLOW_STARTED, capture_started)
    
    # Emit WORKFLOW_SUBMITTED event
    submitted_event = create_workflow_submitted_event(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        total_tasks=len(workflow.tasks),
        source="test"
    )
    await event_bus.emit(submitted_event)
    await asyncio.sleep(0.1)
    
    # Check workflow still PENDING (waits for first task to start)
    updated_workflow = await persistence.get_workflow(workflow.id)
    assert updated_workflow.status == WorkflowStatus.PENDING
    assert 'submitted_at' in updated_workflow.metadata
    
    # Emit TASK_STARTED for first task
    task_started_event = create_task_started_event(
        task_id="task-1",
        task_name="Task 1",
        protocol="test",
        method="test",
        workflow_id=workflow.id,
        source="test"
    )
    await event_bus.emit(task_started_event)
    await asyncio.sleep(0.1)
    
    # Check workflow marked as RUNNING
    updated_workflow = await persistence.get_workflow(workflow.id)
    assert updated_workflow.status == WorkflowStatus.RUNNING
    assert updated_workflow.started_at is not None
    
    # Check WORKFLOW_STARTED event emitted
    assert len(started_events) == 1
    assert started_events[0].event_type == EventType.WORKFLOW_STARTED
    assert started_events[0].data['workflow_id'] == workflow.id


@pytest.mark.asyncio
async def test_workflow_completion(setup_workflow_manager):
    """Test that workflow completes when all tasks complete"""
    workflow_manager, persistence, event_bus = setup_workflow_manager
    
    # Create workflow with tasks
    workflow = Workflow(
        id="workflow-2",
        name="Test Workflow",
        status=WorkflowStatus.RUNNING,
        started_at=datetime.utcnow(),
        tasks=[
            Task(id="task-1", name="Task 1", protocol="test", method="test"),
            Task(id="task-2", name="Task 2", protocol="test", method="test")
        ]
    )
    await persistence.save_workflow(workflow)
    
    # Save tasks and results
    for task in workflow.tasks:
        await persistence.save_task(task)
    
    # Track completion events
    completion_events = []
    async def capture_completion(event):
        completion_events.append(event)
    
    event_bus.register(EventType.WORKFLOW_COMPLETED, capture_completion)
    
    # Complete first task
    task1 = workflow.tasks[0]
    task1.status = TaskStatus.COMPLETED
    await persistence.save_task(task1)
    # Create TaskResult for completed task
    from gleitzeit.core.models import TaskResult
    task1_result = TaskResult(
        task_id=task1.id,
        status=TaskStatus.COMPLETED,
        result={"output": "success"}
    )
    await persistence.save_task_result(task1_result)
    
    task_completed_event = create_task_completed_event(
        task_id=task1.id,
        workflow_id=workflow.id,
        duration=1.0,
        source="test"
    )
    await event_bus.emit(task_completed_event)
    await asyncio.sleep(0.1)
    
    # Workflow should still be running
    updated_workflow = await persistence.get_workflow(workflow.id)
    assert updated_workflow.status == WorkflowStatus.RUNNING
    
    # Complete second task
    task2 = workflow.tasks[1]
    task2.status = TaskStatus.COMPLETED
    await persistence.save_task(task2)
    task2_result = TaskResult(
        task_id=task2.id,
        status=TaskStatus.COMPLETED,
        result={"output": "success"}
    )
    await persistence.save_task_result(task2_result)
    
    task_completed_event = create_task_completed_event(
        task_id=task2.id,
        workflow_id=workflow.id,
        duration=1.0,
        source="test"
    )
    await event_bus.emit(task_completed_event)
    await asyncio.sleep(0.1)
    
    # Workflow should now be completed
    updated_workflow = await persistence.get_workflow(workflow.id)
    assert updated_workflow.status == WorkflowStatus.COMPLETED
    assert updated_workflow.completed_at is not None
    
    # Check WORKFLOW_COMPLETED event emitted
    assert len(completion_events) == 1
    assert completion_events[0].event_type == EventType.WORKFLOW_COMPLETED
    assert completion_events[0].data['workflow_id'] == workflow.id
    assert completion_events[0].data['completed_tasks'] == 2
    assert completion_events[0].data['failed_tasks'] == 0


@pytest.mark.asyncio
async def test_workflow_failure(setup_workflow_manager):
    """Test that workflow fails when critical task fails"""
    workflow_manager, persistence, event_bus = setup_workflow_manager
    
    # Create workflow
    workflow = Workflow(
        id="workflow-3",
        name="Test Workflow",
        status=WorkflowStatus.RUNNING,
        started_at=datetime.utcnow(),
        tasks=[
            Task(id="task-1", name="Task 1", protocol="test", method="test"),
            Task(id="task-2", name="Task 2", protocol="test", method="test")
        ]
    )
    await persistence.save_workflow(workflow)
    
    # Save tasks
    for task in workflow.tasks:
        await persistence.save_task(task)
    
    # Track failure events
    failure_events = []
    async def capture_failure(event):
        if event.event_type == EventType.WORKFLOW_FAILED:
            failure_events.append(event)
    
    event_bus.register(EventType.WORKFLOW_FAILED, capture_failure)
    
    # Mark first task as permanently failed
    task1 = workflow.tasks[0]
    task1.status = TaskStatus.FAILED
    task1.metadata = {'max_retries_reached': True}
    await persistence.save_task(task1)
    
    # Emit permanent failure event
    task_failed_event = create_task_failed_event(
        task_id=task1.id,
        workflow_id=workflow.id,
        error_message="Permanent failure",
        is_retryable=False,
        is_permanent=True,
        attempt_number=3
    )
    await event_bus.emit(task_failed_event)
    await asyncio.sleep(0.1)
    
    # Workflow should be failed
    updated_workflow = await persistence.get_workflow(workflow.id)
    assert updated_workflow.status == WorkflowStatus.FAILED
    assert updated_workflow.completed_at is not None
    
    # Check WORKFLOW_FAILED event emitted
    assert len(failure_events) == 1
    assert failure_events[0].event_type == EventType.WORKFLOW_FAILED
    assert failure_events[0].data['workflow_id'] == workflow.id
    assert 'Critical task failures' in failure_events[0].data['error_message']


@pytest.mark.asyncio
async def test_workflow_progress_updates(setup_workflow_manager):
    """Test that workflow progress is tracked"""
    workflow_manager, persistence, event_bus = setup_workflow_manager
    
    # Create workflow
    workflow = Workflow(
        id="workflow-4",
        name="Test Workflow",
        status=WorkflowStatus.RUNNING,
        tasks=[
            Task(id="task-1", name="Task 1", protocol="test", method="test"),
            Task(id="task-2", name="Task 2", protocol="test", method="test"),
            Task(id="task-3", name="Task 3", protocol="test", method="test")
        ]
    )
    await persistence.save_workflow(workflow)
    
    # Save tasks
    for task in workflow.tasks:
        task.status = TaskStatus.QUEUED
        await persistence.save_task(task)
    
    # Track progress events
    progress_events = []
    async def capture_progress(event):
        progress_events.append(event)
    
    event_bus.register(EventType.WORKFLOW_PROGRESS, capture_progress)
    
    # Complete first task
    task1 = workflow.tasks[0]
    task1.status = TaskStatus.COMPLETED
    await persistence.save_task(task1)
    
    await workflow_manager._update_workflow_progress(workflow.id)
    await asyncio.sleep(0.1)
    
    # Check progress event
    assert len(progress_events) == 1
    progress = progress_events[0].data['progress']
    assert progress['completed'] == 1
    assert progress['queued'] == 2
    assert progress['total'] == 3
    assert progress['percentage'] == pytest.approx(33.3, 0.1)
    
    # Check workflow metadata updated
    updated_workflow = await persistence.get_workflow(workflow.id)
    assert 'progress' in updated_workflow.metadata
    assert updated_workflow.metadata['progress']['completed'] == 1


@pytest.mark.asyncio
async def test_workflow_status_query(setup_workflow_manager):
    """Test querying workflow status"""
    workflow_manager, persistence, event_bus = setup_workflow_manager
    
    # Create workflow with mixed task states
    workflow = Workflow(
        id="workflow-5",
        name="Test Workflow",
        status=WorkflowStatus.RUNNING,
        created_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
        tasks=[
            Task(id="task-1", name="Task 1", protocol="test", method="test", status=TaskStatus.COMPLETED),
            Task(id="task-2", name="Task 2", protocol="test", method="test", status=TaskStatus.EXECUTING),
            Task(id="task-3", name="Task 3", protocol="test", method="test", status=TaskStatus.QUEUED)
        ]
    )
    await persistence.save_workflow(workflow)
    
    # Save tasks with different states
    for task in workflow.tasks:
        await persistence.save_task(task)
    
    # Query workflow status
    status = await workflow_manager.get_workflow_status(workflow.id)
    
    assert status is not None
    assert status['workflow_id'] == workflow.id
    assert status['name'] == workflow.name
    assert status['status'] == WorkflowStatus.RUNNING.value
    assert len(status['tasks']) == 3
    
    # Check task statuses
    task_statuses = {t['id']: t['status'] for t in status['tasks']}
    assert task_statuses['task-1'] == TaskStatus.COMPLETED.value
    assert task_statuses['task-2'] == TaskStatus.EXECUTING.value
    assert task_statuses['task-3'] == TaskStatus.QUEUED.value


if __name__ == "__main__":
    asyncio.run(pytest.main([__file__, "-v"]))