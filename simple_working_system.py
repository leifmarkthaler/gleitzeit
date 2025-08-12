#!/usr/bin/env python3
"""
Simple working system - minimal architecture that actually executes tasks
"""

import asyncio
import logging
import socketio
from aiohttp import web
from typing import Dict, Any
from gleitzeit_v2.core.models import Task, TaskType, TaskParameters, Workflow
from gleitzeit_v2.providers.ollama_provider import OllamaProvider

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SimpleServer:
    """Simple server that actually works"""
    
    def __init__(self, port=8060):
        self.port = port
        self.sio = socketio.AsyncServer(cors_allowed_origins="*")
        self.app = web.Application()
        
        # State
        self.providers = {}  # provider_id -> provider_socket_id
        self.clients = {}    # client_id -> client_socket_id
        self.workflows = {}  # workflow_id -> workflow_data
        
        self.setup_handlers()
        
    def setup_handlers(self):
        """Setup Socket.IO handlers"""
        
        @self.sio.event
        async def connect(sid, environ):
            print(f"✅ Client connected: {sid}")
        
        @self.sio.event
        async def disconnect(sid):
            print(f"🔌 Client disconnected: {sid}")
            
            # Clean up
            for provider_id, provider_sid in list(self.providers.items()):
                if provider_sid == sid:
                    del self.providers[provider_id]
                    print(f"Provider {provider_id} unregistered")
            
            for client_id, client_sid in list(self.clients.items()):
                if client_sid == sid:
                    del self.clients[client_id]
                    print(f"Client {client_id} unregistered")
        
        @self.sio.on('provider:register')
        async def provider_register(sid, data):
            """Provider registration"""
            provider_data = data.get('provider', {})
            provider_id = provider_data.get('id', sid)
            
            self.providers[provider_id] = sid
            print(f"✅ Provider registered: {provider_id}")
            
            await self.sio.emit('provider:registered', {
                'provider_id': provider_id,
                'status': 'active'
            }, room=sid)
        
        @self.sio.on('workflow:submit')
        async def workflow_submit(sid, data):
            """Workflow submission from client"""
            workflow_data = data.get('workflow', {})
            workflow_id = workflow_data.get('id')
            
            print(f"📋 Received workflow: {workflow_id}")
            
            # Store workflow
            self.workflows[workflow_id] = {
                'data': workflow_data,
                'client_sid': sid,
                'status': 'running'
            }
            
            # Get the task (assume single task for simplicity)
            tasks = workflow_data.get('tasks', [])
            if not tasks:
                await self.sio.emit('workflow:completed', {
                    'workflow_id': workflow_id,
                    'status': 'failed',
                    'error': 'No tasks in workflow'
                }, room=sid)
                return
            
            task = tasks[0]  # Take first task
            
            # Find a provider to execute it
            if not self.providers:
                await self.sio.emit('workflow:completed', {
                    'workflow_id': workflow_id,
                    'status': 'failed', 
                    'error': 'No providers available'
                }, room=sid)
                return
            
            # Get any provider (simple assignment)
            provider_id = list(self.providers.keys())[0]
            provider_sid = self.providers[provider_id]
            
            print(f"🎯 Assigning task {task.get('id')} to provider {provider_id}")
            
            # Send task to provider
            await self.sio.emit('task_assign', {
                'task_id': task.get('id'),
                'workflow_id': workflow_id,
                'task_type': task.get('task_type'),
                'parameters': task.get('parameters', {}),
                'client_sid': sid  # So provider knows where to send results
            }, room=provider_sid)
        
        @self.sio.on('task:completed')
        async def task_completed(sid, data):
            """Task completion from provider"""
            task_id = data.get('task_id')
            workflow_id = data.get('workflow_id')
            result = data.get('result')
            client_sid = data.get('client_sid')
            
            print(f"✅ Task completed: {task_id}")
            
            # Update workflow
            if workflow_id in self.workflows:
                self.workflows[workflow_id]['status'] = 'completed'
                
                # Send completion to client
                await self.sio.emit('workflow:completed', {
                    'workflow_id': workflow_id,
                    'status': 'completed',
                    'results': {task_id: result}
                }, room=client_sid)
                
                print(f"✅ Workflow completed: {workflow_id}")
        
        @self.sio.on('task:failed')
        async def task_failed(sid, data):
            """Task failure from provider"""
            task_id = data.get('task_id')
            workflow_id = data.get('workflow_id') 
            error = data.get('error')
            client_sid = data.get('client_sid')
            
            print(f"❌ Task failed: {task_id} - {error}")
            
            # Send failure to client
            await self.sio.emit('workflow:completed', {
                'workflow_id': workflow_id,
                'status': 'failed',
                'error': error
            }, room=client_sid)
    
    async def start(self):
        """Start the server"""
        self.sio.attach(self.app)
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', self.port)
        await site.start()
        
        print(f"🚀 Simple server running on port {self.port}")
        return runner

