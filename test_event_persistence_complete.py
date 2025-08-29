#!/usr/bin/env python3
"""
Complete test for event persistence following proper Gleitzeit architecture.

Architecture:
- AUTO mode: Check for API server, use it if available
- API mode: Server manages ExecutionEngine
- NATIVE mode: Client manages ExecutionEngine
"""

import asyncio
import yaml
from pathlib import Path
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task, Priority

async def test_with_auto_mode():
    """Test with AUTO mode - uses API if available, native otherwise."""
    
    print("=" * 60)
    print("Testing Event Persistence with AUTO Mode")
    print("=" * 60)
    
    # AUTO mode with event persistence
    config = {
        'persist_events': True,
        'persistence_type': 'memory',
        'max_concurrent_tasks': 5
    }
    
    print("\n1. Initializing client in AUTO mode...")
    print("   This will check for running API server first")
    
    # AUTO mode is default
    client = GleitzeitClient(**config)
    
    try:
        await client.initialize()
        print(f"   ✓ Client initialized in {client.get_mode()} mode")
        
        if client.get_mode() == "api":
            print("   → Using existing API server")
            print("   → Server manages ExecutionEngine")
        else:
            print("   → Using native mode")
            print("   → Client will manage ExecutionEngine")
            # In native mode, we need to start the engine
            await client.start_engine()
            print("   ✓ ExecutionEngine started")
        
        # Load and submit workflow
        print("\n2. Loading test workflow...")
        workflow_file = Path("examples/workflows/simple_echo_v4.yaml")
        
        if workflow_file.exists():
            result = await client.run_workflow(str(workflow_file))
            workflow_id = result.get('workflow_id')
            print(f"   ✓ Workflow submitted: {workflow_id}")
            
            # Wait for execution
            print("\n3. Waiting for workflow execution...")
            await asyncio.sleep(3)
            
            # Get events
            print("\n4. Retrieving events...")
            events = await client.get_events(workflow_id=workflow_id)
            print(f"   Found {len(events)} events")
            
            if events:
                print("\n   Event types:")
                event_types = {}
                for event in events:
                    et = event.get('event_type', 'unknown')
                    event_types[et] = event_types.get(et, 0) + 1
                
                for et, count in sorted(event_types.items()):
                    print(f"     - {et}: {count}")
        else:
            print(f"   ✗ Workflow file not found: {workflow_file}")
        
    finally:
        print("\n5. Shutting down...")
        if client.get_mode() == "native":
            await client.stop_engine()
            print("   ✓ Engine stopped")
        await client.shutdown()
        print("   ✓ Client shutdown complete")


