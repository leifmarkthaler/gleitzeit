"""
Test Suite for In-Memory Adapter

Tests in-memory adapter specific features and edge cases.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
import uuid
import gc

from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def memory_adapter():
    """Create a fresh in-memory adapter for testing"""
    adapter = UnifiedInMemoryAdapter()
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()


@pytest.fixture
async def populated_adapter():
    """Create an in-memory adapter with test data"""
    adapter = UnifiedInMemoryAdapter()
    await adapter.initialize()
    
    # Add test tasks
    for i in range(5):
        task = Task(
            id=f"task_{i}",
            name=f"Task {i}",
            protocol="test",
            method="test_method",
            params={"index": i},
            status="queued" if i < 3 else "completed",
            priority="normal",
            workflow_id="workflow_1" if i < 2 else None
        )
        await adapter.save_task(task)
    
    # Add test resource
    resource = ResourceInstance(
        id="resource_1",
        name="Test Resource",
        type=ResourceType.OLLAMA,
        endpoint="http://localhost:8080",
        status=ResourceStatus.HEALTHY,
        metadata={"test": "data"}
    )
    await adapter.save_instance("hub_1", resource)
    
    yield adapter
    await adapter.shutdown()


# ============================================================================
# Memory Management Tests
# ============================================================================

class TestMemoryManagement:
    """Test memory-specific behavior"""
    
    async def test_initialization_state(self):
        """Test that adapter starts with clean state"""
        adapter = UnifiedInMemoryAdapter()
        
        # Before initialization
        assert not adapter._initialized
        assert len(adapter.tasks) == 0
        assert len(adapter.instances) == 0
        
        await adapter.initialize()
        
        # After initialization
        assert adapter._initialized
        assert len(adapter.tasks) == 0  # Still empty
        assert len(adapter.instances) == 0
        
        await adapter.shutdown()
        assert not adapter._initialized
    
    async def test_data_isolation(self):
        """Test that different adapter instances have isolated data"""
        adapter1 = UnifiedInMemoryAdapter()
        adapter2 = UnifiedInMemoryAdapter()
        
        await adapter1.initialize()
        await adapter2.initialize()
        
        # Save task in adapter1
        task = Task(
            id="isolated_task",
            name="Isolated",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await adapter1.save_task(task)
        
        # Should exist in adapter1
        retrieved1 = await adapter1.get_task("isolated_task")
        assert retrieved1 is not None
        
        # Should not exist in adapter2
        retrieved2 = await adapter2.get_task("isolated_task")
        assert retrieved2 is None
        
        await adapter1.shutdown()
        await adapter2.shutdown()
    
    async def test_data_persistence_across_operations(self, memory_adapter):
        """Test that data persists during adapter lifetime"""
        # Save data
        task = Task(
            id="persist_test",
            name="Persist Test",
            protocol="test",
            method="test",
            params={"data": "test"},
            priority="normal"
        )
        await memory_adapter.save_task(task)
        
        # Data should persist across multiple operations
        for _ in range(5):
            retrieved = await memory_adapter.get_task("persist_test")
            assert retrieved is not None
            assert retrieved.params["data"] == "test"
    
    async def test_shutdown_clears_data(self):
        """Test that shutdown clears all data"""
        adapter = UnifiedInMemoryAdapter()
        await adapter.initialize()
        
        # Add various data
        task = Task(
            id="shutdown_test",
            name="Shutdown Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await adapter.save_task(task)
        
        workflow = Workflow(
            id="shutdown_workflow",
            name="Shutdown Workflow",
            tasks=[]
        )
        await adapter.save_workflow(workflow)
        
        resource = ResourceInstance(
            id="shutdown_resource",
            name="Shutdown Resource",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await adapter.save_instance("shutdown_hub", resource)
        
        # Verify data exists
        assert len(adapter.tasks) == 1
        assert len(adapter.workflows) == 1
        assert len(adapter.instances) == 1
        
        # Shutdown
        await adapter.shutdown()
        
        # All data should be cleared
        assert len(adapter.tasks) == 0
        assert len(adapter.workflows) == 0
        assert len(adapter.instances) == 0
        assert len(adapter.task_results) == 0
        assert len(adapter.workflow_executions) == 0
        assert len(adapter.queue_states) == 0
        assert len(adapter.hub_instances) == 0
        assert len(adapter.metrics) == 0
        assert len(adapter.locks) == 0
    
    async def test_memory_usage_with_large_dataset(self, memory_adapter):
        """Test memory behavior with large datasets"""
        # Add many tasks
        num_tasks = 1000
        for i in range(num_tasks):
            task = Task(
                id=f"large_{i}",
                name=f"Large Task {i}",
                protocol="test",
                method="test",
                params={"index": i, "data": "x" * 100},  # Some data
                priority="normal"
            )
            await memory_adapter.save_task(task)
        
        # Verify all stored
        assert len(memory_adapter.tasks) == num_tasks
        
        # Test retrieval performance
        start = datetime.utcnow()
        tasks = await memory_adapter.get_tasks_by_status("queued")
        duration = (datetime.utcnow() - start).total_seconds()
        
        assert len(tasks) == num_tasks
        assert duration < 0.5  # Should be very fast in memory
    
    async def test_object_reference_handling(self, memory_adapter):
        """Test that adapter stores object references (not copies)"""
        task = Task(
            id="ref_test",
            name="Reference Test",
            protocol="test",
            method="test",
            params={"mutable": [1, 2, 3]},
            priority="normal"
        )
        
        await memory_adapter.save_task(task)
        
        # Modify original task
        task.name = "Modified"
        task.params["mutable"].append(4)
        
        # Retrieved task shares the reference (in-memory behavior)
        retrieved = await memory_adapter.get_task("ref_test")
        assert retrieved.name == "Modified"  # Shares reference with original
        # Note: This is expected behavior for in-memory adapter
        
        # Save a new version to update
        task2 = Task(
            id="ref_test",
            name="Updated",
            protocol="test",
            method="test",
            params={"new": "data"},
            priority="high"
        )
        await memory_adapter.save_task(task2)
        
        # Now should have the updated version
        retrieved2 = await memory_adapter.get_task("ref_test")
        assert retrieved2.name == "Updated"
        assert retrieved2.priority == "high"


# ============================================================================
# Dictionary Storage Tests
# ============================================================================

class TestDictionaryStorage:
    """Test the dictionary-based storage implementation"""
    
    async def test_direct_dictionary_access(self, memory_adapter):
        """Test direct access to internal dictionaries"""
        task = Task(
            id="dict_test",
            name="Dict Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await memory_adapter.save_task(task)
        
        # Direct dictionary access
        assert "dict_test" in memory_adapter.tasks
        assert memory_adapter.tasks["dict_test"].name == "Dict Test"
    
    async def test_hub_instances_mapping(self, memory_adapter):
        """Test hub to instances mapping"""
        # Create multiple instances for different hubs
        for hub_id in ["hub_A", "hub_B"]:
            for i in range(3):
                resource = ResourceInstance(
                    id=f"{hub_id}_resource_{i}",
                    name=f"Resource {i}",
                    type=ResourceType.OLLAMA,
                    endpoint=f"http://localhost:808{i}",
                    status=ResourceStatus.HEALTHY
                )
                await memory_adapter.save_instance(hub_id, resource)
        
        # Check hub_instances mapping
        assert "hub_A" in memory_adapter.hub_instances
        assert "hub_B" in memory_adapter.hub_instances
        assert len(memory_adapter.hub_instances["hub_A"]) == 3
        assert len(memory_adapter.hub_instances["hub_B"]) == 3
        
        # Check instance IDs are correct
        hub_a_ids = memory_adapter.hub_instances["hub_A"]
        assert "hub_A_resource_0" in hub_a_ids
        assert "hub_B_resource_0" not in hub_a_ids
    
    async def test_metrics_list_storage(self, memory_adapter):
        """Test metrics storage as lists"""
        resource = ResourceInstance(
            id="metrics_resource",
            name="Metrics Test",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await memory_adapter.save_instance("metrics_hub", resource)
        
        # Save multiple metrics
        for i in range(10):
            metrics = ResourceMetrics(
                cpu_percent=30.0 + i,
                memory_mb=512 + i * 10,
                request_count=100 * i
            )
            await memory_adapter.save_metrics("metrics_resource", metrics)
        
        # Check internal storage
        assert "metrics_resource" in memory_adapter.metrics
        assert len(memory_adapter.metrics["metrics_resource"]) == 10
        
        # Verify order (should be chronological)
        metrics_list = memory_adapter.metrics["metrics_resource"]
        cpu_values = [m["cpu_percent"] for m in metrics_list]
        assert cpu_values == [30.0 + i for i in range(10)]


# ============================================================================
# Lock Implementation Tests
# ============================================================================

class TestInMemoryLocks:
    """Test in-memory lock implementation"""
    
    async def test_lock_storage_format(self, memory_adapter):
        """Test lock storage format"""
        acquired = await memory_adapter.acquire_lock("resource_1", "owner_1", timeout=30)
        assert acquired is True
        
        # Check internal storage
        assert "resource_1" in memory_adapter.locks
        owner, expiry = memory_adapter.locks["resource_1"]
        assert owner == "owner_1"
        assert isinstance(expiry, datetime)
        assert expiry > datetime.utcnow()
    
    async def test_lock_expiration(self, memory_adapter):
        """Test automatic lock expiration"""
        # Acquire lock with very short timeout
        acquired = await memory_adapter.acquire_lock("expire_test", "owner_1", timeout=1)
        assert acquired is True
        
        # Lock should be held
        owner = await memory_adapter.get_lock_owner("expire_test")
        assert owner == "owner_1"
        
        # Wait for expiration
        await asyncio.sleep(1.5)
        
        # Lock should be expired and automatically cleaned up
        owner = await memory_adapter.get_lock_owner("expire_test")
        assert owner is None
        
        # Another owner should be able to acquire
        acquired2 = await memory_adapter.acquire_lock("expire_test", "owner_2", timeout=30)
        assert acquired2 is True
    
    async def test_lock_extension_updates_expiry(self, memory_adapter):
        """Test that extending lock updates expiry time"""
        # Acquire lock with short timeout
        await memory_adapter.acquire_lock("extend_test", "owner_1", timeout=5)
        
        # Get initial expiry
        _, initial_expiry = memory_adapter.locks["extend_test"]
        
        # Wait a bit
        await asyncio.sleep(1)
        
        # Extend lock
        extended = await memory_adapter.extend_lock("extend_test", "owner_1", timeout=30)
        assert extended is True
        
        # Check new expiry
        _, new_expiry = memory_adapter.locks["extend_test"]
        assert new_expiry > initial_expiry
        assert new_expiry > datetime.utcnow() + timedelta(seconds=25)
    
    async def test_concurrent_lock_operations(self, memory_adapter):
        """Test concurrent lock operations"""
        resource_id = "concurrent_lock"
        
        async def try_acquire(owner_id, delay=0):
            await asyncio.sleep(delay)
            return await memory_adapter.acquire_lock(resource_id, owner_id, timeout=10)
        
        # Run concurrent acquire attempts
        results = await asyncio.gather(
            try_acquire("owner_1", 0),
            try_acquire("owner_2", 0.01),
            try_acquire("owner_3", 0.02),
            try_acquire("owner_4", 0.03),
        )
        
        # Only one should succeed
        assert sum(results) == 1
        assert results[0] is True  # First one should win


# ============================================================================
# Performance Tests
# ============================================================================

class TestInMemoryPerformance:
    """Test performance characteristics of in-memory adapter"""
    
    async def test_query_performance(self, memory_adapter):
        """Test query performance with in-memory data"""
        # Add many tasks with different statuses
        statuses = ["queued", "executing", "completed", "failed"]
        for i in range(1000):
            task = Task(
                id=f"perf_{i}",
                name=f"Perf Task {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal",
                status=statuses[i % 4]
            )
            await memory_adapter.save_task(task)
        
        # Test query performance
        start = datetime.utcnow()
        queued = await memory_adapter.get_tasks_by_status("queued")
        query_time = (datetime.utcnow() - start).total_seconds()
        
        assert len(queued) == 250
        assert query_time < 0.01  # Should be very fast
    
    async def test_batch_operation_performance(self, memory_adapter):
        """Test batch operation performance"""
        tasks = [
            Task(
                id=f"batch_{i}",
                name=f"Batch Task {i}",
                protocol="test",
                method="test",
                params={"index": i},
                priority="normal"
            )
            for i in range(500)
        ]
        
        start = datetime.utcnow()
        await memory_adapter.save_tasks_batch(tasks)
        batch_time = (datetime.utcnow() - start).total_seconds()
        
        assert len(memory_adapter.tasks) == 500
        assert batch_time < 0.1  # Should be very fast
    
    async def test_concurrent_read_write(self, memory_adapter):
        """Test concurrent read/write operations"""
        async def write_task(i):
            task = Task(
                id=f"concurrent_{i}",
                name=f"Concurrent {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            await memory_adapter.save_task(task)
        
        async def read_task(i):
            return await memory_adapter.get_task(f"concurrent_{i}")
        
        # Write tasks concurrently
        write_tasks = [write_task(i) for i in range(100)]
        await asyncio.gather(*write_tasks)
        
        # Read tasks concurrently
        read_tasks = [read_task(i) for i in range(100)]
        results = await asyncio.gather(*read_tasks)
        
        # All should be retrieved successfully
        assert all(r is not None for r in results)
        assert len(results) == 100


# ============================================================================
# Edge Cases and Boundary Tests
# ============================================================================

class TestMemoryEdgeCases:
    """Test edge cases and boundary conditions"""
    
    async def test_empty_queries(self, memory_adapter):
        """Test queries on empty adapter"""
        # All queries should return empty results
        assert await memory_adapter.get_task("nonexistent") is None
        assert await memory_adapter.get_tasks_by_status("queued") == []
        assert await memory_adapter.get_tasks_by_workflow("nonexistent") == []
        assert await memory_adapter.get_all_queued_tasks() == []
        assert await memory_adapter.get_task_count_by_status() == {}
        assert await memory_adapter.list_instances("nonexistent") == []
    
    async def test_duplicate_saves(self, memory_adapter):
        """Test saving duplicate items"""
        task = Task(
            id="duplicate",
            name="Original",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        
        await memory_adapter.save_task(task)
        
        # Save again with modified data
        task.name = "Modified"
        await memory_adapter.save_task(task)
        
        # Should update, not duplicate
        assert len(memory_adapter.tasks) == 1
        retrieved = await memory_adapter.get_task("duplicate")
        assert retrieved.name == "Modified"
    
    async def test_delete_nonexistent(self, memory_adapter):
        """Test deleting non-existent items"""
        # Should return False for non-existent items
        assert await memory_adapter.delete_task("nonexistent") is False
        assert await memory_adapter.delete_queue_state("nonexistent") is False
    
    async def test_none_parameters(self, memory_adapter):
        """Test handling of None/empty parameters"""
        task = Task(
            id="none_test",
            name="None Test",
            protocol="test",
            method="test",
            params={},  # Empty params (None not allowed by pydantic)
            priority="normal",
            workflow_id=None,  # None workflow
            dependencies=[]  # Empty dependencies (None not allowed)
        )
        
        await memory_adapter.save_task(task)
        retrieved = await memory_adapter.get_task("none_test")
        
        assert retrieved is not None
        assert retrieved.params == {}
        assert retrieved.workflow_id is None
        assert retrieved.dependencies == []
    
    async def test_metrics_limit(self, memory_adapter):
        """Test metrics storage limit (100 entries)"""
        resource = ResourceInstance(
            id="limit_test",
            name="Limit Test",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await memory_adapter.save_instance("limit_hub", resource)
        
        # Save more than 100 metrics
        for i in range(150):
            metrics = ResourceMetrics(
                cpu_percent=i,
                memory_mb=512,
                request_count=i
            )
            await memory_adapter.save_metrics("limit_test", metrics)
        
        # Should only keep last 100
        assert len(memory_adapter.metrics["limit_test"]) == 100
        
        # Should have the latest metrics
        latest = memory_adapter.metrics["limit_test"][-1]
        assert latest["cpu_percent"] == 149  # Last one saved


# ============================================================================
# Data Consistency Tests
# ============================================================================

class TestMemoryDataConsistency:
    """Test data consistency in memory adapter"""
    
    async def test_workflow_task_consistency(self, memory_adapter):
        """Test consistency between workflows and tasks"""
        workflow = Workflow(
            id="consistency_wf",
            name="Consistency Test",
            tasks=[
                {"name": "Task 1", "protocol": "test", "method": "method1"},
                {"name": "Task 2", "protocol": "test", "method": "method2"}
            ]
        )
        await memory_adapter.save_workflow(workflow)
        
        # Create tasks for workflow
        for i in range(2):
            task = Task(
                id=f"consistency_task_{i}",
                name=f"Task {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal",
                workflow_id="consistency_wf"
            )
            await memory_adapter.save_task(task)
        
        # Delete one task
        await memory_adapter.delete_task("consistency_task_0")
        
        # Workflow should still exist
        wf = await memory_adapter.get_workflow("consistency_wf")
        assert wf is not None
        
        # Only one task should remain for workflow
        tasks = await memory_adapter.get_tasks_by_workflow("consistency_wf")
        assert len(tasks) == 1
        assert tasks[0].id == "consistency_task_1"
    
    async def test_resource_metrics_consistency(self, memory_adapter):
        """Test consistency between resources and metrics"""
        resource = ResourceInstance(
            id="metrics_consistency",
            name="Metrics Consistency",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await memory_adapter.save_instance("consistency_hub", resource)
        
        # Save metrics
        metrics = ResourceMetrics(
            cpu_percent=50.0,
            memory_mb=512,
            request_count=100
        )
        await memory_adapter.save_metrics("metrics_consistency", metrics)
        
        # Delete resource
        await memory_adapter.delete_instance("metrics_consistency")
        
        # Resource should be gone
        assert await memory_adapter.load_instance("metrics_consistency") is None
        
        # Metrics might still exist (orphaned)
        # This depends on implementation - in-memory doesn't cascade delete
        assert "metrics_consistency" in memory_adapter.metrics
    
    async def test_task_result_consistency(self, memory_adapter):
        """Test consistency between tasks and results"""
        task = Task(
            id="result_consistency",
            name="Result Consistency",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await memory_adapter.save_task(task)
        
        result = TaskResult(
            task_id="result_consistency",
            status="completed",
            result={"output": "test"},
            duration_seconds=1.0
        )
        await memory_adapter.save_task_result(result)
        
        # Delete task
        await memory_adapter.delete_task("result_consistency")
        
        # Task should be gone
        assert await memory_adapter.get_task("result_consistency") is None
        
        # Result might still exist (no cascade delete in memory)
        result = await memory_adapter.get_task_result("result_consistency")
        assert result is not None  # Orphaned result


# ============================================================================
# Integration Tests
# ============================================================================

class TestMemoryIntegration:
    """Integration tests for memory adapter"""
    
    async def test_complete_workflow_in_memory(self, memory_adapter):
        """Test complete workflow execution in memory"""
        # Create workflow with Task objects
        workflow_tasks = [
            Task(
                id=f"wf_task_{i}",
                name=name,
                protocol="test",
                method=method,
                params={}
            )
            for i, (name, method) in enumerate([
                ("Initialize", "init"),
                ("Process", "process"),
                ("Finalize", "finalize")
            ])
        ]
        
        workflow = Workflow(
            id="memory_workflow",
            name="Memory Workflow",
            tasks=workflow_tasks,
            metadata={"memory_test": True}
        )
        await memory_adapter.save_workflow(workflow)
        
        # Create execution  
        execution = WorkflowExecution(
            execution_id="memory_exec",
            workflow_id="memory_workflow",
            status="pending",
            completed_tasks=0,
            failed_tasks=0,
            total_tasks=3
        )
        await memory_adapter.save_workflow_execution(execution)
        
        # Process tasks
        task_ids = []
        for i, task in enumerate(workflow.tasks):
            # Update task with workflow info
            task.workflow_id = "memory_workflow"
            task.priority = "high" if i == 0 else "normal"
            task.dependencies = task_ids[-1:] if task_ids else []
            
            await memory_adapter.save_task(task)
            task_ids.append(task.id)
            
            # Simulate execution
            task.status = "executing"
            await memory_adapter.save_task(task)
            
            # Complete task
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            await memory_adapter.save_task(task)
            
            # Save result
            result = TaskResult(
                task_id=task.id,
                status="completed",
                result={"step": i, "name": task.name},
                duration_seconds=0.1 * (i + 1)
            )
            await memory_adapter.save_task_result(result)
            
            # Update execution
            execution.completed_tasks = i + 1
            if i == 2:
                execution.status = "completed"
            await memory_adapter.save_workflow_execution(execution)
        
        # Verify final state
        final_execution = await memory_adapter.get_workflow_execution("memory_exec")
        assert final_execution.status == "completed"
        assert final_execution.completed_tasks == 3
        
        # Verify all tasks completed
        workflow_tasks = await memory_adapter.get_tasks_by_workflow("memory_workflow")
        assert len(workflow_tasks) == 3
        assert all(t.status == "completed" for t in workflow_tasks)
        
        # Verify results
        for task_id in task_ids:
            result = await memory_adapter.get_task_result(task_id)
            assert result is not None
            assert result.status == "completed"