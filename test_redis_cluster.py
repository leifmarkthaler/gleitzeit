#!/usr/bin/env python3
"""
Test Redis Cluster Implementation

Tests the new Redis scaling features including:
- Cluster mode support
- Hash tag strategy
- Cross-slot operations
- Sharding
- Resilience and failover
- Metrics collection
"""

import asyncio
import json
import time
from datetime import datetime
from typing import List, Dict

# Test configuration
TEST_SINGLE_REDIS = "redis://localhost:6379"
TEST_CLUSTER_NODES = [
    {"host": "localhost", "port": 7000},
    {"host": "localhost", "port": 7001},
    {"host": "localhost", "port": 7002},
]


async def test_hash_tag_strategy():
    """Test hash tag strategy for keeping related data together."""
    print("\n=== Testing Hash Tag Strategy ===")
    
    from src.gleitzeit.persistence.redis_cluster_adapter import HashTagStrategy
    
    # Test workflow key generation
    workflow_id = "workflow-123"
    
    workflow_key = HashTagStrategy.workflow_key(workflow_id, "workflow")
    task_key = HashTagStrategy.task_key("task-456", workflow_id)
    
    print(f"Workflow key: {workflow_key}")
    print(f"Task key: {task_key}")
    
    # Extract hash tags
    workflow_tag = HashTagStrategy.extract_hash_tag(f"prefix:{workflow_key}")
    task_tag = HashTagStrategy.extract_hash_tag(f"prefix:{task_key}")
    
    print(f"Workflow hash tag: {workflow_tag}")
    print(f"Task hash tag: {task_tag}")
    
    # Calculate slots (should be same for related data)
    workflow_slot = HashTagStrategy.calculate_slot(f"prefix:{workflow_key}")
    task_slot = HashTagStrategy.calculate_slot(f"prefix:{task_key}")
    
    print(f"Workflow slot: {workflow_slot}")
    print(f"Task slot: {task_slot}")
    
    # Verify they're on the same slot
    assert workflow_slot == task_slot, "Workflow and task should be on same slot"
    print("✅ Hash tag strategy working correctly")


async def test_sharding_strategy():
    """Test sharding strategies for data distribution."""
    print("\n=== Testing Sharding Strategy ===")
    
    from src.gleitzeit.persistence.redis_sharding import (
        ShardManager, ShardingStrategy, DataType
    )
    
    # Test workflow-based sharding
    manager = ShardManager(
        strategy=ShardingStrategy.WORKFLOW_BASED,
        num_shards=3
    )
    
    workflow_id = "workflow-123"
    task_id = "task-456"
    
    # Get shard keys
    workflow_shard = manager.get_shard_key(DataType.WORKFLOW, workflow_id)
    task_shard = manager.get_shard_key(DataType.TASK, task_id, workflow_id)
    
    print(f"Workflow shard: {workflow_shard}")
    print(f"Task shard: {task_shard}")
    
    # Should be same for workflow-based sharding
    assert workflow_shard == task_shard, "Workflow and task should be on same shard"
    
    # Test distribution estimation
    distribution = manager.estimate_distribution(1000)
    print(f"Distribution for 1000 items: {distribution}")
    
    # Test time-based sharding
    time_manager = ShardManager(
        strategy=ShardingStrategy.TIME_BASED,
        num_shards=3,
        time_window_seconds=3600  # 1 hour buckets
    )
    
    event_shard = time_manager.get_shard_key(
        DataType.EVENT,
        "event-123",
        timestamp=datetime.utcnow()
    )
    print(f"Event shard (time-based): {event_shard}")
    
    print("✅ Sharding strategy working correctly")


