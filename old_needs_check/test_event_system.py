#!/usr/bin/env python
"""Test event system with status enums"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.core.events import (
    EventType, EventSeverity, TaskEvent, WorkflowEvent,
    TimerEvent, SignalEvent
)
from gleitzeit.core.models import TaskStatus, WorkflowStatus

async def test_event_creation():
    """Test creating various events with proper status enums"""

    print("Testing Gleitzeit 0.0.7 Event System")
    print("=" * 50)

    # Task event with SCHEDULED status (for timer)
    timer_task_event = TaskEvent(
        event_type=EventType.TASK_SLEEPING,
        timestamp=datetime.utcnow(),
        severity=EventSeverity.INFO,
        task_id="wait_task",
        workflow_id="workflow_123",
        status=TaskStatus.SCHEDULED,
        protocol="timer/v1",
        method="timer/sleep"
    )

    print(f"\n1. Timer Task Event:")
    print(f"   Type: {timer_task_event.event_type.value}")
    print(f"   Status: {timer_task_event.status.value}")
    print(f"   Protocol: {timer_task_event.protocol}")

    # Timer fired event
    timer_fired_event = TimerEvent(
        event_type=EventType.TIMER_FIRED,
        timestamp=datetime.utcnow(),
        timer_id="timer_123",
        task_id="wait_task",
        workflow_id="workflow_123",
        duration_seconds=3.0
    )

    print(f"\n2. Timer Fired Event:")
    print(f"   Type: {timer_fired_event.event_type.value}")
    print(f"   Duration: {timer_fired_event.duration_seconds}s")

    # Task waiting for signal
    signal_wait_event = TaskEvent(
        event_type=EventType.TASK_WAITING,
        timestamp=datetime.utcnow(),
        severity=EventSeverity.INFO,
        task_id="signal_task",
        workflow_id="workflow_456",
        status=TaskStatus.WAITING,
        protocol="signal/v1",
        method="signal/wait"
    )

    print(f"\n3. Signal Wait Event:")
    print(f"   Type: {signal_wait_event.event_type.value}")
    print(f"   Status: {signal_wait_event.status.value}")

    # Signal received event
    signal_received = SignalEvent(
        event_type=EventType.SIGNAL_RECEIVED,
        timestamp=datetime.utcnow(),
        signal_name="approval_signal",
        workflow_id="workflow_456",
        task_id="signal_task",
        payload={"approved": True, "approver": "admin"}
    )

    print(f"\n4. Signal Received Event:")
    print(f"   Type: {signal_received.event_type.value}")
    print(f"   Signal: {signal_received.signal_name}")
    print(f"   Payload: {signal_received.payload}")

    # Workflow with scheduled tasks (has timers)
    workflow_event = WorkflowEvent(
        event_type=EventType.WORKFLOW_TIMER_SCHEDULED,
        timestamp=datetime.utcnow(),
        workflow_id="workflow_123",
        status=WorkflowStatus.SCHEDULED,
        total_tasks=3,
        completed_tasks=1
    )

    print(f"\n5. Workflow Event:")
    print(f"   Type: {workflow_event.event_type.value}")
    print(f"   Status: {workflow_event.status.value}")
    print(f"   Progress: {workflow_event.completed_tasks}/{workflow_event.total_tasks}")

    # Test serialization
    print(f"\n6. Event Serialization:")
    event_dict = timer_task_event.to_dict()
    print(f"   Serialized task event: {event_dict['event_type']}")
    print(f"   Timestamp: {event_dict['timestamp']}")
    print(f"   Status: {event_dict['status']}")

    print("\n✅ All event types working correctly!")

    # Demonstrate all task statuses
    print("\n7. Available Task Statuses:")
    for status in TaskStatus:
        print(f"   - {status.value}")

    print("\n8. Available Workflow Statuses:")
    for status in WorkflowStatus:
        print(f"   - {status.value}")

    print("\n9. Available Event Types (sample):")
    important_events = [
        EventType.TASK_SLEEPING,
        EventType.TASK_WAITING,
        EventType.TIMER_CREATED,
        EventType.TIMER_FIRED,
        EventType.SIGNAL_SENT,
        EventType.SIGNAL_RECEIVED,
        EventType.WORKFLOW_WAITING_FOR_SIGNAL,
        EventType.WORKFLOW_TIMER_SCHEDULED
    ]
    for event in important_events:
        print(f"   - {event.value}")

if __name__ == "__main__":
    asyncio.run(test_event_creation())