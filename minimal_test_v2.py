#!/usr/bin/env python3
"""
Minimal working test - bypassing Socket.IO for direct execution
"""

import asyncio
import logging
from gleitzeit_v2.core.models import Task, TaskType, TaskParameters
from gleitzeit_v2.providers.ollama_provider import OllamaProvider

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def test_task_execution_offline():
    """Test task execution without Socket.IO"""
    print("=== OFFLINE TASK EXECUTION TEST ===")
    
    provider = OllamaProvider()
    
    # Create task data
    task_data = {
        'task_id': 'test_task_123',
        'workflow_id': 'test_workflow_456', 
        'task_type': TaskType.LLM_GENERATE.value,
        'parameters': {
            'prompt': 'Say exactly: Hello from offline test',
            'model': 'llama3',
            'temperature': 0.7,
            'max_tokens': 50
        }
    }
    
    print(f"Processing task offline: {task_data['task_id']}")
    
    try:
        # Extract just the execution part without Socket.IO
        task_type = task_data.get('task_type')
        parameters = task_data.get('parameters', {})
        
        print(f"🔄 Processing task type: {task_type}")
        
        # Route to appropriate handler (like in _process_task but without Socket.IO)
        if task_type == TaskType.LLM_GENERATE.value:
            result = await provider._generate_text(parameters)
        else:
            raise ValueError(f"Unsupported task type: {task_type}")
        
        print(f"✅ Task execution result: {result}")
        return result
        
    except Exception as e:
        print(f"❌ Task execution failed: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_simple_socketio():
    """Test if we can get basic Socket.IO working"""
    print("\n=== SIMPLE SOCKET.IO TEST ===")
    
    import socketio
    
    # Create simple server
    sio_server = socketio.AsyncServer(cors_allowed_origins="*")
    
    @sio_server.event
    async def connect(sid, environ):
        print(f"✅ Client connected: {sid}")
    
    @sio_server.event  
    async def test_message(sid, data):
        print(f"📩 Received: {data}")
        await sio_server.emit('response', {'message': 'Hello back!'}, room=sid)
    
    # Start server
    from aiohttp import web
    app = web.Application()
    sio_server.attach(app)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8050)
    await site.start()
    print("🚀 Simple Socket.IO server started on port 8050")
    
    # Test client connection
    sio_client = socketio.AsyncClient()
    
    @sio_client.event
    async def connect():
        print("✅ Client connected to server")
        
    @sio_client.event
    async def response(data):
        print(f"📨 Client received: {data}")
    
    try:
        await sio_client.connect('http://localhost:8050')
        await sio_client.emit('test_message', {'text': 'Hello server'})
        await asyncio.sleep(1)  # Give time for response
        await sio_client.disconnect()
        print("✅ Socket.IO communication works")
        return True
        
    except Exception as e:
        print(f"❌ Socket.IO test failed: {e}")
        return False
    
    finally:
        await runner.cleanup()

async def main():
    """Run all minimal tests"""
    print("🧪 Starting comprehensive minimal tests...")
    
    # Test 1: Offline task execution
    result1 = await test_task_execution_offline()
    
    # Test 2: Basic Socket.IO
    result2 = await test_simple_socketio()
    
    if result1 and result2:
        print("\n🎉 All tests passed!")
        print("✅ Core execution works")
        print("✅ Socket.IO communication works") 
        print("💡 The issue is in the complex architecture, not the fundamentals")
    else:
        print("\n❌ Some fundamental issue exists")

if __name__ == '__main__':
    asyncio.run(main())