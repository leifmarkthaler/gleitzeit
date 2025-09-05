"""
Tests for WorkflowCoordinatorMVP
"""

import pytest
import asyncio
from datetime import datetime
from typing import List, Dict, Any

from gleitzeit.core.models import Task, Workflow, WorkflowStatus, TaskStatus
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP, WorkflowState
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType


@pytest.fixture
async def memory_backend():
    """Create test in-memory backend"""
    backend = InMemoryBackend()
    await backend.initialize()
    yield backend
    await backend.cleanup()


@pytest.fixture
def event_bus(memory_backend):
    """Create test event bus with stateless backend"""
    return EventBus(persistence=memory_backend)


@pytest.fixture
async def coordinator(memory_backend, event_bus):
    """Create test coordinator with memory backend"""
    coordinator = WorkflowCoordinatorMVP(
        persistence=memory_backend,
        event_bus=event_bus,
        node_id="test-coordinator"
    )
    yield coordinator


class TestWorkflowSubmission:
    """Test workflow submission and initialization"""
    
    @pytest.mark.asyncio
    async def test_submit_simple_workflow(self, coordinator):
        """Test submitting a simple workflow"""
        # Create workflow
        task = Task(
            id="task-1",
            name="Test Task",
            protocol="python",
            method="test_method",
            params={"key": "value"}
        )
        
        workflow = Workflow(
            id="workflow-1",
            name="Test Workflow",
            tasks=[task]
        )
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Verify submission
        assert workflow_id == "workflow-1"
        assert workflow_id in coordinator.active_workflows
        assert workflow_id in coordinator.workflow_states
        
        # Check initial state
        state = coordinator.workflow_states[workflow_id]
        assert isinstance(state, WorkflowState)
        assert state.workflow_id == workflow_id
        assert state.status == WorkflowStatus.PENDING
        assert state.total_tasks == 1
        assert len(state.task_states) == 1
        assert state.task_states["task-1"] == TaskStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_submit_workflow_with_dependencies(self, coordinator):
        """Test submitting workflow with task dependencies"""
        # Create tasks with dependencies
        task1 = Task(id="t1", name="Task 1", protocol="python", method="m1")
        task2 = Task(id="t2", name="Task 2", protocol="python", method="m2", 
                    dependencies=["t1"])
        task3 = Task(id="t3", name="Task 3", protocol="python", method="m3",
                    dependencies=["t1", "t2"])
        
        workflow = Workflow(
            id="workflow-2",
            name="Dependency Workflow",
            tasks=[task1, task2, task3]
        )
        
        # Submit workflow
        await coordinator.submit_workflow(workflow)
        
        # Check dependency graph
        dep_graph = coordinator.dependency_graphs["workflow-2"]
        assert dep_graph["t1"] == set()
        assert dep_graph["t2"] == {"t1"}
        assert dep_graph["t3"] == {"t1", "t2"}
        
        # Check all tasks are pending initially
        state = coordinator.workflow_states["workflow-2"]
        assert all(status == TaskStatus.PENDING for status in state.task_states.values())
    
    @pytest.mark.asyncio
    async def test_workflow_started_event(self, coordinator, event_bus):
        """Test that workflow started event is emitted"""
        events_received = []
        
        async def capture_event(event):
            events_received.append(event)
        
        event_bus.register(EventType.WORKFLOW_STARTED, capture_event)
        
        # Submit workflow
        task = Task(id="t1", name="Task", protocol="python", method="test")
        workflow = Workflow(id="w1", name="Test", tasks=[task])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)  # Let coordination start
        
        # Check event was emitted
        started_events = [e for e in events_received if e.event_type == EventType.WORKFLOW_STARTED]
        assert len(started_events) == 1
        assert started_events[0].data["workflow_id"] == "w1"


class TestTaskScheduling:
    """Test task scheduling logic"""
    
    @pytest.mark.asyncio
    async def test_schedule_independent_tasks(self, coordinator):
        """Test that independent tasks are scheduled immediately"""
        # Create workflow with independent tasks
        task1 = Task(id="t1", name="Task 1", protocol="python", method="m1")
        task2 = Task(id="t2", name="Task 2", protocol="python", method="m2")
        
        workflow = Workflow(
            id="workflow-3",
            name="Independent Tasks",
            tasks=[task1, task2]
        )
        
        # Submit workflow
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)  # Let scheduling happen
        
        # Both tasks should be queued
        state = coordinator.workflow_states["workflow-3"]
        assert state.task_states["t1"] == TaskStatus.QUEUED
        assert state.task_states["t2"] == TaskStatus.QUEUED
    
    @pytest.mark.asyncio
    async def test_respect_dependencies(self, coordinator):
        """Test that dependencies are respected in scheduling"""
        # Create dependent tasks
        task1 = Task(id="t1", name="Task 1", protocol="python", method="m1")
        task2 = Task(id="t2", name="Task 2", protocol="python", method="m2",
                    dependencies=["t1"])
        task3 = Task(id="t3", name="Task 3", protocol="python", method="m3",
                    dependencies=["t2"])
        
        workflow = Workflow(
            id="workflow-4",
            name="Dependent Tasks",
            tasks=[task1, task2, task3]
        )
        
        # Submit workflow
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)  # Let scheduling happen
        
        # Only task1 should be queued
        state = coordinator.workflow_states["workflow-4"]
        assert state.task_states["t1"] == TaskStatus.QUEUED
        assert state.task_states["t2"] == TaskStatus.PENDING
        assert state.task_states["t3"] == TaskStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_task_ready_event(self, coordinator, event_bus):
        """Test that task ready events are emitted"""
        ready_events = []
        
        async def capture_ready(event):
            ready_events.append(event)
        
        event_bus.register(EventType.TASK_READY, capture_ready)
        
        # Create and submit workflow
        task = Task(id="t1", name="Task", protocol="python", method="test")
        workflow = Workflow(id="w1", name="Test", tasks=[task])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Check task ready event
        assert len(ready_events) == 1
        assert ready_events[0].data["task_id"] == "t1"
        assert ready_events[0].data["workflow_id"] == "w1"


class TestTaskCompletion:
    """Test task completion handling"""
    
    @pytest.mark.asyncio
    async def test_task_completion_updates_state(self, coordinator, event_bus):
        """Test that task completion updates workflow state"""
        # Submit workflow
        task = Task(id="t1", name="Task", protocol="python", method="test")
        workflow = Workflow(id="w1", name="Test", tasks=[task])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Emit task completed event
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={
                "task_id": "t1",
                "workflow_id": "w1",
                "result": {"status": "success"}
            }
        ))
        await asyncio.sleep(0.1)
        
        # Check state updated
        state = coordinator.workflow_states["w1"]
        assert state.task_states["t1"] == TaskStatus.COMPLETED
        assert "t1" in state.completed_tasks
    
    @pytest.mark.asyncio
    async def test_completion_triggers_dependent_tasks(self, coordinator, event_bus):
        """Test that completing a task schedules dependent tasks"""
        # Create dependent tasks
        task1 = Task(id="t1", name="Task 1", protocol="python", method="m1")
        task2 = Task(id="t2", name="Task 2", protocol="python", method="m2",
                    dependencies=["t1"])
        
        workflow = Workflow(id="w1", name="Test", tasks=[task1, task2])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Initially only t1 is queued
        state = coordinator.workflow_states["w1"]
        assert state.task_states["t1"] == TaskStatus.QUEUED
        assert state.task_states["t2"] == TaskStatus.PENDING
        
        # Complete t1
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t1", "workflow_id": "w1"}
        ))
        await asyncio.sleep(0.1)
        
        # Now t2 should be queued
        assert state.task_states["t2"] == TaskStatus.QUEUED
    
    @pytest.mark.asyncio
    async def test_workflow_completion(self, coordinator, event_bus):
        """Test workflow completion when all tasks done"""
        completed_events = []
        
        async def capture_completion(event):
            completed_events.append(event)
        
        event_bus.register(EventType.WORKFLOW_COMPLETED, capture_completion)
        
        # Single task workflow
        task = Task(id="t1", name="Task", protocol="python", method="test")
        workflow = Workflow(id="w1", name="Test", tasks=[task])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Complete the task
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t1", "workflow_id": "w1"}
        ))
        await asyncio.sleep(0.1)
        
        # Check workflow completed
        state = coordinator.workflow_states["w1"]
        assert state.status == WorkflowStatus.COMPLETED
        assert state.completed_at is not None
        
        # Check event emitted
        assert len(completed_events) == 1
        assert completed_events[0].data["workflow_id"] == "w1"
    
    @pytest.mark.asyncio
    async def test_workflow_progress_events(self, coordinator, event_bus):
        """Test workflow progress events are emitted"""
        progress_events = []
        
        async def capture_progress(event):
            progress_events.append(event)
        
        event_bus.register(EventType.WORKFLOW_PROGRESS, capture_progress)
        
        # Two task workflow
        task1 = Task(id="t1", name="Task 1", protocol="python", method="m1")
        task2 = Task(id="t2", name="Task 2", protocol="python", method="m2")
        workflow = Workflow(id="w1", name="Test", tasks=[task1, task2])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Complete first task
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t1", "workflow_id": "w1"}
        ))
        await asyncio.sleep(0.1)
        
        # Check progress event
        assert len(progress_events) > 0
        last_progress = progress_events[-1].data
        assert last_progress["workflow_id"] == "w1"
        assert last_progress["progress"] == 0.5  # 1 of 2 tasks
        assert last_progress["completed_tasks"] == 1
        assert last_progress["total_tasks"] == 2


