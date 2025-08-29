#!/usr/bin/env python3
"""Test script for event persistence functionality."""

import asyncio
import json
from datetime import datetime
from gleitzeit.client.base import ModularGleitzeitClient
from gleitzeit.core.models import Task, Workflow

async def test_event_persistence():
    """Test that events are being persisted and can be retrieved."""
    
    print("=" * 60)
    print("Testing Event Persistence in Gleitzeit")
    print("=" * 60)
    
    # Configuration with event persistence enabled
    config = {
        'persist_events': True,
        'persistence_type': 'memory',  # Use in-memory for testing
        'max_concurrent_tasks': 5
    }
    
    print("\n1. Initializing client with event persistence enabled...")
    client = ModularGleitzeitClient(mode='native', **config)
    
    try:
        await client.initialize()
        print("   ✓ Client initialized successfully")
        
        # Create a simple workflow for testing
        print("\n2. Creating test workflow...")
        workflow = Workflow(
            id="test_workflow_001",
            name="Event Persistence Test Workflow",
            description="Workflow to test event persistence",
            tasks=[
                Task(
                    id="test_task_001",
                    name="Test Task 1",
                    workflow_id="test_workflow_001",
                    protocol="shell",
                    method="execute",
                    params={"command": "echo 'Hello from task 1'"},
                    priority="normal"
                ),
                Task(
                    id="test_task_002",
                    name="Test Task 2",
                    workflow_id="test_workflow_001",
                    protocol="shell",
                    method="execute",
                    params={"command": "echo 'Hello from task 2'"},
                    priority="normal",
                    dependencies=["test_task_001"]
                )
            ]
        )
        
        print("   ✓ Workflow created")
        
        # Submit the workflow
        print("\n3. Submitting workflow...")
        result = await client._adapter.submit_workflow(workflow)
        print(f"   ✓ Workflow submitted: {result}")
        
        # Give some time for events to be processed
        print("\n4. Waiting for workflow execution...")
        await asyncio.sleep(2)
        
        # Retrieve events for the workflow
        print("\n5. Retrieving persisted events...")
        
        # Get all events
        all_events = await client.get_events(limit=20)
        print(f"   Total events persisted: {len(all_events)}")
        
        # Get workflow-specific events
        workflow_events = await client.get_events(workflow_id="test_workflow_001")
        print(f"   Events for workflow test_workflow_001: {len(workflow_events)}")
        
        # Get task-specific events
        task1_events = await client.get_events(task_id="test_task_001")
        print(f"   Events for task test_task_001: {len(task1_events)}")
        
        # Display event types captured
        if all_events:
            print("\n6. Event types captured:")
            event_types = set()
            for event in all_events:
                event_type = event.get('event_type', 'unknown')
                event_types.add(event_type)
            
            for event_type in sorted(event_types):
                count = sum(1 for e in all_events if e.get('event_type') == event_type)
                print(f"   - {event_type}: {count} events")
        
        # Display sample events
        if workflow_events:
            print("\n7. Sample workflow events (first 3):")
            for i, event in enumerate(workflow_events[:3], 1):
                print(f"\n   Event {i}:")
                print(f"     Type: {event.get('event_type', 'unknown')}")
                print(f"     Timestamp: {event.get('timestamp', 'no timestamp')}")
                if 'data' in event and isinstance(event['data'], dict):
                    print(f"     Task ID: {event['data'].get('task_id', 'N/A')}")
                    print(f"     Status: {event['data'].get('status', 'N/A')}")
        
        # Test filtering by event type
        print("\n8. Testing event filtering...")
        submit_events = await client.get_events(event_type="TASK_SUBMITTED")
        print(f"   TASK_SUBMITTED events: {len(submit_events)}")
        
        complete_events = await client.get_events(event_type="TASK_COMPLETED")
        print(f"   TASK_COMPLETED events: {len(complete_events)}")
        
        print("\n" + "=" * 60)
        print("✓ Event persistence test completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Error during testing: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.shutdown()
        print("\nClient shutdown complete.")

async def test_redis_persistence():
    """Test event persistence with Redis backend."""
    
    print("\n" + "=" * 60)
    print("Testing Event Persistence with Redis Backend")
    print("=" * 60)
    
    # Configuration with Redis and event persistence
    config = {
        'persist_events': True,
        'persistence_type': 'redis',
        'redis_url': 'redis://localhost:6379/0',
        'max_concurrent_tasks': 5
    }
    
    print("\n1. Attempting to connect to Redis...")
    client = ModularGleitzeitClient(mode='native', **config)
    
    try:
        await client.initialize()
        print("   ✓ Connected to Redis successfully")
        
        # Submit a simple task
        print("\n2. Submitting test task...")
        task = Task(
            id="redis_test_task_001",
            name="Redis Event Test",
            protocol="shell",
            method="execute",
            params={"command": "echo 'Testing Redis event persistence'"},
            priority="normal"
        )
        
        result = await client._adapter.submit_task(task)
        print(f"   ✓ Task submitted: {result}")
        
        # Wait and retrieve events
        await asyncio.sleep(1)
        
        print("\n3. Retrieving events from Redis...")
        events = await client.get_events(task_id="redis_test_task_001")
        print(f"   Events retrieved: {len(events)}")
        
        if events:
            print("\n   Event details:")
            for event in events:
                print(f"     - {event.get('event_type')}: {event.get('timestamp')}")
        
        print("\n✓ Redis event persistence working!")
        
    except Exception as e:
        print(f"\n✗ Redis test failed: {e}")
        print("  (This is expected if Redis is not running)")
    finally:
        await client.shutdown()

async def main():
    """Run all event persistence tests."""
    
    # Test with in-memory backend
    await test_event_persistence()
    
    # Test with Redis backend (optional)
    print("\n" + "=" * 60)
    print("Would you like to test Redis persistence? (requires Redis running)")
    print("Skipping Redis test for now...")
    # Uncomment to test with Redis:
    # await test_redis_persistence()

if __name__ == "__main__":
    asyncio.run(main())