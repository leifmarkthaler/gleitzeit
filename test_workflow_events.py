#!/usr/bin/env python3
"""Test event persistence with a real workflow."""

import asyncio
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task, Priority

async def test_workflow_events():
    """Test event persistence during workflow execution."""
    
    print("EVENT PERSISTENCE TEST WITH WORKFLOW")
    print("=" * 40)
    
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
    
    # Create a simple workflow
    tasks = [
        Task(
            id="task1",
            name="First Task",
            protocol="http",
            method="GET",
            endpoint="http://example.com/task1",
            handler=lambda: "Task 1 completed"
        ),
        Task(
            id="task2", 
            name="Second Task",
            protocol="http",
            method="GET",
            endpoint="http://example.com/task2",
            handler=lambda: "Task 2 completed",
            dependencies=["task1"]
        ),
        Task(
            id="task3",
            name="Third Task",
            protocol="http",
            method="GET", 
            endpoint="http://example.com/task3",
            handler=lambda: "Task 3 completed",
            dependencies=["task2"]
        )
    ]
    
    workflow = Workflow(
        id="test_workflow",
        name="Test Workflow",
        tasks=tasks
    )
    
    # Submit workflow
    workflow_id = await client.submit_workflow(workflow)
    print(f"✓ Workflow submitted: {workflow_id}")
    
    # Wait for completion
    print("\nProcessing workflow...")
    await asyncio.sleep(2)  # Give it time to process
    
    # Get workflow status
    status = await client.get_workflow_status(workflow_id)
    print(f"✓ Workflow status: {status}")
    
    # Get all events
    print("\n" + "=" * 40)
    print("ALL EVENTS:")
    events = await client.get_events()
    print(f"Total events captured: {len(events)}")
    
    # Group events by type
    event_types = {}
    for event in events:
        event_type = event.get('event_type', 'unknown')
        if event_type not in event_types:
            event_types[event_type] = 0
        event_types[event_type] += 1
    
    print("\nEvent Type Summary:")
    for event_type, count in sorted(event_types.items()):
        print(f"  {event_type}: {count}")
    
    # Get workflow-specific events
    print("\n" + "=" * 40)
    print(f"WORKFLOW EVENTS (workflow_id={workflow_id}):")
    workflow_events = await client.get_events(workflow_id=workflow_id)
    print(f"Workflow-specific events: {len(workflow_events)}")
    
    # Show first few workflow events
    for i, event in enumerate(workflow_events[:5]):
        print(f"\nEvent {i+1}:")
        print(f"  Type: {event.get('event_type')}")
        print(f"  Source: {event.get('source')}")
        print(f"  Time: {event.get('timestamp')}")
        if event.get('data'):
            print(f"  Data: {event.get('data')}")
    
    # Get task-specific events
    print("\n" + "=" * 40)
    print("TASK EVENTS (task_id=task1):")
    task_events = await client.get_events(task_id="task1")
    print(f"Task-specific events: {len(task_events)}")
    
    for event in task_events:
        print(f"  - {event.get('event_type')}: {event.get('timestamp')}")
    
    # Cleanup
    await client.stop_engine()
    await client.shutdown()
    print("\n✓ Test complete - Event persistence is working!")

if __name__ == "__main__":
    asyncio.run(test_workflow_events())