"""
Comprehensive test suite for Gleitzeit memory persistence backend.

Tests all memory adapter operations including:
- Initialization and lifecycle
- Task CRUD operations
- Workflow management
- In-memory storage characteristics
- Event storage
- Resource hub operations
- Locking mechanisms
- Queue state management
- Error handling
"""

import pytest
import asyncio
import copy
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Set
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from collections import deque

# Import models
from gleitzeit.core.models import (
    Task, Workflow, TaskResult, WorkflowExecution,
    TaskStatus, WorkflowStatus, RetryConfig
)
from gleitzeit.hub.base import (
    ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType
)

# Import memory adapters
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.persistence.unified_memory_events import UnifiedMemoryEventsAdapter


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
async def memory_adapter():
    """Create a test memory adapter"""
    adapter = UnifiedInMemoryAdapter()
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()


@pytest.fixture
async def memory_events_adapter():
    """Create a test memory adapter with events support"""
    adapter = UnifiedMemoryEventsAdapter()
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()


@pytest.fixture
def sample_task():
    """Create a sample task for testing"""
    return Task(
        id="test-task-001",
        name="Test Task",
        protocol="test-protocol",
        method="test_method",
        params={"key": "value"},
        priority="normal",
        status=TaskStatus.PENDING,
        workflow_id="test-workflow-001",
        created_at=datetime.utcnow()
    )


@pytest.fixture
def sample_workflow():
    """Create a sample workflow for testing"""
    tasks = [
        Task(
            id=f"task-{i}",
            name=f"Task {i}",
            protocol="test",
            method="method",
            params={},
            workflow_id="workflow-001",
            status=TaskStatus.PENDING
        )
        for i in range(3)
    ]
    return Workflow(
        id="workflow-001",
        name="Test Workflow",
        description="Test workflow description",
        tasks=tasks,
        created_at=datetime.utcnow()
    )


@pytest.fixture
def sample_resource_instance():
    """Create a sample resource instance"""
    return ResourceInstance(
        id="resource-001",
        name="Test Resource",
        type=ResourceType.COMPUTE,
        endpoint="http://localhost:8000",
        status=ResourceStatus.HEALTHY,
        metadata={"version": "1.0"},
        tags={"test", "sample"},
        capabilities={"process", "analyze"}
    )


# =========================================================================
# Initialization and Lifecycle Tests
# =========================================================================

