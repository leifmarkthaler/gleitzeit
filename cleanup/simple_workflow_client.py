#!/usr/bin/env python3
"""
Simple workflow client that connects to existing servers
"""

import asyncio
import socketio
import json
import sys
from typing import Dict, Any

class SimpleWorkflowClient:
    def __init__(self, server_url: str = "http://localhost:8000"):
        self.server_url = server_url
        self.sio = socketio.AsyncClient()
        self.workflow_results = {}
        self.setup_handlers()
    
    def setup_handlers(self):
        @self.sio.event
        async def connect():
            print("✅ Connected to server")
            # Register as client
            await self.sio.emit('component:register', {
                'type': 'client',
                'id': 'test_client'
            })
        
        @self.sio.event
        async def disconnect():
            print("🔌 Disconnected from server")
        
        @self.sio.on('workflow:completed')
        async def workflow_completed(data):
            workflow_id = data.get('workflow_id')
            status = data.get('status')
            results = data.get('results', {})
            
            print(f"🎯 Workflow completed: {workflow_id} (status: {status})")
            self.workflow_results[workflow_id] = {
                'status': status,
                'results': results
            }
        
        @self.sio.on('workflow:submitted')
        async def workflow_submitted(data):
            print(f"📤 Workflow submitted: {data}")
            
        @self.sio.on('server:ready')
        async def server_ready(data):
            print(f"🚀 Server ready: {data}")
    
    async def connect(self):
        await self.sio.connect(self.server_url)
        await asyncio.sleep(1)  # Give time for registration
    
    async def submit_workflow(self, workflow_dict: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
        """Submit workflow and wait for completion"""
        workflow_id = workflow_dict['id']
        
        # Submit workflow
        await self.sio.emit('workflow:submit', {
            'workflow': workflow_dict
        })
        
        # Wait for result
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            if workflow_id in self.workflow_results:
                return self.workflow_results[workflow_id]
            await asyncio.sleep(0.5)
        
        return {'status': 'timeout', 'timeout': timeout}
    
    async def disconnect(self):
        await self.sio.disconnect()

async def submit_workflow_to_existing_server(workflow):
    """Submit workflow to existing Gleitzeit server"""
    client = SimpleWorkflowClient()
    
    try:
        await client.connect()
        result = await client.submit_workflow(workflow.to_dict())
        return result
    except Exception as e:
        print(f"❌ Error submitting workflow: {e}")
        return None
    finally:
        await client.disconnect()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Load workflow from file
        import sys
        workflow_file = sys.argv[1]
        with open(workflow_file, 'r') as f:
            workflow_dict = json.load(f)
        
        async def main():
            client = SimpleWorkflowClient()
            await client.connect()
            result = await client.submit_workflow(workflow_dict)
            print(f"Result: {result}")
            await client.disconnect()
        
        asyncio.run(main())