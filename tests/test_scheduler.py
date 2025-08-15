#!/usr/bin/env python3
"""
Test Event-driven Scheduling
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.scheduler import EventScheduler, ScheduledEventType, ScheduledEvent

async def test_immediate_scheduling():
    """Test immediate event scheduling"""
    emitted_events = []
    
    async def emit_callback(event_type: str, data: dict):
        emitted_events.append((event_type, data))
    
    scheduler = EventScheduler(emit_callback)
    
    # Schedule immediate event
    event_id = await scheduler.schedule_event(
        event_type=ScheduledEventType.TASK_RETRY,
        delay=timedelta(seconds=0.1),
        event_data={"task_id": "test-task"}
    )
    
    await scheduler.start()
    
    # Wait for execution
    await asyncio.sleep(0.2)
    
    assert len(emitted_events) == 1
    assert emitted_events[0][0] == ScheduledEventType.TASK_RETRY
    assert emitted_events[0][1]["task_id"] == "test-task"
    
    await scheduler.stop()
    print("✅ Immediate scheduling test passed")

async def test_delayed_scheduling():
    """Test delayed event scheduling"""
    emitted_events = []
    start_time = datetime.now()
    
    async def emit_callback(event_type: str, data: dict):
        emitted_events.append((event_type, data, datetime.now()))
    
    scheduler = EventScheduler(emit_callback)
    
    # Schedule with 0.3 second delay
    event_id = await scheduler.schedule_event(
        event_type=ScheduledEventType.WORKFLOW_TIMEOUT,
        delay=timedelta(seconds=0.3),
        event_data={"workflow_id": "test-workflow"}
    )
    
    await scheduler.start()
    
    # Wait for execution
    await asyncio.sleep(0.5)
    
    assert len(emitted_events) == 1
    execution_time = emitted_events[0][2]
    time_diff = (execution_time - start_time).total_seconds()
    assert 0.25 <= time_diff <= 0.4  # Allow some margin
    
    await scheduler.stop()
    print("✅ Delayed scheduling test passed")

async def test_multiple_events():
    """Test scheduling multiple events"""
    emitted_events = []
    
    async def emit_callback(event_type: str, data: dict):
        emitted_events.append((event_type, data))
    
    scheduler = EventScheduler(emit_callback)
    
    # Schedule multiple events with different delays
    await scheduler.schedule_event(
        event_type=ScheduledEventType.TASK_RETRY,
        delay=timedelta(seconds=0.1),
        event_data={"task_id": "task-1"}
    )
    await scheduler.schedule_event(
        event_type=ScheduledEventType.HEALTH_CHECK,
        delay=timedelta(seconds=0.2),
        event_data={"provider_id": "provider-1"}
    )
    await scheduler.schedule_event(
        event_type=ScheduledEventType.CLEANUP,
        delay=timedelta(seconds=0.3),
        event_data={"resource_id": "resource-1"}
    )
    
    await scheduler.start()
    
    # Wait for all events
    await asyncio.sleep(0.5)
    
    assert len(emitted_events) == 3
    # Check events were emitted in correct order
    assert emitted_events[0][1]["task_id"] == "task-1"
    assert emitted_events[1][1]["provider_id"] == "provider-1"
    assert emitted_events[2][1]["resource_id"] == "resource-1"
    
    await scheduler.stop()
    print("✅ Multiple events scheduling test passed")

async def test_event_cancellation():
    """Test event cancellation"""
    emitted_events = []
    
    async def emit_callback(event_type: str, data: dict):
        emitted_events.append((event_type, data))
    
    scheduler = EventScheduler(emit_callback)
    
    # Schedule event
    event_id = await scheduler.schedule_event(
        event_type=ScheduledEventType.TASK_RETRY,
        delay=timedelta(seconds=0.3),
        event_data={"task_id": "task-to-cancel"},
        event_id="cancel-test"
    )
    
    await scheduler.start()
    
    # Cancel before execution
    await asyncio.sleep(0.1)
    cancelled = await scheduler.cancel_event("cancel-test")
    
    # Wait to ensure it doesn't execute
    await asyncio.sleep(0.4)
    
    assert cancelled
    assert len(emitted_events) == 0
    await scheduler.stop()
    print("✅ Event cancellation test passed")

async def test_scheduled_event_creation():
    """Test creating scheduled events"""
    event = ScheduledEvent(
        event_type=ScheduledEventType.TASK_RETRY,
        scheduled_at=datetime.now() + timedelta(seconds=1),
        event_data={"task_id": "test-task"},
        event_id="test-event"
    )
    
    assert event.event_type == ScheduledEventType.TASK_RETRY
    assert event.event_data["task_id"] == "test-task"
    assert event.event_id == "test-event"
    print("✅ Scheduled event creation test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing Event-driven Scheduling")
    print("=" * 50)
    
    try:
        await test_immediate_scheduling()
        await test_delayed_scheduling()
        await test_multiple_events()
        await test_event_cancellation()
        await test_scheduled_event_creation()
        
        print("\n✅ All scheduler tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))