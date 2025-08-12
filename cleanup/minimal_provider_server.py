#!/usr/bin/env python3
"""
Minimal Socket.IO server to test /providers namespace

This tests if the issue is with our provider manager setup
"""

import asyncio
import socketio
from aiohttp import web

async def main():
    """Test minimal server with /providers namespace"""
    print("🧪 Starting minimal server with /providers namespace")
    
    # Create Socket.IO server
    sio = socketio.AsyncServer(
        async_mode='aiohttp',
        cors_allowed_origins="*"
    )
    
    # Create web app
    app = web.Application()
    sio.attach(app)
    
    # Setup a simple handler for /providers namespace
    @sio.on('connect', namespace='/providers')
    async def providers_connect(sid):
        print(f"✅ Client connected to /providers namespace: {sid}")
        await sio.emit('welcome', {'message': 'Connected to providers!'}, room=sid, namespace='/providers')
    
    @sio.on('disconnect', namespace='/providers')
    async def providers_disconnect(sid):
        print(f"👋 Client disconnected from /providers namespace: {sid}")
    
    @sio.on('test', namespace='/providers')
    async def providers_test(sid, data):
        print(f"📨 Received test message from {sid}: {data}")
        await sio.emit('test_response', {'success': True, 'data': data}, room=sid, namespace='/providers')
    
    # Also setup /cluster namespace for comparison
    @sio.on('connect', namespace='/cluster')
    async def cluster_connect(sid):
        print(f"✅ Client connected to /cluster namespace: {sid}")
    
    print("🔧 Handlers registered for /providers and /cluster namespaces")
    
    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    
    print("🚀 Server running on http://0.0.0.0:8000")
    print("   - /cluster namespace available")
    print("   - /providers namespace available")
    print("   Press Ctrl+C to stop")
    
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n🛑 Stopping server...")
    finally:
        await runner.cleanup()
        print("👋 Server stopped")

if __name__ == "__main__":
    asyncio.run(main())