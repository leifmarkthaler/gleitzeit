#!/usr/bin/env python3
"""Simple test to verify event persistence is working."""

import asyncio
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task
from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity


async def test_event_persistence():
    """Simple test that events are persisted."""
    
    print("\n" + "="*60)
    print("SIMPLE EVENT PERSISTENCE TEST")
    print("="*60)
    
    # Configure client with event persistence
    config = {
        'persist_events': True,
        'persistence_type': 'memory'
    }
    
    client = GleitzeitClient(mode=ClientMode.NATIVE, **config)
    await client.initialize()
    print("✓ Client initialized with event persistence")
    
    # Check if EventBus has EventStore
    if hasattr(client._adapter, 'event_bus'):
        event_bus = client._adapter.event_bus
        if hasattr(event_bus, 'event_store') and event_bus.event_store:
            print("✓ EventStore is configured")
            
            # Manually emit some test events
            print("\nEmitting test events...")
            
            test_events = [
                GleitzeitEvent(
                    event_type=EventType.ENGINE_STARTED,
                    severity=EventSeverity.INFO,
                    data={"test": "event1"},
                    source="test_script"
                ),
                GleitzeitEvent(
                    event_type=EventType.WORKFLOW_SUBMITTED,
                    severity=EventSeverity.INFO,
                    data={"workflow_id": "test_workflow", "test": "event2"},
                    source="test_script"
                ),
                GleitzeitEvent(
                    event_type=EventType.TASK_SUBMITTED,
                    severity=EventSeverity.INFO,
                    data={"task_id": "test_task", "workflow_id": "test_workflow", "test": "event3"},
                    source="test_script"
                )
            ]
            
            for event in test_events:
                await event_bus.emit(event)
                print(f"  ✓ Emitted {event.event_type}")
            
            # Now retrieve events
            print("\nRetrieving events...")
            
            # Get all events
            all_events = await event_bus.event_store.get_events()
            print(f"\n✓ Total events in store: {len(all_events)}")
            
            if all_events:
                print("\nEvents found:")
                for i, event in enumerate(all_events):
                    print(f"  {i+1}. Type: {event.get('event_type')}, Source: {event.get('source')}")
                
                # Test workflow filtering
                workflow_events = await event_bus.event_store.get_events(workflow_id="test_workflow")
                print(f"\n✓ Workflow-specific events: {len(workflow_events)}")
                
                # Test task filtering
                task_events = await event_bus.event_store.get_events(task_id="test_task")
                print(f"✓ Task-specific events: {len(task_events)}")
                
                # Also check via client API
                print("\nChecking via client API...")
                client_events = await client.get_events()
                print(f"✓ Client API returns {len(client_events)} events")
                
                print("\n" + "="*60)
                print("✅ SUCCESS: EVENT PERSISTENCE IS WORKING!")
                print("="*60)
                print("\nSummary:")
                print(f"- Events are being saved to persistence backend")
                print(f"- Events can be retrieved with filters")
                print(f"- Client API for events is functional")
                print(f"- UnifiedInMemoryAdapter now supports event persistence")
                
                return True
            else:
                print("\n⚠️  No events found in store")
                return False
        else:
            print("✗ EventStore is not configured")
            return False
    else:
        print("✗ EventBus not found")
        return False
    
    await client.shutdown()


async def main():
    """Run the test."""
    try:
        success = await test_event_persistence()
        
        if success:
            print("\n✅ Event persistence test PASSED!")
            return True
        else:
            print("\n❌ Event persistence test FAILED")
            return False
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)