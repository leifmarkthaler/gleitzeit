#!/usr/bin/env python3
"""Test event persistence through the API after running a workflow."""

import asyncio
import aiohttp
import json
import time

async def test_event_persistence_api():
    """Test that events are persisted when running through API."""
    
    print("=" * 60)
    print("Testing Event Persistence via API")
    print("=" * 60)
    
    # First, let's check the workflow status
    workflow_id = "41d44cf5-0c3a-42c9-9fff-0f4bbb8ccd07"  # From previous run
    
    async with aiohttp.ClientSession() as session:
        # Check workflow status
        print(f"\n1. Checking workflow status...")
        async with session.get(f"http://localhost:8000/workflows/{workflow_id}") as resp:
            if resp.status == 200:
                workflow = await resp.json()
                print(f"   Workflow status: {workflow.get('status', 'unknown')}")
            else:
                print(f"   Failed to get workflow: {resp.status}")
        
        # Try to get events through API (if endpoint exists)
        print(f"\n2. Attempting to retrieve events...")
        
        # Try different possible endpoints
        endpoints = [
            f"/events?workflow_id={workflow_id}",
            f"/workflows/{workflow_id}/events",
            "/events"
        ]
        
        for endpoint in endpoints:
            print(f"\n   Trying endpoint: {endpoint}")
            try:
                async with session.get(f"http://localhost:8000{endpoint}") as resp:
                    if resp.status == 200:
                        events = await resp.json()
                        print(f"   ✓ Found events endpoint!")
                        print(f"   Total events: {len(events) if isinstance(events, list) else 'N/A'}")
                        
                        if isinstance(events, list) and events:
                            print("\n   Sample events:")
                            for event in events[:5]:
                                print(f"     - {event.get('event_type', 'unknown')}: {event.get('timestamp', 'no timestamp')}")
                        break
                    elif resp.status == 404:
                        print(f"   ✗ Endpoint not found")
                    else:
                        print(f"   ✗ Error: {resp.status}")
            except Exception as e:
                print(f"   ✗ Error: {e}")

async def run_new_workflow_and_check_events():
    """Run a new workflow and check its events."""
    
    print("\n" + "=" * 60)
    print("Running New Workflow with Event Persistence")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        # Load the workflow file
        with open("examples/workflows/simple_echo_v4.yaml", "r") as f:
            import yaml
            workflow_dict = yaml.safe_load(f)
        
        # Submit workflow
        print("\n1. Submitting workflow...")
        async with session.post(
            "http://localhost:8000/workflows",
            json=workflow_dict
        ) as resp:
            if resp.status in [200, 201]:
                result = await resp.json()
                workflow_id = result.get("workflow_id")
                print(f"   ✓ Workflow submitted: {workflow_id}")
            else:
                print(f"   ✗ Failed to submit: {resp.status}")
                return
        
        # Wait for completion
        print("\n2. Waiting for workflow to complete...")
        await asyncio.sleep(3)
        
        # Check workflow status
        async with session.get(f"http://localhost:8000/workflows/{workflow_id}") as resp:
            if resp.status == 200:
                workflow = await resp.json()
                print(f"   Status: {workflow.get('status', 'unknown')}")
                
                # Check tasks
                tasks = workflow.get('tasks', [])
                if tasks:
                    print(f"   Tasks: {len(tasks)}")
                    for task in tasks:
                        print(f"     - {task.get('id')}: {task.get('status')}")

async def check_client_events_directly():
    """Check events directly through the client."""
    
    print("\n" + "=" * 60)
    print("Checking Events Directly via Client")
    print("=" * 60)
    
    from gleitzeit.client.base import ModularGleitzeitClient
    
    # Use same config as in ~/.gleitzeit/config.yaml
    config = {
        'persist_events': True,
        'persistence_type': 'memory',
        'max_concurrent_tasks': 5
    }
    
    async with ModularGleitzeitClient(mode='native', **config) as client:
        print("\n1. Client initialized")
        
        # Try to get events
        print("\n2. Retrieving all events...")
        events = await client.get_events(limit=20)
        print(f"   Total events found: {len(events)}")
        
        if events:
            print("\n   Event types:")
            event_types = {}
            for event in events:
                event_type = event.get('event_type', 'unknown')
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            for event_type, count in sorted(event_types.items()):
                print(f"     - {event_type}: {count}")
            
            print("\n   Recent events (last 5):")
            for event in events[-5:]:
                print(f"     - {event.get('event_type')}: {event.get('timestamp')}")
                if event.get('workflow_id'):
                    print(f"       Workflow: {event.get('workflow_id')}")
                if event.get('task_id'):
                    print(f"       Task: {event.get('task_id')}")

async def main():
    """Run all tests."""
    
    # Check API endpoints
    await test_event_persistence_api()
    
    # Run a new workflow
    await run_new_workflow_and_check_events()
    
    # Check events directly
    await check_client_events_directly()
    
    print("\n" + "=" * 60)
    print("Event Persistence Testing Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())