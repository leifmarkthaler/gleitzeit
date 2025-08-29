#!/usr/bin/env python3
"""Integration test for event persistence with real Gleitzeit components."""

import asyncio
import yaml
from pathlib import Path
from gleitzeit.client import GleitzeitClient

async def test_full_integration():
    """Test event persistence with a real workflow."""
    
    print("=" * 60)
    print("Event Persistence Integration Test")
    print("=" * 60)
    
    # Configuration with event persistence
    config = {
        'persistence_type': 'memory',  # Use in-memory for testing
        'persist_events': True,
        'max_concurrent_tasks': 5,
        'event_retention_days': 30
    }
    
    print("\n1. Initializing Gleitzeit client...")
    print(f"   Config: {config}")
    
    client = GleitzeitClient(mode='native', **config)
    
    try:
        await client.initialize()
        print("   ✓ Client initialized successfully")
        
        # Verify components are set up
        if hasattr(client._adapter, 'event_bus'):
            print("   ✓ EventBus configured")
            if hasattr(client._adapter.event_bus, 'event_store'):
                if client._adapter.event_bus.event_store:
                    print("   ✓ EventStore attached to EventBus")
                else:
                    print("   ✗ EventStore NOT attached to EventBus")
            else:
                print("   ✗ EventBus has no event_store attribute")
        else:
            print("   ✗ Adapter has no event_bus")
            
        if hasattr(client._adapter, 'execution_engine'):
            if client._adapter.execution_engine:
                print("   ✓ ExecutionEngine configured")
                if hasattr(client._adapter.execution_engine, 'event_bus'):
                    if client._adapter.execution_engine.event_bus:
                        print("   ✓ ExecutionEngine has EventBus")
                        # Check if it's the same EventBus instance
                        if client._adapter.execution_engine.event_bus is client._adapter.event_bus:
                            print("   ✓ ExecutionEngine using shared EventBus")
                        else:
                            print("   ✗ ExecutionEngine using different EventBus!")
                    else:
                        print("   ✗ ExecutionEngine has no EventBus")
            else:
                print("   ✗ ExecutionEngine not initialized")
        
        # Load a simple workflow
        print("\n2. Loading test workflow...")
        workflow_file = Path("examples/workflows/simple_echo_v4.yaml")
        if not workflow_file.exists():
            print(f"   ✗ Workflow file not found: {workflow_file}")
            return
            
        with open(workflow_file) as f:
            workflow_dict = yaml.safe_load(f)
        print(f"   ✓ Loaded workflow: {workflow_dict['name']}")
        print(f"   Tasks: {len(workflow_dict['tasks'])}")
        
        # Submit the workflow
        print("\n3. Submitting workflow...")
        # The client expects a file path or workflow dict
        workflow_result = await client.run_workflow(str(workflow_file))
        workflow_id = workflow_result.get('workflow_id')
        print(f"   ✓ Workflow submitted: {workflow_id}")
        
        # Wait for workflow to process
        print("\n4. Waiting for workflow execution...")
        await asyncio.sleep(3)
        
        # Check workflow status
        workflow = await client.get_workflow(workflow_id)
        if workflow:
            print(f"   Workflow status: {workflow.status}")
            
        # Retrieve events
        print("\n5. Retrieving persisted events...")
        
        # Get all events
        all_events = await client.get_events(limit=100)
        print(f"   Total events: {len(all_events)}")
        
        # Get workflow-specific events
        workflow_events = await client.get_events(workflow_id=workflow_id)
        print(f"   Events for this workflow: {len(workflow_events)}")
        
        # Analyze event types
        if all_events:
            event_types = {}
            for event in all_events:
                event_type = event.get('event_type', 'unknown')
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            print("\n6. Event type breakdown:")
            for event_type, count in sorted(event_types.items()):
                print(f"   - {event_type}: {count}")
        
        # Show workflow events timeline
        if workflow_events:
            print("\n7. Workflow event timeline:")
            for event in workflow_events[:10]:  # First 10 events
                print(f"   {event.get('timestamp', 'no-time')}: {event.get('event_type', 'unknown')}")
                if event.get('task_id'):
                    print(f"      Task: {event.get('task_id')}")
        
        # Success check
        if len(workflow_events) > 0:
            print("\n" + "=" * 60)
            print("✓ EVENT PERSISTENCE IS WORKING!")
            print(f"  Successfully captured {len(workflow_events)} events")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("✗ No events were persisted!")
            print("=" * 60)
            
    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print("\n8. Shutting down client...")
        await client.shutdown()
        print("   ✓ Client shutdown complete")

if __name__ == "__main__":
    asyncio.run(test_full_integration())