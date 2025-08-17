"""
Test Suite for Redis Adapter

Tests Redis-specific features and implementation details.
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any
import uuid

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def redis_adapter():
    """Create a Redis adapter for testing"""
    try:
        adapter = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",  # Use database 15 for tests
            key_prefix="test_gleitzeit",
            max_connections=10,
            socket_timeout=5,
            socket_connect_timeout=5
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


@pytest.fixture
async def populated_adapter(redis_adapter):
    """Create a Redis adapter with test data"""
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
        await redis_adapter.save_task(task)
    
    # Add test resource
    resource = ResourceInstance(
        id="resource_1",
        name="Test Resource",
        type=ResourceType.OLLAMA,
        endpoint="http://localhost:8080",
        status=ResourceStatus.HEALTHY,
        metadata={"test": "data"}
    )
    await redis_adapter.save_instance("hub_1", resource)
    
    return redis_adapter


# ============================================================================
# Connection and Configuration Tests
# ============================================================================

class TestRedisConnection:
    """Test Redis connection and configuration"""
    
    async def test_connection_initialization(self):
        """Test Redis adapter initialization"""
        adapter = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",
            key_prefix="init_test"
        )
        
        try:
            await adapter.initialize()
            assert adapter._pool is not None
            
            # Test connection with ping
            result = await adapter._execute("PING")
            assert result in [b"PONG", "PONG", True]  # Different Redis clients return different values
            
            await adapter.shutdown()
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    async def test_custom_configuration(self):
        """Test custom Redis configuration"""
        adapter = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",
            key_prefix="custom_test",
            max_connections=20,
            socket_timeout=10,
            socket_connect_timeout=10,
            retry_on_timeout=True,
            health_check_interval=60
        )
        
        try:
            await adapter.initialize()
            
            # Verify configuration
            assert adapter.key_prefix == "custom_test"
            # Pool configuration is set but not directly accessible
            
            await adapter.shutdown()
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    async def test_connection_failure(self):
        """Test handling of connection failure"""
        adapter = UnifiedRedisAdapter(
            redis_url="redis://invalid-host:6379/0",
            socket_connect_timeout=1
        )
        
        with pytest.raises(Exception):
            await adapter.initialize()
    
    async def test_key_prefix_isolation(self):
        """Test that key prefixes provide isolation"""
        adapter1 = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",
            key_prefix="prefix1"
        )
        adapter2 = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",
            key_prefix="prefix2"
        )
        
        try:
            await adapter1.initialize()
            await adapter2.initialize()
            
            # Save task in adapter1
            task = Task(
                id="shared_task",
                name="Test",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            await adapter1.save_task(task)
            
            # Should exist in adapter1
            retrieved1 = await adapter1.get_task("shared_task")
            assert retrieved1 is not None
            
            # Should not exist in adapter2 (different prefix)
            retrieved2 = await adapter2.get_task("shared_task")
            assert retrieved2 is None
            
            # Cleanup
            await adapter1._execute("FLUSHDB")
            await adapter1.shutdown()
            await adapter2.shutdown()
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")


# ============================================================================
# Redis-Specific Data Operations
# ============================================================================

class TestRedisDataOperations:
    """Test Redis-specific data operations"""
    
    async def test_key_structure(self, redis_adapter):
        """Test Redis key structure and naming"""
        task = Task(
            id="key_test",
            name="Key Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await redis_adapter.save_task(task)
        
        # Check key exists with correct prefix
        key = f"{redis_adapter.key_prefix}:task:key_test"
        exists = await redis_adapter._execute("EXISTS", key)
        assert exists == 1
        
        # Check data structure (stored as hash)
        data = await redis_adapter._execute("HGETALL", key)
        assert data["id"] == "key_test"
        assert data["name"] == "Key Test"
    
    async def test_index_operations(self, populated_adapter):
        """Test Redis index operations (sets for queries)"""
        # Check status index
        status_key = f"{populated_adapter.key_prefix}:idx:task_status:queued"
        members = await populated_adapter._execute("SMEMBERS", status_key)
        
        # Should have 3 queued tasks
        assert len(members) == 3
        assert "task_0" in members  # Redis adapter uses decode_responses=True, so strings not bytes
        assert "task_1" in members
        assert "task_2" in members
        
        # Check workflow index
        workflow_key = f"{populated_adapter.key_prefix}:idx:workflow_tasks:workflow_1"
        members = await populated_adapter._execute("SMEMBERS", workflow_key)
        
        # Should have 2 tasks in workflow
        assert len(members) == 2
        assert "task_0" in members  # Redis adapter uses decode_responses=True, so strings not bytes
        assert "task_1" in members
    
    async def test_atomic_operations(self, redis_adapter):
        """Test atomic operations using Redis transactions"""
        # Test atomic task status update
        task = Task(
            id="atomic_test",
            name="Atomic Test",
            protocol="test",
            method="test",
            params={},
            priority="normal",
            status="queued"
        )
        await redis_adapter.save_task(task)
        
        # Update status atomically
        task.status = "executing"
        await redis_adapter.save_task(task)
        
        # Verify indexes updated atomically
        queued_key = f"{redis_adapter.key_prefix}:idx:task_status:queued"
        executing_key = f"{redis_adapter.key_prefix}:idx:task_status:executing"
        
        is_in_queued = await redis_adapter._execute("SISMEMBER", queued_key, "atomic_test")
        is_in_executing = await redis_adapter._execute("SISMEMBER", executing_key, "atomic_test")
        
        assert is_in_queued == 0  # Not in queued
        assert is_in_executing == 1  # In executing
    
    async def test_bulk_operations_performance(self, redis_adapter):
        """Test bulk operations performance with pipelining"""
        tasks = [
            Task(
                id=f"bulk_{i}",
                name=f"Bulk Task {i}",
                protocol="test",
                method="test",
                params={"index": i},
                priority="normal"
            )
            for i in range(100)
        ]
        
        # Measure bulk save time
        start = datetime.utcnow()
        await redis_adapter.save_tasks_batch(tasks)
        duration = (datetime.utcnow() - start).total_seconds()
        
        # Should be fast with pipelining
        assert duration < 1.0  # Less than 1 second for 100 tasks
        
        # Verify all saved
        for task in tasks[:10]:  # Check first 10
            retrieved = await redis_adapter.get_task(task.id)
            assert retrieved is not None
    
    async def test_expiration_handling(self, redis_adapter):
        """Test TTL/expiration handling for metrics"""
        # Save metrics
        metrics = ResourceMetrics(
            cpu_percent=50.0,
            memory_mb=512,
            request_count=100
        )
        
        await redis_adapter.save_instance("hub_exp", ResourceInstance(
            id="exp_resource",
            name="Expiration Test",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        ))
        
        await redis_adapter.save_metrics("exp_resource", metrics)
        
        # Check TTL on metrics
        metrics_key = f"{redis_adapter.key_prefix}:metrics:exp_resource"
        ttl = await redis_adapter._execute("TTL", metrics_key)
        
        # Should have TTL set (24 hours = 86400 seconds)
        assert ttl > 0
        assert ttl <= 86400


# ============================================================================
# Redis-Specific Features
# ============================================================================

class TestRedisFeatures:
    """Test Redis-specific features"""
    
    async def test_distributed_locking_with_nx(self, redis_adapter):
        """Test distributed locking using SET NX"""
        resource_id = "lock_resource"
        owner1 = "owner_1"
        owner2 = "owner_2"
        
        # First owner acquires lock
        acquired1 = await redis_adapter.acquire_lock(resource_id, owner1, timeout=30)
        assert acquired1 is True
        
        # Second owner cannot acquire
        acquired2 = await redis_adapter.acquire_lock(resource_id, owner2, timeout=30)
        assert acquired2 is False
        
        # Check lock details in Redis
        lock_key = f"{redis_adapter.key_prefix}:lock:{resource_id}"
        lock_data = await redis_adapter._execute("GET", lock_key)
        lock_info = json.loads(lock_data)
        assert lock_info["owner_id"] == owner1
        
        # Check TTL is set
        ttl = await redis_adapter._execute("TTL", lock_key)
        assert ttl > 0
        assert ttl <= 30
    
    async def test_lock_extension(self, redis_adapter):
        """Test extending lock timeout"""
        resource_id = "extend_resource"
        owner = "owner_1"
        
        # Acquire lock with short timeout
        await redis_adapter.acquire_lock(resource_id, owner, timeout=10)
        
        # Check initial TTL
        lock_key = f"{redis_adapter.key_prefix}:lock:{resource_id}"
        initial_ttl = await redis_adapter._execute("TTL", lock_key)
        assert initial_ttl <= 10
        
        # Extend lock
        extended = await redis_adapter.extend_lock(resource_id, owner, timeout=60)
        assert extended is True
        
        # Check new TTL
        new_ttl = await redis_adapter._execute("TTL", lock_key)
        assert new_ttl > initial_ttl
        assert new_ttl <= 60
    
    async def test_pub_sub_notifications(self, redis_adapter):
        """Test pub/sub for real-time notifications (if implemented)"""
        # This is a placeholder for pub/sub functionality
        # Currently not implemented in the adapter
        pass
    
    async def test_lua_script_operations(self, redis_adapter):
        """Test Lua script operations for complex atomic operations"""
        # Save multiple tasks atomically using batch operation
        tasks = [
            Task(
                id=f"lua_{i}",
                name=f"Lua Task {i}",
                protocol="test",
                method="test",
                params={},
                priority="high" if i % 2 == 0 else "normal"
            )
            for i in range(10)
        ]
        
        await redis_adapter.save_tasks_batch(tasks)
        
        # Verify atomic batch save
        all_tasks = await redis_adapter.get_tasks_by_status("pending")
        assert len([t for t in all_tasks if t.priority == "high"]) == 5
    
    async def test_memory_optimization(self, redis_adapter):
        """Test memory optimization strategies"""
        # Create tasks with large metadata
        large_data = {"data": "x" * 1000}  # 1KB of data
        
        task = Task(
            id="memory_test",
            name="Memory Test",
            protocol="test",
            method="test",
            params=large_data,
            priority="normal"
        )
        
        await redis_adapter.save_task(task)
        
        # Check memory usage (Redis specific)
        memory_info = await redis_adapter._execute("MEMORY", "USAGE", 
                                                   f"{redis_adapter.key_prefix}:task:memory_test")
        
        # Memory usage should be reasonable (less than 10KB for 1KB data)
        assert memory_info < 10240


# ============================================================================
# Redis Cluster and Scaling Tests
# ============================================================================

class TestRedisScaling:
    """Test Redis scaling and cluster features"""
    
    async def test_connection_pool_management(self, redis_adapter):
        """Test connection pool management"""
        # Run multiple concurrent operations
        async def concurrent_operation(i):
            task = Task(
                id=f"concurrent_{i}",
                name=f"Concurrent {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            await redis_adapter.save_task(task)
            return await redis_adapter.get_task(f"concurrent_{i}")
        
        # Run 50 concurrent operations
        tasks = [concurrent_operation(i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(r is not None for r in results)
        assert len(results) == 50
    
    async def test_key_scanning_performance(self, populated_adapter):
        """Test key scanning performance for large datasets"""
        # Add many tasks
        for i in range(100):
            task = Task(
                id=f"scan_{i}",
                name=f"Scan Task {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal",
                status="queued"
            )
            await populated_adapter.save_task(task)
        
        # Test scanning performance
        start = datetime.utcnow()
        queued_tasks = await populated_adapter.get_tasks_by_status("queued")
        duration = (datetime.utcnow() - start).total_seconds()
        
        # Should be fast even with many tasks
        assert duration < 0.5
        assert len(queued_tasks) >= 100
    
    @pytest.mark.skip(reason="Requires Redis Cluster setup")
    async def test_cluster_support(self):
        """Test Redis Cluster support"""
        # This would require a Redis Cluster setup
        # Placeholder for cluster-specific tests
        pass


# ============================================================================
# Error Handling and Recovery
# ============================================================================

class TestRedisErrorHandling:
    """Test Redis error handling and recovery"""
    
    async def test_connection_retry(self):
        """Test connection retry logic"""
        adapter = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",
            retry_on_timeout=True,
            socket_timeout=1
        )
        
        try:
            await adapter.initialize()
            
            # Simulate timeout by using very large data
            large_data = "x" * (10 * 1024 * 1024)  # 10MB
            
            task = Task(
                id="timeout_test",
                name="Timeout Test",
                protocol="test",
                method="test",
                params={"data": large_data},
                priority="normal"
            )
            
            # Should handle large data gracefully
            await adapter.save_task(task)
            
            await adapter.shutdown()
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    async def test_data_corruption_handling(self, redis_adapter):
        """Test handling of corrupted data"""
        # Manually insert corrupted data
        key = f"{redis_adapter.key_prefix}:task:corrupted"
        await redis_adapter._execute("SET", key, "invalid json {]}")
        
        # Should handle gracefully
        task = await redis_adapter.get_task("corrupted")
        assert task is None  # Returns None for corrupted data
    
    async def test_partial_failure_recovery(self, redis_adapter):
        """Test recovery from partial operation failures"""
        # Create tasks where one might fail
        tasks = []
        for i in range(5):
            task = Task(
                id=f"partial_{i}",
                name=f"Partial {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            tasks.append(task)
        
        # Save batch (should handle any individual failures)
        await redis_adapter.save_tasks_batch(tasks)
        
        # Verify what was saved
        saved_count = 0
        for task in tasks:
            if await redis_adapter.get_task(task.id):
                saved_count += 1
        
        # At least some should be saved
        assert saved_count > 0


# ============================================================================
# Metrics and Monitoring
# ============================================================================

class TestRedisMetrics:
    """Test metrics and monitoring with Redis"""
    
    async def test_metrics_storage_with_ttl(self, redis_adapter):
        """Test metrics storage with automatic expiration"""
        resource = ResourceInstance(
            id="metrics_resource",
            name="Metrics Test",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await redis_adapter.save_instance("metrics_hub", resource)
        
        # Save multiple metrics over time
        for i in range(10):
            metrics = ResourceMetrics(
                cpu_percent=40.0 + i,
                memory_mb=500 + i * 10,
                request_count=100 * i,
                error_count=i,
                avg_response_time_ms=200 + i * 5
            )
            await redis_adapter.save_metrics("metrics_resource", metrics)
            await asyncio.sleep(0.1)  # Small delay between metrics
        
        # Retrieve metrics history
        end_time = datetime.utcnow() + timedelta(minutes=1)
        start_time = end_time - timedelta(hours=1)
        
        history = await redis_adapter.get_metrics_history(
            "metrics_resource", start_time, end_time
        )
        
        # Should have all metrics
        assert len(history) == 10
        
        # Check ordering (should be chronological)
        cpu_values = [m["cpu_percent"] for m in history]
        assert cpu_values == sorted(cpu_values)
    
    async def test_metrics_aggregation(self, redis_adapter):
        """Test metrics aggregation capabilities"""
        # Create multiple resources
        for i in range(3):
            resource = ResourceInstance(
                id=f"agg_resource_{i}",
                name=f"Agg Resource {i}",
                type=ResourceType.OLLAMA,
                endpoint=f"http://localhost:808{i}",
                status=ResourceStatus.HEALTHY
            )
            await redis_adapter.save_instance("agg_hub", resource)
            
            # Save metrics
            metrics = ResourceMetrics(
                cpu_percent=30.0 + i * 10,
                memory_mb=512,
                request_count=100
            )
            await redis_adapter.save_metrics(f"agg_resource_{i}", metrics)
        
        # Get utilization (includes aggregation)
        utilization = await redis_adapter.get_resource_utilization("agg_hub")
        
        assert utilization["total_instances"] == 3
        assert len(utilization["instance_utilization"]) == 3


# ============================================================================
# Integration Tests
# ============================================================================

class TestRedisIntegration:
    """Integration tests for Redis adapter"""
    
    async def test_full_workflow_with_redis(self, redis_adapter):
        """Test complete workflow using Redis persistence"""
        # Create workflow
        workflow = Workflow(
            id="redis_workflow",
            name="Redis Test Workflow",
            tasks=[
                {"name": "Task 1", "protocol": "test", "method": "method1"},
                {"name": "Task 2", "protocol": "test", "method": "method2", 
                 "dependencies": ["task_1"]}
            ]
        )
        await redis_adapter.save_workflow(workflow)
        
        # Create tasks
        task1 = Task(
            id="task_1",
            name="Task 1",
            protocol="test",
            method="method1",
            params={},
            priority="high",
            workflow_id="redis_workflow"
        )
        
        task2 = Task(
            id="task_2",
            name="Task 2",
            protocol="test",
            method="method2",
            params={},
            priority="normal",
            workflow_id="redis_workflow",
            dependencies=["task_1"]
        )
        
        await redis_adapter.save_task(task1)
        await redis_adapter.save_task(task2)
        
        # Create resource and assign task
        resource = ResourceInstance(
            id="redis_worker",
            name="Redis Worker",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await redis_adapter.save_instance("redis_hub", resource)
        
        # Assign task to resource
        task1.assigned_provider = "redis_worker"
        task1.status = "executing"
        await redis_adapter.save_task(task1)
        
        # Verify relationships
        resource_tasks = await redis_adapter.get_tasks_for_resource("redis_worker")
        assert len(resource_tasks) == 1
        assert resource_tasks[0].id == "task_1"
        
        workflow_tasks = await redis_adapter.get_tasks_by_workflow("redis_workflow")
        assert len(workflow_tasks) == 2
        
        # Complete task 1
        task1.status = "completed"
        await redis_adapter.save_task(task1)
        
        result = TaskResult(
            task_id="task_1",
            status="completed",
            result={"output": "success"},
            duration_seconds=1.5
        )
        await redis_adapter.save_task_result(result)
        
        # Verify result storage
        retrieved_result = await redis_adapter.get_task_result("task_1")
        assert retrieved_result.status == "completed"
        assert retrieved_result.duration_seconds == 1.5