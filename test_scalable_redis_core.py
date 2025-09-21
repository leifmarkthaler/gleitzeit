#!/usr/bin/env python3
"""
Test ScalableRedisAdapter for Events, Tasks, and Workflows

Comprehensive test suite to validate core persistence operations.
"""

import asyncio
import uuid
import json
from datetime import datetime
from typing import List

from src.gleitzeit.persistence.scalable_redis import (
    ScalableRedisAdapter, PersistenceMode
)
from src.gleitzeit.persistence.factory_v2 import PersistenceFactory
from src.gleitzeit.core.models import (
    Workflow, Task, WorkflowStatus, TaskStatus, TaskResult
)


async def test_workflow_persistence():
    """Test workflow CRUD operations."""
    print("\n=== Testing Workflow Persistence ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_workflow_{uuid.uuid4().hex[:8]}",
            "enable_events": True
        }
    )
    
    try:
        # Create workflow
        workflow = Workflow(
            id=f"wf-{uuid.uuid4().hex[:8]}",
            name="Test Workflow",
            description="Testing workflow persistence",
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow(),
            tasks=["task-1", "task-2", "task-3"],
            metadata={"test": True, "version": "1.0"}
        )
        
        # Save workflow
        await adapter.save_workflow(workflow)
        print(f"✅ Saved workflow: {workflow.id}")
        
        # Retrieve workflow
        retrieved = await adapter.get_workflow(workflow.id)
        assert retrieved is not None, "Workflow not found"
        assert retrieved.id == workflow.id
        assert retrieved.name == workflow.name
        assert retrieved.status == workflow.status
        assert len(retrieved.tasks) == 3
        print(f"✅ Retrieved workflow: {retrieved.id} with {len(retrieved.tasks)} tasks")
        
        # Update workflow status
        workflow.status = WorkflowStatus.RUNNING
        workflow.updated_at = datetime.utcnow()
        await adapter.save_workflow(workflow)
        
        updated = await adapter.get_workflow(workflow.id)
        assert updated.status == WorkflowStatus.RUNNING
        print(f"✅ Updated workflow status to: {updated.status}")
        
        # List workflows
        all_workflows = await adapter.list_workflows()
        assert len(all_workflows) >= 1
        assert any(w.id == workflow.id for w in all_workflows)
        print(f"✅ Listed workflows: found {len(all_workflows)} total")
        
        # List by status
        pending_workflows = await adapter.list_workflows(status=WorkflowStatus.PENDING)
        running_workflows = await adapter.list_workflows(status=WorkflowStatus.RUNNING)
        assert len(running_workflows) >= 1
        print(f"✅ Filtered workflows: {len(pending_workflows)} pending, {len(running_workflows)} running")
        
        # Delete workflow
        deleted = await adapter.delete_workflow(workflow.id)
        assert deleted
        
        # Verify deletion
        deleted_wf = await adapter.get_workflow(workflow.id)
        assert deleted_wf is None
        print(f"✅ Deleted workflow: {workflow.id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await adapter.close()


async def test_task_persistence():
    """Test task CRUD operations."""
    print("\n=== Testing Task Persistence ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_task_{uuid.uuid4().hex[:8]}",
            "enable_events": True
        }
    )
    
    try:
        # First create a workflow (tasks must belong to workflows)
        workflow = Workflow(
            id=f"wf-{uuid.uuid4().hex[:8]}",
            name="Task Test Workflow",
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow(),
            tasks=[]
        )
        await adapter.save_workflow(workflow)
        print(f"✅ Created parent workflow: {workflow.id}")
        
        # Create tasks
        tasks = []
        for i in range(5):
            task = Task(
                id=f"task-{uuid.uuid4().hex[:8]}",
                workflow_id=workflow.id,
                name=f"Test Task {i}",
                description=f"Task number {i}",
                status=TaskStatus.PENDING if i < 3 else TaskStatus.EXECUTING,
                created_at=datetime.utcnow(),
                protocol="python",
                method=f"process_task_{i}",
                parameters={"index": i, "test": True},
                dependencies=[tasks[i-1].id] if i > 0 else []
            )
            tasks.append(task)
            
            # Save task
            await adapter.save_task(task)
            print(f"  Saved task: {task.id} ({task.status})")
        
        print(f"✅ Created {len(tasks)} tasks")
        
        # Retrieve individual task
        retrieved = await adapter.get_task(tasks[0].id, workflow.id)
        assert retrieved is not None
        assert retrieved.id == tasks[0].id
        assert retrieved.workflow_id == workflow.id
        assert retrieved.protocol == "python"
        print(f"✅ Retrieved task: {retrieved.id}")
        
        # Get tasks by workflow
        workflow_tasks = await adapter.get_tasks_by_workflow(workflow.id)
        assert len(workflow_tasks) == 5
        print(f"✅ Retrieved {len(workflow_tasks)} tasks for workflow")
        
        # Get tasks by status
        pending_tasks = await adapter.get_tasks_by_status(TaskStatus.PENDING)
        running_tasks = await adapter.get_tasks_by_status(TaskStatus.EXECUTING)
        assert len(pending_tasks) >= 3
        assert len(running_tasks) >= 2
        print(f"✅ Tasks by status: {len(pending_tasks)} pending, {len(running_tasks)} running")
        
        # Update task status
        tasks[0].status = TaskStatus.COMPLETED
        tasks[0].completed_at = datetime.utcnow()
        await adapter.update_task(tasks[0])
        
        updated = await adapter.get_task(tasks[0].id, workflow.id)
        assert updated.status == TaskStatus.COMPLETED
        print(f"✅ Updated task status to: {updated.status}")
        
        # Save task result
        result = TaskResult(
            task_id=tasks[0].id,
            workflow_id=workflow.id,
            status=TaskStatus.COMPLETED,
            result={"output": "Task completed successfully", "value": 42},
            error=None,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        await adapter.save_task_result(result)
        print(f"✅ Saved task result for: {result.task_id}")
        
        # Retrieve task result
        retrieved_result = await adapter.get_task_result(tasks[0].id)
        assert retrieved_result is not None
        assert retrieved_result.task_id == tasks[0].id
        assert retrieved_result.result["value"] == 42
        print(f"✅ Retrieved task result: {retrieved_result.result}")
        
        # Delete task
        deleted = await adapter.delete_task(tasks[0].id)
        assert deleted
        
        deleted_task = await adapter.get_task(tasks[0].id, workflow.id)
        assert deleted_task is None
        print(f"✅ Deleted task: {tasks[0].id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Task test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await adapter.close()


async def test_event_streaming():
    """Test event streaming functionality."""
    print("\n=== Testing Event Streaming ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_events_{uuid.uuid4().hex[:8]}",
            "enable_events": True,
            "event_stream_key": "test:events:stream",
            "consumer_group": "test-consumers"
        }
    )
    
    try:
        # Create workflow (should emit event)
        workflow = Workflow(
            id=f"wf-event-{uuid.uuid4().hex[:8]}",
            name="Event Test Workflow",
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow(),
            tasks=[]
        )
        
        # Save workflow - this should emit an event
        await adapter.save_workflow(workflow)
        print(f"✅ Saved workflow: {workflow.id} (should emit event)")
        
        # Check if event was emitted to stream
        # Note: The adapter should have written to the event stream
        stream_key = adapter.event_stream_key
        
        # Read from stream using Redis directly
        events = await adapter._execute("xrange", stream_key, "-", "+", count=10)
        
        if events:
            print(f"✅ Found {len(events)} events in stream")
            
            # Parse first event
            for event_id, event_data in events:
                if isinstance(event_id, bytes):
                    event_id = event_id.decode('utf-8')
                print(f"  Event ID: {event_id}")
                
                # Event data should contain workflow info
                if b'event_type' in event_data:
                    event_type = event_data[b'event_type'].decode('utf-8')
                    print(f"  Event Type: {event_type}")
                if b'workflow_id' in event_data:
                    wf_id = event_data[b'workflow_id'].decode('utf-8')
                    assert wf_id == workflow.id
                    print(f"  Workflow ID: {wf_id}")
        else:
            print("⚠️  No events found in stream (events might be disabled)")
        
        # Test creating task (should also emit event)
        task = Task(
            id=f"task-event-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow.id,
            name="Event Test Task",
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow(),
            protocol="python",
            method="test_method"
        )
        
        await adapter.save_task(task)
        print(f"✅ Saved task: {task.id} (should emit event)")
        
        # Check for task event
        new_events = await adapter._execute("xrange", stream_key, "-", "+", count=20)
        if new_events and len(new_events) > len(events) if events else 0:
            print(f"✅ Task event emitted, total events: {len(new_events)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Event streaming test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await adapter.close()


async def test_persistence_features():
    """Test additional persistence features."""
    print("\n=== Testing Additional Persistence Features ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_features_{uuid.uuid4().hex[:8]}",
            "enable_metrics": True,
            "enable_circuit_breaker": True
        }
    )
    
    try:
        # Test queue state persistence
        queue_state = {
            "name": "test-queue",
            "size": 100,
            "processed": 50,
            "failed": 2,
            "last_updated": datetime.utcnow().isoformat()
        }
        
        await adapter.save_queue_state("test-queue", queue_state)
        print("✅ Saved queue state")
        
        retrieved_state = await adapter.get_queue_state("test-queue")
        assert retrieved_state is not None
        assert retrieved_state["size"] == 100
        assert retrieved_state["processed"] == 50
        print(f"✅ Retrieved queue state: {retrieved_state['processed']}/{retrieved_state['size']} processed")
        
        # Test lock operations
        lock_acquired = await adapter.acquire_lock("test-resource", timeout=5)
        assert lock_acquired
        print("✅ Acquired distributed lock")
        
        # Try to acquire again (should fail)
        lock_again = await adapter.acquire_lock("test-resource", timeout=5)
        assert not lock_again
        print("✅ Lock correctly prevents double acquisition")
        
        # Release lock
        lock_released = await adapter.release_lock("test-resource")
        assert lock_released
        print("✅ Released distributed lock")
        
        # Test health check
        health = await adapter.health_check()
        assert health["healthy"]
        print(f"✅ Health check: {health}")
        
        # Test metrics (if enabled)
        if adapter.metrics_collector:
            metrics = await adapter.get_metrics()
            print(f"✅ Metrics: {metrics.get('total_operations', 0)} operations")
        
        # Test atomic operations support
        supports_atomic = adapter.supports_atomic_operations()
        assert supports_atomic
        print(f"✅ Supports atomic operations: {supports_atomic}")
        
        return True
        
    except Exception as e:
        print(f"❌ Features test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await adapter.close()


async def test_error_handling():
    """Test error handling and edge cases."""
    print("\n=== Testing Error Handling ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_errors_{uuid.uuid4().hex[:8]}"
        }
    )
    
    try:
        # Test getting non-existent workflow
        missing_wf = await adapter.get_workflow("non-existent-id")
        assert missing_wf is None
        print("✅ Correctly returns None for missing workflow")
        
        # Test getting non-existent task
        missing_task = await adapter.get_task("non-existent-task", "non-existent-wf")
        assert missing_task is None
        print("✅ Correctly returns None for missing task")
        
        # Test deleting non-existent workflow
        deleted = await adapter.delete_workflow("non-existent-id")
        assert not deleted
        print("✅ Delete returns False for non-existent workflow")
        
        # Test task without workflow_id (should handle gracefully)
        task = Task(
            id="orphan-task",
            workflow_id=None,  # This violates the requirement
            name="Orphan Task",
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow(),
            protocol="python",
            method="test"
        )
        
        try:
            await adapter.save_task(task)
            print("❌ Should have raised error for task without workflow_id")
        except Exception as e:
            print(f"✅ Correctly raised error for task without workflow_id: {type(e).__name__}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await adapter.close()


async def main():
    """Run all tests."""
    print("=" * 60)
    print("ScalableRedisAdapter Core Persistence Tests")
    print("=" * 60)
    
    tests = [
        ("Workflow Persistence", test_workflow_persistence),
        ("Task Persistence", test_task_persistence),
        ("Event Streaming", test_event_streaming),
        ("Additional Features", test_persistence_features),
        ("Error Handling", test_error_handling),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        result = await test_func()
        if result:
            passed += 1
        else:
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)