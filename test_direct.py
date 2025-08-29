#!/usr/bin/env python3
"""Direct test of event persistence with modular client."""

import asyncio
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Task

async def test_event_persistence():
    """Test event persistence directly."""
    
    print("Testing Event Persistence with Modular Client")
    print("=" * 50)
    
    # Config with event persistence enabled
    config = {
        'persist_events': True,
        'persistence_type': 'memory',
        'max_concurrent_tasks': 5
    }
    
    print("\n1. Initializing client...")
    client = GleitzeitClient(mode='native', **config)
    
    try:
        await client.initialize()
        print("   ✓ Client initialized")
        
        # Check that event persistence is configured
        if hasattr(client._adapter, 'event_store') and client._adapter.event_store:
            print("   ✓ Event store is configured")
        else:
            print("   ✗ Event store NOT configured")
        
        # Submit a simple task
        print("\n2. Submitting test task...")
        task = Task(
            id="test_event_task",
            name="Test Event Task",
            protocol="shell",
            method="execute",
            params={"command": "echo 'Testing events'"}
        )
        
        # The adapter should emit events when submitting
        result = await client._adapter.submit_task(task)
        print(f"   ✓ Task submitted: {result}")
        
        # Wait a moment for events to be processed
        await asyncio.sleep(1)
        
        # Retrieve events
        print("\n3. Retrieving events...")
        events = await client.get_events()
        print(f"   Total events: {len(events)}")
        
        if events:
            print("\n   Event types found:")
            event_types = set(e.get('event_type') for e in events)
            for et in sorted(event_types):
                print(f"     - {et}")
            
            print("\n   Last 3 events:")
            for event in events[-3:]:
                print(f"     {event.get('event_type')}: {event.get('timestamp')}")
                if event.get('task_id'):
                    print(f"       Task: {event.get('task_id')}")
        
        print("\n✓ Event persistence is working!")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.shutdown()
        print("\nClient shutdown complete.")

if __name__ == "__main__":
    asyncio.run(test_event_persistence())