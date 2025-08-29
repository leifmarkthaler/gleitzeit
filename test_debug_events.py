#!/usr/bin/env python3
"""Debug test to trace event persistence issue."""

import asyncio
import logging
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task, Priority

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

async def test_debug():
    """Debug event persistence."""
    
    print("DEBUG: Event Persistence Test")
    print("=" * 40)
    
    config = {
        'persist_events': True,
        'persistence_type': 'memory'
    }
    
    client = GleitzeitClient(mode=ClientMode.NATIVE, **config)
    
    await client.initialize()
    print(f"\n1. Client initialized")
    
    # Check EventBus and EventStore
    if hasattr(client._adapter, 'event_bus'):
        event_bus = client._adapter.event_bus
        print(f"   EventBus: {event_bus}")
        
        if hasattr(event_bus, 'event_store'):
            print(f"   EventStore: {event_bus.event_store}")
            if event_bus.event_store:
                print("   ✓ EventStore is configured")
                
                # Check persistence backend
                if hasattr(event_bus.event_store, 'persistence'):
                    print(f"   Persistence: {event_bus.event_store.persistence}")
                    
                    # Try to manually save an event
                    from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity
                    test_event = GleitzeitEvent(
                        event_type=EventType.ENGINE_STARTED,
                        severity=EventSeverity.INFO,
                        data={"test": "manual"},
                        source="test_script"
                    )
                    
                    print("\n2. Testing manual event save...")
                    try:
                        await event_bus.emit(test_event)
                        print("   ✓ Event emitted")
                        
                        # Check if it was saved
                        events = await event_bus.event_store.get_events()
                        print(f"   Events in store: {len(events)}")
                        
                        if events:
                            print("   ✓ Event persistence is working!")
                            for event in events:
                                print(f"     - {event}")
                        else:
                            print("   ✗ Event was not persisted")
                            
                    except Exception as e:
                        print(f"   ✗ Error: {e}")
                        import traceback
                        traceback.print_exc()
            else:
                print("   ✗ EventStore is None!")
        else:
            print("   ✗ EventBus has no event_store attribute!")
    else:
        print("   ✗ Adapter has no event_bus!")
    
    # Check ExecutionEngine
    if hasattr(client._adapter, 'execution_engine'):
        engine = client._adapter.execution_engine
        print(f"\n3. ExecutionEngine: {engine}")
        
        if hasattr(engine, 'event_bus'):
            print(f"   Engine EventBus: {engine.event_bus}")
            
            # Check if it's the same EventBus
            if engine.event_bus is client._adapter.event_bus:
                print("   ✓ Engine using same EventBus")
            else:
                print("   ✗ Engine using different EventBus!")
                
                # Check if engine's EventBus has event_store
                if hasattr(engine.event_bus, 'event_store'):
                    print(f"   Engine EventStore: {engine.event_bus.event_store}")
    
    await client.shutdown()
    print("\n✓ Debug test complete")

if __name__ == "__main__":
    asyncio.run(test_debug())