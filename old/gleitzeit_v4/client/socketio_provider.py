"""
Socket.IO Provider Client for Gleitzeit V4

Base class for protocol providers that connect to the central server
via Socket.IO instead of running in the same process.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from pathlib import Path
import socketio

from providers.base import ProtocolProvider

logger = logging.getLogger(__name__)


class SocketIOProviderClient:
    """
    Socket.IO client for protocol providers
    
    Providers inherit from this class to connect to the central server
    and handle requests via Socket.IO events.
    """
    
    def __init__(
        self,
        provider_id: str,
        protocol_id: str,
        server_url: str = "http://localhost:8000",
        name: Optional[str] = None,
        description: Optional[str] = None
    ):
        self.provider_id = provider_id
        self.protocol_id = protocol_id
        self.server_url = server_url
        self.name = name or f"{protocol_id} Provider"
        self.description = description
        
        # Socket.IO client
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.running = False
        
        # Provider implementation
        self.provider_instance: Optional[ProtocolProvider] = None
        
        # Setup event handlers
        self._setup_events()
        
        logger.info(f"Initialized SocketIO Provider Client: {provider_id}")
    
    def set_provider_instance(self, provider: ProtocolProvider):
        """Set the actual provider implementation"""
        self.provider_instance = provider
        logger.info(f"Set provider instance: {provider.__class__.__name__}")
    
    def _setup_events(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info(f"Connected to central server: {self.server_url}")
            
            # Register with central server
            await self._register_provider()
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            logger.info("Disconnected from central server")
        
        @self.sio.event
        async def connected(data):
            logger.info(f"Server response: {data['message']}")
        
        @self.sio.event
        async def provider_registered(data):
            logger.info(f"Provider registered: {data['message']}")
        
        @self.sio.event
        async def error(data):
            logger.error(f"Server error: {data['message']}")
        
        @self.sio.on('execute_method')
        async def execute_method(data):
            """Handle method execution request from server"""
            try:
                method = data.get('method')
                params = data.get('params', {})
                
                if not self.provider_instance:
                    return {'error': 'Provider instance not set'}
                
                # Execute method on provider
                result = await self.provider_instance.handle_request(method, params)
                
                return {'result': result}
                
            except Exception as e:
                logger.error(f"Method execution failed: {e}")
                return {'error': str(e)}
        
        @self.sio.on('initialize')
        async def initialize(data):
            """Handle initialization request"""
            try:
                if self.provider_instance:
                    await self.provider_instance.initialize()
                return {'success': True}
            except Exception as e:
                logger.error(f"Provider initialization failed: {e}")
                return {'error': str(e)}
        
        @self.sio.on('shutdown')
        async def shutdown(data):
            """Handle shutdown request"""
            try:
                if self.provider_instance:
                    await self.provider_instance.shutdown()
                return {'success': True}
            except Exception as e:
                logger.error(f"Provider shutdown failed: {e}")
                return {'error': str(e)}
        
        @self.sio.on('health_check')
        async def health_check(data):
            """Handle health check request"""
            try:
                if self.provider_instance:
                    return await self.provider_instance.health_check()
                else:
                    return {
                        'status': 'unhealthy',
                        'details': 'Provider instance not set'
                    }
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                return {
                    'status': 'unhealthy',
                    'details': str(e)
                }
    
    async def _register_provider(self):
        """Register this provider with the central server"""
        try:
            # Initialize the provider instance first
            if self.provider_instance and not self.provider_instance.is_initialized():
                logger.info(f"Initializing provider instance: {self.provider_id}")
                await self.provider_instance.initialize()
            
            supported_methods = []
            if self.provider_instance:
                supported_methods = self.provider_instance.get_supported_methods()
            
            await self.sio.emit('register_provider', {
                'provider_id': self.provider_id,
                'protocol_id': self.protocol_id,
                'supported_methods': supported_methods,
                'name': self.name,
                'description': self.description
            })
            
        except Exception as e:
            logger.error(f"Failed to register provider: {e}")
    
    async def start(self):
        """Start the provider client"""
        if self.running:
            return
        
        self.running = True
        logger.info(f"Starting provider client: {self.provider_id}")
        
        try:
            await self.sio.connect(self.server_url)
            
            # Event-driven operation - wait for events without polling
            # Socket.IO connection management handles keep-alive automatically
            logger.info("Provider client running in event-driven mode")
            
            # Wait for shutdown signal or connection loss
            shutdown_event = asyncio.Event()
            
            @self.sio.event
            async def disconnect():
                logger.info("Disconnected from server")
                shutdown_event.set()
            
            # Block until shutdown or disconnect
            await shutdown_event.wait()
                
        except Exception as e:
            logger.error(f"Provider client error: {e}")
            self.running = False
            raise
        finally:
            if self.sio.connected:
                await self.sio.disconnect()
    
    async def stop(self):
        """Stop the provider client"""
        self.running = False
        
        if self.sio.connected:
            await self.sio.disconnect()
        
        logger.info(f"Stopped provider client: {self.provider_id}")
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connected and self.sio.connected


class SocketIOEchoProvider(SocketIOProviderClient):
    """Echo provider using Socket.IO connection"""
    
    def __init__(self, provider_id: str = "socketio-echo-1", server_url: str = "http://localhost:8000"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="echo/v1",
            server_url=server_url,
            name="Socket.IO Echo Provider",
            description="Echo provider connected via Socket.IO"
        )
        
        # Import and set provider instance
        from providers.echo_provider import EchoProvider
        echo_provider = EchoProvider(provider_id)
        self.set_provider_instance(echo_provider)


class SocketIOPythonFunctionProvider(SocketIOProviderClient):
    """Python function provider using Socket.IO connection"""
    
    def __init__(self, provider_id: str = "socketio-python-1", server_url: str = "http://localhost:8000",
                 functions_dir: Optional[Path] = None):
        super().__init__(
            provider_id=provider_id,
            protocol_id="python/v1",
            server_url=server_url,
            name="Socket.IO Python Function Provider",
            description="Python function provider connected via Socket.IO"
        )
        
        # Import and set provider instance
        from providers.python_function_provider import CustomFunctionProvider
        python_provider = CustomFunctionProvider(provider_id, functions_dir)
        self.set_provider_instance(python_provider)


class SocketIOWebSearchProvider(SocketIOProviderClient):
    """Web search provider using Socket.IO connection"""
    
    def __init__(self, provider_id: str = "socketio-web-search-1", server_url: str = "http://localhost:8000"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="web-search/v1",
            server_url=server_url,
            name="Socket.IO Web Search Provider",
            description="Web search provider connected via Socket.IO"
        )
        
        # Import and set provider instance
        from providers.mock_web_search_provider import MockWebSearchProvider
        search_provider = MockWebSearchProvider(provider_id)
        self.set_provider_instance(search_provider)


class SocketIOTextProcessingProvider(SocketIOProviderClient):
    """Text processing provider using Socket.IO connection"""
    
    def __init__(self, provider_id: str = "socketio-text-processing-1", server_url: str = "http://localhost:8000"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="text-processing/v1",
            server_url=server_url,
            name="Socket.IO Text Processing Provider",
            description="Text processing provider connected via Socket.IO"
        )
        
        # Import and set provider instance
        from providers.mock_text_processing_provider import MockTextProcessingProvider
        text_provider = MockTextProcessingProvider(provider_id)
        self.set_provider_instance(text_provider)


class SocketIOOllamaProvider(SocketIOProviderClient):
    """Ollama provider using Socket.IO connection"""
    
    def __init__(self, provider_id: str = "socketio-ollama-1", server_url: str = "http://localhost:8000", ollama_url: str = "http://localhost:11434"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            server_url=server_url,
            name="Socket.IO Ollama Provider",
            description="Ollama LLM provider connected via Socket.IO"
        )
        
        # Import and set provider instance
        from providers.ollama_provider import OllamaProvider
        ollama_provider = OllamaProvider(provider_id, ollama_url)
        self.set_provider_instance(ollama_provider)


# Convenience functions for running providers
async def run_echo_provider(server_url: str = "http://localhost:8000"):
    """Run echo provider as Socket.IO client"""
    provider = SocketIOEchoProvider(server_url=server_url)
    await provider.start()


async def run_web_search_provider(server_url: str = "http://localhost:8000"):
    """Run web search provider as Socket.IO client"""
    provider = SocketIOWebSearchProvider(server_url=server_url)
    await provider.start()


async def run_text_processing_provider(server_url: str = "http://localhost:8000"):
    """Run text processing provider as Socket.IO client"""
    provider = SocketIOTextProcessingProvider(server_url=server_url)
    await provider.start()


async def run_ollama_provider(server_url: str = "http://localhost:8000", ollama_url: str = "http://localhost:11434"):
    """Run Ollama provider as Socket.IO client"""
    provider = SocketIOOllamaProvider(server_url=server_url, ollama_url=ollama_url)
    await provider.start()