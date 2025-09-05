#!/usr/bin/env python
"""Test that events are being persisted properly."""

import asyncio
import sys
from datetime import datetime
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity
from gleitzeit.events.store import EventStore
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter

async def test_event_persistence():
    """Test that events are persisted when emitted."""
    print("Testing Event Persistence")
    print("=" * 50)
    
    # Initialize client
    client = GleitzeitClient(mode="api")
    await client.initialize()
    
    print("\n1. Submitting a test workflow to generate events...")
    
    # Submit a simple workflow
    workflow_config = {
        "id": "test_event_persistence",
        "name": "Event Persistence Test",
        "tasks": [
            {
                "id": "task1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Testing event persistence'); result = 'task1_complete'"
                }
            }
        ]
    }
    
    try:
        result = await client.submit_workflow(workflow_config)
        workflow_id = result.get("workflow_id", "test_event_persistence")
        print(f"   Workflow submitted: {workflow_id}")
        
        # Wait for workflow to complete
        print("\n2. Waiting for workflow to complete and generate events...")
        await asyncio.sleep(3)
        
        # Check if events were persisted
        print("\n3. Checking persisted events...")
        
        # Create persistence backend and event store directly
        backend = UnifiedRedisAdapter()
        event_store = EventStore(backend)
        
        # Query for events
        events = await event_store.get_events(
            workflow_id=workflow_id,
            limit=100
        )
        
        print(f"\n4. Found {len(events)} persisted events")
        
        if events:
            print("\n   Event Types Found:")
            event_types = set()
            for event in events:
                event_type = event.get('event_type', 'unknown')
                event_types.add(event_type)
                
            for event_type in sorted(event_types):
                count = sum(1 for e in events if e.get('event_type') == event_type)
                print(f"      - {event_type}: {count} events")
            
            print("\n   Sample Event Details:")
            sample_event = events[0]
            print(f"      Event ID: {sample_event.get('event_id')}")
            print(f"      Event Type: {sample_event.get('event_type')}")
            print(f"      Timestamp: {sample_event.get('timestamp')}")
            print(f"      Workflow ID: {sample_event.get('workflow_id', 'N/A')}")
            print(f"      Task ID: {sample_event.get('task_id', 'N/A')}")
            
            print("\n✅ EVENT PERSISTENCE IS WORKING!")
            print("   Events are being properly saved to the backend.")
            
        else:
            print("\n⚠️  No persisted events found")
            print("   This might mean:")
            print("   - Events are not being persisted yet")
            print("   - The workflow hasn't generated events yet")
            print("   - There's an issue with the persistence backend")
            
            # Try checking if persistence backend has save_event method
            if hasattr(backend, 'save_event'):
                print("\n   ✓ Backend supports event persistence (has save_event method)")
            else:
                print("\n   ✗ Backend doesn't support event persistence (missing save_event method)")
        
    except Exception as e:
        print(f"\n❌ Error testing event persistence: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        await client.close()
    
    return len(events) > 0 if 'events' in locals() else False

if __name__ == "__main__":
    success = asyncio.run(test_event_persistence())
    sys.exit(0 if success else 1)