"""
Test Suite for Unified Persistence Architecture

Tests all persistence adapters (Redis, SQL, In-Memory) with the same test cases
to ensure they all implement the interface correctly.
"""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid

# Import all adapters
from gleitzeit.persistence.unified_persistence import (
    UnifiedPersistenceAdapter,
    UnifiedInMemoryAdapter
)
from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter

# Import models
from gleitzeit.core.models import (
    Task, Workflow, TaskResult, WorkflowExecution,
    Priority, TaskStatus
)
from gleitzeit.hub.base import (
    ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def memory_adapter():
    """Create an in-memory adapter for testing"""
    adapter = UnifiedInMemoryAdapter()
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()


@pytest.fixture
async def sql_adapter():
    """Create a SQLite adapter for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    adapter = UnifiedSQLAlchemyAdapter(db_path=db_path)
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()
    
    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
async def redis_adapter():
    """Create a Redis adapter for testing (requires Redis running)"""
    try:
        adapter = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",  # Use database 15 for tests
            key_prefix="test_gleitzeit"
        )
        await adapter.initialize()
        
        # Clear test data
        await adapter._execute("FLUSHDB")
        
        yield adapter
        
        # Cleanup
        await adapter._execute("FLUSHDB")
        await adapter.shutdown()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.fixture(params=["memory", "sql", "redis"])
async def adapter(request):
    """Parametrized fixture that provides all adapter types"""
    if request.param == "memory":
        adapter = UnifiedInMemoryAdapter()
    elif request.param == "sql":
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        adapter = UnifiedSQLAlchemyAdapter(db_path=db_path)
    elif request.param == "redis":
        try:
            adapter = UnifiedRedisAdapter(
                redis_url="redis://localhost:6379/15",
                key_prefix="test_gleitzeit"
            )
            await adapter.initialize()
            await adapter._execute("FLUSHDB")
            await adapter.shutdown()
            
            # Recreate for actual test
            adapter = UnifiedRedisAdapter(
                redis_url="redis://localhost:6379/15",
                key_prefix="test_gleitzeit"
            )
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()
    
    # Cleanup for SQL
    if request.param == "sql":
        try:
            os.unlink(db_path)
        except:
            pass


# ============================================================================
# Test Helpers
# ============================================================================

def create_test_task(
    task_id: Optional[str] = None,
    name: str = "Test Task",
    status: str = "queued",
    priority: str = "normal",
    workflow_id: Optional[str] = None,
    dependencies: Optional[List[str]] = None,
    assigned_provider: Optional[str] = None
) -> Task:
    """Create a test task"""
    return Task(
        id=task_id or f"task_{uuid.uuid4().hex[:8]}",
        name=name,
        protocol="test",
        method="test_method",
        params={"test": "data"},
        status=status,
        priority=priority,
        workflow_id=workflow_id,
        dependencies=dependencies or [],  # Default to empty list instead of None
        assigned_provider=assigned_provider
    )


def create_test_workflow(
    workflow_id: Optional[str] = None,
    name: str = "Test Workflow"
) -> Workflow:
    """Create a test workflow"""
    return Workflow(
        id=workflow_id or f"workflow_{uuid.uuid4().hex[:8]}",
        name=name,
        tasks=[
            {"name": "Task 1", "protocol": "test", "method": "method1"},
            {"name": "Task 2", "protocol": "test", "method": "method2"}
        ],
        metadata={"test": "metadata"}
    )


def create_test_resource(
    instance_id: Optional[str] = None,
    name: str = "Test Resource",
    resource_type: ResourceType = ResourceType.OLLAMA,
    status: ResourceStatus = ResourceStatus.HEALTHY
) -> ResourceInstance:
    """Create a test resource instance"""
    return ResourceInstance(
        id=instance_id or f"resource_{uuid.uuid4().hex[:8]}",
        name=name,
        type=resource_type,
        endpoint="http://localhost:8080",
        status=status,
        metadata={"test": "metadata"},
        tags={"test", "resource"},
        capabilities={"llm", "embedding"}
    )


# ============================================================================
# Task/Workflow Tests
# ============================================================================

class TestTaskOperations:
    """Test task-related operations"""
    
    async def test_save_and_get_task(self, adapter):
        """Test saving and retrieving a task"""
        task = create_test_task(task_id="test_001")
        
        # Save task
        await adapter.save_task(task)
        
        # Retrieve task
        retrieved = await adapter.get_task("test_001")
        
        assert retrieved is not None
        assert retrieved.id == "test_001"
        assert retrieved.name == "Test Task"
        assert retrieved.protocol == "test"
        assert retrieved.status == "queued"
    
    async def test_get_nonexistent_task(self, adapter):
        """Test retrieving a non-existent task"""
        task = await adapter.get_task("nonexistent")
        assert task is None
    
    async def test_delete_task(self, adapter):
        """Test deleting a task"""
        task = create_test_task(task_id="test_002")
        
        # Save and verify
        await adapter.save_task(task)
        assert await adapter.get_task("test_002") is not None
        
        # Delete
        result = await adapter.delete_task("test_002")
        assert result is True
        
        # Verify deleted
        assert await adapter.get_task("test_002") is None
        
        # Delete non-existent
        result = await adapter.delete_task("test_002")
        assert result is False
    
    async def test_get_tasks_by_status(self, adapter):
        """Test retrieving tasks by status"""
        # Create tasks with different statuses
        tasks = [
            create_test_task(f"task_{i}", status=status)
            for i, status in enumerate(["queued", "queued", "executing", "completed"])
        ]
        
        for task in tasks:
            await adapter.save_task(task)
        
        # Get by status
        queued = await adapter.get_tasks_by_status("queued")
        assert len(queued) == 2
        
        executing = await adapter.get_tasks_by_status("executing")
        assert len(executing) == 1
        
        completed = await adapter.get_tasks_by_status("completed")
        assert len(completed) == 1
        
        failed = await adapter.get_tasks_by_status("failed")
        assert len(failed) == 0
    
    async def test_get_tasks_by_workflow(self, adapter):
        """Test retrieving tasks by workflow"""
        workflow_id = "workflow_001"
        
        # Create tasks with and without workflow
        tasks = [
            create_test_task(f"task_{i}", workflow_id=workflow_id if i < 3 else None)
            for i in range(5)
        ]
        
        for task in tasks:
            await adapter.save_task(task)
        
        # Get by workflow
        workflow_tasks = await adapter.get_tasks_by_workflow(workflow_id)
        assert len(workflow_tasks) == 3
        
        # Non-existent workflow
        empty = await adapter.get_tasks_by_workflow("nonexistent")
        assert len(empty) == 0
    
    async def test_save_tasks_batch(self, adapter):
        """Test batch saving of tasks"""
        tasks = [create_test_task(f"batch_{i}") for i in range(10)]
        
        # Batch save
        await adapter.save_tasks_batch(tasks)
        
        # Verify all saved
        for task in tasks:
            retrieved = await adapter.get_task(task.id)
            assert retrieved is not None
            assert retrieved.name == task.name
    
    async def test_task_result(self, adapter):
        """Test saving and retrieving task results"""
        task = create_test_task("task_with_result")
        await adapter.save_task(task)
        
        # Create and save result
        result = TaskResult(
            task_id="task_with_result",
            status="completed",
            result={"output": "test output"},
            error_message=None,
            duration_seconds=1.5
        )
        
        await adapter.save_task_result(result)
        
        # Retrieve result
        retrieved = await adapter.get_task_result("task_with_result")
        assert retrieved is not None
        assert retrieved.status == "completed"
        assert retrieved.result["output"] == "test output"
        assert retrieved.duration_seconds == 1.5
        
        # Non-existent result
        none_result = await adapter.get_task_result("nonexistent")
        assert none_result is None
    
    async def test_get_all_queued_tasks(self, adapter):
        """Test retrieving all queued tasks"""
        # Create tasks with various statuses
        statuses = ["queued", "retry_pending", "executing", "completed", "failed"]
        tasks = [
            create_test_task(f"queue_test_{i}", status=status)
            for i, status in enumerate(statuses)
        ]
        
        for task in tasks:
            await adapter.save_task(task)
        
        # Get queued tasks (should include queued, retry_pending, executing)
        queued = await adapter.get_all_queued_tasks()
        assert len(queued) == 3
        
        queued_statuses = {t.status for t in queued}
        assert queued_statuses == {"queued", "retry_pending", "executing"}
    
    async def test_get_task_count_by_status(self, adapter):
        """Test getting task counts by status"""
        # Create tasks with various statuses
        status_counts = {
            "queued": 5,
            "executing": 2,
            "completed": 3,
            "failed": 1
        }
        
        for status, count in status_counts.items():
            for i in range(count):
                task = create_test_task(f"{status}_{i}", status=status)
                await adapter.save_task(task)
        
        # Get counts
        counts = await adapter.get_task_count_by_status()
        
        for status, expected in status_counts.items():
            assert counts.get(status, 0) == expected


class TestWorkflowOperations:
    """Test workflow-related operations"""
    
    async def test_save_and_get_workflow(self, adapter):
        """Test saving and retrieving a workflow"""
        workflow = create_test_workflow("workflow_001")
        
        # Save workflow
        await adapter.save_workflow(workflow)
        
        # Retrieve workflow
        retrieved = await adapter.get_workflow("workflow_001")
        
        assert retrieved is not None
        assert retrieved.id == "workflow_001"
        assert retrieved.name == "Test Workflow"
        assert len(retrieved.tasks) == 2
    
    async def test_workflow_execution(self, adapter):
        """Test workflow execution tracking"""
        workflow = create_test_workflow("workflow_002")
        await adapter.save_workflow(workflow)
        
        # Create execution
        execution = WorkflowExecution(
            execution_id="exec_001",
            workflow_id="workflow_002",
            status="running",
            completed_tasks=1,
            failed_tasks=0,
            total_tasks=2
        )
        
        await adapter.save_workflow_execution(execution)
        
        # Retrieve execution
        retrieved = await adapter.get_workflow_execution("exec_001")
        assert retrieved is not None
        assert retrieved.workflow_id == "workflow_002"
        assert retrieved.status == "running"
        assert retrieved.completed_tasks == 1
        assert retrieved.total_tasks == 2


class TestQueueState:
    """Test queue state persistence"""
    
    async def test_save_and_get_queue_state(self, adapter):
        """Test saving and retrieving queue state"""
        state = {
            "total_enqueued": 100,
            "total_dequeued": 75,
            "completed_tasks": ["task_1", "task_2"],
            "failed_tasks": ["task_3"]
        }
        
        # Save state
        await adapter.save_queue_state("test_queue", state)
        
        # Retrieve state
        retrieved = await adapter.get_queue_state("test_queue")
        assert retrieved is not None
        assert retrieved["total_enqueued"] == 100
        assert retrieved["total_dequeued"] == 75
        assert "task_1" in retrieved["completed_tasks"]
    
    async def test_delete_queue_state(self, adapter):
        """Test deleting queue state"""
        state = {"test": "data"}
        
        # Save and verify
        await adapter.save_queue_state("delete_queue", state)
        assert await adapter.get_queue_state("delete_queue") is not None
        
        # Delete
        result = await adapter.delete_queue_state("delete_queue")
        assert result is True
        
        # Verify deleted
        assert await adapter.get_queue_state("delete_queue") is None
        
        # Delete non-existent
        result = await adapter.delete_queue_state("delete_queue")
        assert result is False


# ============================================================================
# Resource Management Tests
# ============================================================================

class TestResourceOperations:
    """Test resource management operations"""
    
    async def test_save_and_load_instance(self, adapter):
        """Test saving and loading resource instances"""
        instance = create_test_resource("resource_001")
        
        # Save instance
        await adapter.save_instance("hub_001", instance)
        
        # Load instance
        loaded = await adapter.load_instance("resource_001")
        assert loaded is not None
        assert loaded["id"] == "resource_001"
        assert loaded["name"] == "Test Resource"
        assert loaded["hub_id"] == "hub_001"
    
    async def test_list_instances(self, adapter):
        """Test listing instances for a hub"""
        # Create instances for different hubs
        instances = [
            create_test_resource(f"resource_{i}")
            for i in range(5)
        ]
        
        # Save to different hubs
        for i, instance in enumerate(instances):
            hub_id = "hub_A" if i < 3 else "hub_B"
            await adapter.save_instance(hub_id, instance)
        
        # List instances
        hub_a_instances = await adapter.list_instances("hub_A")
        assert len(hub_a_instances) == 3
        
        hub_b_instances = await adapter.list_instances("hub_B")
        assert len(hub_b_instances) == 2
        
        empty = await adapter.list_instances("hub_C")
        assert len(empty) == 0
    
    async def test_delete_instance(self, adapter):
        """Test deleting resource instances"""
        instance = create_test_resource("delete_me")
        
        # Save and verify
        await adapter.save_instance("hub_001", instance)
        assert await adapter.load_instance("delete_me") is not None
        
        # Delete
        await adapter.delete_instance("delete_me")
        
        # Verify deleted
        assert await adapter.load_instance("delete_me") is None
        
        # Verify removed from hub listing
        instances = await adapter.list_instances("hub_001")
        assert all(i["id"] != "delete_me" for i in instances)
    
    async def test_save_and_get_metrics(self, adapter):
        """Test saving and retrieving metrics"""
        instance = create_test_resource("metrics_test")
        await adapter.save_instance("hub_001", instance)
        
        # Save metrics
        metrics = ResourceMetrics(
            cpu_percent=45.5,
            memory_mb=1024,
            request_count=100,
            error_count=2,
            avg_response_time_ms=250,
            p95_response_time_ms=500,
            p99_response_time_ms=750
        )
        
        await adapter.save_metrics("metrics_test", metrics)
        
        # Retrieve metrics
        end_time = datetime.utcnow() + timedelta(minutes=1)
        start_time = end_time - timedelta(hours=1)
        
        history = await adapter.get_metrics_history("metrics_test", start_time, end_time)
        assert len(history) > 0
        
        latest = history[-1]
        assert latest["cpu_percent"] == 45.5
        assert latest["memory_mb"] == 1024
        assert latest["request_count"] == 100


class TestDistributedLocks:
    """Test distributed locking functionality"""
    
    async def test_acquire_and_release_lock(self, adapter):
        """Test acquiring and releasing locks"""
        # Acquire lock
        acquired = await adapter.acquire_lock("resource_1", "owner_1", timeout=30)
        assert acquired is True
        
        # Try to acquire same lock with different owner
        acquired2 = await adapter.acquire_lock("resource_1", "owner_2", timeout=30)
        assert acquired2 is False
        
        # Check owner
        owner = await adapter.get_lock_owner("resource_1")
        assert owner == "owner_1"
        
        # Release lock
        await adapter.release_lock("resource_1", "owner_1")
        
        # Check released
        owner = await adapter.get_lock_owner("resource_1")
        assert owner is None
        
        # Now different owner can acquire
        acquired3 = await adapter.acquire_lock("resource_1", "owner_2", timeout=30)
        assert acquired3 is True
    
    async def test_extend_lock(self, adapter):
        """Test extending lock timeout"""
        # Acquire lock
        await adapter.acquire_lock("resource_2", "owner_1", timeout=30)
        
        # Extend lock
        extended = await adapter.extend_lock("resource_2", "owner_1", timeout=60)
        assert extended is True
        
        # Try to extend with wrong owner
        extended2 = await adapter.extend_lock("resource_2", "owner_2", timeout=60)
        assert extended2 is False
        
        # Release
        await adapter.release_lock("resource_2", "owner_1")
    
    async def test_lock_expiration(self, adapter):
        """Test lock expiration (for in-memory adapter)"""
        if not isinstance(adapter, UnifiedInMemoryAdapter):
            pytest.skip("Lock expiration test only for in-memory adapter")
        
        # Acquire lock with very short timeout
        await adapter.acquire_lock("resource_3", "owner_1", timeout=1)
        
        # Wait for expiration
        await asyncio.sleep(2)
        
        # Lock should be expired
        owner = await adapter.get_lock_owner("resource_3")
        assert owner is None
        
        # Another owner can now acquire
        acquired = await adapter.acquire_lock("resource_3", "owner_2", timeout=30)
        assert acquired is True


# ============================================================================
# Cross-Domain Tests
# ============================================================================

class TestCrossDomainOperations:
    """Test operations that link tasks and resources"""
    
    async def test_get_tasks_for_resource(self, adapter):
        """Test getting tasks assigned to a resource"""
        # Create resource
        resource = create_test_resource("resource_x")
        await adapter.save_instance("hub_001", resource)
        
        # Create tasks assigned to this resource
        for i in range(3):
            task = create_test_task(
                f"task_r_{i}",
                status="executing",
                assigned_provider="resource_x"
            )
            await adapter.save_task(task)
        
        # Create tasks assigned elsewhere
        for i in range(2):
            task = create_test_task(
                f"task_other_{i}",
                status="executing",
                assigned_provider="resource_y"
            )
            await adapter.save_task(task)
        
        # Get tasks for resource
        tasks = await adapter.get_tasks_for_resource("resource_x")
        assert len(tasks) == 3
        assert all(t.assigned_provider == "resource_x" for t in tasks)
    
    async def test_get_resource_for_task(self, adapter):
        """Test getting resource assigned to a task"""
        # Create resource
        resource = create_test_resource("resource_y")
        await adapter.save_instance("hub_001", resource)
        
        # Create task assigned to resource
        task = create_test_task(
            "task_with_resource",
            assigned_provider="resource_y"
        )
        await adapter.save_task(task)
        
        # Get resource for task
        resource_data = await adapter.get_resource_for_task("task_with_resource")
        assert resource_data is not None
        assert resource_data["id"] == "resource_y"
        
        # Task without resource
        task2 = create_test_task("task_no_resource")
        await adapter.save_task(task2)
        
        resource_data2 = await adapter.get_resource_for_task("task_no_resource")
        assert resource_data2 is None
    
    async def test_get_resource_utilization(self, adapter):
        """Test getting resource utilization for a hub"""
        # Create resources with different statuses
        resources = [
            create_test_resource(f"util_{i}", status=status)
            for i, status in enumerate([
                ResourceStatus.HEALTHY,
                ResourceStatus.HEALTHY,
                ResourceStatus.DEGRADED,
                ResourceStatus.UNHEALTHY
            ])
        ]
        
        for resource in resources:
            await adapter.save_instance("hub_util", resource)
        
        # Create tasks for some resources
        for i in range(5):
            task = create_test_task(
                f"util_task_{i}",
                status="executing",
                assigned_provider=f"util_{i % 2}"  # Assign to first two resources
            )
            await adapter.save_task(task)
        
        # Get utilization
        utilization = await adapter.get_resource_utilization("hub_util")
        
        assert utilization["total_instances"] == 4
        assert utilization["status_distribution"][ResourceStatus.HEALTHY.value] == 2
        assert utilization["status_distribution"][ResourceStatus.DEGRADED.value] == 1
        
        # Check task distribution
        util_map = {u["instance_id"]: u["active_tasks"] 
                   for u in utilization["instance_utilization"]}
        assert util_map["util_0"] == 3  # Tasks 0, 2, 4
        assert util_map["util_1"] == 2  # Tasks 1, 3
        assert util_map["util_2"] == 0
        assert util_map["util_3"] == 0


# ============================================================================
# Data Cleanup Tests
# ============================================================================

class TestDataCleanup:
    """Test data cleanup operations"""
    
    async def test_cleanup_old_data(self, adapter):
        """Test cleaning up old completed tasks"""
        now = datetime.utcnow()
        
        # Create old completed tasks
        for i in range(3):
            task = create_test_task(f"old_{i}", status="completed")
            task.completed_at = now - timedelta(days=35)
            await adapter.save_task(task)
        
        # Create recent completed tasks
        for i in range(2):
            task = create_test_task(f"recent_{i}", status="completed")
            task.completed_at = now - timedelta(days=5)
            await adapter.save_task(task)
        
        # Create active tasks
        for i in range(2):
            task = create_test_task(f"active_{i}", status="executing")
            await adapter.save_task(task)
        
        # Cleanup old data (30 days)
        cutoff = now - timedelta(days=30)
        deleted = await adapter.cleanup_old_data(cutoff)
        
        assert deleted == 3
        
        # Verify old tasks deleted
        for i in range(3):
            task = await adapter.get_task(f"old_{i}")
            assert task is None
        
        # Verify recent and active tasks remain
        for i in range(2):
            task = await adapter.get_task(f"recent_{i}")
            assert task is not None
            
            task = await adapter.get_task(f"active_{i}")
            assert task is not None


# ============================================================================
# Performance Tests
# ============================================================================

class TestPerformance:
    """Test performance characteristics"""
    
    @pytest.mark.parametrize("count", [100, 500])
    async def test_bulk_operations(self, adapter, count):
        """Test bulk save and retrieve operations"""
        # Create many tasks
        tasks = [create_test_task(f"perf_{i}") for i in range(count)]
        
        # Measure bulk save time
        start = datetime.utcnow()
        await adapter.save_tasks_batch(tasks)
        save_time = (datetime.utcnow() - start).total_seconds()
        
        print(f"\nBulk save {count} tasks: {save_time:.3f}s")
        
        # Measure retrieve time
        start = datetime.utcnow()
        retrieved = await adapter.get_tasks_by_status("queued")
        retrieve_time = (datetime.utcnow() - start).total_seconds()
        
        print(f"Retrieve {len(retrieved)} tasks: {retrieve_time:.3f}s")
        
        assert len(retrieved) == count
        
        # Performance assertions (generous for CI environments)
        assert save_time < count * 0.1  # Less than 100ms per task
        assert retrieve_time < 5.0  # Less than 5 seconds total


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for complex scenarios"""
    
    async def test_complete_workflow_lifecycle(self, adapter):
        """Test complete workflow lifecycle with tasks and resources"""
        # Create workflow
        workflow = create_test_workflow("integration_workflow")
        await adapter.save_workflow(workflow)
        
        # Create execution
        execution = WorkflowExecution(
            execution_id="integration_exec",
            workflow_id="integration_workflow",
            status="pending",
            completed_tasks=0,
            failed_tasks=0,
            total_tasks=2
        )
        await adapter.save_workflow_execution(execution)
        
        # Create workflow tasks
        task1 = create_test_task(
            "wf_task_1",
            workflow_id="integration_workflow",
            status="queued"
        )
        task2 = create_test_task(
            "wf_task_2",
            workflow_id="integration_workflow",
            status="queued",
            dependencies=["wf_task_1"]
        )
        
        await adapter.save_task(task1)
        await adapter.save_task(task2)
        
        # Create resources
        resource = create_test_resource("integration_resource")
        await adapter.save_instance("integration_hub", resource)
        
        # Assign task to resource
        task1.status = "executing"
        task1.assigned_provider = "integration_resource"
        await adapter.save_task(task1)
        
        # Save metrics for resource
        metrics = ResourceMetrics(
            cpu_percent=50.0,
            memory_mb=512,
            request_count=1
        )
        await adapter.save_metrics("integration_resource", metrics)
        
        # Complete task 1
        task1.status = "completed"
        task1.completed_at = datetime.utcnow()
        await adapter.save_task(task1)
        
        result1 = TaskResult(
            task_id="wf_task_1",
            status="completed",
            result={"output": "Task 1 complete"},
            duration_seconds=2.5
        )
        await adapter.save_task_result(result1)
        
        # Update execution progress
        execution.completed_tasks = 1
        await adapter.save_workflow_execution(execution)
        
        # Verify workflow state
        wf_tasks = await adapter.get_tasks_by_workflow("integration_workflow")
        assert len(wf_tasks) == 2
        
        completed_tasks = [t for t in wf_tasks if t.status == "completed"]
        assert len(completed_tasks) == 1
        
        # Verify resource utilization
        utilization = await adapter.get_resource_utilization("integration_hub")
        assert utilization["total_instances"] == 1
        
        # Verify metrics
        end_time = datetime.utcnow() + timedelta(minutes=1)
        start_time = end_time - timedelta(hours=1)
        metrics_history = await adapter.get_metrics_history(
            "integration_resource", start_time, end_time
        )
        assert len(metrics_history) > 0