class TestInitializationLifecycle:
    """Test memory adapter initialization and lifecycle"""
    
    @pytest.mark.asyncio
    async def test_initialize(self):
        """Test successful initialization"""
        adapter = UnifiedInMemoryAdapter()
        
        assert not adapter._initialized
        
        await adapter.initialize()
        
        assert adapter._initialized
        assert isinstance(adapter.tasks, dict)
        assert isinstance(adapter.workflows, dict)
        assert isinstance(adapter.task_results, dict)
    
    @pytest.mark.asyncio
    async def test_double_initialize(self):
        """Test that double initialization is safe"""
        adapter = UnifiedInMemoryAdapter()
        
        await adapter.initialize()
        assert adapter._initialized
        
        # Add some data
        task = Task(
            id="test-task",
            name="Test",
            protocol="test",
            method="test",
            params={},
            workflow_id="test-workflow"
        )
        await adapter.save_task(task)
        
        # Second initialization should be safe
        await adapter.initialize()
        assert adapter._initialized
        
        # Data should still be there
        retrieved = await adapter.get_task("test-task")
        assert retrieved is not None
    
    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Test proper shutdown clears all data"""
        adapter = UnifiedInMemoryAdapter()
        await adapter.initialize()
        
        # Add some data
        task = Task(
            id="test-task",
            name="Test",
            protocol="test",
            method="test",
            params={},
            workflow_id="test-workflow"
        )
        await adapter.save_task(task)
        
        workflow = Workflow(
            id="test-workflow",
            name="Test Workflow",
            tasks=[task]
        )
        await adapter.save_workflow(workflow)
        
        # Shutdown should clear everything
        await adapter.shutdown()
        
        assert not adapter._initialized
        assert len(adapter.tasks) == 0
        assert len(adapter.workflows) == 0
        assert len(adapter.task_results) == 0
        assert len(adapter.instances) == 0
        assert len(adapter.locks) == 0
    
    @pytest.mark.asyncio
    async def test_event_storage_initialization(self):
        """Test event storage structures are initialized"""
        adapter = UnifiedInMemoryAdapter()
        await adapter.initialize()
        
        assert isinstance(adapter.events_global, deque)
        assert adapter.events_global.maxlen == 10000
        assert isinstance(adapter.events_by_workflow, dict)
        assert isinstance(adapter.events_by_task, dict)


# =========================================================================
# Task Operations Tests
# =========================================================================

class TestTaskOperations:
    """Test task CRUD operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_task(self, memory_adapter, sample_task):
        """Test saving and retrieving a task"""
        await memory_adapter.save_task(sample_task)
        
        retrieved = await memory_adapter.get_task(sample_task.id)
        
        assert retrieved is not None
        assert retrieved.id == sample_task.id
        assert retrieved.name == sample_task.name
        assert retrieved.protocol == sample_task.protocol
        assert retrieved.params == sample_task.params
        assert retrieved.workflow_id == sample_task.workflow_id
    
    @pytest.mark.asyncio
    async def test_save_task_without_workflow_id(self, memory_adapter):
        """Test that saving task without workflow_id raises error"""
        task = Task(
            id="no-workflow-task",
            name="Task without workflow",
            protocol="test",
            method="test",
            params={},
            workflow_id=None  # No workflow ID
        )
        
        with pytest.raises(ValueError, match="cannot be saved without a workflow_id"):
            await memory_adapter.save_task(task)
    
    @pytest.mark.asyncio
    async def test_update_task(self, memory_adapter, sample_task):
        """Test updating an existing task"""
        await memory_adapter.save_task(sample_task)
        
        # Update task
        sample_task.status = TaskStatus.EXECUTING
        sample_task.assigned_provider = "provider-001"
        sample_task.started_at = datetime.utcnow()
        
        await memory_adapter.save_task(sample_task)
        
        retrieved = await memory_adapter.get_task(sample_task.id)
        assert retrieved.status == TaskStatus.EXECUTING
        assert retrieved.assigned_provider == "provider-001"
        assert retrieved.started_at is not None
    
    @pytest.mark.asyncio
    async def test_delete_task(self, memory_adapter, sample_task):
        """Test deleting a task"""
        await memory_adapter.save_task(sample_task)
        
        # Verify task exists
        assert await memory_adapter.get_task(sample_task.id) is not None
        
        # Delete task
        result = await memory_adapter.delete_task(sample_task.id)
        assert result is True
        
        # Verify task is deleted
        assert await memory_adapter.get_task(sample_task.id) is None
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self, memory_adapter):
        """Test deleting a task that doesn't exist"""
        result = await memory_adapter.delete_task("nonexistent-task")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_save_tasks_batch(self, memory_adapter):
        """Test saving multiple tasks in batch"""
        tasks = [
            Task(
                id=f"batch-task-{i}",
                name=f"Batch Task {i}",
                protocol="test",
                method="test",
                params={},
                workflow_id="batch-workflow",
                status=TaskStatus.PENDING
            )
            for i in range(5)
        ]
        
        await memory_adapter.save_tasks_batch(tasks)
        
        # Verify all tasks were saved
        for task in tasks:
            retrieved = await memory_adapter.get_task(task.id)
            assert retrieved is not None
            assert retrieved.name == task.name
    
    @pytest.mark.asyncio
    async def test_task_references_are_shared(self, memory_adapter, sample_task):
        """Test that retrieved tasks are references to the same object (in-memory behavior)"""
        await memory_adapter.save_task(sample_task)
        
        retrieved1 = await memory_adapter.get_task(sample_task.id)
        retrieved2 = await memory_adapter.get_task(sample_task.id)
        
        # Modify one retrieved task - in memory storage, this affects all references
        retrieved1.status = TaskStatus.COMPLETED
        
        # Other retrieved task should be affected (same reference)
        assert retrieved2.status == TaskStatus.COMPLETED
        
        # Original in storage should also be affected
        stored = await memory_adapter.get_task(sample_task.id)
        assert stored.status == TaskStatus.COMPLETED


# =========================================================================
# Task Status and Query Tests
# =========================================================================

