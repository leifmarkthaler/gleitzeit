#!/usr/bin/env python3
"""
Test Scalable Redis Adapter

Validates the new unified ScalableRedisAdapter that replaces
all other persistence backends.
"""

import asyncio
import uuid
from datetime import datetime

from src.gleitzeit.persistence.scalable_redis import (
    ScalableRedisAdapter, PersistenceMode
)
from src.gleitzeit.persistence.factory_v2 import (
    PersistenceFactory, SimplifiedFactory
)
from src.gleitzeit.core.models import (
    Workflow, Task, WorkflowStatus, TaskStatus
)


async def test_single_mode():
    """Test single Redis instance mode."""
    print("\n=== Testing Single Mode ===")
    
    # Create adapter
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        redis_url="redis://localhost:6379/0",
        config={
            "key_prefix": f"test_{uuid.uuid4().hex[:8]}",
            "enable_metrics": True
        }
    )
    
    try:
        # Test workflow operations
        workflow = Workflow(
            id="test-workflow-1",
            name="Test Workflow",
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow(),
            tasks=[]
        )
        
        await adapter.save_workflow(workflow)
        print(f"✅ Saved workflow {workflow.id}")
        
        # Retrieve workflow
        retrieved = await adapter.get_workflow(workflow.id)
        assert retrieved is not None
        assert retrieved.id == workflow.id
        print(f"✅ Retrieved workflow {retrieved.id}")
        
        # Test task operations
        task = Task(
            id="test-task-1",
            workflow_id=workflow.id,
            name="Test Task",
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow(),
            protocol="python",  # Required field
            method="test_method"  # Required field
        )
        
        await adapter.save_task(task)
        print(f"✅ Saved task {task.id}")
        
        # Retrieve task
        retrieved_task = await adapter.get_task(task.id, workflow.id)
        assert retrieved_task is not None
        assert retrieved_task.id == task.id
        print(f"✅ Retrieved task {retrieved_task.id}")
        
        # Test health check
        health = await adapter.health_check()
        assert health["healthy"]
        print(f"✅ Health check passed: {health}")
        
        # Test metrics
        metrics = await adapter.get_metrics()
        print(f"✅ Metrics collected: {metrics.get('total_operations', 0)} operations")
        
        # Cleanup
        await adapter.delete_workflow(workflow.id)
        print(f"✅ Cleaned up workflow {workflow.id}")
        
    finally:
        await adapter.close()
    
    print("✅ Single mode test completed")


async def test_factory_methods():
    """Test simplified factory methods."""
    print("\n=== Testing Factory Methods ===")
    
    # Test development factory
    dev_adapter = await SimplifiedFactory.create_development()
    assert dev_adapter.mode == PersistenceMode.SINGLE
    assert dev_adapter.key_prefix == "gleitzeit_dev"
    await dev_adapter.close()
    print("✅ Development factory works")
    
    # Test testing factory
    test_adapter = await SimplifiedFactory.create_testing("mytest")
    assert test_adapter.mode == PersistenceMode.SINGLE
    assert "test_mytest" in test_adapter.key_prefix
    await test_adapter.close()
    print("✅ Testing factory works")
    
    print("✅ Factory methods test completed")


async def test_resilience_features():
    """Test resilience features."""
    print("\n=== Testing Resilience Features ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_resilience_{uuid.uuid4().hex[:8]}",
            "enable_circuit_breaker": True,
            "enable_metrics": True,
            "max_retries": 3
        }
    )
    
    try:
        # Test normal operation
        await adapter._execute("set", "test_key", "test_value")
        value = await adapter._execute("get", "test_key")
        assert value in [b"test_value", "test_value"]
        print("✅ Normal operations work with circuit breaker")
        
        # Check circuit breaker metrics
        if adapter.circuit_breaker:
            metrics = adapter.circuit_breaker.get_metrics()
            print(f"✅ Circuit breaker metrics: {metrics}")
        
        # Check operation metrics
        if adapter.metrics_collector:
            summary = adapter.metrics_collector.get_summary()
            print(f"✅ Operations tracked: {summary['total_operations']}")
        
    finally:
        await adapter.close()
    
    print("✅ Resilience features test completed")


