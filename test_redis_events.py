#!/usr/bin/env python
"""
Test script for Redis event-driven architecture.

Tests:
1. Event publishing via Redis pub/sub
2. Event subscription and handling
3. Atomic workflow completion
4. Distributed locking
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import List, Dict, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import Gleitzeit components
from gleitzeit.persistence.unified_redis_events import UnifiedRedisEventsAdapter
from gleitzeit.core.models import Task, TaskStatus, Workflow, WorkflowStatus
from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity


class EventCollector:
    """Collects events for testing"""
    
    def __init__(self):
        self.events = []
    
    async def handle_event(self, event_data: Dict[str, Any]):
        """Handle an event by storing it"""
        self.events.append(event_data)
        logger.info(f"Collected event: {event_data.get('event_type')}")


async def test_event_publishing():
    """Test publishing events via Redis pub/sub"""
    print("\n=== Testing Event Publishing ===\n")
    
    # Create adapter
    adapter = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",  # Use database 1 for testing
        key_prefix="test_gleitzeit"
    )
    
    try:
        await adapter.initialize()
        
        # Create and save a task
        task = Task(
            id="test-task-001",
            name="Test Task",
            protocol="test",
            method="test/method",
            params={"test": "data"},
            priority="normal",
            status=TaskStatus.PENDING
        )
        
        print("Saving task (should emit no event for PENDING)...")
        await adapter.save_task(task)
        
        # Update to EXECUTING (should emit TASK_STARTED)
        print("Updating task to EXECUTING (should emit TASK_STARTED)...")
        task.status = TaskStatus.EXECUTING
        task.started_at = datetime.utcnow()
        await adapter.save_task(task)
        
        # Update to COMPLETED (should emit TASK_COMPLETED)
        print("Updating task to COMPLETED (should emit TASK_COMPLETED)...")
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        await adapter.save_task(task)
        
        print("✅ Event publishing test completed")
        
    finally:
        await adapter.shutdown()


async def test_event_subscription():
    """Test subscribing to events"""
    print("\n=== Testing Event Subscription ===\n")
    
    # Create two adapters - publisher and subscriber
    publisher = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_gleitzeit"
    )
    
    subscriber = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_gleitzeit"
    )
    
    collector = EventCollector()
    
    try:
        await publisher.initialize()
        await subscriber.initialize()
        
        # Register event handlers
        subscriber.register_event_handler('TASK_STARTED', collector.handle_event)
        subscriber.register_event_handler('TASK_COMPLETED', collector.handle_event)
        
        # Start subscription
        await subscriber.start_event_subscription(['TASK_STARTED', 'TASK_COMPLETED'])
        
        # Give subscription time to connect
        await asyncio.sleep(0.5)
        
        # Publish events
        print("Publishing TASK_STARTED event...")
        await publisher.emit_event(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            severity=EventSeverity.INFO,
            data={'task_id': 'test-001', 'task_name': 'Test Task'},
            source='test'
        ))
        
        print("Publishing TASK_COMPLETED event...")
        await publisher.emit_event(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            severity=EventSeverity.INFO,
            data={'task_id': 'test-001', 'status': 'completed'},
            source='test'
        ))
        
        # Wait for events to be received
        await asyncio.sleep(1)
        
        # Check collected events
        print(f"\nCollected {len(collector.events)} events:")
        for event in collector.events:
            print(f"  - {event.get('event_type')}: {event.get('data', {}).get('task_id')}")
        
        assert len(collector.events) == 2, f"Expected 2 events, got {len(collector.events)}"
        print("✅ Event subscription test completed")
        
    finally:
        await subscriber.stop_event_subscription()
        await publisher.shutdown()
        await subscriber.shutdown()


async def test_atomic_workflow_completion():
    """Test atomic workflow completion checking"""
    print("\n=== Testing Atomic Workflow Completion ===\n")
    
    adapter = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_gleitzeit"
    )
    
    try:
        await adapter.initialize()
        
        # Create a workflow with 3 tasks
        workflow = Workflow(
            id="test-workflow-001",
            name="Test Workflow",
            tasks=[
                Task(id="task-001", name="Task 1", protocol="test", method="test", 
                     params={}, priority="normal", workflow_id="test-workflow-001"),
                Task(id="task-002", name="Task 2", protocol="test", method="test",
                     params={}, priority="normal", workflow_id="test-workflow-001"),
                Task(id="task-003", name="Task 3", protocol="test", method="test",
                     params={}, priority="normal", workflow_id="test-workflow-001")
            ],
            timeout=60
        )
        
        print("Saving workflow and tasks...")
        await adapter.save_workflow(workflow)
        for task in workflow.tasks:
            task.status = TaskStatus.QUEUED
            await adapter.save_task(task)
        
        # Check completion (should be False - tasks not completed)
        print("Checking workflow completion (should be False)...")
        completed = await adapter.check_and_complete_workflow(workflow.id)
        assert not completed, "Workflow should not be complete yet"
        
        # Complete first two tasks
        print("Completing first two tasks...")
        for task_id in ["task-001", "task-002"]:
            task = await adapter.get_task(task_id)
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            await adapter.save_task(task)
        
        # Check completion (should be False - one task pending)
        print("Checking workflow completion (should still be False)...")
        completed = await adapter.check_and_complete_workflow(workflow.id)
        assert not completed, "Workflow should not be complete with pending task"
        
        # Complete last task
        print("Completing last task...")
        task = await adapter.get_task("task-003")
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        await adapter.save_task(task)
        
        # Check completion (should be True now)
        print("Checking workflow completion (should be True)...")
        completed = await adapter.check_and_complete_workflow(workflow.id)
        assert completed, "Workflow should be complete now"
        
        # Check workflow status
        workflow = await adapter.get_workflow(workflow.id)
        assert workflow.status == WorkflowStatus.COMPLETED, f"Workflow status should be COMPLETED, got {workflow.status}"
        
        print("✅ Atomic workflow completion test completed")
        
    finally:
        await adapter.shutdown()


async def test_distributed_locking():
    """Test distributed locking mechanism"""
    print("\n=== Testing Distributed Locking ===\n")
    
    # Create two adapters simulating different instances
    adapter1 = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_gleitzeit"
    )
    
    adapter2 = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_gleitzeit"
    )
    
    try:
        await adapter1.initialize()
        await adapter2.initialize()
        
        resource_id = "test-resource-001"
        
        # Adapter 1 acquires lock
        print(f"Adapter 1 acquiring lock for {resource_id}...")
        lock1 = await adapter1.acquire_lock(resource_id, timeout_ms=5000)
        assert lock1 is not None, "Adapter 1 should acquire lock"
        print(f"✅ Adapter 1 acquired lock: {lock1[:8]}...")
        
        # Adapter 2 tries to acquire same lock (should fail)
        print(f"Adapter 2 trying to acquire same lock...")
        lock2 = await adapter2.acquire_lock(resource_id, timeout_ms=5000)
        assert lock2 is None, "Adapter 2 should not acquire lock"
        print("✅ Adapter 2 correctly failed to acquire lock")
        
        # Adapter 1 releases lock
        print(f"Adapter 1 releasing lock...")
        released = await adapter1.release_lock(resource_id, lock1)
        assert released, "Adapter 1 should release lock"
        print("✅ Adapter 1 released lock")
        
        # Now adapter 2 can acquire lock
        print(f"Adapter 2 acquiring lock after release...")
        lock2 = await adapter2.acquire_lock(resource_id, timeout_ms=5000)
        assert lock2 is not None, "Adapter 2 should now acquire lock"
        print(f"✅ Adapter 2 acquired lock: {lock2[:8]}...")
        
        # Adapter 1 tries to release with wrong token (should fail)
        print(f"Adapter 1 trying to release with wrong token...")
        released = await adapter1.release_lock(resource_id, "wrong-token")
        assert not released, "Should not release with wrong token"
        print("✅ Correctly failed to release with wrong token")
        
        # Adapter 2 releases lock
        print(f"Adapter 2 releasing lock...")
        released = await adapter2.release_lock(resource_id, lock2)
        assert released, "Adapter 2 should release lock"
        print("✅ Adapter 2 released lock")
        
        print("✅ Distributed locking test completed")
        
    finally:
        await adapter1.shutdown()
        await adapter2.shutdown()


async def test_full_workflow_with_events():
    """Test complete workflow execution with event flow"""
    print("\n=== Testing Full Workflow with Events ===\n")
    
    adapter = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_gleitzeit"
    )
    
    collector = EventCollector()
    
    try:
        await adapter.initialize()
        
        # Register event handlers
        adapter.register_event_handler('TASK_STARTED', collector.handle_event)
        adapter.register_event_handler('TASK_COMPLETED', collector.handle_event)
        adapter.register_event_handler('WORKFLOW_COMPLETED', collector.handle_event)
        
        # Start subscription
        await adapter.start_event_subscription()
        await asyncio.sleep(0.5)  # Let subscription connect
        
        # Create workflow
        workflow = Workflow(
            id="test-workflow-002",
            name="Event Test Workflow",
            tasks=[
                Task(id="task-101", name="Task 1", protocol="test", method="test",
                     params={}, priority="normal", workflow_id="test-workflow-002"),
                Task(id="task-102", name="Task 2", protocol="test", method="test",
                     params={}, priority="normal", workflow_id="test-workflow-002")
            ],
            timeout=60
        )
        
        print("Creating workflow with 2 tasks...")
        workflow.status = WorkflowStatus.PENDING
        workflow.started_at = datetime.utcnow()
        await adapter.save_workflow(workflow)
        
        for task in workflow.tasks:
            task.status = TaskStatus.QUEUED
            await adapter.save_task(task)
        
        # Simulate task execution
        for task in workflow.tasks:
            print(f"\nExecuting {task.name}...")
            
            # Start task
            task.status = TaskStatus.EXECUTING
            task.started_at = datetime.utcnow()
            await adapter.save_task(task)
            
            # Simulate work
            await asyncio.sleep(0.1)
            
            # Complete task
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            await adapter.save_task(task)
        
        # Check workflow completion
        print("\nChecking workflow completion...")
        completed = await adapter.check_and_complete_workflow(workflow.id)
        
        # Wait for events to propagate
        await asyncio.sleep(1)
        
        # Verify events
        print(f"\nCollected {len(collector.events)} events:")
        event_types = [e.get('event_type') for e in collector.events]
        for event in collector.events:
            print(f"  - {event.get('event_type')}")
        
        assert 'TASK_STARTED' in event_types, "Should have TASK_STARTED events"
        assert 'TASK_COMPLETED' in event_types, "Should have TASK_COMPLETED events"
        assert 'WORKFLOW_COMPLETED' in event_types, "Should have WORKFLOW_COMPLETED event"
        
        print("✅ Full workflow event test completed")
        
    finally:
        await adapter.stop_event_subscription()
        await adapter.shutdown()


async def cleanup_test_data():
    """Clean up test data from Redis"""
    print("\n=== Cleaning Up Test Data ===\n")
    
    adapter = UnifiedRedisEventsAdapter(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_gleitzeit"
    )
    
    try:
        await adapter.initialize()
        
        # Delete all test keys
        pattern = "test_gleitzeit:*"
        cursor = 0
        deleted_count = 0
        
        while True:
            cursor, keys = await adapter.redis.scan(cursor, match=pattern, count=100)
            if keys:
                deleted_count += await adapter.redis.delete(*keys)
            if cursor == 0:
                break
        
        print(f"Deleted {deleted_count} test keys")
        
    finally:
        await adapter.shutdown()


async def main():
    """Run all tests"""
    print("=" * 60)
    print("Redis Event-Driven Architecture Tests")
    print("=" * 60)
    
    try:
        # Check Redis connection first
        adapter = UnifiedRedisEventsAdapter(redis_url="redis://localhost:6379/1")
        await adapter.initialize()
        await adapter.redis.ping()
        await adapter.shutdown()
        print("✅ Redis connection successful\n")
        
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("Make sure Redis is running on localhost:6379")
        return
    
    # Run tests
    tests = [
        test_event_publishing,
        test_event_subscription,
        test_atomic_workflow_completion,
        test_distributed_locking,
        test_full_workflow_with_events
    ]
    
    for test in tests:
        try:
            await test()
        except AssertionError as e:
            print(f"❌ Test failed: {e}")
        except Exception as e:
            print(f"❌ Test error: {e}")
            import traceback
            traceback.print_exc()
    
    # Cleanup
    await cleanup_test_data()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())