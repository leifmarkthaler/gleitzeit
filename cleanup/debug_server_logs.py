#!/usr/bin/env python3
"""
Debug server-side logs during connection attempts
"""

import asyncio
import logging
import socketio
from aiohttp import web

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def create_debug_server():
    """Create a simple server with detailed logging"""
    
    # Create Socket.IO server with logging enabled
    sio = socketio.AsyncServer(
        async_mode='aiohttp',
        cors_allowed_origins="*",
        logger=True,  # Enable Socket.IO logging
        engineio_logger=True  # Enable Engine.IO logging
    )
    
    app = web.Application()
    sio.attach(app)
    
    # Add handlers for both namespaces
    @sio.on('connect', namespace='/cluster')
    async def cluster_connect(sid, environ):
        print(f"✅ CLUSTER connect: {sid}")
        logger.info(f"Cluster client connected: {sid}")
    
    @sio.on('connect', namespace='/providers')
    async def providers_connect(sid, environ):
        print(f"✅ PROVIDERS connect: {sid}")
        logger.info(f"Providers client connected: {sid}")
    
    @sio.on('disconnect', namespace='/cluster')
    async def cluster_disconnect(sid):
        print(f"👋 CLUSTER disconnect: {sid}")
    
    @sio.on('disconnect', namespace='/providers')
    async def providers_disconnect(sid):
        print(f"👋 PROVIDERS disconnect: {sid}")
    
    # Add connection error handler
    @sio.on('connect_error')
    async def connect_error(sid, data):
        print(f"❌ Connection error: {data}")
        logger.error(f"Connection error for {sid}: {data}")
    
    print("🔧 Starting debug server...")
    print("   - /cluster namespace handler registered")
    print("   - /providers namespace handler registered")
    print("   - Full logging enabled")
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    
    print("🚀 Debug server running on http://0.0.0.0:8000")
    
    return runner, sio

async def test_connections(sio_server):
    """Test both namespace connections"""
    await asyncio.sleep(1)  # Let server start
    
    print("\n🧪 Testing namespace connections...")
    
    # Test /cluster namespace
    print("\n1. Testing /cluster namespace:")
    sio_cluster = socketio.AsyncClient(logger=True, engineio_logger=True)
    
    try:
        await sio_cluster.connect('http://localhost:8000', namespaces=['/cluster'])
        print("   ✅ /cluster connected successfully")
        await sio_cluster.disconnect()
    except Exception as e:
        print(f"   ❌ /cluster failed: {e}")
    
    # Test /providers namespace
    print("\n2. Testing /providers namespace:")
    sio_providers = socketio.AsyncClient(logger=True, engineio_logger=True)
    
    try:
        await sio_providers.connect('http://localhost:8000', namespaces=['/providers'])
        print("   ✅ /providers connected successfully")
        await sio_providers.disconnect()
    except Exception as e:
        print(f"   ❌ /providers failed: {e}")

async def main():
    print("🔍 Socket.IO Namespace Debug Tool")
    print("=" * 50)
    
    runner, sio_server = await create_debug_server()
    
    try:
        # Test connections
        await test_connections(sio_server)
        
        # Keep running briefly to see any additional logs
        print("\n⏳ Waiting for any additional logs...")
        await asyncio.sleep(2)
        
    finally:
        print("\n🧹 Shutting down debug server...")
        await runner.cleanup()
        print("👋 Debug session complete")

if __name__ == "__main__":
    asyncio.run(main())