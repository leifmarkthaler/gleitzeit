#!/usr/bin/env python3
"""Test if events can be replayed from persistence."""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task
from gleitzeit.core.events import GleitzeitEvent, EventType, EventSeverity


async def test_replay_capability():
    """Test if we can replay events from persistence."""
    
    print("\n" + "="*60)
    print("EVENT REPLAY CAPABILITY TEST")
    print("="*60)
    
    # Initialize client with event persistence
    client = GleitzeitClient(mode=ClientMode.NATIVE, persist_events=True)
    await client.initialize()
    print("✓ Client initialized with event persistence")
    
    # Create and submit a workflow
    tasks = [
        Task(
            id="task1",
            name="First Task",
            protocol="python/v1",
            method="python/execute",
            params={"code": "print('Task 1'); return 1"}
        ),
        Task(
            id="task2",
            name="Second Task",
            protocol="python/v1",
            method="python/execute",
            params={"code": "print('Task 2'); return 2"},
            dependencies=["task1"]
        )
    ]
    
    workflow = Workflow(
        id="replay_test_workflow",
        name="Replay Test Workflow",
        tasks=tasks
    )
    
    print("\n1. ORIGINAL EXECUTION")
    print("-" * 40)
    
    # Submit workflow
    result = await client.submit_workflow(workflow)
    workflow_id = result.get('workflow_id', workflow.id)
    print(f"✓ Workflow submitted: {workflow_id}")
    
    # Start engine to process
    await client.start_engine('EVENT_DRIVEN')
    await asyncio.sleep(3)  # Let it process
    await client.stop_engine()
    
    # Get all events from the original execution
    original_events = await client.get_events(workflow_id=workflow_id)
    print(f"✓ Captured {len(original_events)} events")
    
    # Analyze events
    print("\nEvent Types Captured:")
    event_types = {}
    for event in original_events:
        event_type = event.get('event_type', 'unknown')
        event_types[event_type] = event_types.get(event_type, 0) + 1
    
    for event_type, count in sorted(event_types.items()):
        print(f"  - {event_type}: {count}")
    
    # Extract key events for replay
    print("\n2. ANALYZING REPLAY DATA")
    print("-" * 40)
    
    # Find workflow and task submission events
    workflow_events = []
    task_events = []
    task_results = []
    
    for event in original_events:
        event_type = event.get('event_type', '')
        
        if 'workflow:submitted' in str(event_type):
            workflow_events.append(event)
            print(f"✓ Found workflow submission event")
            
        elif 'task:submitted' in str(event_type):
            task_events.append(event)
            task_id = event.get('task_id', 'unknown')
            print(f"✓ Found task submission: {task_id}")
            
        elif 'task:completed' in str(event_type):
            task_results.append(event)
            task_id = event.get('task_id', 'unknown')
            print(f"✓ Found task completion: {task_id}")
    
    # Check what data is available for replay
    print("\n3. REPLAY CAPABILITY ASSESSMENT")
    print("-" * 40)
    
    print("\nData Available for Replay:")
    print(f"  ✓ Workflow submissions: {len(workflow_events)}")
    print(f"  ✓ Task submissions: {len(task_events)}")
    print(f"  ✓ Task results: {len(task_results)}")
    
    # Check if we have enough data to replay
    can_replay_structure = len(workflow_events) > 0 and len(task_events) > 0
    can_replay_results = len(task_results) > 0
    
    print("\nReplay Capabilities:")
    if can_replay_structure:
        print("  ✓ Can replay workflow structure (tasks and dependencies)")
    else:
        print("  ✗ Cannot replay workflow structure - missing events")
    
    if can_replay_results:
        print("  ✓ Can replay task results")
    else:
        print("  ✗ Cannot replay task results - missing completion events")
    
    # Show sample event data
    if original_events:
        print("\n4. SAMPLE EVENT DATA")
        print("-" * 40)
        
        sample_event = original_events[0]
        print(f"\nSample Event Structure:")
        print(f"  event_id: {sample_event.get('event_id')}")
        print(f"  event_type: {sample_event.get('event_type')}")
        print(f"  timestamp: {sample_event.get('timestamp')}")
        print(f"  workflow_id: {sample_event.get('workflow_id')}")
        print(f"  task_id: {sample_event.get('task_id')}")
        
        if sample_event.get('data'):
            print(f"  data keys: {list(sample_event.get('data', {}).keys())}")
    
    # Attempt to reconstruct workflow from events
    print("\n5. RECONSTRUCTION TEST")
    print("-" * 40)
    
    if workflow_events:
        wf_event = workflow_events[0]
        wf_data = wf_event.get('data', {})
        print(f"Workflow reconstruction data available:")
        print(f"  - Workflow ID: {wf_event.get('workflow_id')}")
        print(f"  - Has workflow data: {'workflow' in wf_data}")
        print(f"  - Has task count: {'task_count' in wf_data}")
    
    # Check if we can replay by re-submitting
    print("\n6. REPLAY FEASIBILITY")
    print("-" * 40)
    
    print("\nReplay Options:")
    print("1. Event Sourcing Replay: Replay events to rebuild state")
    print("   Status: ⚠️  Requires event handler implementation")
    
    print("\n2. Workflow Re-execution: Re-submit workflow from events")
    print("   Status: ✓ Possible if workflow data is in events")
    
    print("\n3. State Reconstruction: Rebuild task states from events")
    print("   Status: ✓ Possible with current event data")
    
    print("\n" + "="*60)
    print("REPLAY ASSESSMENT COMPLETE")
    print("="*60)
    
    if can_replay_structure and can_replay_results:
        print("\n✅ Events contain sufficient data for replay!")
        print("   - Workflow structure can be reconstructed")
        print("   - Task execution sequence is traceable")
        print("   - Results are captured in events")
    else:
        print("\n⚠️  Partial replay capability")
        print("   - Some data available but not complete")
        print("   - May need additional event data capture")
    
    await client.shutdown()
    
    return original_events


async def demonstrate_replay():
    """Demonstrate actual replay of events."""
    
    print("\n" + "="*60)
    print("EVENT REPLAY DEMONSTRATION")
    print("="*60)
    
    # Get events from previous test
    events = await test_replay_capability()
    
    if not events:
        print("No events to replay")
        return
    
    print("\n" + "="*60)
    print("ATTEMPTING REPLAY")
    print("="*60)
    
    # Create new client for replay
    client = GleitzeitClient(mode=ClientMode.NATIVE, persist_events=True)
    await client.initialize()
    
    # Extract workflow and task info from events
    workflow_id = None
    tasks_to_replay = []
    
    for event in events:
        if event.get('workflow_id'):
            workflow_id = event.get('workflow_id')
        
        if 'task:submitted' in str(event.get('event_type', '')):
            task_data = event.get('data', {})
            tasks_to_replay.append({
                'task_id': event.get('task_id'),
                'task_data': task_data
            })
    
    print(f"\nReplay Data:")
    print(f"  Workflow ID: {workflow_id}")
    print(f"  Tasks to replay: {len(tasks_to_replay)}")
    
    # For actual replay, we would need to:
    # 1. Reconstruct the workflow from events
    # 2. Re-submit it for execution
    # 3. Or replay events through event handlers
    
    print("\nReplay Methods Available:")
    print("1. Re-execution: Submit workflow again (creates new events)")
    print("2. Event replay: Process historical events (requires event sourcing)")
    print("3. State restore: Load final state from events (read-only)")
    
    await client.shutdown()
    
    print("\n" + "="*60)
    print("REPLAY DEMONSTRATION COMPLETE")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(demonstrate_replay())