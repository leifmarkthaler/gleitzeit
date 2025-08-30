"""
Comprehensive test suite for Gleitzeit Redis persistence backend.

Tests all Redis adapter operations including:
- Connection and lifecycle management
- Task CRUD operations
- Workflow management
- Index maintenance
- Atomic operations
- Locking mechanisms
- Resource hub operations
- Metrics storage
- Error handling and edge cases
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from unittest.mock import Mock, patch, AsyncMock, MagicMock

# Test configuration
REDIS_TEST_URL = "redis://localhost:6379/15"  # Use DB 15 for tests
TEST_KEY_PREFIX = "test_gleitzeit"

# Import models
from gleitzeit.core.models import (
    Task, Workflow, TaskResult, WorkflowExecution,
    TaskStatus, WorkflowStatus, RetryConfig
)
from gleitzeit.hub.base import (
    ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType
)

# Import Redis adapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
async def redis_adapter():
    """Create a test Redis adapter"""
    adapter = UnifiedRedisAdapter(
        redis_url=REDIS_TEST_URL,
        key_prefix=TEST_KEY_PREFIX,
        metrics_retention_hours=1,
        enable_pubsub=True
    )
    await adapter.initialize()
    
    # Clean up any existing test data
    if adapter.redis:
        pattern = f"{TEST_KEY_PREFIX}:*"
        keys = []
        cursor = 0
        while True:
            cursor, batch = await adapter.redis.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        if keys:
            await adapter.redis.delete(*keys)
    
    yield adapter
    
    # Cleanup after test
    if adapter.redis:
        pattern = f"{TEST_KEY_PREFIX}:*"
        keys = []
        cursor = 0
        while True:
            cursor, batch = await adapter.redis.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        if keys:
            await adapter.redis.delete(*keys)
    
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
# Connection and Lifecycle Tests
# =========================================================================

class TestConnectionLifecycle:
    """Test Redis connection and lifecycle management"""
    
    @pytest.mark.asyncio
    async def test_initialize_connection(self):
        """Test successful Redis connection initialization"""
        adapter = UnifiedRedisAdapter(
            redis_url=REDIS_TEST_URL,
            key_prefix=TEST_KEY_PREFIX
        )
        
        assert not adapter._initialized
        assert adapter.redis is None
        
        await adapter.initialize()
        
        assert adapter._initialized
        assert adapter.redis is not None
        
        # Test connection is working
        result = await adapter.redis.ping()
        assert result is True
        
        await adapter.shutdown()
    
    @pytest.mark.asyncio
    async def test_initialize_with_pubsub(self):
        """Test initialization with pub/sub enabled"""
        adapter = UnifiedRedisAdapter(
            redis_url=REDIS_TEST_URL,
            key_prefix=TEST_KEY_PREFIX,
            enable_pubsub=True
        )
        
        await adapter.initialize()
        
        assert adapter._initialized
        assert adapter.pubsub is not None
        
        await adapter.shutdown()
        assert adapter.pubsub is None
    
    @pytest.mark.asyncio
    async def test_double_initialize(self):
        """Test that double initialization is safe"""
        adapter = UnifiedRedisAdapter(
            redis_url=REDIS_TEST_URL,
            key_prefix=TEST_KEY_PREFIX
        )
        
        await adapter.initialize()
        first_redis = adapter.redis
        
        await adapter.initialize()  # Should be no-op
        assert adapter.redis is first_redis
        
        await adapter.shutdown()
    
    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Test proper shutdown"""
        adapter = UnifiedRedisAdapter(
            redis_url=REDIS_TEST_URL,
            key_prefix=TEST_KEY_PREFIX,
            enable_pubsub=True
        )
        
        await adapter.initialize()
        await adapter.shutdown()
        
        assert not adapter._initialized
        assert adapter.redis is None
        assert adapter.pubsub is None
    
    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test handling of connection errors"""
        adapter = UnifiedRedisAdapter(
            redis_url="redis://nonexistent:6379/0",
            key_prefix=TEST_KEY_PREFIX
        )
        
        with pytest.raises(Exception):
            await adapter.initialize()
    
    @pytest.mark.asyncio
    async def test_redis_not_available(self):
        """Test error when redis package not installed"""
        with patch('gleitzeit.persistence.unified_redis.REDIS_AVAILABLE', False):
            with pytest.raises(ImportError, match="redis not installed"):
                UnifiedRedisAdapter()


# =========================================================================
# Task Operations Tests
# =========================================================================

class TestTaskOperations:
    """Test task CRUD operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_task(self, redis_adapter, sample_task):
        """Test saving and retrieving a task"""
        await redis_adapter.save_task(sample_task)
        
        retrieved = await redis_adapter.get_task(sample_task.id)
        
        assert retrieved is not None
        assert retrieved.id == sample_task.id
        assert retrieved.name == sample_task.name
        assert retrieved.protocol == sample_task.protocol
        assert retrieved.params == sample_task.params
        assert retrieved.workflow_id == sample_task.workflow_id
    
    @pytest.mark.asyncio
    async def test_save_task_without_workflow_id(self, redis_adapter):
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
            await redis_adapter.save_task(task)
    
    @pytest.mark.asyncio
    async def test_update_task(self, redis_adapter, sample_task):
        """Test updating an existing task"""
        await redis_adapter.save_task(sample_task)
        
        # Update task
        sample_task.status = TaskStatus.EXECUTING
        sample_task.assigned_provider = "provider-001"
        sample_task.started_at = datetime.utcnow()
        
        await redis_adapter.save_task(sample_task)
        
        retrieved = await redis_adapter.get_task(sample_task.id)
        assert retrieved.status == TaskStatus.EXECUTING
        assert retrieved.assigned_provider == "provider-001"
        assert retrieved.started_at is not None
    
    @pytest.mark.asyncio
    async def test_delete_task(self, redis_adapter, sample_task):
        """Test deleting a task"""
        await redis_adapter.save_task(sample_task)
        
        # Verify task exists
        assert await redis_adapter.get_task(sample_task.id) is not None
        
        # Delete task
        result = await redis_adapter.delete_task(sample_task.id)
        assert result is True
        
        # Verify task is deleted
        assert await redis_adapter.get_task(sample_task.id) is None
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self, redis_adapter):
        """Test deleting a task that doesn't exist"""
        result = await redis_adapter.delete_task("nonexistent-task")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_save_tasks_batch(self, redis_adapter):
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
        
        await redis_adapter.save_tasks_batch(tasks)
        
        # Verify all tasks were saved
        for task in tasks:
            retrieved = await redis_adapter.get_task(task.id)
            assert retrieved is not None
            assert retrieved.name == task.name
    
    @pytest.mark.asyncio
    async def test_task_with_complex_data(self, redis_adapter):
        """Test saving task with complex nested data"""
        task = Task(
            id="complex-task",
            name="Complex Task",
            protocol="test",
            method="complex_method",
            params={
                "nested": {
                    "deeply": {
                        "nested": ["value1", "value2"]
                    }
                },
                "list": [1, 2, 3],
                "bool": True
            },
            dependencies=["dep1", "dep2", "dep3"],
            retry_config=RetryConfig(
                max_attempts=3,
                backoff_multiplier=2.0,
                max_backoff=60
            ),
            tags={"tag1": "value1", "tag2": "value2"},
            metadata={"meta1": "data1"},
            workflow_id="complex-workflow"
        )
        
        await redis_adapter.save_task(task)
        retrieved = await redis_adapter.get_task(task.id)
        
        assert retrieved.params == task.params
        assert retrieved.dependencies == task.dependencies
        assert retrieved.retry_config.max_attempts == 3
        assert retrieved.tags == task.tags
        assert retrieved.metadata == task.metadata


