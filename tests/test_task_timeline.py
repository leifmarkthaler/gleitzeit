"""
Test task-specific timeline functionality
"""

import pytest
import pytest_asyncio
import asyncio
import json
import uuid
from datetime import datetime

from gleitzeit.core.event_store import EventStore, EventLevel, WorkflowEvent
from gleitzeit.core.events import EventType


@pytest_asyncio.fixture
async def redis_client():
    """Create a test Redis client"""
    import redis.asyncio as aioredis
    redis = aioredis.from_url('redis://localhost:6379', decode_responses=False)

    # Clean up any test data for all test workflows
    test_workflows = [
        "test_workflow_task_timeline",
        "test_xor_workflow",
        "test_duration_workflow"
    ]

    for workflow_id in test_workflows:
        for shard in range(10):  # Clean all possible shards
            test_key = f"{{shard:{shard}}}:events:{workflow_id}"
            await redis.delete(test_key.encode())

    yield redis

    # Cleanup
    for workflow_id in test_workflows:
        for shard in range(10):
            test_key = f"{{shard:{shard}}}:events:{workflow_id}"
            await redis.delete(test_key.encode())

    await redis.aclose()


@pytest_asyncio.fixture
async def event_store(redis_client):
    """Create event store instance"""
    return EventStore(redis_client)


async def create_sample_events(event_store, workflow_id="test_workflow_task_timeline"):
    """Create sample workflow with multiple tasks"""

    # Workflow starts
    await event_store.store_event(
        EventType.WORKFLOW_STARTED,
        workflow_id,
        level=EventLevel.CRITICAL,
        data={"worker_id": "worker_1"}
    )

    # Task 1: validate_input - starts and completes
    await event_store.store_event(
        EventType.TASK_READY,
        workflow_id,
        task_id="validate_input",
        level=EventLevel.IMPORTANT,
        data={"is_initial": True}
    )

    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="validate_input",
        level=EventLevel.CRITICAL,
        data={
            "protocol": "validation/v1",
            "execution_id": "exec_001",
            "handler_id": "validator_1"
        }
    )

    await asyncio.sleep(0.01)  # Small delay to ensure different timestamps

    await event_store.store_event(
        EventType.TASK_COMPLETED,
        workflow_id,
        task_id="validate_input",
        level=EventLevel.CRITICAL,
        data={
            "result": {"valid": True, "data": {"amount": 100}},
            "worker_id": "worker_1"
        }
    )

    # Task 2: process_payment - starts and fails
    await event_store.store_event(
        EventType.TASK_READY,
        workflow_id,
        task_id="process_payment",
        level=EventLevel.IMPORTANT,
        data={"triggered_by": "validate_input"}
    )

    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="process_payment",
        level=EventLevel.CRITICAL,
        data={
            "protocol": "python/v1",
            "execution_id": "exec_002",
            "handler_id": "payment_processor"
        }
    )

    await asyncio.sleep(0.01)

    await event_store.store_event(
        EventType.TASK_FAILED,
        workflow_id,
        task_id="process_payment",
        level=EventLevel.CRITICAL,
        data={
            "error": "Payment gateway timeout",
            "worker_id": "worker_2"
        }
    )

    # Task 3: send_notification - skipped due to validation
    await event_store.store_event(
        EventType.TASK_SKIPPED,
        workflow_id,
        task_id="send_notification",
        level=EventLevel.IMPORTANT,
        data={
            "reason": "Validation check_notification_enabled returned false",
            "validation_task": "check_notification_enabled"
        }
    )

    # Task 4: log_result - completes
    await event_store.store_event(
        EventType.TASK_READY,
        workflow_id,
        task_id="log_result",
        level=EventLevel.IMPORTANT,
        data={"triggered_by": "process_payment"}
    )

    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="log_result",
        level=EventLevel.CRITICAL,
        data={
            "protocol": "python/v1",
            "execution_id": "exec_003"
        }
    )

    await asyncio.sleep(0.01)

    await event_store.store_event(
        EventType.TASK_COMPLETED,
        workflow_id,
        task_id="log_result",
        level=EventLevel.CRITICAL,
        data={
            "result": {"logged": True},
            "worker_id": "worker_3"
        }
    )

    # Workflow completes with failures
    await event_store.store_event(
        EventType.WORKFLOW_FAILED,
        workflow_id,
        level=EventLevel.CRITICAL,
        data={
            "failed_tasks": ["process_payment"],
            "completed_tasks": ["validate_input", "log_result"],
            "skipped_tasks": ["send_notification"]
        }
    )

    # Simulate a replay that affects process_payment
    await event_store.store_event(
        EventType.WORKFLOW_RESUMED,
        workflow_id,
        level=EventLevel.CRITICAL,
        data={
            "replay_id": "replay_001",
            "mode": "failed_only",
            "tasks_to_replay": ["process_payment"]
        }
    )

    # process_payment succeeds on replay
    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="process_payment",
        level=EventLevel.CRITICAL,
        data={
            "protocol": "python/v1",
            "execution_id": "exec_004",
            "handler_id": "payment_processor"
        },
        replay_id="replay_001"
    )

    await asyncio.sleep(0.01)

    await event_store.store_event(
        EventType.TASK_COMPLETED,
        workflow_id,
        task_id="process_payment",
        level=EventLevel.CRITICAL,
        data={
            "result": {"payment_id": "pay_123", "status": "success"},
            "worker_id": "worker_4"
        },
        replay_id="replay_001"
    )


