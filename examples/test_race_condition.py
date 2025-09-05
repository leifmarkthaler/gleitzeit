#!/usr/bin/env python3
"""
Test script to verify race conditions are fixed.
"""

import asyncio
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.events import EventType, GleitzeitEvent

async def main():
    """Test async startup and event handling."""
    
    print("Starting async test...")
    
    # Create and initialize client
    client = GleitzeitClient(mode="native")
    await client.initialize()
    
    print("Client initialized!")
    
    # Test event handling - this would fail with race conditions
    event_received = False
    
    @client.on_event(EventType.ENGINE_STARTED)
    async def on_engine_start(event):
        nonlocal event_received
        event_received = True
        print(f"Received event: {event.event_type}")
    
    # Emit test event immediately - would fail if race condition exists
    await client.event_bus.emit(GleitzeitEvent(
        event_type=EventType.ENGINE_STARTED,
        data={"test": "data"}
    ))
    
    # Small delay to ensure handler executes
    await asyncio.sleep(0.1)
    
    if event_received:
        print("✅ SUCCESS: Event handler worked immediately (no race condition!)")
    else:
        print("❌ FAILED: Event handler not ready (race condition exists)")
    
    # Cleanup
    await client.shutdown()
    print("Test complete!")

if __name__ == "__main__":
    asyncio.run(main())