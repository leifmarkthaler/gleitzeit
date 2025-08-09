#!/usr/bin/env python3
"""
Debug Socket.IO Provider Connection

Simple test to debug the connection issue
"""

import asyncio
import socketio
from gleitzeit_cluster.communication.provider_client import ProviderSocketClient

async def test_direct_connection():
    """Test direct Socket.IO connection"""
    print("🔍 Testing direct Socket.IO connection...")
    
    # Try basic socketio client first
    sio = socketio.AsyncClient()
    
    @sio.on('connect', namespace='/providers')
    async def on_connect():
        print("✅ Connected to /providers namespace!")
        
    @sio.on('connect_error', namespace='/providers')
    async def on_connect_error(data):
        print(f"❌ Connection error to /providers: {data}")
        
    @sio.on('disconnect', namespace='/providers')
    async def on_disconnect():
        print("🔌 Disconnected from /providers namespace")
        
    try:
        print("   Attempting to connect to http://localhost:8000...")
        await sio.connect('http://localhost:8000', namespaces=['/providers'])
        await asyncio.sleep(2)
        print("   Connection successful!")
        await sio.disconnect()
    except Exception as e:
        print(f"   ❌ Direct connection failed: {e}")
        
    # Now test our ProviderSocketClient
    print("\n🧪 Testing ProviderSocketClient...")
    try:
        client = ProviderSocketClient('http://localhost:8000')
        success = await client.connect()
        if success:
            print("✅ ProviderSocketClient connected!")
            await client.disconnect()
        else:
            print("❌ ProviderSocketClient failed to connect")
    except Exception as e:
        print(f"❌ ProviderSocketClient error: {e}")

async def test_server_namespaces():
    """Test what namespaces are available"""
    print("\n🌐 Testing server namespace availability...")
    
    # Test cluster namespace (should work)
    sio_cluster = socketio.AsyncClient()
    
    @sio_cluster.on('connect', namespace='/cluster')
    async def on_cluster_connect():
        print("✅ /cluster namespace is available")
        
    @sio_cluster.on('connect_error', namespace='/cluster')
    async def on_cluster_error(data):
        print(f"❌ /cluster namespace error: {data}")
        
    try:
        await sio_cluster.connect('http://localhost:8000', namespaces=['/cluster'])
        await asyncio.sleep(1)
        await sio_cluster.disconnect()
    except Exception as e:
        print(f"❌ /cluster test failed: {e}")
        
    # Test providers namespace
    sio_providers = socketio.AsyncClient()
    
    @sio_providers.on('connect', namespace='/providers')
    async def on_providers_connect():
        print("✅ /providers namespace is available")
        
    @sio_providers.on('connect_error', namespace='/providers')  
    async def on_providers_error(data):
        print(f"❌ /providers namespace error: {data}")
        
    try:
        await sio_providers.connect('http://localhost:8000', namespaces=['/providers'])
        await asyncio.sleep(1)
        await sio_providers.disconnect()
    except Exception as e:
        print(f"❌ /providers test failed: {e}")

if __name__ == "__main__":
    print("🚀 Socket.IO Debug Test")
    print("=" * 40)
    print("Make sure to start the demo server first:")
    print("python examples/socketio_provider_demo.py")
    print()
    
    asyncio.run(test_server_namespaces())
    asyncio.run(test_direct_connection())