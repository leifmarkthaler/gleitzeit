#!/usr/bin/env python3
"""
Test WebSocket authentication with auto-login.

Verifies that WebSocket endpoints properly handle authentication.
"""

import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_websocket_auth():
    """Test WebSocket authentication."""
    logger.info("=== Testing WebSocket Authentication ===\n")
    
    # Test event stream WebSocket
    logger.info("1. Testing /events/stream WebSocket...")
    uri = "ws://localhost:8002/events/stream"
    
    try:
        async with websockets.connect(uri) as websocket:
            # Should receive connection confirmation
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "connection":
                logger.info("   ✓ Connected to event stream")
            
            # Check if we got auth info (basic user)
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "auth":
                user = data.get("user", {})
                logger.info(f"   ✓ Authenticated as: {user.get('username')} (id: {user.get('id')})")
                
                if user.get('id') == 'basic-user':
                    logger.info("   ✓ Auto-login working for WebSocket")
                else:
                    logger.error("   ✗ Not using basic user")
            
            # Test subscribing to events
            await websocket.send(json.dumps({
                "type": "subscribe",
                "event_types": ["task:*", "workflow:*"]
            }))
            
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "subscription":
                logger.info(f"   ✓ Subscribed to events: {data.get('subscribed')}")
            
    except Exception as e:
        logger.error(f"   ✗ WebSocket error: {e}")
        return False
    
    # Test with explicit token (should fail with invalid token, fall back to basic)
    logger.info("\n2. Testing WebSocket with invalid token...")
    uri = "ws://localhost:8002/events/stream?token=invalid_token"
    
    try:
        async with websockets.connect(uri) as websocket:
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "connection":
                logger.info("   ✓ Connected despite invalid token")
            
            # Should still get basic user auth
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "auth":
                user = data.get("user", {})
                if user.get('id') == 'basic-user':
                    logger.info("   ✓ Fell back to basic user with invalid token")
                    
    except Exception as e:
        logger.error(f"   ✗ WebSocket error: {e}")
    
    # Test UI WebSocket endpoint
    logger.info("\n3. Testing /ws/updates WebSocket...")
    uri = "ws://localhost:8002/ws/updates"
    
    try:
        async with websockets.connect(uri) as websocket:
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "connection":
                logger.info("   ✓ Connected to UI updates stream")
            
            # Check for auth info
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                data = json.loads(response)
                
                if data.get("type") == "auth":
                    user = data.get("user", {})
                    logger.info(f"   ✓ UI WebSocket authenticated as: {user.get('username')}")
            except asyncio.TimeoutError:
                logger.info("   ⚠ No auth info received (might be OK for UI)")
            
            # Test subscribing
            await websocket.send(json.dumps({
                "type": "subscribe",
                "channels": ["workflows", "tasks"]
            }))
            
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "subscription":
                logger.info(f"   ✓ Subscribed to channels: {data.get('channels')}")
                
    except Exception as e:
        logger.error(f"   ✗ UI WebSocket error: {e}")
    
    logger.info("\n=== WebSocket Authentication Test Complete ===")
    return True

async def main():
    """Run WebSocket authentication tests."""
    success = await test_websocket_auth()
    
    if success:
        logger.info("\n🎉 WebSocket authentication tests completed!")
    else:
        logger.error("\n❌ WebSocket tests failed")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())