class SimpleProvider:
    """Simple provider that works with the simple server"""
    
    def __init__(self, server_url="http://localhost:8060"):
        self.server_url = server_url
        self.sio = socketio.AsyncClient()
        self.ollama_provider = OllamaProvider()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup Socket.IO handlers"""
        
        @self.sio.event
        async def connect():
            print("✅ Provider connected to server")
            
            # Register as provider
            await self.sio.emit('provider:register', {
                'provider': {
                    'id': 'simple_ollama_provider',
                    'name': 'Simple Ollama Provider',
                    'type': 'llm'
                }
            })
        
        @self.sio.on('provider:registered')
        async def provider_registered(data):
            print(f"✅ Provider registered: {data}")
        
        @self.sio.on('task_assign')
        async def task_assign(data):
            """Handle task assignment"""
            task_id = data.get('task_id')
            workflow_id = data.get('workflow_id')
            task_type = data.get('task_type')
            parameters = data.get('parameters', {})
            client_sid = data.get('client_sid')
            
            print(f"📋 Processing task: {task_id}")
            
            try:
                # Execute the task directly using Ollama
                if task_type == TaskType.LLM_GENERATE.value:
                    result = await self.ollama_provider._generate_text(parameters)
                else:
                    raise ValueError(f"Unsupported task type: {task_type}")
                
                # Report success
                await self.sio.emit('task:completed', {
                    'task_id': task_id,
                    'workflow_id': workflow_id,
                    'result': result,
                    'client_sid': client_sid
                })
                
                print(f"✅ Task completed: {task_id}")
                
            except Exception as e:
                print(f"❌ Task failed: {task_id} - {e}")
                
                # Report failure  
                await self.sio.emit('task:failed', {
                    'task_id': task_id,
                    'workflow_id': workflow_id,
                    'error': str(e),
                    'client_sid': client_sid
                })
    
    async def start(self):
        """Connect to server"""
        await self.sio.connect(self.server_url)

class SimpleClient:
    """Simple client that works with the simple server"""
    
    def __init__(self, server_url="http://localhost:8060"):
        self.server_url = server_url
        self.sio = socketio.AsyncClient()
        self.workflow_futures = {}
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup Socket.IO handlers"""
        
        @self.sio.event
        async def connect():
            print("✅ Client connected to server")
        
        @self.sio.on('workflow:completed')
        async def workflow_completed(data):
            """Handle workflow completion"""
            workflow_id = data.get('workflow_id')
            
            if workflow_id in self.workflow_futures:
                future = self.workflow_futures.pop(workflow_id)
                if not future.done():
                    future.set_result(data)
    
    async def connect(self):
        """Connect to server"""
        await self.sio.connect(self.server_url)
    
    async def run_text_generation(self, prompt, model="llama3", timeout=30):
        """Run text generation"""
        # Create simple task
        task = {
            'id': f'task_{len(self.workflow_futures)}',
            'task_type': TaskType.LLM_GENERATE.value,
            'parameters': {
                'prompt': prompt,
                'model': model
            }
        }
        
        # Create simple workflow
        workflow = {
            'id': f'workflow_{len(self.workflow_futures)}',
            'name': 'Simple Text Generation',
            'tasks': [task]
        }
        
        # Create future
        future = asyncio.Future()
        self.workflow_futures[workflow['id']] = future
        
        # Submit workflow
        await self.sio.emit('workflow:submit', {'workflow': workflow})
        
        # Wait for result
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            if result['status'] == 'completed':
                return list(result['results'].values())[0]  # Return first task result
            else:
                raise RuntimeError(f"Workflow failed: {result.get('error', 'Unknown error')}")
        except asyncio.TimeoutError:
            raise RuntimeError(f"Workflow timeout after {timeout}s")
    
    async def disconnect(self):
        """Disconnect from server"""
        await self.sio.disconnect()

async def test_simple_system():
    """Test the simple working system"""
    print("🧪 Testing simple working system...")
    
    # Start server
    server = SimpleServer(port=8060)
    runner = await server.start()
    
    try:
        # Give server time to start
        await asyncio.sleep(1)
        
        # Start provider
        provider = SimpleProvider()
        await provider.start()
        
        # Give provider time to register
        await asyncio.sleep(1)
        
        # Test with client
        client = SimpleClient()
        await client.connect()
        
        # Run text generation
        result = await client.run_text_generation(
            "Say exactly: Simple system works!",
            timeout=15
        )
        
        print(f"🎉 SUCCESS! Result: {result}")
        
        await client.disconnect()
        
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(test_simple_system())