# =========================================================================
# Task Status and Index Tests
# =========================================================================

class TestTaskStatusAndIndexes:
    """Test task status tracking and index operations"""
    
    @pytest.mark.asyncio
    async def test_get_tasks_by_status(self, redis_adapter):
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
            await redis_adapter.save_task(task)
        
        # Test retrieving by each status
        pending_tasks = await redis_adapter.get_tasks_by_status("pending")
        assert len(pending_tasks) == 1
        assert pending_tasks[0].status == TaskStatus.PENDING
        
        executing_tasks = await redis_adapter.get_tasks_by_status("executing")
        assert len(executing_tasks) == 1
        assert executing_tasks[0].status == TaskStatus.EXECUTING
    
    @pytest.mark.asyncio
    async def test_status_index_update(self, redis_adapter, sample_task):
        """Test that status indexes are updated when task status changes"""
        # Save task as pending
        sample_task.status = TaskStatus.PENDING
        await redis_adapter.save_task(sample_task)
        
        # Verify in pending index
        pending_tasks = await redis_adapter.get_tasks_by_status("pending")
        assert any(t.id == sample_task.id for t in pending_tasks)
        
        # Update to executing
        sample_task.status = TaskStatus.EXECUTING
        await redis_adapter.save_task(sample_task)
        
        # Verify moved from pending to executing index
        pending_tasks = await redis_adapter.get_tasks_by_status("pending")
        assert not any(t.id == sample_task.id for t in pending_tasks)
        
        executing_tasks = await redis_adapter.get_tasks_by_status("executing")
        assert any(t.id == sample_task.id for t in executing_tasks)
    
    @pytest.mark.asyncio
    async def test_get_tasks_by_workflow(self, redis_adapter):
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
            await redis_adapter.save_task(task)
        
        # Create task for different workflow
        other_task = Task(
            id="other-workflow-task",
            name="Other Task",
            protocol="test",
            method="test",
            params={},
            workflow_id="other-workflow"
        )
        await redis_adapter.save_task(other_task)
        
        # Get tasks for specific workflow
        tasks = await redis_adapter.get_tasks_by_workflow(workflow_id)
        assert len(tasks) == 3
        assert all(t.workflow_id == workflow_id for t in tasks)
    
    @pytest.mark.asyncio
    async def test_provider_index(self, redis_adapter):
        """Test provider index maintenance"""
        provider_id = "test-provider-001"
        
        # Create tasks assigned to provider
        for i in range(2):
            task = Task(
                id=f"provider-task-{i}",
                name=f"Task {i}",
                protocol="test",
                method="test",
                params={},
                workflow_id="provider-workflow",
                assigned_provider=provider_id
            )
            await redis_adapter.save_task(task)
        
        # Get tasks for provider
        tasks = await redis_adapter.get_tasks_for_resource(provider_id)
        assert len(tasks) == 0  # Only returns executing tasks
        
        # Update one to executing
        task = await redis_adapter.get_task("provider-task-0")
        task.status = TaskStatus.EXECUTING
        await redis_adapter.save_task(task)
        
        tasks = await redis_adapter.get_tasks_for_resource(provider_id)
        assert len(tasks) == 1
        assert tasks[0].id == "provider-task-0"


