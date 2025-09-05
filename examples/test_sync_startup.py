#!/usr/bin/env python3
"""
Test synchronous startup with fixed race conditions.
"""

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.events import EventType, GleitzeitEvent
import time

def main():
    """Test sync startup."""
    
    print("Testing synchronous startup...")
    start_time = time.time()
    
    # Use the new sync startup
    client = GleitzeitClient.start_sync()
    
    startup_time = time.time() - start_time
    print(f"Client ready in {startup_time*1000:.1f}ms")
    
    # Test that events work immediately
    print("\nTesting immediate event handling...")
    
    event_count = [0]  # Use list to allow modification in nested function
    
    async def handle_test_event(event):
        event_count[0] += 1
        print(f"  Handler called! Count: {event_count[0]}")
    
    # Register handler
    client.event_bus.register(EventType.TASK_QUEUED, handle_test_event)
    
    # Emit events immediately - would fail with race condition
    import asyncio
    async def emit_events():
        for i in range(3):
            await client.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_QUEUED,
                data={"test": i}
            ))
    
    # Use the client's loop
    if hasattr(client, '_sync_loop'):
        client._sync_loop.run_until_complete(emit_events())
    else:
        asyncio.run(emit_events())
    
    if event_count[0] == 3:
        print(f"\n✅ SUCCESS: All {event_count[0]} events handled immediately!")
        print("   No race conditions detected.")
    else:
        print(f"\n❌ FAILED: Only {event_count[0]}/3 events handled")
        print("   Race condition may still exist.")
    
    # Cleanup
    print("\nShutting down...")
    client.stop_sync()
    print("Done!")

if __name__ == "__main__":
    main()