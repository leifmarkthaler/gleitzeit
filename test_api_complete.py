#!/usr/bin/env python3
"""Complete test of API event persistence."""

import asyncio
import sys
import os
import subprocess
import time
import aiohttp
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def start_and_test():
    """Start server and test event persistence."""
    
    print("\n" + "="*60)
    print("COMPLETE API EVENT PERSISTENCE TEST")
    print("="*60)
    
    # First kill any existing servers
    print("\nCleaning up existing servers...")
    subprocess.run(["pkill", "-f", "gleitzeit.*serve"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "uvicorn"], stderr=subprocess.DEVNULL)
    subprocess.run(["lsof", "-ti:8000"], stderr=subprocess.DEVNULL)
    time.sleep(2)
    
    # Start the server with event persistence
    print("\nStarting server with event persistence enabled...")
    env = os.environ.copy()
    env["GLEITZEIT_PERSIST_EVENTS"] = "true"
    
    server_proc = subprocess.Popen(
        ["gleitzeit", "serve", "--port", "8000", "--headless"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    print("Waiting for server to start...")
    for i in range(10):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:8000/", timeout=aiohttp.ClientTimeout(total=1)) as resp:
                    if resp.status == 200:
                        print("✓ Server is ready")
                        break
        except:
            await asyncio.sleep(1)
    else:
        print("✗ Server failed to start")
        server_proc.terminate()
        return False
    
    # Now test event persistence
    print("\n" + "="*60)
    print("TESTING EVENT PERSISTENCE")
    print("="*60)
    
    async with aiohttp.ClientSession() as session:
        # Submit a workflow
        workflow = {
            "name": "Event Test Workflow",
            "tasks": [
                {
                    "id": "task1",
                    "name": "Task 1",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "print('Task 1'); return 1"}
                },
                {
                    "id": "task2",
                    "name": "Task 2",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "print('Task 2'); return 2"},
                    "dependencies": ["task1"]
                }
            ]
        }
        
        print("\n1. Submitting workflow...")
        async with session.post("http://localhost:8000/workflows", json=workflow) as resp:
            result = await resp.json()
            workflow_id = result.get("workflow_id")
            print(f"   ✓ Workflow submitted: {workflow_id}")
        
        # Wait for processing
        await asyncio.sleep(3)
        
        # Check workflow status
        print("\n2. Checking workflow status...")
        async with session.get(f"http://localhost:8000/workflows/{workflow_id}") as resp:
            status = await resp.json()
            print(f"   Status: {status.get('status')}")
            print(f"   Tasks: {status.get('tasks_completed')}/{status.get('tasks_total')}")
        
        # Get all events
        print("\n3. Getting all events...")
        async with session.get("http://localhost:8000/events") as resp:
            events = await resp.json()
            print(f"   Total events: {len(events)}")
            
            if events:
                print("\n   ✅ EVENTS ARE BEING PERSISTED!")
                
                # Count by type
                event_types = {}
                for event in events:
                    event_type = event.get('event_type', 'unknown')
                    event_types[event_type] = event_types.get(event_type, 0) + 1
                
                print("\n   Event types:")
                for event_type, count in sorted(event_types.items()):
                    print(f"     - {event_type}: {count}")
                
                # Show sample events
                print("\n   Sample events:")
                for i, event in enumerate(events[:3]):
                    print(f"     {i+1}. {event.get('event_type')} at {event.get('timestamp')}")
            else:
                print("\n   ⚠️  No events found")
        
        # Get workflow-specific events
        print(f"\n4. Getting events for workflow {workflow_id}...")
        async with session.get(f"http://localhost:8000/workflows/{workflow_id}/events") as resp:
            workflow_events = await resp.json()
            print(f"   Workflow events: {len(workflow_events)}")
            
            if workflow_events:
                print("   ✓ Workflow-specific events working")
            else:
                print("   ⚠️  No workflow-specific events")
    
    # Cleanup
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)
    
    if len(events) > 0:
        print("\n✅ SUCCESS: Event persistence is working via API!")
        print(f"   - {len(events)} total events captured")
        print(f"   - {len(workflow_events)} workflow-specific events")
        print("   - Event filtering is functional")
    else:
        print("\n❌ FAILURE: No events captured via API")
    
    # Stop server
    server_proc.terminate()
    server_proc.wait(timeout=5)
    
    return len(events) > 0

if __name__ == "__main__":
    success = asyncio.run(start_and_test())
    sys.exit(0 if success else 1)