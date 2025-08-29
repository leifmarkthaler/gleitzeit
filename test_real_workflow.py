#!/usr/bin/env python3
"""Test event persistence with a real workflow execution."""

import asyncio
import yaml
from pathlib import Path
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.execution_engine import ExecutionMode

async def test_workflow_with_events():
    """Test event persistence during actual workflow execution."""
    
    print("=" * 60)
    print("Event Persistence with Workflow Execution")
    print("=" * 60)
    
    config = {
        'persistence_type': 'memory',
        'persist_events': True,
        'max_concurrent_tasks': 5
    }
    
    print("\n1. Initializing client...")
    client = GleitzeitClient(mode='native', **config)
    
    try:
        await client.initialize()
        print("   ✓ Client initialized")
        
        # Start the execution engine in background
        print("\n2. Starting execution engine...")
        await client.start_engine('EVENT_DRIVEN')
        print("   ✓ Execution engine started in background")
        
        # Load workflow
        print("\n3. Loading workflow...")
        workflow_file = Path("examples/workflows/simple_echo_v4.yaml")
        with open(workflow_file) as f:
            workflow_dict = yaml.safe_load(f)
        
        # Convert to Workflow object
        from gleitzeit.core.models import Workflow, Task, Priority
        
        # Create workflow with tasks
        workflow = Workflow(
            id=f"test_workflow_{asyncio.get_event_loop().time()}",
            name=workflow_dict['name'],
            description=workflow_dict.get('description', ''),
            tasks=[]
        )
        
        # Add tasks
        for task_dict in workflow_dict['tasks']:
            # Convert priority string to enum
            priority_str = task_dict.get('priority', 'normal')
            priority = Priority[priority_str.upper()] if priority_str else Priority.NORMAL
            
            task = Task(
                id=task_dict['id'],
                name=task_dict['name'],
                workflow_id=workflow.id,
                protocol=task_dict.get('protocol', 'echo/v1'),
                method=task_dict.get('method', 'echo'),
                params=task_dict.get('params', {}),
                dependencies=task_dict.get('dependencies', []),
                priority=priority
            )
            # Debug: Check priority type
            print(f"      Task {task.id}: priority={task.priority}, type={type(task.priority)}")
            workflow.tasks.append(task)
        
        print(f"   ✓ Loaded workflow: {workflow.name}")
        print(f"   Tasks: {len(workflow.tasks)}")
        
        # Submit workflow
        print("\n4. Submitting workflow...")
        result = await client._adapter.submit_workflow(workflow)
        workflow_id = result.get('workflow_id', workflow.id)
        print(f"   ✓ Workflow submitted: {workflow_id}")
        
        # Wait for execution
        print("\n5. Waiting for workflow execution...")
        await asyncio.sleep(3)
        
        # Get workflow status
        workflow_status = await client._adapter.get_workflow(workflow_id)
        if workflow_status:
            print(f"   Workflow status: {workflow_status.status}")
        
        # Get events
        print("\n6. Retrieving persisted events...")
        
        # All events
        all_events = await client.get_events(limit=100)
        print(f"   Total events: {len(all_events)}")
        
        # Workflow events
        workflow_events = await client.get_events(workflow_id=workflow_id)
        print(f"   Workflow events: {len(workflow_events)}")
        
        # Event types
        if all_events:
            event_types = {}
            for event in all_events:
                et = event.get('event_type', 'unknown')
                event_types[et] = event_types.get(et, 0) + 1
            
            print("\n7. Event type breakdown:")
            for et, count in sorted(event_types.items()):
                print(f"   - {et}: {count}")
        
        # Show some workflow events
        if workflow_events:
            print("\n8. Sample workflow events:")
            for event in workflow_events[:5]:
                print(f"   {event.get('timestamp')}: {event.get('event_type')}")
                if event.get('task_id'):
                    print(f"      Task: {event.get('task_id')}")
        
        # Check success
        if len(workflow_events) > 0:
            print("\n" + "=" * 60)
            print("✓ EVENT PERSISTENCE IS WORKING!")
            print(f"  Captured {len(workflow_events)} workflow events")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("✗ No workflow events captured")
            print("=" * 60)
        
        # Stop execution engine
        print("\n9. Stopping execution engine...")
        await client.stop_engine()
        print("   ✓ Engine stopped")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n10. Shutting down...")
        await client.shutdown()
        print("    ✓ Shutdown complete")

if __name__ == "__main__":
    asyncio.run(test_workflow_with_events())