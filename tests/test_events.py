#!/usr/bin/env python3
"""
Test Event System Architecture
"""

import asyncio
import sys
import os
from typing import List
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.events import EventType, GleitzeitEvent, EventSeverity

# Simple EventRouter implementation for testing
class EventRouter:
    def __init__(self):
        self.handlers = {}
    
    def subscribe(self, event_type: EventType, handler):
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)
    
    async def emit(self, event: GleitzeitEvent):
        if event.event_type in self.handlers:
            for handler in self.handlers[event.event_type]:
                await handler(event)

async def test_event_creation():
    """Test event creation and properties"""
    event = GleitzeitEvent(
        event_type=EventType.TASK_SUBMITTED,
        data={"task_id": "test-123"},
        source="test",
        correlation_id="corr-123",
        severity=EventSeverity.INFO
    )
    
    assert event.event_type == EventType.TASK_SUBMITTED
    assert event.data["task_id"] == "test-123"
    assert event.source == "test"
    assert event.correlation_id == "corr-123"
    assert event.severity == EventSeverity.INFO
    print("✅ Event creation test passed")

async def test_event_router():
    """Test event routing functionality"""
    router = EventRouter()
    received_events = []
    
    async def handler(event):
        received_events.append(event)
    
    # Subscribe to events
    router.subscribe(EventType.TASK_SUBMITTED, handler)
    
    # Emit event
    event = GleitzeitEvent(
        event_type=EventType.TASK_SUBMITTED,
        data={"task_id": "test-456"},
        source="test"
    )
    await router.emit(event)
    
    # Give a moment for async processing
    await asyncio.sleep(0.1)
    
    assert len(received_events) == 1
    assert received_events[0].data["task_id"] == "test-456"
    print("✅ Event routing test passed")

async def test_multiple_handlers():
    """Test multiple handlers for same event type"""
    router = EventRouter()
    handler1_called = False
    handler2_called = False
    
    async def handler1(event):
        nonlocal handler1_called
        handler1_called = True
    
    async def handler2(event):
        nonlocal handler2_called
        handler2_called = True
    
    router.subscribe(EventType.TASK_COMPLETED, handler1)
    router.subscribe(EventType.TASK_COMPLETED, handler2)
    
    event = GleitzeitEvent(
        event_type=EventType.TASK_COMPLETED,
        data={"task_id": "test-789"},
        source="test"
    )
    await router.emit(event)
    
    await asyncio.sleep(0.1)
    
    assert handler1_called
    assert handler2_called
    print("✅ Multiple handlers test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing Event System Architecture")
    print("=" * 50)
    
    try:
        await test_event_creation()
        await test_event_router()
        await test_multiple_handlers()
        
        print("\n✅ All event system tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))