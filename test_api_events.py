#!/usr/bin/env python3
"""Test event persistence via API."""

import asyncio
import aiohttp
import json

async def test_api_events():
    """Test events via API."""
    
    print("\n" + "="*60)
    print("API EVENT PERSISTENCE TEST")
    print("="*60)
    
    async with aiohttp.ClientSession() as session:
        # Submit a simple workflow
        workflow = {
            "name": "Test Event Workflow",
            "tasks": [
                {
                    "id": "task1",
                    "name": "Simple Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "print('Hello from task1'); return 42"
                    }
                }
            ]
        }
        
        print("\nSubmitting workflow via API...")
        async with session.post(
            "http://localhost:8000/workflows",
            json=workflow
        ) as resp:
            result = await resp.json()
            workflow_id = result.get("workflow_id")
            print(f"✓ Workflow submitted: {workflow_id}")
        
        # Wait a bit for processing
        await asyncio.sleep(2)
        
        # Check workflow status
        print("\nChecking workflow status...")
        async with session.get(f"http://localhost:8000/workflows/{workflow_id}") as resp:
            status = await resp.json()
            print(f"Status: {status.get('status')}")
            print(f"Tasks: {status.get('tasks_completed')}/{status.get('tasks_total')}")
        
        # Check for events
        print("\n" + "="*60)
        print("CHECKING EVENTS")
        print("="*60)
        
        # Get all events
        print("\nGetting all events...")
        async with session.get("http://localhost:8000/events") as resp:
            events = await resp.json()
            print(f"Total events: {len(events)}")
            
            if events:
                print("\nFirst 3 events:")
                for i, event in enumerate(events[:3]):
                    print(f"  {i+1}. Type: {event.get('event_type')}")
        
        # Get workflow events
        print(f"\nGetting events for workflow {workflow_id}...")
        async with session.get(f"http://localhost:8000/workflows/{workflow_id}/events") as resp:
            workflow_events = await resp.json()
            print(f"Workflow events: {len(workflow_events)}")
        
        if len(events) > 0:
            print("\n✅ Events ARE being persisted via API!")
        else:
            print("\n⚠️  No events found via API")
            print("\nPossible reasons:")
            print("1. Event persistence might not be enabled in the API server")
            print("2. The API endpoints might not be connected to the event store")
            print("3. Events might be in a different persistence backend")

if __name__ == "__main__":
    asyncio.run(test_api_events())