class TestTaskStatusAndQueries:
    """Test task status operations and queries"""
    
    @pytest.mark.asyncio
    async def test_get_tasks_by_status(self, memory_adapter):
        """Test retrieving tasks by status"""
        # Create tasks with different statuses
        statuses = [TaskStatus.PENDING, TaskStatus.EXECUTING, TaskStatus.COMPLETED, TaskStatus.FAILED]
        for i, status in enumerate(statuses):
            task = Task(
                id=f"status-task-{i}",
                name=f"Task {status}",
                protocol="test",
                method="test",
                params={},
                workflow_id="status-workflow",
                status=status
            )
            await memory_adapter.save_task(task)
        
        # Test retrieving by each status
        pending_tasks = await memory_adapter.get_tasks_by_status("pending")
        assert len(pending_tasks) == 1
        assert pending_tasks[0].status == TaskStatus.PENDING
        
        executing_tasks = await memory_adapter.get_tasks_by_status("executing")
        assert len(executing_tasks) == 1
        assert executing_tasks[0].status == TaskStatus.EXECUTING
    
    @pytest.mark.asyncio
    async def test_get_tasks_by_workflow(self, memory_adapter):
        """Test retrieving tasks by workflow ID"""
        workflow_id = "test-workflow-123"
        
        # Create tasks for workflow
        for i in range(3):
            task = Task(
                id=f"workflow-task-{i}",
                name=f"Task {i}",
                protocol="test",
                method="test",
                params={},
                workflow_id=workflow_id
            )
            await memory_adapter.save_task(task)
        
        # Create task for different workflow
        other_task = Task(
            id="other-workflow-task",
            name="Other Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="other-workflow"
        )
        await memory_adapter.save_task(other_task)
        
        # Get tasks for specific workflow
        tasks = await memory_adapter.get_tasks_by_workflow(workflow_id)
        assert len(tasks) == 3
        assert all(t.workflow_id == workflow_id for t in tasks)
    
    @pytest.mark.asyncio
    async def test_get_all_queued_tasks(self, memory_adapter):
        """Test getting all queued tasks"""
        # Create tasks with queue-relevant statuses
        for status in [TaskStatus.QUEUED, TaskStatus.RETRY_PENDING, TaskStatus.EXECUTING]:
            task = Task(
                id=f"queue-{status}-task",
                name=f"Queue {status} Task",
                protocol="test",
                method="test",
                params={},
                workflow_id="queue-workflow",
                status=status
            )
            await memory_adapter.save_task(task)
        
        # Add a completed task that shouldn't be included
        completed_task = Task(
            id="completed-task",
            name="Completed Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="queue-workflow",
            status=TaskStatus.COMPLETED
        )
        await memory_adapter.save_task(completed_task)
        
        queued_tasks = await memory_adapter.get_all_queued_tasks()
        
        assert len(queued_tasks) == 3
        task_statuses = [t.status for t in queued_tasks]
        assert TaskStatus.QUEUED in task_statuses
        assert TaskStatus.RETRY_PENDING in task_statuses
        assert TaskStatus.EXECUTING in task_statuses
        assert TaskStatus.COMPLETED not in task_statuses
    
    @pytest.mark.asyncio
    async def test_get_task_count_by_status(self, memory_adapter):
        """Test getting task counts by status"""
        # Create tasks with various statuses
        statuses = [
            TaskStatus.PENDING, TaskStatus.PENDING,
            TaskStatus.EXECUTING,
            TaskStatus.COMPLETED, TaskStatus.COMPLETED, TaskStatus.COMPLETED,
            TaskStatus.FAILED
        ]
        
        for i, status in enumerate(statuses):
            task = Task(
                id=f"count-task-{i}",
                name=f"Task {i}",
                protocol="test",
                method="test",
                params={},
                workflow_id="count-workflow",
                status=status
            )
            await memory_adapter.save_task(task)
        
        counts = await memory_adapter.get_task_count_by_status()
        
        assert counts.get("pending", 0) == 2
        assert counts.get("executing", 0) == 1
        assert counts.get("completed", 0) == 3
        assert counts.get("failed", 0) == 1


# =========================================================================
# Workflow Operations Tests
# =========================================================================