@pytest.mark.asyncio
async def test_get_task_timeline(event_store):
    """Test retrieving timeline for a specific task"""
    workflow_id = "test_workflow_task_timeline"

    # Create sample events
    await create_sample_events(event_store, workflow_id)

    # Test 1: Get timeline for validate_input (simple success case)
    events = await event_store.get_task_timeline(workflow_id, "validate_input")

    assert len(events) >= 3  # READY, STARTED, COMPLETED

    # Check event types for validate_input
    event_types = [e.event_type for e in events if e.task_id == "validate_input"]
    assert EventType.TASK_READY in event_types
    assert EventType.TASK_STARTED in event_types
    assert EventType.TASK_COMPLETED in event_types

    # Test 2: Get timeline for process_payment (failure and retry)
    events = await event_store.get_task_timeline(workflow_id, "process_payment")

    # Should include initial failure, replay event, and retry success
    assert len(events) >= 5  # READY, STARTED, FAILED, WORKFLOW_RESUMED, STARTED, COMPLETED

    # Check that we have both failure and success events
    event_types = [e.event_type for e in events]
    assert EventType.TASK_FAILED in event_types
    assert EventType.TASK_COMPLETED in event_types
    assert EventType.WORKFLOW_RESUMED in event_types

    # Test 3: Get timeline for skipped task
    events = await event_store.get_task_timeline(workflow_id, "send_notification")

    # Should have skip event and workflow completion mentioning it
    assert len(events) >= 1
    assert any(e.event_type == EventType.TASK_SKIPPED for e in events)

    # Test 4: Non-existent task should return empty list
    events = await event_store.get_task_timeline(workflow_id, "non_existent_task")
    assert len(events) == 0


@pytest.mark.asyncio
async def test_get_task_execution_details(event_store):
    """Test retrieving detailed execution info for a task"""
    workflow_id = "test_workflow_task_timeline"

    # Create sample events
    await create_sample_events(event_store, workflow_id)

    # Test 1: Successful task (validate_input)
    details = await event_store.get_task_execution_details(workflow_id, "validate_input")

    assert details['task_id'] == "validate_input"
    assert details['workflow_id'] == workflow_id
    assert details['status'] == "completed"
    assert details['protocol'] == "validation/v1"
    assert details['execution_id'] == "exec_001"
    assert details['is_validation'] == True
    assert details['result'] == {"valid": True, "data": {"amount": 100}}
    assert details['start_time'] is not None
    assert details['end_time'] is not None
    assert details['duration_ms'] is not None
    assert details['duration_ms'] >= 0
    assert len(details['events']) >= 3

    # Test 2: Failed then succeeded task (process_payment)
    details = await event_store.get_task_execution_details(workflow_id, "process_payment")

    assert details['task_id'] == "process_payment"
    assert details['status'] == "completed"  # Final status after retry
    assert details['retry_count'] == 1  # Was replayed once
    assert details['result'] == {"payment_id": "pay_123", "status": "success"}
    assert details['execution_id'] == "exec_004"  # Latest execution

    # Check that events include both attempts
    event_types = [e['type'] for e in details['events']]
    assert event_types.count('task:started') == 2  # Started twice
    assert 'task:failed' in event_types
    assert 'task:completed' in event_types

    # Test 3: Skipped task (send_notification)
    details = await event_store.get_task_execution_details(workflow_id, "send_notification")

    assert details['task_id'] == "send_notification"
    assert details['status'] == "skipped"
    assert details['skip_reason'] == "Validation check_notification_enabled returned false"
    assert details['validation_task'] == "check_notification_enabled"
    assert details['start_time'] is None  # Never started
    assert details['end_time'] is None
    assert details['duration_ms'] is None

    # Test 4: Non-existent task
    details = await event_store.get_task_execution_details(workflow_id, "non_existent_task")

    assert details['task_id'] == "non_existent_task"
    assert details['status'] == "unknown"
    assert details['start_time'] is None
    assert len(details['events']) == 0