class TestTaskFailure:
    """Test task failure handling"""
    
    @pytest.mark.asyncio
    async def test_task_failure_updates_state(self, coordinator, event_bus):
        """Test that task failure updates state correctly"""
        # Submit workflow
        task = Task(id="t1", name="Task", protocol="python", method="test")
        workflow = Workflow(id="w1", name="Test", tasks=[task])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Emit task failed event
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={
                "task_id": "t1",
                "workflow_id": "w1",
                "error": "Test error"
            }
        ))
        await asyncio.sleep(0.1)
        
        # Check state updated
        state = coordinator.workflow_states["w1"]
        assert state.task_states["t1"] == TaskStatus.FAILED
        assert "t1" in state.failed_tasks
    
    @pytest.mark.asyncio
    async def test_task_failure_fails_workflow(self, coordinator, event_bus):
        """Test that task failure fails the entire workflow (MVP behavior)"""
        failed_events = []
        
        async def capture_failure(event):
            failed_events.append(event)
        
        event_bus.register(EventType.WORKFLOW_FAILED, capture_failure)
        
        # Submit workflow
        task = Task(id="t1", name="Task", protocol="python", method="test")
        workflow = Workflow(id="w1", name="Test", tasks=[task])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Fail the task
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={
                "task_id": "t1",
                "workflow_id": "w1",
                "error": "Task execution failed"
            }
        ))
        await asyncio.sleep(0.1)
        
        # Check workflow failed
        state = coordinator.workflow_states["w1"]
        assert state.status == WorkflowStatus.FAILED
        assert state.error == "Task t1 failed: Task execution failed"
        
        # Check event emitted
        assert len(failed_events) == 1
        assert failed_events[0].data["workflow_id"] == "w1"
        assert "Task t1 failed" in failed_events[0].data["reason"]


class TestWorkflowStatus:
    """Test workflow status retrieval"""
    
    @pytest.mark.asyncio
    async def test_get_workflow_status(self, coordinator):
        """Test getting workflow status"""
        # Submit workflow
        task1 = Task(id="t1", name="Task 1", protocol="python", method="m1")
        task2 = Task(id="t2", name="Task 2", protocol="python", method="m2")
        workflow = Workflow(id="w1", name="Test", tasks=[task1, task2])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Get status
        status = coordinator.get_workflow_status("w1")
        
        assert status is not None
        assert status["workflow_id"] == "w1"
        assert status["status"] == WorkflowStatus.RUNNING.value
        assert status["total_tasks"] == 2
        assert status["completed_tasks"] == 0
        assert status["failed_tasks"] == 0
        assert status["progress"] == 0.0
        
    @pytest.mark.asyncio
    async def test_get_nonexistent_workflow_status(self, coordinator):
        """Test getting status of non-existent workflow"""
        status = coordinator.get_workflow_status("nonexistent")
        assert status is None
    
    @pytest.mark.asyncio
    async def test_status_includes_task_states(self, coordinator, event_bus):
        """Test that status includes individual task states"""
        # Submit workflow with dependent tasks
        task1 = Task(id="t1", name="Task 1", protocol="python", method="m1")
        task2 = Task(id="t2", name="Task 2", protocol="python", method="m2",
                    dependencies=["t1"])
        workflow = Workflow(id="w1", name="Test", tasks=[task1, task2])
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Complete first task
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t1", "workflow_id": "w1"}
        ))
        await asyncio.sleep(0.1)
        
        # Get status
        status = coordinator.get_workflow_status("w1")
        
        assert status["task_states"]["t1"] == TaskStatus.COMPLETED.value
        assert status["task_states"]["t2"] == TaskStatus.QUEUED.value
        assert status["completed_tasks"] == 1
        assert status["progress"] == 0.5


