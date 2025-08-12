#!/usr/bin/env python3
"""
Debug CORS and transport issues with Socket.IO
"""

import asyncio
import socketio
from aiohttp import web
import logging

logging.basicConfig(level=logging.DEBUG)

async def test_cors_and_transport():
    """Test different CORS and transport configurations"""
    
    print("🔍 Testing CORS and Transport Configurations")
    print("=" * 50)
    
    configs = [
        {
            "name": "Default Config",
            "cors": "*",
            "transports": None
        },
        {
            "name": "Explicit CORS", 
            "cors": ["http://localhost:8000", "http://127.0.0.1:8000"],
            "transports": None
        },
        {
            "name": "WebSocket Only",
            "cors": "*",
            "transports": ["websocket"]
        },
        {
            "name": "Polling Only", 
            "cors": "*",
            "transports": ["polling"]
        }
    ]
    
    for i, config in enumerate(configs, 1):
        print(f"\n{i}. Testing {config['name']}...")
        
        # Create server with specific config
        sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins=config["cors"],
            logger=True,
            engineio_logger=False
        )
        
        app = web.Application()
        sio.attach(app)
        
        # Add handlers
        @sio.on('connect', namespace='/providers')
        async def providers_connect(sid, environ):
            print(f"   ✅ /providers connected: {sid}")
            print(f"   Environ keys: {list(environ.keys())[:5]}...")
            return True  # Explicitly allow connection
            
        # Start server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 8000)
        await site.start()
        
        # Wait for server to start
        await asyncio.sleep(0.5)
        
        # Test client connection
        try:
            client_config = {}
            if config["transports"]:
                client_config["transports"] = config["transports"]
                
            client = socketio.AsyncClient(**client_config)
            
            connected = False
            
            @client.on('connect', namespace='/providers')
            async def on_connect():
                nonlocal connected
                connected = True
                print("   ✅ Client connected successfully!")
                
            # Try connection
            await client.connect('http://127.0.0.1:8000', namespaces=['/providers'])
            await asyncio.sleep(1)
            
            if connected:
                print(f"   🎉 {config['name']} WORKS!")
            else:
                print(f"   ❌ {config['name']} failed to connect")
                
            await client.disconnect()
            
        except Exception as e:
            print(f"   ❌ {config['name']} error: {e}")
        
        # Cleanup
        await runner.cleanup()
        await asyncio.sleep(0.5)
    
    # Test the actual gleitzeit server setup
    print(f"\n5. Testing Gleitzeit Server Setup...")
    await test_gleitzeit_server()

async def test_gleitzeit_server():
    """Test the actual gleitzeit server configuration"""
    from gleitzeit_cluster.communication.socketio_server import SocketIOServer
    
    # Start gleitzeit server
    server = SocketIOServer(
        host="127.0.0.1",
        port=8001,
        cors_allowed_origins="*"
    )
    
    # Add explicit providers handler
    @server.sio.on('connect', namespace='/providers')
    async def explicit_providers_connect(sid, environ):
        print(f"   ✅ Gleitzeit /providers connected: {sid}")
        return True
        
    await server.start()
    await asyncio.sleep(1)
    
    # Test connection
    try:
        client = socketio.AsyncClient()
        
        connected = False
        @client.on('connect', namespace='/providers')
        async def on_connect():
            nonlocal connected
            connected = True
            print("   ✅ Gleitzeit client connected!")
            
        await client.connect('http://127.0.0.1:8001', namespaces=['/providers'])
        await asyncio.sleep(1)
        
        if connected:
            print("   🎉 Gleitzeit server config WORKS!")
        else:
            print("   ❌ Gleitzeit server still fails")
            
        await client.disconnect()
        
    except Exception as e:
        print(f"   ❌ Gleitzeit server error: {e}")
    
    await server.stop()

if __name__ == "__main__":
    asyncio.run(test_cors_and_transport())