@pytest.mark.asyncio
async def test_task_timeline_with_validation_flow(event_store):
    """Test task timeline with XOR validation pattern"""
    workflow_id = "test_xor_workflow"

    # Create XOR pattern: validate_option_a and validate_option_b are mutually exclusive

    # Both validations run
    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="validate_option_a",
        data={"protocol": "validation/v1", "execution_id": "val_a"}
    )

    await event_store.store_event(
        EventType.TASK_COMPLETED,
        workflow_id,
        task_id="validate_option_a",
        data={"result": {"valid": True}}
    )

    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="validate_option_b",
        data={"protocol": "validation/v1", "execution_id": "val_b"}
    )

    await event_store.store_event(
        EventType.TASK_COMPLETED,
        workflow_id,
        task_id="validate_option_b",
        data={"result": {"valid": False}}
    )

    # Option A proceeds, Option B is skipped
    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="process_option_a",
        data={"protocol": "python/v1"}
    )

    await event_store.store_event(
        EventType.TASK_COMPLETED,
        workflow_id,
        task_id="process_option_a",
        data={"result": {"processed": "option_a"}}
    )

    await event_store.store_event(
        EventType.TASK_SKIPPED,
        workflow_id,
        task_id="process_option_b",
        data={
            "reason": "Validation validate_option_b returned false",
            "validation_task": "validate_option_b"
        }
    )

    # Test validation task details
    details_a = await event_store.get_task_execution_details(workflow_id, "validate_option_a")
    assert details_a['status'] == "completed"
    assert details_a['is_validation'] == True
    assert details_a['result'] == {"valid": True}

    details_b = await event_store.get_task_execution_details(workflow_id, "validate_option_b")
    assert details_b['status'] == "completed"
    assert details_b['is_validation'] == True
    assert details_b['result'] == {"valid": False}

    # Test processing task details
    details_proc_a = await event_store.get_task_execution_details(workflow_id, "process_option_a")
    assert details_proc_a['status'] == "completed"
    assert details_proc_a['result'] == {"processed": "option_a"}

    details_proc_b = await event_store.get_task_execution_details(workflow_id, "process_option_b")
    assert details_proc_b['status'] == "skipped"
    assert details_proc_b['validation_task'] == "validate_option_b"


@pytest.mark.asyncio
async def test_task_duration_calculation(event_store):
    """Test that duration is correctly calculated"""
    workflow_id = "test_duration_workflow"

    start_time = datetime.utcnow()

    await event_store.store_event(
        EventType.TASK_STARTED,
        workflow_id,
        task_id="timed_task",
        data={"protocol": "python/v1"}
    )

    # Simulate some processing time
    await asyncio.sleep(0.1)  # 100ms

    await event_store.store_event(
        EventType.TASK_COMPLETED,
        workflow_id,
        task_id="timed_task",
        data={"result": {"done": True}}
    )

    details = await event_store.get_task_execution_details(workflow_id, "timed_task")

    assert details['duration_ms'] is not None
    assert details['duration_ms'] >= 100  # At least 100ms
    assert details['duration_ms'] < 200  # But not too long


if __name__ == "__main__":
    # Run tests
    asyncio.run(test_get_task_timeline(EventStore(None)))