async def test_single_mode_adapter():
    """Test Redis adapter in single-instance mode."""
    print("\n=== Testing Single Mode Adapter ===")
    
    from src.gleitzeit.persistence.redis_cluster_adapter import (
        ClusterRedisAdapter, RedisMode
    )
    from src.gleitzeit.core.models import Workflow, WorkflowStatus
    
    # Create adapter in single mode
    adapter = ClusterRedisAdapter(
        redis_url=TEST_SINGLE_REDIS,
        redis_mode=RedisMode.SINGLE,
        key_prefix="test"
    )
    
    try:
        # Initialize
        await adapter.initialize()
        print("✅ Adapter initialized in single mode")
        
        # Test save and get workflow
        workflow = Workflow(
            id="test-workflow-1",
            name="Test Workflow",
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow(),
            config={},
            metadata={"test": True}
        )
        
        await adapter.save_workflow(workflow)
        print(f"✅ Saved workflow {workflow.id}")
        
        # Retrieve workflow
        retrieved = await adapter.get_workflow(workflow.id)
        assert retrieved is not None, "Should retrieve workflow"
        assert retrieved.id == workflow.id, "Workflow ID should match"
        print(f"✅ Retrieved workflow {retrieved.id}")
        
        # Test health check
        health = await adapter.health_check()
        print(f"Health status: {health}")
        assert health["healthy"], "Should be healthy"
        print("✅ Health check passed")
        
    finally:
        await adapter.close()
    
    print("✅ Single mode adapter test completed")


async def test_circuit_breaker():
    """Test circuit breaker pattern."""
    print("\n=== Testing Circuit Breaker ===")
    
    from src.gleitzeit.persistence.redis_resilience import (
        CircuitBreaker, CircuitBreakerConfig, CircuitOpenError
    )
    
    # Create circuit breaker
    config = CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout=1.0  # 1 second for testing
    )
    breaker = CircuitBreaker(config)
    
    # Simulate failures
    async def failing_operation():
        raise Exception("Simulated failure")
    
    async def successful_operation():
        return "success"
    
    # Test failures opening circuit
    for i in range(3):
        try:
            await breaker.call(failing_operation)
        except Exception:
            pass
    
    print(f"Circuit state after 3 failures: {breaker.state}")
    assert breaker.state.value == "open", "Circuit should be open"
    
    # Test circuit open rejection
    try:
        await breaker.call(successful_operation)
        assert False, "Should raise CircuitOpenError"
    except CircuitOpenError:
        print("✅ Circuit correctly rejecting calls when open")
    
    # Wait for timeout
    await asyncio.sleep(1.1)
    
    # Test half-open state
    result = await breaker.call(successful_operation)
    assert result == "success", "Should succeed in half-open"
    print(f"Circuit state after 1 success: {breaker.state}")
    
    # One more success should close circuit
    result = await breaker.call(successful_operation)
    print(f"Circuit state after 2 successes: {breaker.state}")
    assert breaker.state.value == "closed", "Circuit should be closed"
    
    print("✅ Circuit breaker working correctly")


async def test_metrics_collector():
    """Test metrics collection."""
    print("\n=== Testing Metrics Collector ===")
    
    from src.gleitzeit.persistence.redis_metrics import RedisMetricsCollector
    
    # Create metrics collector
    collector = RedisMetricsCollector(
        bucket_size_seconds=1,
        max_buckets=10
    )
    
    # Record some operations
    operations = [
        ("get", 0.001, True),
        ("get", 0.002, True),
        ("get", 0.1, False),  # Slow/failed
        ("set", 0.003, True),
        ("set", 0.004, True),
        ("hget", 0.002, True),
    ]
    
    for op, latency, success in operations:
        collector.record_operation(op, latency, success)
    
    # Get metrics summary
    summary = collector.get_summary()
    
    print(f"Total operations: {summary['total_operations']}")
    print(f"Total errors: {summary['total_errors']}")
    print(f"Error rate: {summary['error_rate']:.2%}")
    
    # Check percentiles
    percentiles = collector.get_latency_percentiles()
    print(f"Latency percentiles: {percentiles}")
    
    # Check per-operation stats
    print("\nOperation stats:")
    for op, stats in summary["operation_stats"].items():
        print(f"  {op}: count={stats['count']}, errors={stats['errors']}, p50={stats['p50']:.3f}s")
    
    assert summary["total_operations"] == 6, "Should have 6 operations"
    assert summary["total_errors"] == 1, "Should have 1 error"
    
    print("✅ Metrics collector working correctly")


