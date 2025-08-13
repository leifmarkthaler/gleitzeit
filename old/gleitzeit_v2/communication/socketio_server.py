"""
Central Socket.IO Communications Server for Gleitzeit V2

This is the central hub that all components connect to:
- Workflow orchestration server
- Providers (Ollama, etc.)  
- Clients

Handles all event routing between components.
"""

import asyncio
import logging
from typing import Dict, Set, Any
from datetime import datetime

import socketio
from aiohttp import web

logger = logging.getLogger(__name__)


class CentralSocketIOServer:
    """
    Central Socket.IO server for all Gleitzeit V2 communications
    
    All components connect here:
    - Server (workflow orchestration)
    - Providers (task execution) 
    - Clients (workflow submission)
    
    Routes events between components appropriately.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        
        # Socket.IO server
        self.sio = socketio.AsyncServer(
            cors_allowed_origins="*",
            logger=logger,
            engineio_logger=logger
        )
        
        # Component tracking
        self.servers: Set[str] = set()  # Socket IDs of orchestration servers
        self.providers: Dict[str, str] = {}  # provider_id -> socket_id
        self.clients: Set[str] = set()  # Socket IDs of clients
        self.socket_to_type: Dict[str, str] = {}  # socket_id -> component_type
        
        # Setup event handlers
        self._setup_handlers()
        
        logger.info("Central Socket.IO Server initialized")
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f"Component connected: {sid}")
            
            # Send server ready signal
            await self.sio.emit('server:ready', {
                'server_version': '2.0',
                'capabilities': ['workflows', 'batches', 'dependencies', 'providers'],
                'timestamp': datetime.utcnow().isoformat()
            }, room=sid)
        
        @self.sio.event
        async def disconnect(sid):
            component_type = self.socket_to_type.get(sid)
            logger.info(f"Component disconnected: {sid} (type: {component_type})")
            
            # Clean up tracking
            if sid in self.servers:
                self.servers.remove(sid)
            if sid in self.clients:
                self.clients.remove(sid)
            
            # Clean up providers
            provider_to_remove = None
            for provider_id, socket_id in self.providers.items():
                if socket_id == sid:
                    provider_to_remove = provider_id
                    break
            if provider_to_remove:
                self.providers.pop(provider_to_remove)
                # Notify servers about provider disconnect
                await self._broadcast_to_servers('provider:disconnected', {
                    'provider_id': provider_to_remove,
                    'timestamp': datetime.utcnow().isoformat()
                })
            
            self.socket_to_type.pop(sid, None)
        
        # Component registration
        @self.sio.on('component:register')
        async def component_register(sid, data):
            """Register component type"""
            component_type = data.get('type')  # 'server', 'provider', 'client'
            component_id = data.get('id', sid)
            
            self.socket_to_type[sid] = component_type
            
            if component_type == 'server':
                self.servers.add(sid)
                logger.info(f"Orchestration server registered: {sid}")
            elif component_type == 'client':
                self.clients.add(sid)
                logger.info(f"Client registered: {sid}")
            
            await self.sio.emit('component:registered', {
                'type': component_type,
                'id': component_id,
                'status': 'active'
            }, room=sid)
        
        # Provider events
        @self.sio.on('provider:register')
        async def provider_register(sid, data):
            """Provider registration - forward to servers"""
            provider_data = data.get('provider', {})
            provider_id = provider_data.get('id', sid)
            
            # Track provider
            self.providers[provider_id] = sid
            self.socket_to_type[sid] = 'provider'
            
            logger.info(f"Provider registered: {provider_id} ({sid})")
            
            # Forward to all servers
            await self._broadcast_to_servers('provider:register', {
                'provider': {**provider_data, 'socket_id': sid},
                'timestamp': datetime.utcnow().isoformat()
            })
            
            # Confirm to provider
            await self.sio.emit('provider:registered', {
                'provider_id': provider_id,
                'status': 'active',
                'timestamp': datetime.utcnow().isoformat()
            }, room=sid)
        
        @self.sio.on('provider:heartbeat')
        async def provider_heartbeat(sid, data):
            """Provider heartbeat - forward to servers"""
            await self._broadcast_to_servers('provider:heartbeat', {
                **data,
                'socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        # Task execution events (provider -> server)
        @self.sio.on('task:accepted')
        async def task_accepted(sid, data):
            """Task accepted by provider - forward to servers"""
            await self._broadcast_to_servers('task:accepted', {
                **data,
                'provider_socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        @self.sio.on('task:progress')
        async def task_progress(sid, data):
            """Task progress - forward to servers and clients"""
            await self._broadcast_to_servers('task:progress', {
                **data,
                'provider_socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            # Also forward to clients if they want progress updates
            await self._broadcast_to_clients('task:progress', data)
        
        @self.sio.on('task:completed')
        async def task_completed(sid, data):
            """Task completed - forward to servers"""
            logger.info(f"Task completed: {data.get('task_id')} from provider {sid}")
            await self._broadcast_to_servers('task:completed', {
                **data,
                'provider_socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        @self.sio.on('task:failed')
        async def task_failed(sid, data):
            """Task failed - forward to servers"""
            logger.warning(f"Task failed: {data.get('task_id')} from provider {sid}")
            await self._broadcast_to_servers('task:failed', {
                **data,
                'provider_socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        # Workflow events (server -> clients)
        @self.sio.on('workflow:submitted')
        async def workflow_submitted(sid, data):
            """Workflow submitted - forward to clients"""
            await self._broadcast_to_clients('workflow:submitted', data)
        
        @self.sio.on('workflow:completed')
        async def workflow_completed(sid, data):
            """Workflow completed - forward to clients"""
            logger.info(f"Workflow completed: {data.get('workflow_id')}")
            await self._broadcast_to_clients('workflow:completed', data)
        
        # Client events (client -> server)
        @self.sio.on('workflow:submit')
        async def workflow_submit(sid, data):
            """Workflow submission - forward to servers"""
            logger.info(f"Workflow submission from client {sid}")
            await self._broadcast_to_servers('workflow:submit', {
                **data,
                'client_socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        @self.sio.on('workflow:status')
        async def workflow_status(sid, data):
            """Workflow status request - forward to servers"""
            await self._broadcast_to_servers('workflow:status', {
                **data,
                'client_socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        @self.sio.on('workflow:cancel')
        async def workflow_cancel(sid, data):
            """Workflow cancellation - forward to servers"""
            await self._broadcast_to_servers('workflow:cancel', {
                **data,
                'client_socket_id': sid,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        # Server to provider events (server -> provider)
        @self.sio.on('task:assign')
        async def task_assign(sid, data):
            """Task assignment - route to specific provider"""
            provider_id = data.get('provider_id')
            provider_socket_id = data.get('provider_socket_id')
            
            # Route to provider
            if provider_socket_id:
                logger.info(f"Routing task {data.get('task_id')} to provider {provider_socket_id}")
                await self.sio.emit('task:assign', data, room=provider_socket_id)
            else:
                logger.warning(f"No provider socket ID for task assignment: {data}")
    
    async def _broadcast_to_servers(self, event: str, data: Dict[str, Any]):
        """Broadcast event to all registered servers"""
        if not self.servers:
            logger.warning(f"No servers connected to receive event: {event}")
            return
        
        for server_sid in self.servers:
            await self.sio.emit(event, data, room=server_sid)
    
    async def _broadcast_to_clients(self, event: str, data: Dict[str, Any]):
        """Broadcast event to all registered clients"""
        if not self.clients:
            return
        
        for client_sid in self.clients:
            await self.sio.emit(event, data, room=client_sid)
    
    async def _broadcast_to_providers(self, event: str, data: Dict[str, Any]):
        """Broadcast event to all registered providers"""
        for provider_socket_id in self.providers.values():
            await self.sio.emit(event, data, room=provider_socket_id)
    
    async def start(self):
        """Start the central Socket.IO server"""
        app = web.Application()
        
        # Health endpoint
        async def health(request):
            return web.json_response({
                'status': 'healthy',
                'service': 'central_socketio_server',
                'connected_servers': len(self.servers),
                'connected_providers': len(self.providers),
                'connected_clients': len(self.clients),
                'total_connections': len(self.socket_to_type),
                'timestamp': datetime.utcnow().isoformat()
            })
        
        app.router.add_get('/health', health)
        
        # Attach Socket.IO
        self.sio.attach(app)
        
        # Start web server
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        logger.info(f"🚀 Central Socket.IO Server running at http://{self.host}:{self.port}")
        
        return runner
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics"""
        return {
            'connected_servers': len(self.servers),
            'connected_providers': len(self.providers),
            'connected_clients': len(self.clients),
            'total_connections': len(self.socket_to_type),
            'providers': list(self.providers.keys())
        }


async def main():
    """Run the central Socket.IO server"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Central Socket.IO Communications Server")
    parser.add_argument('--host', default='0.0.0.0', help='Server host')
    parser.add_argument('--port', type=int, default=8000, help='Server port')
    parser.add_argument('--log-level', default='INFO', help='Log level')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and start server
    socketio_server = CentralSocketIOServer(host=args.host, port=args.port)
    runner = await socketio_server.start()
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down server...")
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())