async def test_sharding_support():
    """Test sharding and key generation."""
    print("\n=== Testing Sharding Support ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_shard_{uuid.uuid4().hex[:8]}",
            "sharding_strategy": "workflow_based"
        }
    )
    
    try:
        # Test workflow key generation
        workflow_id = "workflow-123"
        workflow_key = adapter._workflow_key(workflow_id)
        print(f"Workflow key: {workflow_key}")
        
        # Test task key generation (should stay with workflow)
        task_id = "task-456"
        task_key = adapter._task_key(task_id, workflow_id)
        print(f"Task key: {task_key}")
        
        # Verify shard manager
        if adapter.shard_manager:
            from src.gleitzeit.persistence.redis_sharding import DataType
            shard = adapter.shard_manager.get_shard_key(
                DataType.WORKFLOW,
                workflow_id
            )
            print(f"✅ Shard manager working: {shard}")
        
    finally:
        await adapter.close()
    
    print("✅ Sharding support test completed")


async def test_event_streaming():
    """Test event streaming capabilities."""
    print("\n=== Testing Event Streaming ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_events_{uuid.uuid4().hex[:8]}",
            "enable_events": True,
            "consumer_group": "test-workers"
        }
    )
    
    try:
        # Create and save workflow (should emit event)
        workflow = Workflow(
            id="event-workflow-1",
            name="Event Test",
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow(),
            tasks=[]
        )
        
        await adapter.save_workflow(workflow)
        print(f"✅ Workflow saved, event should be emitted")
        
        # Check if event was written to stream
        stream_key = adapter.event_stream_key
        events = await adapter._execute("xrange", stream_key, "-", "+", count=10)
        
        if events:
            print(f"✅ Found {len(events)} events in stream")
            # Decode first event
            if events[0] and len(events[0]) > 1:
                event_data = events[0][1]
                print(f"   Event data: {event_data}")
        
    finally:
        await adapter.close()
    
    print("✅ Event streaming test completed")


async def test_lock_operations():
    """Test distributed lock operations."""
    print("\n=== Testing Lock Operations ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_locks_{uuid.uuid4().hex[:8]}"
        }
    )
    
    try:
        # Acquire lock
        lock_key = "test-resource"
        acquired = await adapter.acquire_lock(lock_key, timeout=5)
        assert acquired
        print(f"✅ Lock acquired: {lock_key}")
        
        # Try to acquire again (should fail)
        acquired_again = await adapter.acquire_lock(lock_key, timeout=5)
        assert not acquired_again
        print(f"✅ Lock correctly prevents double acquisition")
        
        # Release lock
        released = await adapter.release_lock(lock_key)
        assert released
        print(f"✅ Lock released: {lock_key}")
        
        # Should be able to acquire again
        acquired_after = await adapter.acquire_lock(lock_key, timeout=5)
        assert acquired_after
        print(f"✅ Lock can be reacquired after release")
        
        # Cleanup
        await adapter.release_lock(lock_key)
        
    finally:
        await adapter.close()
    
    print("✅ Lock operations test completed")


async def test_list_workflows():
    """Test listing workflows with filtering."""
    print("\n=== Testing List Workflows ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_list_{uuid.uuid4().hex[:8]}"
        }
    )
    
    try:
        # Create multiple workflows
        workflows = []
        for i in range(5):
            wf = Workflow(
                id=f"list-workflow-{i}",
                name=f"Workflow {i}",
                status=WorkflowStatus.PENDING if i % 2 == 0 else WorkflowStatus.RUNNING,
                created_at=datetime.utcnow(),
                tasks=[]
            )
            await adapter.save_workflow(wf)
            workflows.append(wf)
        
        print(f"✅ Created {len(workflows)} workflows")
        
        # List all workflows
        all_workflows = await adapter.list_workflows()
        assert len(all_workflows) == 5
        print(f"✅ Listed all workflows: {len(all_workflows)}")
        
        # List with status filter
        pending = await adapter.list_workflows(status=WorkflowStatus.PENDING)
        assert len(pending) == 3  # 0, 2, 4 are PENDING
        print(f"✅ Filtered by status: {len(pending)} PENDING")
        
        # Cleanup
        for wf in workflows:
            await adapter.delete_workflow(wf.id)
        
    finally:
        await adapter.close()
    
    print("✅ List workflows test completed")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Scalable Redis Adapter Tests")
    print("=" * 60)
    
    tests = [
        ("Single Mode", test_single_mode),
        ("Factory Methods", test_factory_methods),
        ("Resilience Features", test_resilience_features),
        ("Sharding Support", test_sharding_support),
        ("Event Streaming", test_event_streaming),
        ("Lock Operations", test_lock_operations),
        ("List Workflows", test_list_workflows),
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
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)