async def test_resilient_pool():
    """Test resilient connection pool."""
    print("\n=== Testing Resilient Connection Pool ===")
    
    from src.gleitzeit.persistence.redis_resilience import (
        ResilientConnectionPool, ConnectionPoolConfig
    )
    
    # Create pool with single Redis
    config = ConnectionPoolConfig(
        max_connections=10,
        health_check_interval=5.0
    )
    
    pool = ResilientConnectionPool(
        primary_urls=[TEST_SINGLE_REDIS],
        replica_urls=[],  # No replicas for this test
        config=config
    )
    
    try:
        # Initialize pool
        await pool.initialize()
        print("✅ Pool initialized")
        
        # Test write operation
        await pool.execute_write("set", "test_key", "test_value")
        print("✅ Write operation successful")
        
        # Test read operation
        value = await pool.execute_read("get", "test_key")
        assert value == b"test_value" or value == "test_value", "Should read value"
        print("✅ Read operation successful")
        
        # Get health status
        health = pool.get_health_status()
        print(f"Pool health: {health}")
        assert health["healthy_primaries"] > 0, "Should have healthy primary"
        
    finally:
        await pool.close()
    
    print("✅ Resilient pool test completed")


async def test_cross_slot_operations():
    """Test cross-slot operation handling."""
    print("\n=== Testing Cross-Slot Operations ===")
    
    from src.gleitzeit.persistence.redis_cluster_adapter import (
        CrossSlotOperationHandler, HashTagStrategy
    )
    
    # This test requires actual Redis connection
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(TEST_SINGLE_REDIS)
        
        # Create handler
        handler = CrossSlotOperationHandler(redis_client)
        
        # Prepare test data across different slots
        test_data = {
            "key1": {"data": "value1"},
            "key2": {"data": "value2"},
            "key3": {"data": "value3"},
        }
        
        # Set test data
        for key, value in test_data.items():
            await redis_client.set(key, json.dumps(value))
        
        # Test multi-get across slots
        keys = list(test_data.keys())
        results = await handler.multi_get(keys)
        
        print(f"Multi-get results: {results}")
        assert len(results) == len(keys), "Should get all keys"
        
        # Test multi-set across slots
        new_data = {
            "new_key1": {"new": "data1"},
            "new_key2": {"new": "data2"},
        }
        
        success = await handler.multi_set(new_data)
        assert success, "Multi-set should succeed"
        print("✅ Multi-set successful")
        
        # Verify the set worked
        for key in new_data:
            value = await redis_client.get(key)
            assert value is not None, f"Key {key} should exist"
        
        # Cleanup
        for key in list(test_data.keys()) + list(new_data.keys()):
            await redis_client.delete(key)
        
        await redis_client.close()
        print("✅ Cross-slot operations working correctly")
        
    except ImportError:
        print("⚠️ Redis not available for cross-slot test")


async def test_performance_tracker():
    """Test performance tracking."""
    print("\n=== Testing Performance Tracker ===")
    
    from src.gleitzeit.persistence.redis_metrics import PerformanceTracker
    
    # Create tracker
    tracker = PerformanceTracker(slow_query_threshold=0.01)
    
    # Track some operations
    tracker.track_operation("get", "user:123", 0.002)
    tracker.track_operation("get", "user:123", 0.003)
    tracker.track_operation("get", "user:456", 0.001)
    tracker.track_operation("set", "user:789", 0.015)  # Slow query
    tracker.track_operation("hget", "session:abc", 0.002)
    tracker.track_operation("hget", "session:def", 0.020)  # Slow query
    
    # Get hot keys
    hot_keys = tracker.get_hot_keys(3)
    print(f"Hot keys: {hot_keys}")
    assert hot_keys[0][0] == "user:123", "user:123 should be hottest"
    
    # Get slow queries
    slow_queries = tracker.get_slow_queries()
    print(f"Slow queries: {len(slow_queries)} found")
    assert len(slow_queries) == 2, "Should have 2 slow queries"
    
    # Get command stats
    stats = tracker.get_command_stats()
    print("\nCommand pattern stats:")
    for pattern, data in stats.items():
        print(f"  {pattern}: count={data['count']}, avg={data['avg_latency']:.3f}s")
    
    print("✅ Performance tracker working correctly")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Redis Cluster Implementation Tests")
    print("=" * 60)
    
    tests = [
        ("Hash Tag Strategy", test_hash_tag_strategy),
        ("Sharding Strategy", test_sharding_strategy),
        ("Single Mode Adapter", test_single_mode_adapter),
        ("Circuit Breaker", test_circuit_breaker),
        ("Metrics Collector", test_metrics_collector),
        ("Resilient Pool", test_resilient_pool),
        ("Cross-Slot Operations", test_cross_slot_operations),
        ("Performance Tracker", test_performance_tracker),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"❌ {name} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {name} error: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)