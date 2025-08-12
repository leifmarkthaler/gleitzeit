#!/usr/bin/env python3
"""
Debug provider connection issues
"""

import asyncio
import logging
import socketio
from gleitzeit_v2.core.models import TaskType

logging.basicConfig(level=logging.DEBUG)

async def test_provider_registration():
    """Test provider registration step by step"""
    
    sio = socketio.AsyncClient(logger=True, engineio_logger=True)
    
    @sio.event
    async def connect():
        print("✅ Connected to server")
        
        # Try to register provider
        capabilities = {
            'task_types': [TaskType.LLM_GENERATE.value],
            'models': ['llama3'],
            'max_concurrent': 2,
            'features': ['test']
        }
        
        provider_data = {
            'provider': {
                'id': 'test_provider',
                'name': 'Test Provider',
                'type': 'llm',
                'capabilities': capabilities
            }
        }
        
        print(f"📤 Sending provider registration: {provider_data}")
        
        try:
            await sio.emit('provider:register', provider_data)
            print("✅ Registration data sent")
        except Exception as e:
            print(f"❌ Failed to send registration: {e}")
    
    @sio.event
    async def disconnect():
        print("🔌 Disconnected from server")
    
    @sio.event
    async def provider_registered(data):
        print(f"✅ Provider registered successfully: {data}")
    
    @sio.event
    async def server_ready(data):
        print(f"🔥 Server ready: {data}")
    
    @sio.event
    async def error(data):
        print(f"❌ Server error: {data}")
    
    try:
        print("🔗 Connecting to server...")
        await sio.connect('http://localhost:8005')
        
        # Wait a bit to see what happens
        await asyncio.sleep(5)
        
        await sio.disconnect()
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(test_provider_registration())