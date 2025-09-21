#!/usr/bin/env python3
"""
Simple test to check if WebSocket endpoints are working.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_websocket():
    """Test WebSocket connection without authentication complexity."""
    
    # First, test if the regular API is working
    import aiohttp
    
    logger.info("Testing regular API first...")
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8003/workflows/") as resp:
            logger.info(f"Regular API status: {resp.status}")
            if resp.status == 200:
                logger.info("✓ Regular API working")
    
    # Now test WebSocket
    logger.info("\nTesting WebSocket connection...")
    
    try:
        import websockets
        
        # Try basic connection
        uri = "ws://localhost:8003/events/stream"
        logger.info(f"Connecting to {uri}")
        
        async with websockets.connect(uri) as websocket:
            logger.info("✓ WebSocket connected!")
            
            # Receive initial messages
            msg = await websocket.recv()
            logger.info(f"Received: {msg}")
            
            # Try to receive auth message if sent
            try:
                msg2 = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                logger.info(f"Received auth: {msg2}")
            except asyncio.TimeoutError:
                logger.info("No auth message (may be OK)")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ WebSocket error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run WebSocket test."""
    success = await test_websocket()
    if success:
        logger.info("\n✓ WebSocket is working!")
    else:
        logger.info("\n✗ WebSocket is NOT working")
        
        # Check if it's an import issue
        logger.info("\nChecking dependencies...")
        try:
            import websockets
            logger.info("✓ websockets library installed")
        except ImportError:
            logger.error("✗ websockets library not installed - run: pip install websockets")

if __name__ == "__main__":
    asyncio.run(main())