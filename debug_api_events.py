#!/usr/bin/env python3
"""Debug API event persistence."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity

async def debug_api():
    """Debug the API's event persistence."""
    
    print("\nDEBUGGING API EVENT PERSISTENCE")
    print("="*60)
    
    # Create a client same way the API does
    client = GleitzeitClient(mode="native", persist_events=True)
    await client.initialize()
    print("✓ Client initialized with persist_events=True")
    
    # Check if event persistence is set up
    if hasattr(client._adapter, 'event_bus'):
        event_bus = client._adapter.event_bus
        print(f"✓ EventBus found: {event_bus}")
        
        if hasattr(event_bus, 'event_store'):
            print(f"✓ EventStore found: {event_bus.event_store}")
            
            if event_bus.event_store:
                # Emit a test event
                test_event = GleitzeitEvent(
                    event_type=EventType.ENGINE_STARTED,
                    severity=EventSeverity.INFO,
                    data={"source": "debug_test"},
                    source="debug_api"
                )
                await event_bus.emit(test_event)
                print("✓ Test event emitted")
                
                # Get events via client
                events = await client.get_events()
                print(f"\n✓ Client.get_events() returns: {len(events)} events")
                
                if events:
                    print("\nEvents found via client API:")
                    for i, event in enumerate(events[:3]):
                        print(f"  {i+1}. {event.get('event_type')}")
                else:
                    print("\n⚠️  No events returned by client.get_events()")
                    
                    # Check persistence directly
                    if hasattr(client._adapter, 'persistence'):
                        persistence = client._adapter.persistence
                        print(f"\nPersistence backend: {type(persistence).__name__}")
                        
                        if hasattr(persistence, 'events_global'):
                            print(f"Events in persistence.events_global: {len(persistence.events_global)}")
                            
                            # Try calling get_events directly on persistence
                            if hasattr(persistence, 'get_events'):
                                direct_events = await persistence.get_events()
                                print(f"Direct persistence.get_events(): {len(direct_events)} events")
            else:
                print("✗ EventStore is None!")
        else:
            print("✗ EventBus has no event_store!")
    else:
        print("✗ Adapter has no event_bus!")
    
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(debug_api())