class TestComplexWorkflows:
    """Test complex workflow scenarios"""
    
    @pytest.mark.asyncio
    async def test_diamond_dependency_pattern(self, coordinator, event_bus):
        """Test diamond dependency pattern execution"""
        # Create diamond pattern: t1 -> t2,t3 -> t4
        task1 = Task(id="t1", name="Start", protocol="python", method="m1")
        task2 = Task(id="t2", name="Branch 1", protocol="python", method="m2",
                    dependencies=["t1"])
        task3 = Task(id="t3", name="Branch 2", protocol="python", method="m3",
                    dependencies=["t1"])
        task4 = Task(id="t4", name="Join", protocol="python", method="m4",
                    dependencies=["t2", "t3"])
        
        workflow = Workflow(
            id="diamond",
            name="Diamond Pattern",
            tasks=[task1, task2, task3, task4]
        )
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        state = coordinator.workflow_states["diamond"]
        
        # Initially only t1 should be queued
        assert state.task_states["t1"] == TaskStatus.QUEUED
        assert state.task_states["t2"] == TaskStatus.PENDING
        assert state.task_states["t3"] == TaskStatus.PENDING
        assert state.task_states["t4"] == TaskStatus.PENDING
        
        # Complete t1
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t1", "workflow_id": "diamond"}
        ))
        await asyncio.sleep(0.1)
        
        # Both t2 and t3 should be queued
        assert state.task_states["t2"] == TaskStatus.QUEUED
        assert state.task_states["t3"] == TaskStatus.QUEUED
        assert state.task_states["t4"] == TaskStatus.PENDING
        
        # Complete t2
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t2", "workflow_id": "diamond"}
        ))
        await asyncio.sleep(0.1)
        
        # t4 still pending (waiting for t3)
        assert state.task_states["t4"] == TaskStatus.PENDING
        
        # Complete t3
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t3", "workflow_id": "diamond"}
        ))
        await asyncio.sleep(0.1)
        
        # Now t4 should be queued
        assert state.task_states["t4"] == TaskStatus.QUEUED
    
    @pytest.mark.asyncio
    async def test_parallel_chains(self, coordinator, event_bus):
        """Test parallel chains of tasks"""
        # Create two parallel chains
        # Chain 1: t1 -> t2 -> t3
        # Chain 2: t4 -> t5 -> t6
        tasks = [
            Task(id="t1", name="Chain1-1", protocol="python", method="m1"),
            Task(id="t2", name="Chain1-2", protocol="python", method="m2",
                dependencies=["t1"]),
            Task(id="t3", name="Chain1-3", protocol="python", method="m3",
                dependencies=["t2"]),
            Task(id="t4", name="Chain2-1", protocol="python", method="m4"),
            Task(id="t5", name="Chain2-2", protocol="python", method="m5",
                dependencies=["t4"]),
            Task(id="t6", name="Chain2-3", protocol="python", method="m6",
                dependencies=["t5"]),
        ]
        
        workflow = Workflow(id="parallel", name="Parallel Chains", tasks=tasks)
        
        await coordinator.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        state = coordinator.workflow_states["parallel"]
        
        # Both chain starts should be queued
        assert state.task_states["t1"] == TaskStatus.QUEUED
        assert state.task_states["t4"] == TaskStatus.QUEUED
        
        # Others should be pending
        assert state.task_states["t2"] == TaskStatus.PENDING
        assert state.task_states["t3"] == TaskStatus.PENDING
        assert state.task_states["t5"] == TaskStatus.PENDING
        assert state.task_states["t6"] == TaskStatus.PENDING