class TestWorkflowOperations:
    """Test workflow CRUD operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_workflow(self, memory_adapter, sample_workflow):
        """Test saving and retrieving a workflow"""
        await memory_adapter.save_workflow(sample_workflow)
        
        retrieved = await memory_adapter.get_workflow(sample_workflow.id)
        
        assert retrieved is not None
        assert retrieved.id == sample_workflow.id
        assert retrieved.name == sample_workflow.name
        assert retrieved.description == sample_workflow.description
        assert len(retrieved.tasks) == len(sample_workflow.tasks)
    
    @pytest.mark.asyncio
    async def test_update_workflow(self, memory_adapter, sample_workflow):
        """Test updating workflow"""
        await memory_adapter.save_workflow(sample_workflow)
        
        # Update workflow
        sample_workflow.status = WorkflowStatus.RUNNING
        sample_workflow.started_at = datetime.utcnow()
        
        await memory_adapter.save_workflow(sample_workflow)
        
        retrieved = await memory_adapter.get_workflow(sample_workflow.id)
        assert retrieved.status == WorkflowStatus.RUNNING
        assert retrieved.started_at is not None
    
    @pytest.mark.asyncio
    async def test_delete_workflow(self, memory_adapter, sample_workflow):
        """Test deleting workflow and its tasks"""
        # Save workflow and its tasks
        await memory_adapter.save_workflow(sample_workflow)
        for task in sample_workflow.tasks:
            await memory_adapter.save_task(task)
        
        # Delete workflow
        result = await memory_adapter.delete_workflow(sample_workflow.id)
        assert result is True
        
        # Verify workflow is deleted
        assert await memory_adapter.get_workflow(sample_workflow.id) is None
        
        # Verify tasks are also deleted
        for task in sample_workflow.tasks:
            assert await memory_adapter.get_task(task.id) is None
    
    @pytest.mark.asyncio
    async def test_delete_workflow_with_orphan_tasks(self, memory_adapter):
        """Test deleting workflow that has orphan tasks (no workflow record)"""
        # Create orphan tasks without workflow record
        for i in range(3):
            task = Task(
                id=f"orphan-task-{i}",
                name=f"Orphan Task {i}",
                protocol="test",
                method="test",
                params={},
                workflow_id="orphan-workflow"
            )
            await memory_adapter.save_task(task)
        
        # Delete should still work and remove tasks
        result = await memory_adapter.delete_workflow("orphan-workflow")
        assert result is True
        
        # Verify tasks are deleted
        for i in range(3):
            assert await memory_adapter.get_task(f"orphan-task-{i}") is None
    
    @pytest.mark.asyncio
    async def test_list_workflows(self, memory_adapter):
        """Test listing workflows with filtering"""
        # Create workflows with different statuses
        for i, status in enumerate([WorkflowStatus.PENDING, WorkflowStatus.RUNNING, WorkflowStatus.COMPLETED]):
            workflow = Workflow(
                id=f"list-workflow-{i}",
                name=f"Workflow {i}",
                tasks=[],
                status=status
            )
            await memory_adapter.save_workflow(workflow)
        
        # List all workflows
        result = await memory_adapter.list_workflows()
        assert result["total"] >= 3
        
        # List with status filter
        result = await memory_adapter.list_workflows(status="running")
        running_workflows = [w for w in result["workflows"] if w["status"] == "running"]
        assert len(running_workflows) >= 1
        
        # Test pagination
        result = await memory_adapter.list_workflows(limit=2, offset=0)
        assert len(result["workflows"]) <= 2


# =========================================================================
# Task Result Tests
# =========================================================================

class TestTaskResults:
    """Test task result operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_task_result(self, memory_adapter):
        """Test saving and retrieving task results"""
        result = TaskResult(
            task_id="result-task-001",
            workflow_id="result-workflow-001",
            status=TaskStatus.COMPLETED,
            result={"output": "success", "data": [1, 2, 3]},
            duration_seconds=5.5,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        
        await memory_adapter.save_task_result(result)
        
        retrieved = await memory_adapter.get_task_result(result.task_id)
        assert retrieved is not None
        assert retrieved.task_id == result.task_id
        assert retrieved.status == TaskStatus.COMPLETED
        assert retrieved.result == result.result
        assert retrieved.duration_seconds == result.duration_seconds
    
    @pytest.mark.asyncio
    async def test_task_result_with_error(self, memory_adapter):
        """Test saving task result with error"""
        result = TaskResult(
            task_id="error-task-001",
            status=TaskStatus.FAILED,
            error="Task failed due to timeout",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        
        await memory_adapter.save_task_result(result)
        
        retrieved = await memory_adapter.get_task_result(result.task_id)
        assert retrieved.status == TaskStatus.FAILED
        assert retrieved.error == "Task failed due to timeout"
        assert retrieved.result is None


# =========================================================================
# Workflow Execution Tests
# =========================================================================

class TestWorkflowExecution:
    """Test workflow execution tracking"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_workflow_execution(self, memory_adapter):
        """Test saving and retrieving workflow execution"""
        execution = WorkflowExecution(
            execution_id="exec-001",
            workflow_id="workflow-001",
            status=WorkflowStatus.RUNNING,
            started_at=datetime.utcnow(),
            completed_tasks=2,
            failed_tasks=0,
            total_tasks=5
        )
        
        await memory_adapter.save_workflow_execution(execution)
        
        retrieved = await memory_adapter.get_workflow_execution(execution.execution_id)
        assert retrieved is not None
        assert retrieved.execution_id == execution.execution_id
        assert retrieved.workflow_id == execution.workflow_id
        assert retrieved.status == WorkflowStatus.RUNNING
        assert retrieved.completed_tasks == 2
        assert retrieved.total_tasks == 5


# =========================================================================
# Queue State Tests
# =========================================================================

class TestQueueState:
    """Test queue state persistence"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_queue_state(self, memory_adapter):
        """Test saving and retrieving queue state"""
        queue_state = {
            "name": "test-queue",
            "size": 10,
            "processing": 3,
            "completed_tasks": ["task-1", "task-2"],
            "failed_tasks": ["task-3"]
        }
        
        await memory_adapter.save_queue_state("test-queue", queue_state)
        
        retrieved = await memory_adapter.get_queue_state("test-queue")
        assert retrieved is not None
        assert retrieved["name"] == "test-queue"
        assert retrieved["size"] == 10
        assert retrieved["completed_tasks"] == ["task-1", "task-2"]
    
    @pytest.mark.asyncio
    async def test_delete_queue_state(self, memory_adapter):
        """Test deleting queue state"""
        queue_state = {"name": "delete-queue", "size": 5}
        
        await memory_adapter.save_queue_state("delete-queue", queue_state)
        assert await memory_adapter.get_queue_state("delete-queue") is not None
        
        result = await memory_adapter.delete_queue_state("delete-queue")
        assert result is True
        
        assert await memory_adapter.get_queue_state("delete-queue") is None
    
    @pytest.mark.asyncio
    async def test_clean_queue_state_for_tasks(self, memory_adapter):
        """Test cleaning queue state when tasks are deleted"""
        # Save queue state with task references
        queue_state = {
            "completed_tasks": ["task-1", "task-2", "task-3"],
            "failed_tasks": ["task-4", "task-5"]
        }
        await memory_adapter.save_queue_state("cleanup-queue", queue_state)
        
        # Clean tasks 2 and 4
        await memory_adapter.clean_queue_state_for_tasks(["task-2", "task-4"])
        
        retrieved = await memory_adapter.get_queue_state("cleanup-queue")
        assert "task-2" not in retrieved["completed_tasks"]
        assert "task-4" not in retrieved["failed_tasks"]
        assert "task-1" in retrieved["completed_tasks"]
        assert "task-3" in retrieved["completed_tasks"]
        assert "task-5" in retrieved["failed_tasks"]


# =========================================================================
# Locking Tests
# =========================================================================

class TestLocking:
    """Test locking mechanisms"""
    
    @pytest.mark.asyncio
    async def test_acquire_and_release_lock(self, memory_adapter):
        """Test acquiring and releasing a lock"""
        resource_id = "test-resource"
        owner_id = "test-owner"
        
        # Acquire lock
        acquired = await memory_adapter.acquire_lock(resource_id, owner_id, timeout=10)
        assert acquired is True
        
        # Verify lock owner
        owner = await memory_adapter.get_lock_owner(resource_id)
        assert owner == owner_id
        
        # Release lock
        await memory_adapter.release_lock(resource_id, owner_id)
        
        # Verify lock released
        owner = await memory_adapter.get_lock_owner(resource_id)
        assert owner is None
    
    @pytest.mark.asyncio
    async def test_lock_prevents_double_acquisition(self, memory_adapter):
        """Test that lock prevents double acquisition"""
        resource_id = "exclusive-resource"
        
        # First owner acquires lock
        acquired1 = await memory_adapter.acquire_lock(resource_id, "owner1", timeout=10)
        assert acquired1 is True
        
        # Second owner tries to acquire - should fail
        acquired2 = await memory_adapter.acquire_lock(resource_id, "owner2", timeout=10)
        assert acquired2 is False
        
        # Release first lock
        await memory_adapter.release_lock(resource_id, "owner1")
        
        # Now second owner can acquire
        acquired2 = await memory_adapter.acquire_lock(resource_id, "owner2", timeout=10)
        assert acquired2 is True
    
    @pytest.mark.asyncio
    async def test_lock_expiration(self, memory_adapter):
        """Test that locks expire after timeout"""
        resource_id = "expiring-resource"
        owner_id = "expiring-owner"
        
        # Acquire lock with very short timeout
        acquired = await memory_adapter.acquire_lock(resource_id, owner_id, timeout=1)
        assert acquired is True
        
        # Wait for expiration
        await asyncio.sleep(1.5)
        
        # Lock should be expired, another owner can acquire
        acquired2 = await memory_adapter.acquire_lock(resource_id, "new-owner", timeout=10)
        assert acquired2 is True
    
    @pytest.mark.asyncio
    async def test_extend_lock(self, memory_adapter):
        """Test extending lock timeout"""
        resource_id = "extend-resource"
        owner_id = "extend-owner"
        
        # Acquire lock with short timeout
        await memory_adapter.acquire_lock(resource_id, owner_id, timeout=2)
        
        # Extend lock
        extended = await memory_adapter.extend_lock(resource_id, owner_id, timeout=10)
        assert extended is True
        
        # Wait original timeout
        await asyncio.sleep(2.5)
        
        # Lock should still be held due to extension
        owner = await memory_adapter.get_lock_owner(resource_id)
        assert owner == owner_id


# =========================================================================
# Resource Hub Operations Tests
# =========================================================================

class TestResourceHubOperations:
    """Test resource hub persistence operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_load_instance(self, memory_adapter, sample_resource_instance):
        """Test saving and loading resource instance"""
        hub_id = "test-hub-001"
        
        await memory_adapter.save_instance(hub_id, sample_resource_instance)
        
        loaded = await memory_adapter.load_instance(sample_resource_instance.id)
        assert loaded is not None
        assert loaded["id"] == sample_resource_instance.id
        assert loaded["name"] == sample_resource_instance.name
        assert loaded["type"] == sample_resource_instance.type.value
        assert loaded["hub_id"] == hub_id
    
    @pytest.mark.asyncio
    async def test_list_instances(self, memory_adapter):
        """Test listing instances for a hub"""
        hub_id = "list-hub-001"
        
        # Save multiple instances
        for i in range(3):
            instance = ResourceInstance(
                id=f"instance-{i}",
                name=f"Instance {i}",
                type=ResourceType.COMPUTE,
                endpoint=f"http://localhost:800{i}"
            )
            await memory_adapter.save_instance(hub_id, instance)
        
        # List instances
        instances = await memory_adapter.list_instances(hub_id)
        assert len(instances) == 3
        assert all(inst["hub_id"] == hub_id for inst in instances)
    
    @pytest.mark.asyncio
    async def test_delete_instance(self, memory_adapter, sample_resource_instance):
        """Test deleting resource instance"""
        hub_id = "delete-hub-001"
        
        await memory_adapter.save_instance(hub_id, sample_resource_instance)
        assert await memory_adapter.load_instance(sample_resource_instance.id) is not None
        
        await memory_adapter.delete_instance(sample_resource_instance.id)
        
        assert await memory_adapter.load_instance(sample_resource_instance.id) is None
        
        # Verify removed from hub's instance list
        instances = await memory_adapter.list_instances(hub_id)
        assert len(instances) == 0


# =========================================================================
# Metrics Operations Tests
# =========================================================================

class TestMetricsOperations:
    """Test metrics storage and retrieval"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_metrics(self, memory_adapter):
        """Test saving and retrieving metrics"""
        instance_id = "metrics-instance-001"
        
        metrics = ResourceMetrics(
            cpu_percent=45.5,
            memory_percent=60.2,
            request_count=100,
            error_count=2,
            avg_response_time_ms=150,
            active_connections=5
        )
        
        await memory_adapter.save_metrics(instance_id, metrics)
        
        # Get metrics history
        start_time = datetime.utcnow() - timedelta(hours=1)
        end_time = datetime.utcnow() + timedelta(hours=1)
        
        history = await memory_adapter.get_metrics_history(
            instance_id, start_time, end_time
        )
        
        assert len(history) > 0
        assert history[0]["cpu_percent"] == 45.5
        assert history[0]["memory_percent"] == 60.2
    
    @pytest.mark.asyncio
    async def test_metrics_ordering(self, memory_adapter):
        """Test that metrics are stored in time order"""
        instance_id = "ordering-instance-001"
        
        # Save multiple metrics
        for i in range(5):
            metrics = ResourceMetrics(
                cpu_percent=50 + i,
                memory_percent=60 + i
            )
            await memory_adapter.save_metrics(instance_id, metrics)
            await asyncio.sleep(0.01)  # Small delay to ensure different timestamps
        
        # Get metrics history
        start_time = datetime.utcnow() - timedelta(hours=1)
        end_time = datetime.utcnow() + timedelta(hours=1)
        
        history = await memory_adapter.get_metrics_history(
            instance_id, start_time, end_time
        )
        
        # Verify metrics are in chronological order
        timestamps = [m["timestamp"] for m in history]
        assert timestamps == sorted(timestamps)


# =========================================================================
# Memory-Specific Tests
# =========================================================================

class TestMemorySpecificFeatures:
    """Test features specific to in-memory storage"""
    
    @pytest.mark.asyncio
    async def test_data_isolation(self, memory_adapter):
        """Test that data is properly isolated between different types"""
        # Create items with same ID but different types
        task_id = "shared-id-001"
        workflow_id = "shared-id-001"
        
        task = Task(
            id=task_id,
            name="Test Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="some-workflow"
        )
        
        workflow = Workflow(
            id=workflow_id,
            name="Test Workflow",
            tasks=[]
        )
        
        await memory_adapter.save_task(task)
        await memory_adapter.save_workflow(workflow)
        
        # Verify they don't interfere with each other
        retrieved_task = await memory_adapter.get_task(task_id)
        retrieved_workflow = await memory_adapter.get_workflow(workflow_id)
        
        assert retrieved_task.name == "Test Task"
        assert retrieved_workflow.name == "Test Workflow"
    
    @pytest.mark.asyncio
    async def test_event_storage_limits(self, memory_adapter):
        """Test that event storage respects maxlen limits"""
        await memory_adapter.initialize()
        
        # Add more events than maxlen
        for i in range(10005):
            memory_adapter.events_global.append(f"event-{i}")
        
        # Should only keep last 10000
        assert len(memory_adapter.events_global) == 10000
        assert memory_adapter.events_global[0] == "event-5"
        assert memory_adapter.events_global[-1] == "event-10004"
    
    @pytest.mark.asyncio
    async def test_cleanup_old_data(self, memory_adapter):
        """Test cleaning up old completed tasks"""
        # Create old completed tasks
        old_date = datetime.utcnow() - timedelta(days=30)
        recent_date = datetime.utcnow() - timedelta(hours=1)
        
        old_task = Task(
            id="old-completed-task",
            name="Old Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="cleanup-workflow",
            status=TaskStatus.COMPLETED,
            completed_at=old_date
        )
        
        recent_task = Task(
            id="recent-completed-task",
            name="Recent Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="cleanup-workflow",
            status=TaskStatus.COMPLETED,
            completed_at=recent_date
        )
        
        await memory_adapter.save_task(old_task)
        await memory_adapter.save_task(recent_task)
        
        # Clean up data older than 7 days
        cutoff = datetime.utcnow() - timedelta(days=7)
        deleted_count = await memory_adapter.cleanup_old_data(cutoff)
        
        assert deleted_count == 1
        assert await memory_adapter.get_task("old-completed-task") is None
        assert await memory_adapter.get_task("recent-completed-task") is not None


# =========================================================================
# Event Adapter Tests
# =========================================================================

class TestEventAdapter:
    """Test the event-enabled memory adapter"""
    
    @pytest.mark.asyncio
    async def test_event_adapter_initialization(self):
        """Test event adapter initialization"""
        adapter = UnifiedMemoryEventsAdapter()
        await adapter.initialize()
        
        assert adapter._initialized
        assert isinstance(adapter._event_queue, asyncio.Queue)
        assert isinstance(adapter._event_channels, dict)
        assert isinstance(adapter._locks, dict)
        
        await adapter.shutdown()
    
    @pytest.mark.asyncio
    async def test_event_emission(self, memory_events_adapter):
        """Test event emission"""
        from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity
        
        event = GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            severity=EventSeverity.INFO,
            data={"task_id": "test-task-001"},
            source="test",
            tags={"test": "value"}
        )
        
        await memory_events_adapter.emit_event(event)
        
        # Check event was queued
        assert memory_events_adapter._event_queue.qsize() > 0
        
        # Get the event from queue
        event_data = await memory_events_adapter._event_queue.get()
        assert event_data["event_type"] == "task:started"  # Event type is normalized
        assert event_data["data"]["task_id"] == "test-task-001"
    
    @pytest.mark.asyncio
    async def test_task_status_change_emits_event(self, memory_events_adapter):
        """Test that task status changes emit events"""
        task = Task(
            id="event-task-001",
            name="Event Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="event-workflow",
            status=TaskStatus.PENDING
        )
        
        await memory_events_adapter.save_task(task)
        
        # Clear any events from initial save
        while not memory_events_adapter._event_queue.empty():
            await memory_events_adapter._event_queue.get()
        
        # Update task status to trigger event - create a new task object
        updated_task = Task(
            id=task.id,
            name=task.name,
            protocol=task.protocol,
            method=task.method,
            params=task.params,
            workflow_id=task.workflow_id,
            status=TaskStatus.EXECUTING,
            assigned_provider="provider-001"
        )
        await memory_events_adapter.save_task(updated_task)
        
        # Verify status was updated
        updated_task = await memory_events_adapter.get_task(task.id)
        assert updated_task.status == TaskStatus.EXECUTING
        assert updated_task.assigned_provider == "provider-001"
        
        # Check that event was emitted
        assert memory_events_adapter._event_queue.qsize() > 0
    
    @pytest.mark.asyncio
    async def test_workflow_completion_check(self, memory_events_adapter):
        """Test workflow completion checking"""
        # Create workflow with tasks
        workflow = Workflow(
            id="check-workflow",
            name="Check Workflow",
            tasks=[]
        )
        await memory_events_adapter.save_workflow(workflow)
        
        # Create tasks
        for i in range(3):
            task = Task(
                id=f"check-task-{i}",
                name=f"Task {i}",
                protocol="test",
                method="test",
                params={},
                workflow_id=workflow.id,
                status=TaskStatus.COMPLETED if i < 2 else TaskStatus.PENDING
            )
            await memory_events_adapter.save_task(task)
        
        # Check if workflow is complete (should use check_and_complete_workflow)
        is_complete = await memory_events_adapter.check_and_complete_workflow(workflow.id)
        assert not is_complete
        
        # Complete last task
        last_task = await memory_events_adapter.get_task("check-task-2")
        last_task.status = TaskStatus.COMPLETED
        await memory_events_adapter.save_task(last_task)
        
        # Now workflow should be complete
        is_complete = await memory_events_adapter.check_and_complete_workflow(workflow.id)
        assert is_complete


# =========================================================================
# Error Handling Tests
# =========================================================================

class TestErrorHandling:
    """Test error handling and edge cases"""
    
    @pytest.mark.asyncio
    async def test_operations_without_initialization(self):
        """Test that operations work even without explicit initialization"""
        adapter = UnifiedInMemoryAdapter()
        
        # Should auto-initialize or handle gracefully
        task = Task(
            id="no-init-task",
            name="Test",
            protocol="test",
            method="test",
            params={},
            workflow_id="test"
        )
        
        await adapter.save_task(task)
        result = await adapter.get_task("no-init-task")
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_concurrent_modifications(self, memory_adapter):
        """Test handling concurrent modifications"""
        task = Task(
            id="concurrent-task",
            name="Concurrent Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="concurrent-workflow",
            status=TaskStatus.PENDING
        )
        
        await memory_adapter.save_task(task)
        
        # Simulate concurrent updates
        async def update_task(status):
            task_copy = await memory_adapter.get_task("concurrent-task")
            task_copy.status = status
            await memory_adapter.save_task(task_copy)
        
        # Run concurrent updates
        await asyncio.gather(
            update_task(TaskStatus.EXECUTING),
            update_task(TaskStatus.COMPLETED),
            update_task(TaskStatus.FAILED)
        )
        
        # One of the updates should win
        final_task = await memory_adapter.get_task("concurrent-task")
        assert final_task.status in [TaskStatus.EXECUTING, TaskStatus.COMPLETED, TaskStatus.FAILED]
    
    @pytest.mark.asyncio
    async def test_large_workflow_handling(self, memory_adapter):
        """Test handling of large workflows with many tasks"""
        # Create workflow with many tasks
        num_tasks = 1000
        tasks = [
            Task(
                id=f"large-task-{i}",
                name=f"Task {i}",
                protocol="test",
                method="test",
                params={"index": i},
                workflow_id="large-workflow"
            )
            for i in range(num_tasks)
        ]
        
        workflow = Workflow(
            id="large-workflow",
            name="Large Workflow",
            tasks=tasks
        )
        
        # Should handle large workflow
        await memory_adapter.save_workflow(workflow)
        retrieved = await memory_adapter.get_workflow("large-workflow")
        
        assert retrieved is not None
        assert len(retrieved.tasks) == num_tasks


# =========================================================================
# Integration Tests
# =========================================================================

class TestIntegration:
    """Integration tests for complex scenarios"""
    
    @pytest.mark.asyncio
    async def test_complete_workflow_lifecycle(self, memory_adapter):
        """Test complete workflow lifecycle from creation to completion"""
        # Create workflow with dependencies
        task1 = Task(
            id="lifecycle-task-1",
            name="Task 1",
            protocol="test",
            method="init",
            params={},
            workflow_id="lifecycle-workflow"
        )
        
        task2 = Task(
            id="lifecycle-task-2",
            name="Task 2",
            protocol="test",
            method="process",
            params={},
            dependencies=["lifecycle-task-1"],
            workflow_id="lifecycle-workflow"
        )
        
        task3 = Task(
            id="lifecycle-task-3",
            name="Task 3",
            protocol="test",
            method="finalize",
            params={},
            dependencies=["lifecycle-task-2"],
            workflow_id="lifecycle-workflow"
        )
        
        workflow = Workflow(
            id="lifecycle-workflow",
            name="Lifecycle Workflow",
            tasks=[task1, task2, task3]
        )
        
        # Save workflow
        await memory_adapter.save_workflow(workflow)
        for task in workflow.tasks:
            await memory_adapter.save_task(task)
        
        # Start execution
        execution = WorkflowExecution(
            execution_id="lifecycle-exec-001",
            workflow_id=workflow.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.utcnow(),
            total_tasks=3
        )
        await memory_adapter.save_workflow_execution(execution)
        
        # Execute tasks in order
        for task in [task1, task2, task3]:
            # Update task status
            task.status = TaskStatus.EXECUTING
            task.started_at = datetime.utcnow()
            await memory_adapter.save_task(task)
            
            # Complete task
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            await memory_adapter.save_task(task)
            
            # Save result
            result = TaskResult(
                task_id=task.id,
                workflow_id=workflow.id,
                status=TaskStatus.COMPLETED,
                result={"success": True},
                started_at=task.started_at,
                completed_at=task.completed_at
            )
            await memory_adapter.save_task_result(result)
            
            # Update execution
            execution.completed_tasks += 1
        
        # Complete execution
        execution.status = WorkflowStatus.COMPLETED
        execution.completed_at = datetime.utcnow()
        await memory_adapter.save_workflow_execution(execution)
        
        # Verify final state
        final_execution = await memory_adapter.get_workflow_execution(execution.execution_id)
        assert final_execution.status == WorkflowStatus.COMPLETED
        assert final_execution.completed_tasks == 3
        assert final_execution.failed_tasks == 0
        
        # Verify all tasks completed
        workflow_tasks = await memory_adapter.get_tasks_by_workflow(workflow.id)
        assert all(t.status == TaskStatus.COMPLETED for t in workflow_tasks)


# =========================================================================
# Performance Tests
# =========================================================================

class TestPerformance:
    """Test performance characteristics"""
    
    @pytest.mark.asyncio
    async def test_bulk_operations_performance(self, memory_adapter):
        """Test performance of bulk operations"""
        import time
        
        num_tasks = 10000
        tasks = [
            Task(
                id=f"perf-task-{i}",
                name=f"Performance Task {i}",
                protocol="test",
                method="test",
                params={"index": i},
                workflow_id="perf-workflow",
                status=TaskStatus.PENDING if i % 2 == 0 else TaskStatus.COMPLETED
            )
            for i in range(num_tasks)
        ]
        
        # Measure batch save time
        start_time = time.time()
        await memory_adapter.save_tasks_batch(tasks)
        batch_time = time.time() - start_time
        
        # Memory operations should be very fast
        assert batch_time < 1.0  # 1 second for 10000 tasks
        
        # Measure retrieval by status
        start_time = time.time()
        pending_tasks = await memory_adapter.get_tasks_by_status("pending")
        query_time = time.time() - start_time
        
        assert len(pending_tasks) == 5000
        assert query_time < 0.5  # Should be very fast for in-memory
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, memory_adapter):
        """Test concurrent operations don't cause issues"""
        async def worker(worker_id):
            for i in range(100):
                task = Task(
                    id=f"concurrent-{worker_id}-{i}",
                    name=f"Task {worker_id}-{i}",
                    protocol="test",
                    method="test",
                    params={},
                    workflow_id=f"concurrent-workflow-{worker_id}"
                )
                await memory_adapter.save_task(task)
                
                # Random operations
                await memory_adapter.get_task(task.id)
                task.status = TaskStatus.EXECUTING
                await memory_adapter.save_task(task)
        
        # Run multiple workers concurrently
        await asyncio.gather(*[worker(i) for i in range(10)])
        
        # Verify all tasks were saved
        all_tasks = await memory_adapter.get_tasks_by_status("executing")
        assert len(all_tasks) >= 1000  # 10 workers * 100 tasks


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])