# =========================================================================
# Workflow Operations Tests
# =========================================================================

class TestWorkflowOperations:
    """Test workflow CRUD operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_workflow(self, redis_adapter, sample_workflow):
        """Test saving and retrieving a workflow"""
        await redis_adapter.save_workflow(sample_workflow)
        
        retrieved = await redis_adapter.get_workflow(sample_workflow.id)
        
        assert retrieved is not None
        assert retrieved.id == sample_workflow.id
        assert retrieved.name == sample_workflow.name
        assert retrieved.description == sample_workflow.description
        assert len(retrieved.tasks) == len(sample_workflow.tasks)
    
    @pytest.mark.asyncio
    async def test_update_workflow(self, redis_adapter, sample_workflow):
        """Test updating workflow"""
        await redis_adapter.save_workflow(sample_workflow)
        
        # Update workflow
        sample_workflow.status = WorkflowStatus.RUNNING
        sample_workflow.started_at = datetime.utcnow()
        
        await redis_adapter.save_workflow(sample_workflow)
        
        retrieved = await redis_adapter.get_workflow(sample_workflow.id)
        assert retrieved.status == WorkflowStatus.RUNNING
        assert retrieved.started_at is not None
    
    @pytest.mark.asyncio
    async def test_delete_workflow(self, redis_adapter, sample_workflow):
        """Test deleting workflow and its tasks"""
        # Save workflow and its tasks
        await redis_adapter.save_workflow(sample_workflow)
        for task in sample_workflow.tasks:
            await redis_adapter.save_task(task)
        
        # Delete workflow
        result = await redis_adapter.delete_workflow(sample_workflow.id)
        assert result is True
        
        # Verify workflow is deleted
        assert await redis_adapter.get_workflow(sample_workflow.id) is None
        
        # Verify tasks are also deleted
        for task in sample_workflow.tasks:
            assert await redis_adapter.get_task(task.id) is None
    
    @pytest.mark.asyncio
    async def test_list_workflows(self, redis_adapter):
        """Test listing workflows with filtering"""
        # Create workflows with different statuses
        for i, status in enumerate([WorkflowStatus.PENDING, WorkflowStatus.RUNNING, WorkflowStatus.COMPLETED]):
            workflow = Workflow(
                id=f"list-workflow-{i}",
                name=f"Workflow {i}",
                tasks=[],
                status=status
            )
            await redis_adapter.save_workflow(workflow)
        
        # List all workflows
        result = await redis_adapter.list_workflows()
        assert result["total"] >= 3
        
        # List with status filter
        result = await redis_adapter.list_workflows(status="running")
        running_workflows = [w for w in result["workflows"] if w["status"] == "running"]
        assert len(running_workflows) >= 1
        
        # Test pagination
        result = await redis_adapter.list_workflows(limit=2, offset=0)
        assert len(result["workflows"]) <= 2


# =========================================================================
# Task Result Tests
# =========================================================================

class TestTaskResults:
    """Test task result operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_task_result(self, redis_adapter):
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
        
        await redis_adapter.save_task_result(result)
        
        retrieved = await redis_adapter.get_task_result(result.task_id)
        assert retrieved is not None
        assert retrieved.task_id == result.task_id
        assert retrieved.status == TaskStatus.COMPLETED
        assert retrieved.result == result.result
        assert retrieved.duration_seconds == result.duration_seconds
    
    @pytest.mark.asyncio
    async def test_task_result_with_error(self, redis_adapter):
        """Test saving task result with error"""
        result = TaskResult(
            task_id="error-task-001",
            status=TaskStatus.FAILED,
            error="Task failed due to timeout",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        
        await redis_adapter.save_task_result(result)
        
        retrieved = await redis_adapter.get_task_result(result.task_id)
        assert retrieved.status == TaskStatus.FAILED
        assert retrieved.error == "Task failed due to timeout"
        assert retrieved.result is None
    
    @pytest.mark.asyncio
    async def test_task_result_expiration(self, redis_adapter):
        """Test that task results have expiration set"""
        result = TaskResult(
            task_id="expiring-task-001",
            status=TaskStatus.COMPLETED,
            result={"data": "test"}
        )
        
        await redis_adapter.save_task_result(result)
        
        # Check TTL is set (should be 7 days)
        ttl = await redis_adapter.redis.ttl(
            redis_adapter._task_result_key(result.task_id)
        )
        assert ttl > 0
        assert ttl <= 7 * 24 * 3600


# =========================================================================
# Workflow Execution Tests
# =========================================================================

class TestWorkflowExecution:
    """Test workflow execution tracking"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_workflow_execution(self, redis_adapter):
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
        
        await redis_adapter.save_workflow_execution(execution)
        
        retrieved = await redis_adapter.get_workflow_execution(execution.execution_id)
        assert retrieved is not None
        assert retrieved.execution_id == execution.execution_id
        assert retrieved.workflow_id == execution.workflow_id
        assert retrieved.status == WorkflowStatus.RUNNING
        assert retrieved.completed_tasks == 2
        assert retrieved.total_tasks == 5
    
    @pytest.mark.asyncio
    async def test_workflow_execution_with_error(self, redis_adapter):
        """Test workflow execution with error"""
        execution = WorkflowExecution(
            execution_id="exec-error-001",
            workflow_id="workflow-001",
            status=WorkflowStatus.FAILED,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            error_message="Workflow failed due to dependency error",
            completed_tasks=3,
            failed_tasks=1,
            total_tasks=5
        )
        
        await redis_adapter.save_workflow_execution(execution)
        
        retrieved = await redis_adapter.get_workflow_execution(execution.execution_id)
        assert retrieved.status == WorkflowStatus.FAILED
        assert retrieved.error_message == "Workflow failed due to dependency error"
        assert retrieved.failed_tasks == 1


# =========================================================================
# Queue State Tests
# =========================================================================

class TestQueueState:
    """Test queue state persistence"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_queue_state(self, redis_adapter):
        """Test saving and retrieving queue state"""
        queue_state = {
            "name": "test-queue",
            "size": 10,
            "processing": 3,
            "completed_tasks": ["task-1", "task-2"],
            "failed_tasks": ["task-3"]
        }
        
        await redis_adapter.save_queue_state("test-queue", queue_state)
        
        retrieved = await redis_adapter.get_queue_state("test-queue")
        assert retrieved is not None
        assert retrieved["name"] == "test-queue"
        assert retrieved["size"] == 10
        assert retrieved["completed_tasks"] == ["task-1", "task-2"]
    
    @pytest.mark.asyncio
    async def test_delete_queue_state(self, redis_adapter):
        """Test deleting queue state"""
        queue_state = {"name": "delete-queue", "size": 5}
        
        await redis_adapter.save_queue_state("delete-queue", queue_state)
        assert await redis_adapter.get_queue_state("delete-queue") is not None
        
        result = await redis_adapter.delete_queue_state("delete-queue")
        assert result is True
        
        assert await redis_adapter.get_queue_state("delete-queue") is None
    
    @pytest.mark.asyncio
    async def test_clean_queue_state_for_tasks(self, redis_adapter):
        """Test cleaning queue state when tasks are deleted"""
        # Save queue state with task references
        queue_state = {
            "completed_tasks": ["task-1", "task-2", "task-3"],
            "failed_tasks": ["task-4", "task-5"]
        }
        await redis_adapter.save_queue_state("cleanup-queue", queue_state)
        
        # Clean tasks 2 and 4
        await redis_adapter.clean_queue_state_for_tasks(["task-2", "task-4"])
        
        retrieved = await redis_adapter.get_queue_state("cleanup-queue")
        assert "task-2" not in retrieved["completed_tasks"]
        assert "task-4" not in retrieved["failed_tasks"]
        assert "task-1" in retrieved["completed_tasks"]
        assert "task-3" in retrieved["completed_tasks"]
        assert "task-5" in retrieved["failed_tasks"]


# =========================================================================
# Distributed Locking Tests
# =========================================================================

class TestDistributedLocking:
    """Test distributed locking mechanisms"""
    
    @pytest.mark.asyncio
    async def test_acquire_and_release_lock(self, redis_adapter):
        """Test acquiring and releasing a lock"""
        resource_id = "test-resource"
        owner_id = "test-owner"
        
        # Acquire lock
        acquired = await redis_adapter.acquire_lock(resource_id, owner_id, timeout=10)
        assert acquired is True
        
        # Verify lock owner
        owner = await redis_adapter.get_lock_owner(resource_id)
        assert owner == owner_id
        
        # Release lock
        await redis_adapter.release_lock(resource_id, owner_id)
        
        # Verify lock released
        owner = await redis_adapter.get_lock_owner(resource_id)
        assert owner is None
    
    @pytest.mark.asyncio
    async def test_lock_prevents_double_acquisition(self, redis_adapter):
        """Test that lock prevents double acquisition"""
        resource_id = "exclusive-resource"
        
        # First owner acquires lock
        acquired1 = await redis_adapter.acquire_lock(resource_id, "owner1", timeout=10)
        assert acquired1 is True
        
        # Second owner tries to acquire - should fail
        acquired2 = await redis_adapter.acquire_lock(resource_id, "owner2", timeout=10)
        assert acquired2 is False
        
        # Release first lock
        await redis_adapter.release_lock(resource_id, "owner1")
        
        # Now second owner can acquire
        acquired2 = await redis_adapter.acquire_lock(resource_id, "owner2", timeout=10)
        assert acquired2 is True
    
    @pytest.mark.asyncio
    async def test_release_lock_wrong_owner(self, redis_adapter):
        """Test that only the owner can release a lock"""
        resource_id = "owned-resource"
        
        # Owner1 acquires lock
        await redis_adapter.acquire_lock(resource_id, "owner1", timeout=10)
        
        # Owner2 tries to release - should fail silently
        await redis_adapter.release_lock(resource_id, "owner2")
        
        # Lock should still be held by owner1
        owner = await redis_adapter.get_lock_owner(resource_id)
        assert owner == "owner1"
    
    @pytest.mark.asyncio
    async def test_extend_lock(self, redis_adapter):
        """Test extending lock timeout"""
        resource_id = "extend-resource"
        owner_id = "extend-owner"
        
        # Acquire lock with short timeout
        await redis_adapter.acquire_lock(resource_id, owner_id, timeout=5)
        
        # Extend lock
        extended = await redis_adapter.extend_lock(resource_id, owner_id, timeout=30)
        assert extended is True
        
        # Check TTL is updated
        ttl = await redis_adapter.redis.ttl(
            redis_adapter._lock_key(resource_id)
        )
        assert ttl > 20  # Should be close to 30
    
    @pytest.mark.asyncio
    async def test_extend_lock_wrong_owner(self, redis_adapter):
        """Test that only owner can extend lock"""
        resource_id = "extend-fail-resource"
        
        await redis_adapter.acquire_lock(resource_id, "owner1", timeout=10)
        
        # Different owner tries to extend
        extended = await redis_adapter.extend_lock(resource_id, "owner2", timeout=30)
        assert extended is False


# =========================================================================
# Resource Hub Operations Tests
# =========================================================================

class TestResourceHubOperations:
    """Test resource hub persistence operations"""
    
    @pytest.mark.asyncio
    async def test_save_and_load_instance(self, redis_adapter, sample_resource_instance):
        """Test saving and loading resource instance"""
        hub_id = "test-hub-001"
        
        await redis_adapter.save_instance(hub_id, sample_resource_instance)
        
        loaded = await redis_adapter.load_instance(sample_resource_instance.id)
        assert loaded is not None
        assert loaded["id"] == sample_resource_instance.id
        assert loaded["name"] == sample_resource_instance.name
        assert loaded["type"] == "compute"
        assert loaded["hub_id"] == hub_id
    
    @pytest.mark.asyncio
    async def test_list_instances(self, redis_adapter):
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
            await redis_adapter.save_instance(hub_id, instance)
        
        # List instances
        instances = await redis_adapter.list_instances(hub_id)
        assert len(instances) == 3
        assert all(inst["hub_id"] == hub_id for inst in instances)
    
    @pytest.mark.asyncio
    async def test_delete_instance(self, redis_adapter, sample_resource_instance):
        """Test deleting resource instance"""
        hub_id = "delete-hub-001"
        
        await redis_adapter.save_instance(hub_id, sample_resource_instance)
        assert await redis_adapter.load_instance(sample_resource_instance.id) is not None
        
        await redis_adapter.delete_instance(sample_resource_instance.id)
        
        assert await redis_adapter.load_instance(sample_resource_instance.id) is None
        
        # Verify removed from hub's instance list
        instances = await redis_adapter.list_instances(hub_id)
        assert len(instances) == 0


# =========================================================================
# Metrics Operations Tests
# =========================================================================

class TestMetricsOperations:
    """Test metrics storage and retrieval"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_metrics(self, redis_adapter):
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
        
        await redis_adapter.save_metrics(instance_id, metrics)
        
        # Get metrics history
        start_time = datetime.utcnow() - timedelta(hours=1)
        end_time = datetime.utcnow() + timedelta(hours=1)
        
        history = await redis_adapter.get_metrics_history(
            instance_id, start_time, end_time
        )
        
        assert len(history) > 0
        assert history[0]["cpu_percent"] == 45.5
        assert history[0]["memory_percent"] == 60.2
    
    @pytest.mark.asyncio
    async def test_metrics_retention(self, redis_adapter):
        """Test that old metrics are automatically removed"""
        instance_id = "retention-instance-001"
        
        # Save multiple metrics
        for i in range(5):
            metrics = ResourceMetrics(
                cpu_percent=50 + i,
                memory_percent=60 + i
            )
            await redis_adapter.save_metrics(instance_id, metrics)
            await asyncio.sleep(0.1)
        
        # Check TTL is set
        ttl = await redis_adapter.redis.ttl(
            redis_adapter._metrics_key(instance_id)
        )
        assert ttl > 0
        assert ttl <= redis_adapter.metrics_retention_hours * 3600


# =========================================================================
# Utility and Statistics Tests
# =========================================================================

class TestUtilityOperations:
    """Test utility and statistics operations"""
    
    @pytest.mark.asyncio
    async def test_get_task_count_by_status(self, redis_adapter):
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
            await redis_adapter.save_task(task)
        
        counts = await redis_adapter.get_task_count_by_status()
        
        assert counts.get("pending", 0) == 2
        assert counts.get("executing", 0) == 1
        assert counts.get("completed", 0) == 3
        assert counts.get("failed", 0) == 1
    
    @pytest.mark.asyncio
    async def test_get_all_queued_tasks(self, redis_adapter):
        """Test getting all tasks that should be queued"""
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
            await redis_adapter.save_task(task)
        
        queued_tasks = await redis_adapter.get_all_queued_tasks()
        
        assert len(queued_tasks) >= 3
        task_statuses = [t.status for t in queued_tasks]
        assert TaskStatus.QUEUED in task_statuses
        assert TaskStatus.RETRY_PENDING in task_statuses
        assert TaskStatus.EXECUTING in task_statuses
    
    @pytest.mark.asyncio
    async def test_cleanup_old_data(self, redis_adapter):
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
        
        await redis_adapter.save_task(old_task)
        await redis_adapter.save_task(recent_task)
        
        # Clean up data older than 7 days
        cutoff = datetime.utcnow() - timedelta(days=7)
        deleted_count = await redis_adapter.cleanup_old_data(cutoff)
        
        assert deleted_count == 1
        assert await redis_adapter.get_task("old-completed-task") is None
        assert await redis_adapter.get_task("recent-completed-task") is not None


# =========================================================================
# Error Handling and Edge Cases
# =========================================================================

class TestErrorHandlingAndEdgeCases:
    """Test error handling and edge cases"""
    
    @pytest.mark.asyncio
    async def test_operations_without_initialization(self):
        """Test that operations fail gracefully without initialization"""
        adapter = UnifiedRedisAdapter()
        
        task = Task(
            id="no-init-task",
            name="Test",
            protocol="test",
            method="test",
            params={},
            workflow_id="test"
        )
        
        # save_task raises RuntimeError when not initialized
        with pytest.raises(RuntimeError, match="Redis adapter not initialized"):
            await adapter.save_task(task)
        
        # Other operations return None/False/[] without raising
        result = await adapter.get_task("no-init-task")
        assert result is None
        
        tasks = await adapter.get_tasks_by_status("pending")
        assert tasks == []
        
        deleted = await adapter.delete_task("no-init-task")
        assert deleted is False
    
    @pytest.mark.asyncio
    async def test_malformed_data_handling(self, redis_adapter):
        """Test handling of malformed data in Redis"""
        # Manually insert malformed data
        await redis_adapter.redis.hset(
            redis_adapter._task_key("malformed-task"),
            mapping={
                "id": "malformed-task",
                "name": "Malformed",
                "params": "not-valid-json",  # Invalid JSON
                "status": "invalid-status"  # Invalid status
            }
        )
        
        # Should handle gracefully
        task = await redis_adapter.get_task("malformed-task")
        # Task might be None or have default values
        if task:
            assert task.status == TaskStatus.PENDING  # Should default
    
    @pytest.mark.asyncio
    async def test_concurrent_modifications(self, redis_adapter):
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
        
        await redis_adapter.save_task(task)
        
        # Simulate concurrent updates
        async def update_task(status):
            task_copy = await redis_adapter.get_task("concurrent-task")
            task_copy.status = status
            await redis_adapter.save_task(task_copy)
        
        # Run concurrent updates
        await asyncio.gather(
            update_task(TaskStatus.EXECUTING),
            update_task(TaskStatus.COMPLETED),
            update_task(TaskStatus.FAILED)
        )
        
        # One of the updates should win
        final_task = await redis_adapter.get_task("concurrent-task")
        assert final_task.status in [TaskStatus.EXECUTING, TaskStatus.COMPLETED, TaskStatus.FAILED]
    
    @pytest.mark.asyncio
    async def test_large_workflow_handling(self, redis_adapter):
        """Test handling of large workflows with many tasks"""
        # Create workflow with many tasks
        num_tasks = 100
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
        await redis_adapter.save_workflow(workflow)
        retrieved = await redis_adapter.get_workflow("large-workflow")
        
        assert retrieved is not None
        assert len(retrieved.tasks) == num_tasks
    
    @pytest.mark.asyncio
    async def test_special_characters_in_ids(self, redis_adapter):
        """Test handling of special characters in IDs"""
        special_ids = [
            "task:with:colons",
            "task-with-dashes",
            "task_with_underscores",
            "task.with.dots",
            "task/with/slashes"
        ]
        
        for task_id in special_ids:
            task = Task(
                id=task_id,
                name=f"Task {task_id}",
                protocol="test",
                method="test",
                params={},
                workflow_id="special-workflow"
            )
            
            await redis_adapter.save_task(task)
            retrieved = await redis_adapter.get_task(task_id)
            
            assert retrieved is not None
            assert retrieved.id == task_id


# =========================================================================
# Integration Tests
# =========================================================================

class TestIntegration:
    """Integration tests for complex scenarios"""
    
    @pytest.mark.asyncio
    async def test_complete_workflow_lifecycle(self, redis_adapter):
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
        await redis_adapter.save_workflow(workflow)
        for task in workflow.tasks:
            await redis_adapter.save_task(task)
        
        # Start execution
        execution = WorkflowExecution(
            execution_id="lifecycle-exec-001",
            workflow_id=workflow.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.utcnow(),
            total_tasks=3
        )
        await redis_adapter.save_workflow_execution(execution)
        
        # Execute tasks in order
        for task in [task1, task2, task3]:
            # Update task status
            task.status = TaskStatus.EXECUTING
            task.started_at = datetime.utcnow()
            await redis_adapter.save_task(task)
            
            # Complete task
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            await redis_adapter.save_task(task)
            
            # Save result
            result = TaskResult(
                task_id=task.id,
                workflow_id=workflow.id,
                status=TaskStatus.COMPLETED,
                result={"success": True},
                started_at=task.started_at,
                completed_at=task.completed_at
            )
            await redis_adapter.save_task_result(result)
            
            # Update execution
            execution.completed_tasks += 1
        
        # Complete execution
        execution.status = WorkflowStatus.COMPLETED
        execution.completed_at = datetime.utcnow()
        await redis_adapter.save_workflow_execution(execution)
        
        # Verify final state
        final_execution = await redis_adapter.get_workflow_execution(execution.execution_id)
        assert final_execution.status == WorkflowStatus.COMPLETED
        assert final_execution.completed_tasks == 3
        assert final_execution.failed_tasks == 0
        
        # Verify all tasks completed
        workflow_tasks = await redis_adapter.get_tasks_by_workflow(workflow.id)
        assert all(t.status == TaskStatus.COMPLETED for t in workflow_tasks)
    
    @pytest.mark.asyncio
    async def test_resource_hub_with_metrics(self, redis_adapter):
        """Test resource hub with metrics tracking"""
        hub_id = "metrics-hub-001"
        
        # Register resources
        resources = []
        for i in range(3):
            resource = ResourceInstance(
                id=f"resource-{i}",
                name=f"Resource {i}",
                type=ResourceType.COMPUTE,
                endpoint=f"http://localhost:900{i}"
            )
            await redis_adapter.save_instance(hub_id, resource)
            resources.append(resource)
        
        # Simulate metrics over time
        for _ in range(5):
            for resource in resources:
                metrics = ResourceMetrics(
                    cpu_percent=30 + (10 * _),
                    memory_percent=40 + (5 * _),
                    request_count=_ * 10,
                    avg_response_time_ms=100 + (_ * 10)
                )
                await redis_adapter.save_metrics(resource.id, metrics)
            await asyncio.sleep(0.1)
        
        # Get metrics history
        start_time = datetime.utcnow() - timedelta(hours=1)
        end_time = datetime.utcnow() + timedelta(hours=1)
        
        for resource in resources:
            history = await redis_adapter.get_metrics_history(
                resource.id, start_time, end_time
            )
            assert len(history) == 5
            # Verify metrics are ordered by time
            timestamps = [m["timestamp"] for m in history]
            assert timestamps == sorted(timestamps)


# =========================================================================
# Performance Tests
# =========================================================================

class TestPerformance:
    """Test performance characteristics"""
    
    @pytest.mark.asyncio
    async def test_bulk_operations_performance(self, redis_adapter):
        """Test performance of bulk operations"""
        import time
        
        num_tasks = 1000
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
        await redis_adapter.save_tasks_batch(tasks)
        batch_time = time.time() - start_time
        
        # Should complete reasonably quickly (adjust threshold as needed)
        assert batch_time < 5.0  # 5 seconds for 1000 tasks
        
        # Measure retrieval by status
        start_time = time.time()
        pending_tasks = await redis_adapter.get_tasks_by_status("pending")
        query_time = time.time() - start_time
        
        assert len(pending_tasks) == 500
        assert query_time < 1.0  # Should be fast
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, redis_adapter):
        """Test concurrent operations don't cause issues"""
        async def worker(worker_id):
            for i in range(10):
                task = Task(
                    id=f"concurrent-{worker_id}-{i}",
                    name=f"Task {worker_id}-{i}",
                    protocol="test",
                    method="test",
                    params={},
                    workflow_id=f"concurrent-workflow-{worker_id}"
                )
                await redis_adapter.save_task(task)
                
                # Random operations
                await redis_adapter.get_task(task.id)
                task.status = TaskStatus.EXECUTING
                await redis_adapter.save_task(task)
        
        # Run multiple workers concurrently
        await asyncio.gather(*[worker(i) for i in range(10)])
        
        # Verify all tasks were saved
        all_tasks = await redis_adapter.get_tasks_by_status("executing")
        assert len(all_tasks) >= 100  # 10 workers * 10 tasks


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])