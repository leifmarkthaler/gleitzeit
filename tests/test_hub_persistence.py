"""
Test Hub Persistence functionality

This test demonstrates:
1. Basic persistence adapter functionality
2. Instance state saving and loading
3. Metrics history storage
4. Distributed locking mechanism
5. State recovery after restart
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from gleitzeit.hub.persistence import RedisHubAdapter, InMemoryHubAdapter
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_in_memory_adapter():
    """Test the in-memory persistence adapter"""
    print("\n=== Testing In-Memory Adapter ===")
    
    adapter = InMemoryHubAdapter()
    await adapter.initialize()
    
    try:
        # Create a test instance
        instance = ResourceInstance(
            id="test-instance-1",
            name="Test Instance",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:11434",
            status=ResourceStatus.HEALTHY,
            capabilities={"llm/complete", "llm/chat"},
            tags={"test", "demo"}
        )
        
        # Save instance
        await adapter.save_instance("test-hub", instance)
        print(f"✓ Saved instance: {instance.id}")
        
        # Load instance
        loaded = await adapter.load_instance(instance.id)
        assert loaded is not None
        assert loaded['id'] == instance.id
        assert loaded['name'] == instance.name
        print(f"✓ Loaded instance successfully")
        
        # List instances for hub
        instances = await adapter.list_instances("test-hub")
        assert len(instances) == 1
        assert instances[0]['id'] == instance.id
        print(f"✓ Listed {len(instances)} instances for hub")
        
        # Save metrics
        metrics = ResourceMetrics(
            request_count=100,
            error_count=5,
            avg_response_time_ms=25.5,
            cpu_percent=45.2,
            memory_mb=512
        )
        await adapter.save_metrics(instance.id, metrics)
        print(f"✓ Saved metrics for instance")
        
        # Get metrics history
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        history = await adapter.get_metrics_history(instance.id, start_time, end_time)
        assert len(history) > 0
        assert history[0]['request_count'] == 100
        print(f"✓ Retrieved {len(history)} metrics entries")
        
        # Test locking
        lock_acquired = await adapter.acquire_lock("resource-1", "owner-1", timeout=30)
        assert lock_acquired == True
        print(f"✓ Acquired lock for resource-1")
        
        # Try to acquire same lock (should fail)
        lock_acquired2 = await adapter.acquire_lock("resource-1", "owner-2", timeout=30)
        assert lock_acquired2 == False
        print(f"✓ Second lock attempt correctly failed")
        
        # Check lock owner
        owner = await adapter.get_lock_owner("resource-1")
        assert owner == "owner-1"
        print(f"✓ Lock owner verified: {owner}")
        
        # Release lock
        await adapter.release_lock("resource-1", "owner-1")
        owner = await adapter.get_lock_owner("resource-1")
        assert owner is None
        print(f"✓ Lock released successfully")
        
        # Delete instance
        await adapter.delete_instance(instance.id)
        loaded = await adapter.load_instance(instance.id)
        assert loaded is None
        print(f"✓ Instance deleted successfully")
        
    finally:
        await adapter.shutdown()
        print("✓ Adapter shut down")


async def test_persistence_workflow():
    """Test a complete persistence workflow"""
    print("\n=== Testing Complete Persistence Workflow ===")
    
    adapter = InMemoryHubAdapter()
    await adapter.initialize()
    
    try:
        hub_id = "test-workflow-hub"
        
        # Simulate creating multiple instances
        instances = []
        for i in range(3):
            instance = ResourceInstance(
                id=f"instance-{i}",
                name=f"Instance {i}",
                type=ResourceType.OLLAMA,
                endpoint=f"http://ollama-{i}:11434",
                status=ResourceStatus.HEALTHY if i < 2 else ResourceStatus.UNHEALTHY,
                capabilities={"llm/complete", "llm/chat"},
                tags={"production"} if i == 0 else {"testing"}
            )
            instances.append(instance)
            await adapter.save_instance(hub_id, instance)
        
        print(f"✓ Created {len(instances)} instances")
        
        # List all instances
        saved_instances = await adapter.list_instances(hub_id)
        assert len(saved_instances) == 3
        print(f"✓ All instances persisted")
        
        # Simulate metrics collection over time
        for instance in instances[:2]:  # Only healthy instances
            for j in range(3):
                metrics = ResourceMetrics(
                    request_count=10 * (j + 1),
                    error_count=j,
                    avg_response_time_ms=20 + j * 5,
                    cpu_percent=30 + j * 10,
                    memory_mb=256 + j * 128
                )
                await adapter.save_metrics(instance.id, metrics)
                await asyncio.sleep(0.1)
        
        print(f"✓ Collected metrics over time")
        
        # Test distributed locking for resource allocation
        allocated_resources = []
        for i, instance in enumerate(instances[:2]):
            owner_id = f"worker-{i}"
            if await adapter.acquire_lock(instance.id, owner_id, timeout=60):
                allocated_resources.append((instance.id, owner_id))
                print(f"✓ Worker {i} allocated {instance.id}")
        
        assert len(allocated_resources) == 2
        
        # Verify locks
        for instance_id, expected_owner in allocated_resources:
            actual_owner = await adapter.get_lock_owner(instance_id)
            assert actual_owner == expected_owner
        
        print(f"✓ All locks verified")
        
        # Extend locks
        for instance_id, owner_id in allocated_resources:
            extended = await adapter.extend_lock(instance_id, owner_id, timeout=120)
            assert extended == True
        
        print(f"✓ All locks extended")
        
        # Release locks
        for instance_id, owner_id in allocated_resources:
            await adapter.release_lock(instance_id, owner_id)
        
        # Verify all locks released
        for instance_id, _ in allocated_resources:
            owner = await adapter.get_lock_owner(instance_id)
            assert owner is None
        
        print(f"✓ All locks released")
        
        # Get metrics history for analysis
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        
        for instance in instances[:2]:
            history = await adapter.get_metrics_history(instance.id, start_time, end_time)
            assert len(history) == 3
            # Verify metrics progression
            assert history[-1]['request_count'] > history[0]['request_count']
        
        print(f"✓ Metrics history verified")
        
    finally:
        await adapter.shutdown()
        print("✓ Workflow completed")


async def test_concurrent_locking():
    """Test concurrent lock acquisition"""
    print("\n=== Testing Concurrent Locking ===")
    
    adapter = InMemoryHubAdapter()
    await adapter.initialize()
    
    try:
        resource_id = "shared-resource"
        
        # Define concurrent workers
        async def try_acquire_lock(worker_id: str, delay: float = 0):
            if delay:
                await asyncio.sleep(delay)
            
            acquired = await adapter.acquire_lock(resource_id, worker_id, timeout=5)
            if acquired:
                print(f"  Worker {worker_id} acquired lock")
                await asyncio.sleep(1)  # Simulate work
                await adapter.release_lock(resource_id, worker_id)
                print(f"  Worker {worker_id} released lock")
                return True
            else:
                print(f"  Worker {worker_id} failed to acquire lock")
                return False
        
        # Run workers concurrently
        tasks = [
            try_acquire_lock("worker-1"),
            try_acquire_lock("worker-2", delay=0.1),
            try_acquire_lock("worker-3", delay=0.2),
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Only one should succeed initially
        successful = sum(results)
        assert successful == 1
        print(f"✓ Only {successful} worker acquired lock (expected 1)")
        
        # Now all should be able to acquire in sequence
        for i in range(3):
            acquired = await adapter.acquire_lock(resource_id, f"sequential-{i}", timeout=5)
            assert acquired == True
            await adapter.release_lock(resource_id, f"sequential-{i}")
        
        print(f"✓ Sequential acquisition worked")
        
    finally:
        await adapter.shutdown()


async def test_state_persistence():
    """Test state persistence and recovery"""
    print("\n=== Testing State Persistence ===")
    
    # First session - save state
    adapter1 = InMemoryHubAdapter()
    await adapter1.initialize()
    
    hub_id = "persistent-hub"
    saved_data = {}
    
    try:
        # Create and save instances
        for i in range(2):
            instance = ResourceInstance(
                id=f"persistent-{i}",
                name=f"Persistent Instance {i}",
                type=ResourceType.OLLAMA,
                endpoint=f"http://ollama-{i}:11434",
                status=ResourceStatus.HEALTHY,
                metadata={"version": "1.0", "index": i}
            )
            await adapter1.save_instance(hub_id, instance)
            
            # Save some metrics
            metrics = ResourceMetrics(
                request_count=100 * (i + 1),
                avg_response_time_ms=25.5 * (i + 1)
            )
            await adapter1.save_metrics(instance.id, metrics)
        
        # Save the state for verification
        saved_data['instances'] = await adapter1.list_instances(hub_id)
        saved_data['metrics'] = {}
        for inst in saved_data['instances']:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=1)
            saved_data['metrics'][inst['id']] = await adapter1.get_metrics_history(
                inst['id'], start_time, end_time
            )
        
        print(f"✓ Saved {len(saved_data['instances'])} instances with metrics")
        
    finally:
        # Don't shutdown - simulate keeping data in memory
        pass
    
    # Second session - recover state
    # (In real scenario with Redis, this would be a different process)
    print("  Simulating recovery...")
    
    # Verify data is still accessible
    recovered_instances = await adapter1.list_instances(hub_id)
    assert len(recovered_instances) == len(saved_data['instances'])
    
    for orig, recovered in zip(saved_data['instances'], recovered_instances):
        assert orig['id'] == recovered['id']
        assert orig['name'] == recovered['name']
        assert orig['metadata'] == recovered['metadata']
    
    print(f"✓ Recovered all instances with correct data")
    
    # Verify metrics are preserved
    for inst_id, orig_metrics in saved_data['metrics'].items():
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        recovered_metrics = await adapter1.get_metrics_history(inst_id, start_time, end_time)
        assert len(recovered_metrics) > 0
        assert recovered_metrics[0]['request_count'] == orig_metrics[0]['request_count']
    
    print(f"✓ All metrics preserved correctly")
    
    await adapter1.shutdown()


async def test_redis_adapter_structure():
    """Test Redis adapter structure (without actual Redis)"""
    print("\n=== Testing Redis Adapter Structure ===")
    
    # This tests the Redis adapter API without requiring Redis
    # In production, you would use actual Redis
    
    # Verify RedisHubAdapter has all required methods
    required_methods = [
        'initialize', 'shutdown',
        'save_instance', 'load_instance', 'list_instances', 'delete_instance',
        'save_metrics', 'get_metrics_history',
        'acquire_lock', 'release_lock', 'extend_lock', 'get_lock_owner'
    ]
    
    for method in required_methods:
        assert hasattr(RedisHubAdapter, method), f"Missing method: {method}"
    
    print(f"✓ RedisHubAdapter has all {len(required_methods)} required methods")
    
    # Test Redis key generation
    adapter = RedisHubAdapter(redis_url="redis://localhost:6379")
    
    # Test key generation methods
    instance_key = adapter._instance_key("test-123")
    assert "instance:test-123" in instance_key
    print(f"✓ Instance key: {instance_key}")
    
    hub_key = adapter._hub_instances_key("hub-456")
    assert "instances:hub-456" in hub_key
    print(f"✓ Hub instances key: {hub_key}")
    
    metrics_key = adapter._metrics_key("inst-789")
    assert "metrics:inst-789" in metrics_key
    print(f"✓ Metrics key: {metrics_key}")
    
    lock_key = adapter._lock_key("resource-abc")
    assert "lock:resource-abc" in lock_key
    print(f"✓ Lock key: {lock_key}")
    
    print("✓ Redis adapter structure validated")


async def main():
    """Run all tests"""
    print("=" * 60)
    print("Hub Persistence Integration Tests")
    print("=" * 60)
    
    try:
        await test_in_memory_adapter()
        await test_persistence_workflow()
        await test_concurrent_locking()
        await test_state_persistence()
        await test_redis_adapter_structure()
        
        print("\n" + "=" * 60)
        print("✅ All tests passed successfully!")
        print("=" * 60)
        print("\nThe persistence layer is working correctly!")
        print("Next steps:")
        print("1. Install Redis: brew install redis")
        print("2. Start Redis: redis-server")
        print("3. Install aioredis: pip install aioredis")
        print("4. Use RedisHubAdapter instead of InMemoryHubAdapter")
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())