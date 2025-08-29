#!/usr/bin/env python3
"""Test server with event persistence."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_server():
    """Start server and test events."""
    from gleitzeit.api.main import app, app_state
    import uvicorn
    
    print("\nSTARTING SERVER WITH EVENT PERSISTENCE")
    print("="*60)
    
    # Start server in background
    config = uvicorn.Config(app=app, host="localhost", port=8000, log_level="info")
    server = uvicorn.Server(config)
    
    # Run server in background task
    server_task = asyncio.create_task(server.serve())
    
    # Wait for server to start
    await asyncio.sleep(2)
    
    print("\nTesting event persistence...")
    
    # Now test via HTTP
    import aiohttp
    async with aiohttp.ClientSession() as session:
        # Submit a workflow
        workflow = {
            "name": "Test Workflow",
            "tasks": [
                {
                    "id": "test_task",
                    "name": "Test Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "return 'test'"}
                }
            ]
        }
        
        async with session.post("http://localhost:8000/workflows", json=workflow) as resp:
            result = await resp.json()
            workflow_id = result.get("workflow_id")
            print(f"✓ Workflow submitted: {workflow_id}")
        
        await asyncio.sleep(1)
        
        # Check events
        async with session.get("http://localhost:8000/events") as resp:
            events = await resp.json()
            print(f"✓ Total events via API: {len(events)}")
            
            if events:
                print("\n✅ EVENT PERSISTENCE IS WORKING IN API SERVER!")
            else:
                print("\n⚠️  No events via API - checking client directly...")
                
                # Check the app_state client directly
                if app_state.client:
                    direct_events = await app_state.client.get_events()
                    print(f"Direct client.get_events(): {len(direct_events)} events")
                    
                    # Check adapter
                    if hasattr(app_state.client._adapter, 'event_bus'):
                        eb = app_state.client._adapter.event_bus
                        print(f"EventBus: {eb}")
                        print(f"EventStore: {getattr(eb, 'event_store', None)}")
    
    # Cancel server
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(test_server())