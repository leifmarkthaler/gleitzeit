"""
Socket.IO-based Provider Manager for Gleitzeit

This module provides a unified provider interface using Socket.IO for communication,
replacing the MCP stdio-based approach with the existing Socket.IO infrastructure.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime

import socketio
from socketio import AsyncServer

from .exceptions import ExtensionError, ExtensionNotFound

logger = logging.getLogger(__name__)


@dataclass
class SocketIOProvider:
    """Information about a Socket.IO connected provider"""
    sid: str  # Socket.IO session ID
    name: str
    type: str  # "llm", "tool", "extension"
    models: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    health_status: Dict[str, Any] = field(default_factory=dict)


class SocketIOProviderManager:
    """
    Manages providers (LLM, tools, extensions) via Socket.IO
    
    This replaces the MCP stdio-based approach with Socket.IO for consistency
    with the rest of the Gleitzeit architecture.
    """
    
    def __init__(self, sio_server: Optional[AsyncServer] = None):
        """
        Initialize the Socket.IO provider manager
        
        Args:
            sio_server: Existing Socket.IO server instance (optional)
        """
        self.sio = sio_server
        self.providers: Dict[str, SocketIOProvider] = {}
        self.provider_rooms: Dict[str, Set[str]] = {}  # provider_name -> set of sids
        self._model_routing: Dict[str, str] = {}  # model -> provider_name cache
        self._capability_index: Dict[str, Set[str]] = {}  # capability -> set of provider_names
        
        if self.sio:
            self._setup_handlers()
    
    def attach_to_server(self, sio_server: AsyncServer):
        """Attach to an existing Socket.IO server"""
        self.sio = sio_server
        self._setup_handlers()
        logger.info("SocketIO Provider Manager attached to server")
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers for provider namespace"""
        if not self.sio:
            return
            
        # Provider lifecycle events
        self.sio.on('connect', namespace='/providers')(self.handle_provider_connect)
        self.sio.on('disconnect', namespace='/providers')(self.handle_provider_disconnect)
        self.sio.on('provider:register', namespace='/providers')(self.handle_provider_register)
        self.sio.on('provider:heartbeat', namespace='/providers')(self.handle_provider_heartbeat)
        self.sio.on('provider:health', namespace='/providers')(self.handle_provider_health)
        
        # Provider capability events
        self.sio.on('provider:list_models', namespace='/providers')(self.handle_list_models)
        self.sio.on('provider:list_tools', namespace='/providers')(self.handle_list_tools)
        self.sio.on('provider:capabilities', namespace='/providers')(self.handle_capabilities)
        
        # Provider invocation events
        self.sio.on('provider:invoke', namespace='/providers')(self.handle_provider_invoke)
        self.sio.on('provider:stream', namespace='/providers')(self.handle_provider_stream)
        
        logger.info("Provider Socket.IO handlers registered")
    
    # === Connection Management ===
    
    async def handle_provider_connect(self, sid, environ):
        """Handle provider connection"""
        logger.info(f"Provider connected: {sid}")
        return True
    
    async def handle_provider_disconnect(self, sid):
        """Handle provider disconnection"""
        if sid in self.providers:
            provider = self.providers[sid]
            logger.info(f"Provider disconnected: {provider.name} ({sid})")
            
            # Remove from provider rooms
            if provider.name in self.provider_rooms:
                self.provider_rooms[provider.name].discard(sid)
                if not self.provider_rooms[provider.name]:
                    del self.provider_rooms[provider.name]
            
            # Clear caches
            self._clear_provider_cache(provider.name)
            
            # Remove provider
            del self.providers[sid]
            
            # Broadcast disconnection
            await self._broadcast_provider_status(provider.name, "disconnected")
    
    async def handle_provider_register(self, sid, data):
        """
        Register a new provider
        
        Expected data format:
        {
            "name": "openai",
            "type": "llm",
            "models": ["gpt-4", "gpt-3.5-turbo"],
            "capabilities": ["text", "vision", "function_calling"],
            "description": "OpenAI GPT models",
            "metadata": {...}
        }
        """
        try:
            # Validate required fields
            if not data.get('name'):
                return {"success": False, "error": "Provider name is required"}
            
            # Create provider instance
            provider = SocketIOProvider(
                sid=sid,
                name=data['name'],
                type=data.get('type', 'unknown'),
                models=data.get('models', []),
                capabilities=data.get('capabilities', []),
                description=data.get('description', ''),
                metadata=data.get('metadata', {})
            )
            
            # Register provider
            self.providers[sid] = provider
            
            # Add to provider room
            if provider.name not in self.provider_rooms:
                self.provider_rooms[provider.name] = set()
            self.provider_rooms[provider.name].add(sid)
            
            # Join Socket.IO room for this provider
            await self.sio.enter_room(sid, f"provider:{provider.name}", namespace='/providers')
            
            # Update indices
            self._update_provider_indices(provider)
            
            logger.info(f"Provider registered: {provider.name} ({sid})")
            
            # Broadcast registration
            await self._broadcast_provider_status(provider.name, "connected")
            
            return {"success": True, "provider_id": sid}
            
        except Exception as e:
            logger.error(f"Failed to register provider: {e}")
            return {"success": False, "error": str(e)}
    
    async def handle_provider_heartbeat(self, sid, data):
        """Handle provider heartbeat"""
        if sid in self.providers:
            self.providers[sid].last_heartbeat = datetime.utcnow()
            return {"success": True}
        return {"success": False, "error": "Provider not registered"}
    
    async def handle_provider_health(self, sid, data):
        """Handle provider health status update"""
        if sid in self.providers:
            self.providers[sid].health_status = data.get('status', {})
            self.providers[sid].last_heartbeat = datetime.utcnow()
            return {"success": True}
        return {"success": False, "error": "Provider not registered"}
    
    # === Provider Discovery ===
    
    async def handle_list_models(self, sid, data):
        """Handle request for available models"""
        provider_name = data.get('provider')
        
        if provider_name:
            # Get models from specific provider
            if provider_name in self.provider_rooms:
                for psid in self.provider_rooms[provider_name]:
                    if psid in self.providers:
                        return {
                            "success": True,
                            "models": self.providers[psid].models
                        }
            return {"success": False, "error": f"Provider '{provider_name}' not found"}
        else:
            # Get all models from all providers
            all_models = {}
            for provider in self.providers.values():
                for model in provider.models:
                    all_models[model] = provider.name
            return {"success": True, "models": all_models}
    
    async def handle_list_tools(self, sid, data):
        """Handle request for available tools"""
        provider_name = data.get('provider')
        
        if provider_name:
            # Get tools from specific provider
            if provider_name in self.provider_rooms:
                # Request tools from the provider
                response = await self.sio.call(
                    'get_tools',
                    namespace='/providers',
                    to=f"provider:{provider_name}",
                    timeout=5
                )
                return response
        else:
            # Get tools from all providers
            all_tools = []
            for provider_name in self.provider_rooms:
                try:
                    response = await self.sio.call(
                        'get_tools',
                        namespace='/providers',
                        to=f"provider:{provider_name}",
                        timeout=5
                    )
                    if response.get('success'):
                        all_tools.extend(response.get('tools', []))
                except Exception as e:
                    logger.error(f"Failed to get tools from {provider_name}: {e}")
            return {"success": True, "tools": all_tools}
    
    async def handle_capabilities(self, sid, data):
        """Handle request for provider capabilities"""
        capability = data.get('capability')
        
        if capability:
            # Find providers with specific capability
            providers = []
            for provider in self.providers.values():
                if capability in provider.capabilities:
                    providers.append({
                        "name": provider.name,
                        "type": provider.type,
                        "models": provider.models
                    })
            return {"success": True, "providers": providers}
        else:
            # Return all capabilities
            all_capabilities = set()
            for provider in self.providers.values():
                all_capabilities.update(provider.capabilities)
            return {"success": True, "capabilities": list(all_capabilities)}
    
    # === Provider Invocation ===
    
    async def handle_provider_invoke(self, sid, data):
        """
        Handle synchronous provider invocation
        
        Expected data format:
        {
            "provider": "openai",  # optional, auto-route if not specified
            "model": "gpt-4",      # optional for model-based routing
            "method": "generate",
            "args": {...},
            "timeout": 30
        }
        """
        try:
            provider_name = data.get('provider')
            model = data.get('model')
            method = data.get('method', 'invoke')
            args = data.get('args', {})
            timeout = data.get('timeout', 30)
            
            # Route to provider
            if not provider_name and model:
                provider_name = self.find_provider_for_model(model)
            
            if not provider_name:
                return {"success": False, "error": "No provider specified or found"}
            
            if provider_name not in self.provider_rooms:
                return {"success": False, "error": f"Provider '{provider_name}' not available"}
            
            # Get a provider instance (load balancing could go here)
            provider_sid = next(iter(self.provider_rooms[provider_name]))
            
            # Forward request to provider
            response = await self.sio.call(
                method,
                args,
                namespace='/providers',
                to=provider_sid,
                timeout=timeout
            )
            
            return response
            
        except asyncio.TimeoutError:
            return {"success": False, "error": "Provider invocation timed out"}
        except Exception as e:
            logger.error(f"Provider invocation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def handle_provider_stream(self, sid, data):
        """
        Handle streaming provider invocation
        
        Establishes a streaming connection between client and provider
        """
        try:
            provider_name = data.get('provider')
            model = data.get('model')
            stream_id = data.get('stream_id')
            args = data.get('args', {})
            
            # Route to provider
            if not provider_name and model:
                provider_name = self.find_provider_for_model(model)
            
            if not provider_name:
                await self.sio.emit(
                    'stream:error',
                    {"stream_id": stream_id, "error": "No provider found"},
                    namespace='/providers',
                    to=sid
                )
                return
            
            # Get provider instance
            provider_sid = next(iter(self.provider_rooms[provider_name]))
            
            # Setup bidirectional streaming
            # Client -> Provider
            await self.sio.emit(
                'stream:start',
                {
                    "stream_id": stream_id,
                    "client_sid": sid,
                    "args": args
                },
                namespace='/providers',
                to=provider_sid
            )
            
            # The provider will emit stream:data and stream:end events directly to client
            
        except Exception as e:
            logger.error(f"Stream setup failed: {e}")
            await self.sio.emit(
                'stream:error',
                {"stream_id": stream_id, "error": str(e)},
                namespace='/providers',
                to=sid
            )
    
    # === Public API ===
    
    def get_all_providers(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all connected providers"""
        providers_info = {}
        for provider in self.providers.values():
            providers_info[provider.name] = {
                "type": provider.type,
                "models": provider.models,
                "capabilities": provider.capabilities,
                "description": provider.description,
                "connected": True,
                "health": provider.health_status,
                "last_heartbeat": provider.last_heartbeat.isoformat()
            }
        return providers_info
    
    def find_provider_for_model(self, model: str) -> Optional[str]:
        """Find which provider supports a specific model"""
        # Check cache first
        if model in self._model_routing:
            provider_name = self._model_routing[model]
            if provider_name in self.provider_rooms:
                return provider_name
        
        # Search all providers
        for provider in self.providers.values():
            if model in provider.models:
                self._model_routing[model] = provider.name
                return provider.name
        
        return None
    
    def find_providers_by_capability(self, capability: str) -> List[str]:
        """Find all providers that support a specific capability"""
        if capability in self._capability_index:
            return list(self._capability_index[capability])
        
        providers = []
        for provider in self.providers.values():
            if capability in provider.capabilities:
                providers.append(provider.name)
        
        return providers
    
    async def invoke_provider(
        self,
        provider_name: str,
        method: str,
        **kwargs
    ) -> Any:
        """
        Invoke a method on a provider
        
        Args:
            provider_name: Name of the provider
            method: Method to invoke
            **kwargs: Arguments to pass to the method
            
        Returns:
            Response from the provider
        """
        if provider_name not in self.provider_rooms:
            raise ExtensionNotFound(f"Provider '{provider_name}' not found")
        
        # Get a provider instance
        provider_sid = next(iter(self.provider_rooms[provider_name]))
        
        try:
            response = await self.sio.call(
                method,
                kwargs,
                namespace='/providers',
                to=provider_sid,
                timeout=30
            )
            
            if not response.get('success'):
                raise ExtensionError(f"Provider invocation failed: {response.get('error')}")
            
            return response.get('result')
            
        except asyncio.TimeoutError:
            raise ExtensionError(f"Provider '{provider_name}' invocation timed out")
    
    # === Private Helpers ===
    
    def _update_provider_indices(self, provider: SocketIOProvider):
        """Update internal indices when a provider is added"""
        # Update model routing
        for model in provider.models:
            self._model_routing[model] = provider.name
        
        # Update capability index
        for capability in provider.capabilities:
            if capability not in self._capability_index:
                self._capability_index[capability] = set()
            self._capability_index[capability].add(provider.name)
    
    def _clear_provider_cache(self, provider_name: str):
        """Clear caches when a provider is removed"""
        # Clear model routing
        models_to_remove = [
            model for model, pname in self._model_routing.items()
            if pname == provider_name
        ]
        for model in models_to_remove:
            del self._model_routing[model]
        
        # Clear capability index
        for capability_providers in self._capability_index.values():
            capability_providers.discard(provider_name)
    
    async def _broadcast_provider_status(self, provider_name: str, status: str):
        """Broadcast provider status change"""
        if self.sio:
            await self.sio.emit(
                'provider:status',
                {
                    "provider": provider_name,
                    "status": status,
                    "timestamp": datetime.utcnow().isoformat()
                },
                namespace='/providers'
            )
    
    async def monitor_health(self, interval: int = 30):
        """Monitor provider health with heartbeats"""
        while True:
            try:
                now = datetime.utcnow()
                disconnected = []
                
                for sid, provider in self.providers.items():
                    # Check if heartbeat is stale (> 60 seconds)
                    if (now - provider.last_heartbeat).total_seconds() > 60:
                        logger.warning(f"Provider {provider.name} heartbeat is stale")
                        disconnected.append(sid)
                
                # Remove stale providers
                for sid in disconnected:
                    await self.handle_provider_disconnect(sid)
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(interval)