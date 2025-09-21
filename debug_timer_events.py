#!/usr/bin/env python3
"""
Debug timer event emission - test if timer monitor can emit events
"""

import asyncio
import redis.asyncio as redis
import time
from datetime import datetime
from gleitzeit.core.models import TaskStatus, TaskResult
from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.events.stream_event_bus import GleitzeitStreamEvent

async def test_timer_event_emission():
    # Connect to Redis
    client = redis.from_url("redis://localhost:6379/0", decode_responses=False)
    
    try:
        # Create a fake timer completion event (similar to timer monitor)
        event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={
                "task_id": "test-timer-task",
                "workflow_id": "test-workflow",
                "status": "completed"
            },
            source="timer_monitor_test",
            correlation_id="test-workflow"
        )
        
        # Convert to stream event format
        stream_event = GleitzeitStreamEvent.from_event(event)
        
        print(f"Event data: {stream_event.to_dict()}")
        
        # Try to emit to the same stream as timer monitor
        stream_key = "gleitzeit:events:stream:task:completed"
        result = await client.xadd(stream_key, stream_event.to_dict())
        
        print(f"Successfully emitted event to {stream_key}: {result}")
        
        # Check stream length
        length = await client.xlen(stream_key)
        print(f"Stream now has {length} events")
        
    except Exception as e:
        print(f"Error emitting event: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_timer_event_emission())