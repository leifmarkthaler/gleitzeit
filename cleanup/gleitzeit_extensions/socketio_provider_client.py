"""
Socket.IO Provider Client

Base client for creating Socket.IO-based providers that connect to the Gleitzeit cluster.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from abc import ABC, abstractmethod
import socketio
import sys
from pathlib import Path

# Ensure we can import service discovery
try:
    sys.path.append(str(Path(__file__).parent.parent))
    from gleitzeit_cluster.communication.service_discovery import get_socketio_url
except ImportError:
    # Fallback if import fails
    def get_socketio_url():
        return "http://localhost:8000"

logger = logging.getLogger(__name__)


class SocketIOProviderClient(ABC):
    """
    Base class for Socket.IO provider clients
    
    Providers (LLM, tools, extensions) should inherit from this class
    and implement the required abstract methods.
    """
    
    def __init__(
        self,
        name: str,
        provider_type: str = "unknown",
        server_url: str = None,  # Auto-discover if not provided
        models: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize provider client
        
        Args:
            name: Unique provider name
            provider_type: Type of provider (llm, tool, extension)
            server_url: Socket.IO server URL
            models: List of supported models (for LLM providers)
            capabilities: List of capabilities
            description: Provider description
            metadata: Additional metadata
        """
        self.name = name
        self.provider_type = provider_type
        self.server_url = server_url or get_socketio_url()  # Auto-discover
        self.models = models or []
        self.capabilities = capabilities or []
        self.description = description
        self.metadata = metadata or {}
        
        # Socket.IO client
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.provider_id = None
        
        # Heartbeat task
        self._heartbeat_task = None
        self._heartbeat_interval = 30  # seconds
        
        # Setup handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        # Connection events
        self.sio.on('connect', namespace='/providers')(self._on_connect)
        self.sio.on('disconnect', namespace='/providers')(self._on_disconnect)
        
        # Provider method invocations
        self.sio.on('invoke', namespace='/providers')(self._handle_invoke)
        self.sio.on('generate', namespace='/providers')(self._handle_generate)
        self.sio.on('get_tools', namespace='/providers')(self._handle_get_tools)
        
        # Streaming
        self.sio.on('stream:start', namespace='/providers')(self._handle_stream_start)
        self.sio.on('stream:cancel', namespace='/providers')(self._handle_stream_cancel)
    
    async def connect(self):
        """Connect to Socket.IO server and register as provider"""
        try:
            logger.info(f"Connecting to {self.server_url}")
            await self.sio.connect(
                self.server_url,
                namespaces=['/providers']
            )
            self.connected = True
            
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from Socket.IO server"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self.connected:
            await self.sio.disconnect()
            self.connected = False
    
    async def _on_connect(self):
        """Handle connection establishment"""
        logger.info(f"Connected to server, registering provider: {self.name}")
        
        # Register as provider
        response = await self.sio.call(
            'provider:register',
            {
                'name': self.name,
                'type': self.provider_type,
                'models': self.models,
                'capabilities': self.capabilities,
                'description': self.description,
                'metadata': self.metadata
            },
            namespace='/providers'
        )
        
        if response.get('success'):
            self.provider_id = response.get('provider_id')
            logger.info(f"Provider registered successfully: {self.provider_id}")
            
            # Start heartbeat
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            # Call setup hook
            await self.on_connected()
        else:
            logger.error(f"Failed to register: {response.get('error')}")
            await self.disconnect()
    
    async def _on_disconnect(self):
        """Handle disconnection"""
        logger.info(f"Disconnected from server")
        self.connected = False
        self.provider_id = None
        
        # Call cleanup hook
        await self.on_disconnected()
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats"""
        while self.connected:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                
                if self.connected:
                    # Send heartbeat with health status
                    health = await self.get_health_status()
                    
                    await self.sio.emit(
                        'provider:heartbeat',
                        {'status': health},
                        namespace='/providers'
                    )
                    
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def _handle_invoke(self, data):
        """Handle method invocation request"""
        try:
            method = data.get('method', 'invoke')
            args = data.get('args', {})
            
            # Call the provider's invoke method
            result = await self.invoke(method, **args)
            
            return {"success": True, "result": result}
            
        except Exception as e:
            logger.error(f"Invocation error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_generate(self, data):
        """Handle generation request (for LLM providers)"""
        try:
            result = await self.generate(**data)
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_get_tools(self, data):
        """Handle tools listing request"""
        try:
            tools = await self.get_tools()
            return {"success": True, "tools": tools}
        except Exception as e:
            logger.error(f"Get tools error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_stream_start(self, data):
        """Handle streaming request"""
        stream_id = data.get('stream_id')
        client_sid = data.get('client_sid')
        args = data.get('args', {})
        
        try:
            # Start streaming
            async for chunk in self.stream(**args):
                if not self.connected:
                    break
                    
                # Send chunk to client
                await self.sio.emit(
                    'stream:data',
                    {
                        'stream_id': stream_id,
                        'data': chunk
                    },
                    namespace='/providers',
                    to=client_sid
                )
            
            # Send end of stream
            await self.sio.emit(
                'stream:end',
                {'stream_id': stream_id},
                namespace='/providers',
                to=client_sid
            )
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            await self.sio.emit(
                'stream:error',
                {
                    'stream_id': stream_id,
                    'error': str(e)
                },
                namespace='/providers',
                to=client_sid
            )
    
    async def _handle_stream_cancel(self, data):
        """Handle stream cancellation"""
        # Implementation depends on specific provider
        pass
    
    # === Abstract Methods (must be implemented by subclasses) ===
    
    @abstractmethod
    async def invoke(self, method: str, **kwargs) -> Any:
        """
        Invoke a method on the provider
        
        Args:
            method: Method name
            **kwargs: Method arguments
            
        Returns:
            Method result
        """
        pass
    
    @abstractmethod
    async def get_health_status(self) -> Dict[str, Any]:
        """
        Get provider health status
        
        Returns:
            Health status dictionary
        """
        pass
    
    # === Optional Methods (can be overridden) ===
    
    async def on_connected(self):
        """Called when provider is successfully connected and registered"""
        pass
    
    async def on_disconnected(self):
        """Called when provider is disconnected"""
        pass
    
    async def generate(self, **kwargs) -> Any:
        """Generate content (for LLM providers)"""
        raise NotImplementedError(f"Provider {self.name} does not support generation")
    
    async def get_tools(self) -> List[Dict[str, Any]]:
        """Get available tools (for tool providers)"""
        return []
    
    async def stream(self, **kwargs):
        """Stream responses (async generator)"""
        raise NotImplementedError(f"Provider {self.name} does not support streaming")
    
    # === Helper Methods ===
    
    async def update_models(self, models: List[str]):
        """Update the list of supported models"""
        self.models = models
        if self.connected:
            # Notify server of model update
            await self.sio.emit(
                'provider:update',
                {
                    'models': models
                },
                namespace='/providers'
            )
    
    async def update_capabilities(self, capabilities: List[str]):
        """Update the list of capabilities"""
        self.capabilities = capabilities
        if self.connected:
            # Notify server of capability update
            await self.sio.emit(
                'provider:update',
                {
                    'capabilities': capabilities
                },
                namespace='/providers'
            )
    
    async def run(self):
        """Run the provider client (connects and maintains connection)"""
        try:
            await self.connect()
            
            # Keep running until disconnected
            while self.connected:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Shutting down provider client")
        finally:
            await self.disconnect()


# === Example Provider Implementations ===

class OpenAIProvider(SocketIOProviderClient):
    """Example OpenAI provider implementation"""
    
    def __init__(self, api_key: str, **kwargs):
        super().__init__(
            name="openai",
            provider_type="llm",
            models=["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
            capabilities=["text", "vision", "function_calling", "streaming"],
            description="OpenAI GPT models provider",
            **kwargs
        )
        self.api_key = api_key
        # Initialize OpenAI client here
    
    async def invoke(self, method: str, **kwargs) -> Any:
        if method == "complete":
            return await self.complete(**kwargs)
        elif method == "embed":
            return await self.embed(**kwargs)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def complete(self, prompt: str, model: str = "gpt-4", **kwargs):
        """Complete text using OpenAI"""
        # Actual OpenAI API call would go here
        return f"Mock completion for: {prompt}"
    
    async def embed(self, text: str, model: str = "text-embedding-ada-002"):
        """Generate embeddings"""
        # Actual embedding call would go here
        return [0.1, 0.2, 0.3]  # Mock embedding
    
    async def generate(self, **kwargs):
        """Generate content"""
        return await self.complete(**kwargs)
    
    async def stream(self, prompt: str, model: str = "gpt-4", **kwargs):
        """Stream responses"""
        # Mock streaming
        words = prompt.split()
        for word in words:
            yield {"content": word + " "}
            await asyncio.sleep(0.1)
    
    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "api_key_set": bool(self.api_key),
            "models_available": len(self.models)
        }


class ToolProvider(SocketIOProviderClient):
    """Example tool provider implementation"""
    
    def __init__(self, **kwargs):
        super().__init__(
            name="calculator",
            provider_type="tool",
            capabilities=["math", "calculation"],
            description="Basic calculator tools",
            **kwargs
        )
        self.tools = [
            {
                "name": "add",
                "description": "Add two numbers",
                "parameters": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                }
            },
            {
                "name": "multiply",
                "description": "Multiply two numbers",
                "parameters": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                }
            }
        ]
    
    async def invoke(self, method: str, **kwargs) -> Any:
        if method == "add":
            return kwargs.get('a', 0) + kwargs.get('b', 0)
        elif method == "multiply":
            return kwargs.get('a', 0) * kwargs.get('b', 0)
        else:
            raise ValueError(f"Unknown tool: {method}")
    
    async def get_tools(self) -> List[Dict[str, Any]]:
        return self.tools
    
    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "tools_count": len(self.tools)
        }