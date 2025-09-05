"""
Integration tests for MVP orchestration components
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from gleitzeit.core.models import Task, Workflow, WorkflowStatus, TaskStatus
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP, WorkflowState
from gleitzeit.orchestration.provider_pull import ProviderPullAdapter
from gleitzeit.persistence.redis_backend import RedisBackend
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType


class MockProvider:
    """Mock provider for testing"""
    
    def __init__(self, protocol_name="python"):
        self.protocol_name = protocol_name
        self.executed_tasks = []
        
    async def execute(self, method: str, params: dict):
        """Mock execution"""
        self.executed_tasks.append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        
        # Simulate some work
        await asyncio.sleep(0.1)
        
        # Return mock result
        return {"status": "success", "method": method}


@pytest.fixture
async def redis_backend():
    """Create test Redis backend"""
    backend = RedisBackend()
    await backend.initialize()
    
    # Clear any existing test data
    await backend.redis.flushdb()
    
    yield backend
    
    # Cleanup
    await backend.redis.flushdb()
    await backend.cleanup()


@pytest.fixture
async def memory_backend():
    """Create test in-memory backend"""
    backend = InMemoryBackend()
    await backend.initialize()
    yield backend
    await backend.cleanup()


@pytest.fixture
def event_bus():
    """Create test event bus"""
    return EventBus()


@pytest.fixture
async def coordinator_with_redis(redis_backend, event_bus):
    """Create coordinator with Redis backend"""
    coordinator = WorkflowCoordinatorMVP(
        persistence=redis_backend,
        event_bus=event_bus,
        node_id="test-coordinator"
    )
    yield coordinator


@pytest.fixture
async def coordinator_with_memory(memory_backend, event_bus):
    """Create coordinator with memory backend"""
    coordinator = WorkflowCoordinatorMVP(
        persistence=memory_backend,
        event_bus=event_bus,
        node_id="test-coordinator"
    )
    yield coordinator


class TestWorkflowCoordinatorMVP:
    """Test WorkflowCoordinatorMVP functionality"""
    
    @pytest.mark.asyncio
    async def test_submit_workflow(self, coordinator_with_memory):
        """Test workflow submission"""
        # Create simple workflow
        task1 = Task(
            id="task-1",
            name="First Task",
            protocol="python",
            method="print",
            params={"message": "Hello"}
        )
        
        workflow = Workflow(
            id="test-workflow-1",
            name="Test Workflow",
            tasks=[task1]
        )
        
        # Submit workflow
        workflow_id = await coordinator_with_memory.submit_workflow(workflow)
        
        # Verify workflow stored
        assert workflow_id == "test-workflow-1"
        assert workflow_id in coordinator_with_memory.active_workflows
        assert workflow_id in coordinator_with_memory.workflow_states
        
        # Verify state initialized correctly
        state = coordinator_with_memory.workflow_states[workflow_id]
        assert state.status == WorkflowStatus.PENDING
        assert state.total_tasks == 1
        assert len(state.task_states) == 1
        assert state.task_states["task-1"] == TaskStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_dependency_graph_building(self, coordinator_with_memory):
        """Test dependency graph construction"""
        # Create workflow with dependencies
        task1 = Task(id="task-1", name="Task 1", protocol="python", method="test")
        task2 = Task(id="task-2", name="Task 2", protocol="python", method="test", 
                    dependencies=["task-1"])
        task3 = Task(id="task-3", name="Task 3", protocol="python", method="test",
                    dependencies=["task-1", "task-2"])
        
        workflow = Workflow(
            id="test-workflow-2",
            name="Dependency Test",
            tasks=[task1, task2, task3]
        )
        
        # Submit workflow
        await coordinator_with_memory.submit_workflow(workflow)
        
        # Check dependency graph
        dep_graph = coordinator_with_memory.dependency_graphs["test-workflow-2"]
        assert dep_graph["task-1"] == set()
        assert dep_graph["task-2"] == {"task-1"}
        assert dep_graph["task-3"] == {"task-1", "task-2"}
    
    @pytest.mark.asyncio
    async def test_task_scheduling(self, coordinator_with_memory):
        """Test task scheduling based on dependencies"""
        # Create workflow
        task1 = Task(id="task-1", name="Task 1", protocol="python", method="test")
        task2 = Task(id="task-2", name="Task 2", protocol="python", method="test",
                    dependencies=["task-1"])
        
        workflow = Workflow(
            id="test-workflow-3",
            name="Scheduling Test",
            tasks=[task1, task2]
        )
        
        # Submit and let coordination begin
        await coordinator_with_memory.submit_workflow(workflow)
        
        # Give time for coordination to start
        await asyncio.sleep(0.1)
        
        # Check that task1 is queued but not task2
        state = coordinator_with_memory.workflow_states["test-workflow-3"]
        assert state.task_states["task-1"] == TaskStatus.QUEUED
        assert state.task_states["task-2"] == TaskStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_task_completion_handling(self, coordinator_with_memory, event_bus):
        """Test handling of task completion events"""
        # Create workflow with dependencies
        task1 = Task(id="task-1", name="Task 1", protocol="python", method="test")
        task2 = Task(id="task-2", name="Task 2", protocol="python", method="test",
                    dependencies=["task-1"])
        
        workflow = Workflow(
            id="test-workflow-4",
            name="Completion Test",
            tasks=[task1, task2]
        )
        
        # Submit workflow
        await coordinator_with_memory.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Simulate task1 completion
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={
                "task_id": "task-1",
                "workflow_id": "test-workflow-4",
                "result": {"status": "success"}
            }
        ))
        
        # Give time for event processing
        await asyncio.sleep(0.1)
        
        # Check that task2 is now queued
        state = coordinator_with_memory.workflow_states["test-workflow-4"]
        assert state.task_states["task-1"] == TaskStatus.COMPLETED
        assert state.task_states["task-2"] == TaskStatus.QUEUED
        assert "task-1" in state.completed_tasks
    
    @pytest.mark.asyncio
    async def test_workflow_completion(self, coordinator_with_memory, event_bus):
        """Test workflow completion when all tasks done"""
        # Create simple workflow
        task1 = Task(id="task-1", name="Task 1", protocol="python", method="test")
        
        workflow = Workflow(
            id="test-workflow-5",
            name="Completion Test",
            tasks=[task1]
        )
        
        # Track events
        completed_events = []
        
        async def track_completion(event):
            completed_events.append(event)
        
        event_bus.register(EventType.WORKFLOW_COMPLETED, track_completion)
        
        # Submit workflow
        await coordinator_with_memory.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Complete the task
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={
                "task_id": "task-1",
                "workflow_id": "test-workflow-5",
                "result": {"status": "success"}
            }
        ))
        
        # Give time for event processing
        await asyncio.sleep(0.1)
        
        # Check workflow completed
        state = coordinator_with_memory.workflow_states["test-workflow-5"]
        assert state.status == WorkflowStatus.COMPLETED
        assert len(completed_events) == 1
        assert completed_events[0].data["workflow_id"] == "test-workflow-5"
    
    @pytest.mark.asyncio
    async def test_workflow_failure(self, coordinator_with_memory, event_bus):
        """Test workflow failure on task failure"""
        # Create workflow
        task1 = Task(id="task-1", name="Task 1", protocol="python", method="test")
        
        workflow = Workflow(
            id="test-workflow-6",
            name="Failure Test",
            tasks=[task1]
        )
        
        # Submit workflow
        await coordinator_with_memory.submit_workflow(workflow)
        await asyncio.sleep(0.1)
        
        # Simulate task failure
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={
                "task_id": "task-1",
                "workflow_id": "test-workflow-6",
                "error": "Test error"
            }
        ))
        
        # Give time for event processing
        await asyncio.sleep(0.1)
        
        # Check workflow failed
        state = coordinator_with_memory.workflow_states["test-workflow-6"]
        assert state.status == WorkflowStatus.FAILED
        assert state.error == "Task task-1 failed: Test error"
        assert "task-1" in state.failed_tasks


class TestProviderPullAdapter:
    """Test ProviderPullAdapter functionality"""
    
    @pytest.mark.asyncio
    async def test_task_pulling(self, redis_backend, event_bus):
        """Test pulling tasks from queue"""
        # Create mock provider
        provider = MockProvider(protocol_name="python")
        
        # Create adapter
        adapter = ProviderPullAdapter(
            provider=provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis,
            poll_interval=0.1
        )
        
        # Add task to queue
        task_data = {
            "task_id": "test-task-1",
            "workflow_id": "test-workflow",
            "protocol": "python",
            "method": "test_method",
            "params": {"key": "value"}
        }
        
        await redis_backend.redis.lpush(
            "provider:queue:python",
            json.dumps(task_data)
        )
        
        # Pull task
        pulled_task = await adapter._pull_task()
        
        assert pulled_task is not None
        assert pulled_task["task_id"] == "test-task-1"
        assert pulled_task["method"] == "test_method"
    
    @pytest.mark.asyncio
    async def test_task_execution(self, redis_backend, event_bus):
        """Test task execution via provider"""
        # Create mock provider
        provider = MockProvider(protocol_name="python")
        
        # Track events
        events_received = []
        
        async def track_event(event):
            events_received.append(event)
        
        event_bus.register(EventType.TASK_STARTED, track_event)
        event_bus.register(EventType.TASK_COMPLETED, track_event)
        
        # Create adapter
        adapter = ProviderPullAdapter(
            provider=provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis
        )
        
        # Execute task
        task_data = {
            "task_id": "test-task-2",
            "workflow_id": "test-workflow",
            "method": "test_method",
            "params": {"message": "Hello"}
        }
        
        await adapter._execute_task(task_data)
        
        # Check provider executed task
        assert len(provider.executed_tasks) == 1
        assert provider.executed_tasks[0]["method"] == "test_method"
        
        # Check events emitted
        assert len(events_received) == 2
        assert events_received[0].event_type == EventType.TASK_STARTED
        assert events_received[1].event_type == EventType.TASK_COMPLETED
        assert events_received[1].data["task_id"] == "test-task-2"
    
    @pytest.mark.asyncio
    async def test_task_failure_handling(self, redis_backend, event_bus):
        """Test handling of task execution failures"""
        # Create provider that fails
        provider = MockProvider(protocol_name="python")
        provider.execute = AsyncMock(side_effect=Exception("Test failure"))
        
        # Track failure events
        failure_events = []
        
        async def track_failure(event):
            failure_events.append(event)
        
        event_bus.register(EventType.TASK_FAILED, track_failure)
        
        # Create adapter
        adapter = ProviderPullAdapter(
            provider=provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis
        )
        
        # Execute task that will fail
        task_data = {
            "task_id": "test-task-3",
            "workflow_id": "test-workflow",
            "method": "failing_method",
            "params": {}
        }
        
        await adapter._execute_task(task_data)
        
        # Check failure event emitted
        assert len(failure_events) == 1
        assert failure_events[0].data["task_id"] == "test-task-3"
        assert "Test failure" in failure_events[0].data["error"]
    
    @pytest.mark.asyncio
    async def test_recovery_of_processing_tasks(self, redis_backend, event_bus):
        """Test recovery of tasks from processing queue"""
        provider = MockProvider(protocol_name="python")
        
        adapter = ProviderPullAdapter(
            provider=provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis
        )
        
        # Add tasks to processing queue (simulating crash)
        task1 = {"task_id": "recovery-1", "method": "test"}
        task2 = {"task_id": "recovery-2", "method": "test"}
        
        await redis_backend.redis.lpush(
            "provider:processing:python",
            json.dumps(task1),
            json.dumps(task2)
        )
        
        # Recover tasks
        await adapter.recover_processing_tasks()
        
        # Check tasks moved back to main queue
        queue_length = await redis_backend.redis.llen("provider:queue:python")
        assert queue_length == 2
        
        # Check processing queue cleared
        processing_length = await redis_backend.redis.llen("provider:processing:python")
        assert processing_length == 0


@pytest.mark.asyncio
async def test_end_to_end_workflow_execution(redis_backend, event_bus):
    """Test complete workflow execution through coordinator and provider"""
    # Create coordinator
    coordinator = WorkflowCoordinatorMVP(
        persistence=redis_backend,
        event_bus=event_bus
    )
    
    # Create mock provider and adapter
    provider = MockProvider(protocol_name="python")
    adapter = ProviderPullAdapter(
        provider=provider,
        event_bus=event_bus,
        redis_client=redis_backend.redis,
        poll_interval=0.1
    )
    
    # Create workflow
    task1 = Task(id="e2e-task-1", name="Task 1", protocol="python", method="process")
    task2 = Task(id="e2e-task-2", name="Task 2", protocol="python", method="process",
                dependencies=["e2e-task-1"])
    
    workflow = Workflow(
        id="e2e-workflow",
        name="End-to-End Test",
        tasks=[task1, task2]
    )
    
    # Start provider adapter in background
    adapter_task = asyncio.create_task(adapter.start())
    
    try:
        # Submit workflow
        await coordinator.submit_workflow(workflow)
        
        # Wait for workflow to complete (with timeout)
        max_wait = 5.0
        start = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start < max_wait:
            state = coordinator.workflow_states.get("e2e-workflow")
            if state and state.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)
        
        # Verify workflow completed
        state = coordinator.workflow_states["e2e-workflow"]
        assert state.status == WorkflowStatus.COMPLETED
        assert len(state.completed_tasks) == 2
        
        # Verify provider executed both tasks
        assert len(provider.executed_tasks) == 2
        
    finally:
        # Stop adapter
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass