#!/usr/bin/env python3
"""Test WebSocket for receiving logs and events in real-time."""

import asyncio
import websockets
import json
import sys

async def test_api_websocket():
    """Test the main API WebSocket for events and logs."""
    uri = "ws://localhost:8000/events/stream?auto_subscribe=*"
    
    print("Connecting to API WebSocket for events...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to API WebSocket")
            
            # Receive initial connection message
            message = await websocket.recv()
            data = json.loads(message)
            print(f"Connection: {json.dumps(data, indent=2)}")
            
            # Subscribe to all events (including logs)
            subscribe_msg = {
                "type": "subscribe",
                "event_types": ["*"]  # Subscribe to everything
            }
            await websocket.send(json.dumps(subscribe_msg))
            
            # Listen for events
            print("\nListening for events (including logs)...")
            for i in range(10):  # Listen for 10 messages
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(message)
                    
                    if data.get("type") == "event":
                        event = data.get("event", {})
                        event_type = event.get("event_type", "unknown")
                        print(f"\nEvent received: {event_type}")
                        if "log" in event_type.lower():
                            print(f"LOG EVENT: {json.dumps(event, indent=2)}")
                        else:
                            print(f"Data: {event.get('data', {})}")
                    else:
                        print(f"Message: {data.get('type', 'unknown')}")
                        
                except asyncio.TimeoutError:
                    print(".", end="", flush=True)
                    # Send ping to keep connection alive
                    await websocket.send(json.dumps({"type": "ping"}))
                    
    except Exception as e:
        print(f"API WebSocket error: {e}")

async def test_ui_websocket():
    """Test the UI WebSocket for updates."""
    uri = "ws://localhost:8001/ws/updates"
    
    print("\n\nConnecting to UI WebSocket...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to UI WebSocket")
            
            # Receive initial messages
            for _ in range(2):  # Connection and auth messages
                message = await websocket.recv()
                data = json.loads(message)
                print(f"Initial: {json.dumps(data, indent=2)}")
            
            # Subscribe to channels
            subscribe_msg = {
                "type": "subscribe",
                "channels": ["workflows", "tasks", "metrics", "system", "logs"]
            }
            await websocket.send(json.dumps(subscribe_msg))
            
            # Listen for updates
            print("\nListening for UI updates...")
            for i in range(10):
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(message)
                    
                    msg_type = data.get("type", "unknown")
                    print(f"\nUI Update: {msg_type}")
                    
                    if "log" in msg_type.lower():
                        print(f"LOG UPDATE: {json.dumps(data, indent=2)}")
                    elif msg_type == "metrics_update":
                        print(f"Metrics: {data.get('data', {})}")
                    elif msg_type in ["workflow_update", "task_update"]:
                        print(f"Status: {data.get('data', {})}")
                        
                except asyncio.TimeoutError:
                    print(".", end="", flush=True)
                    # Send ping
                    await websocket.send(json.dumps({"type": "ping"}))
                    
    except Exception as e:
        print(f"UI WebSocket error: {e}")

async def submit_test_workflow():
    """Submit a test workflow to generate events."""
    import aiohttp
    
    print("\n\nSubmitting test workflow to generate events...")
    
    workflow = {
        "workflow": {
            "name": "test-websocket-logs",
            "tasks": [
                {
                    "name": "task1",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": """
import time
print("Starting task...")
for i in range(5):
    print(f"Progress: {i+1}/5")
    time.sleep(1)
print("Task complete!")
"""
                    }
                }
            ]
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post("http://localhost:8000/workflows/", json=workflow) as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"Workflow submitted: {result.get('workflow_id')}")
                return result.get('workflow_id')
            else:
                print(f"Failed to submit workflow: {resp.status}")
                return None

async def main():
    """Run all tests."""
    print("WebSocket Logging Test")
    print("=" * 50)
    
    # Submit a workflow to generate events
    workflow_id = await submit_test_workflow()
    
    # Give the workflow a moment to start
    await asyncio.sleep(2)
    
    # Test both WebSockets
    await test_api_websocket()
    await test_ui_websocket()
    
    print("\n" + "=" * 50)
    print("Test complete!")

if __name__ == "__main__":
    asyncio.run(main())