async def test_native_mode_explicitly():
    """Test with explicit NATIVE mode - client manages everything."""
    
    print("\n" + "=" * 60)
    print("Testing Event Persistence with NATIVE Mode")
    print("=" * 60)
    
    config = {
        'persist_events': True,
        'persistence_type': 'memory'
    }
    
    print("\n1. Forcing NATIVE mode (no API server)...")
    client = GleitzeitClient(mode=ClientMode.NATIVE, **config)
    
    try:
        await client.initialize()
        print("   ✓ Client initialized in NATIVE mode")
        
        # Check event persistence setup
        if hasattr(client._adapter, 'event_bus'):
            if hasattr(client._adapter.event_bus, 'event_store'):
                if client._adapter.event_bus.event_store:
                    print("   ✓ EventStore configured")
        
        # Must start engine in native mode
        print("\n2. Starting ExecutionEngine...")
        await client.start_engine('EVENT_DRIVEN')
        print("   ✓ Engine started in EVENT_DRIVEN mode")
        
        # Create a simple workflow
        print("\n3. Creating test workflow...")
        workflow = Workflow(
            id="test_native_workflow",
            name="Native Mode Test",
            description="Testing event persistence in native mode",
            tasks=[
                Task(
                    id="task1",
                    name="First Task",
                    workflow_id="test_native_workflow",
                    protocol="echo/v1",
                    method="echo",
                    params={"message": "Hello from native mode"},
                    priority=Priority.NORMAL
                ),
                Task(
                    id="task2",
                    name="Second Task",
                    workflow_id="test_native_workflow",
                    protocol="echo/v1",
                    method="echo",
                    params={"message": "Task 2 running"},
                    dependencies=["task1"],
                    priority=Priority.NORMAL
                )
            ]
        )
        
        print("\n4. Submitting workflow...")
        result = await client.submit_workflow(workflow)
        print(f"   ✓ Workflow submitted: {result}")
        
        # Wait for execution
        print("\n5. Processing tasks...")
        await asyncio.sleep(2)
        
        # Check events
        print("\n6. Checking persisted events...")
        all_events = await client.get_events()
        workflow_events = await client.get_events(workflow_id="test_native_workflow")
        
        print(f"   Total events: {len(all_events)}")
        print(f"   Workflow events: {len(workflow_events)}")
        
        if workflow_events:
            print("\n   Workflow event timeline:")
            for event in workflow_events[:5]:
                print(f"     {event.get('timestamp', 'N/A')}: {event.get('event_type', 'unknown')}")
        
        # Verify persistence worked
        if len(workflow_events) > 0:
            print("\n✓ Event persistence working in NATIVE mode!")
        else:
            print("\n✗ No events persisted - check configuration")
        
    finally:
        print("\n7. Cleanup...")
        await client.stop_engine()
        await client.shutdown()
        print("   ✓ Complete")


async def test_api_mode_explicitly():
    """Test with explicit API mode - server manages everything."""
    
    print("\n" + "=" * 60)
    print("Testing Event Persistence with API Mode")
    print("=" * 60)
    
    config = {
        'persist_events': True,
        'persistence_type': 'memory'
    }
    
    print("\n1. Using API mode (requires running server)...")
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_host="localhost",
        api_port=8000,
        auto_start_server=True,  # Will start server if not running
        **config
    )
    
    try:
        await client.initialize()
        print("   ✓ Client initialized in API mode")
        print("   → Server manages ExecutionEngine")
        print("   → No need to start engine from client")
        
        # Create and submit workflow
        print("\n2. Creating test workflow...")
        workflow = Workflow(
            id="test_api_workflow",
            name="API Mode Test",
            description="Testing event persistence via API",
            tasks=[
                Task(
                    id="api_task1",
                    name="API Task",
                    workflow_id="test_api_workflow",
                    protocol="echo/v1",
                    method="echo",
                    params={"message": "Hello from API mode"},
                    priority=Priority.NORMAL
                )
            ]
        )
        
        print("\n3. Submitting via API...")
        result = await client.submit_workflow(workflow)
        print(f"   ✓ Submitted: {result}")
        
        # Wait and check events
        await asyncio.sleep(2)
        
        print("\n4. Retrieving events via API...")
        events = await client.get_events(workflow_id="test_api_workflow")
        print(f"   Found {len(events)} events")
        
        if events:
            print("   ✓ Events persisted and retrieved via API")
        else:
            print("   ℹ️  No events - server may not have event persistence enabled")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")
        print("   Note: API mode requires server with event persistence enabled")
    finally:
        print("\n5. Cleanup...")
        await client.shutdown()
        print("   ✓ Complete")


async def main():
    """Run all test scenarios."""
    
    print("GLEITZEIT EVENT PERSISTENCE TEST SUITE")
    print("=" * 60)
    print("\nThis test covers all client modes:")
    print("- AUTO: Detect and use best mode")
    print("- NATIVE: Direct execution, client manages engine")
    print("- API: Server execution, server manages engine")
    print("")
    
    # Test AUTO mode (most common usage)
    await test_with_auto_mode()
    
    # Test explicit NATIVE mode
    await test_native_mode_explicitly()
    
    # Test explicit API mode
    # await test_api_mode_explicitly()  # Uncomment if API server is configured
    
    print("\n" + "=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())