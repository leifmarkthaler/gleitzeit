#!/usr/bin/env python3
"""Simple test for event persistence."""

import asyncio
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.events.store import EventStore
from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity
from datetime import datetime

async def test_event_persistence():
    """Test basic event persistence functionality."""
    
    print("Testing Event Persistence Components")
    print("=" * 40)
    
    # Create persistence backend
    persistence = InMemoryBackend()
    await persistence.initialize()
    print("✓ Persistence backend initialized")
    
    # Create event store
    event_store = EventStore(persistence=persistence)
    print("✓ Event store created")
    
    # Create event bus with event store
    event_bus = EventBus(
        isolate_errors=True,
        track_errors=True,
        event_store=event_store
    )
    print("✓ Event bus created with event store")
    
    # Create and emit some test events
    print("\nEmitting test events...")
    
    # Event 1: Task submitted
    event1 = GleitzeitEvent(
        event_type=EventType.TASK_SUBMITTED,
        data={"task_id": "test_task_001", "workflow_id": "test_workflow_001"},
        severity=EventSeverity.INFO,
        source="test_script"
    )
    await event_bus.emit(event1)
    print(f"  Emitted: {event1.event_type}")
    
    # Event 2: Task started
    event2 = GleitzeitEvent(
        event_type=EventType.TASK_STARTED,
        data={"task_id": "test_task_001", "workflow_id": "test_workflow_001"},
        severity=EventSeverity.INFO,
        source="test_script"
    )
    await event_bus.emit(event2)
    print(f"  Emitted: {event2.event_type}")
    
    # Event 3: Task completed
    event3 = GleitzeitEvent(
        event_type=EventType.TASK_COMPLETED,
        data={"task_id": "test_task_001", "workflow_id": "test_workflow_001", "result": "success"},
        severity=EventSeverity.INFO,
        source="test_script"
    )
    await event_bus.emit(event3)
    print(f"  Emitted: {event3.event_type}")
    
    # Retrieve persisted events
    print("\nRetrieving persisted events...")
    
    # Get all events
    all_events = await event_store.get_events()
    print(f"  Total events persisted: {len(all_events)}")
    
    # Get workflow-specific events
    workflow_events = await event_store.get_events(workflow_id="test_workflow_001")
    print(f"  Events for workflow: {len(workflow_events)}")
    
    # Get task-specific events
    task_events = await event_store.get_events(task_id="test_task_001")
    print(f"  Events for task: {len(task_events)}")
    
    # Display event details
    if all_events:
        print("\nEvent Details:")
        for i, event in enumerate(all_events, 1):
            print(f"\n  Event {i}:")
            print(f"    ID: {event.get('event_id')}")
            print(f"    Type: {event.get('event_type')}")
            print(f"    Timestamp: {event.get('timestamp')}")
            if 'data' in event:
                print(f"    Task ID: {event.get('task_id', 'N/A')}")
                print(f"    Workflow ID: {event.get('workflow_id', 'N/A')}")
    
    # Test filtering by event type
    print("\nTesting event type filtering...")
    completed_events = await event_store.get_events(event_type=EventType.TASK_COMPLETED)
    print(f"  TASK_COMPLETED events: {len(completed_events)}")
    
    print("\n" + "=" * 40)
    print("✓ Event persistence test successful!")
    
    await persistence.shutdown()

if __name__ == "__main__":
    asyncio.run(test_event_persistence())