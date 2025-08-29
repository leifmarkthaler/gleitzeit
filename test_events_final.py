#!/usr/bin/env python3
"""Final test of event persistence functionality."""

import asyncio
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task


async def test_event_persistence():
    """Test that events are properly persisted."""
    
    print("\n" + "="*60)
    print("FINAL EVENT PERSISTENCE TEST")
    print("="*60)
    
    # Configure client with event persistence
    config = {
        'persist_events': True,
        'persistence_type': 'memory'
    }
    
    client = GleitzeitClient(mode=ClientMode.NATIVE, **config)
    await client.initialize()
    print("✓ Client initialized with event persistence")
    
    # Start the engine
    await client.start_engine('EVENT_DRIVEN')
    print("✓ Engine started")
    
    # Create a simple workflow with MCP tasks
    tasks = [
        Task(
            id="add_task",
            name="Addition",
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 5, "b": 10}
        ),
        Task(
            id="multiply_task",
            name="Multiplication",
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 20, "b": 3},
            dependencies=["add_task"]
        )
    ]
    
    workflow = Workflow(
        id="test_workflow",
        name="Event Test Workflow",
        tasks=tasks
    )
    
    # Submit workflow
    result = await client.submit_workflow(workflow)
    workflow_id = result.get('workflow_id', workflow.id)
    print(f"✓ Workflow submitted: {workflow_id}")
    
    # Wait for processing
    print("\nProcessing workflow...")
    await asyncio.sleep(2)
    
    # Get workflow tasks to check status
    tasks_status = await client.get_workflow_tasks(workflow_id)
    print(f"✓ Workflow has {len(tasks_status)} tasks")
    
    # Now check events
    print("\n" + "="*60)
    print("EVENT PERSISTENCE CHECK")
    print("="*60)
    
    # Get all events
    all_events = await client.get_events()
    print(f"\n✓ Total events captured: {len(all_events)}")
    
    if all_events:
        # Count by type
        event_types = {}
        for event in all_events:
            event_type = str(event.get('event_type', 'unknown'))
            event_types[event_type] = event_types.get(event_type, 0) + 1
        
        print("\nEvent Types:")
        for event_type, count in sorted(event_types.items()):
            print(f"  {event_type}: {count}")
        
        # Get workflow-specific events
        workflow_events = await client.get_events(workflow_id=workflow_id)
        print(f"\n✓ Workflow '{workflow_id}' events: {len(workflow_events)}")
        
        # Show some events
        print("\nFirst 3 events:")
        for i, event in enumerate(all_events[:3]):
            print(f"\n  Event {i+1}:")
            print(f"    Type: {event.get('event_type')}")
            print(f"    Time: {event.get('timestamp')}")
            if event.get('workflow_id'):
                print(f"    Workflow: {event.get('workflow_id')}")
            if event.get('task_id'):
                print(f"    Task: {event.get('task_id')}")
        
        # Test task-specific events
        for task_id in ["add_task", "multiply_task"]:
            task_events = await client.get_events(task_id=task_id)
            if task_events:
                print(f"\n✓ Task '{task_id}' has {len(task_events)} events")
        
        print("\n" + "="*60)
        print("✅ EVENT PERSISTENCE IS WORKING!")
        print("Events are being captured and can be retrieved.")
        print("="*60)
        
    else:
        print("\n⚠️  No events captured - checking persistence backend...")
        
        # Direct check of persistence backend
        if hasattr(client._adapter, 'persistence'):
            persistence = client._adapter.persistence
            print(f"Persistence backend: {type(persistence).__name__}")
            
            if hasattr(persistence, 'events_global'):
                print(f"Events in storage: {len(persistence.events_global)}")
    
    # Cleanup
    await client.stop_engine()
    await client.shutdown()
    
    return len(all_events) > 0


async def main():
    """Run the test."""
    try:
        success = await test_event_persistence()
        
        if success:
            print("\n✅ Test PASSED - Event persistence is functional!")
            return True
        else:
            print("\n❌ Test FAILED - No events were persisted")
            return False
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)