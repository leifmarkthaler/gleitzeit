"""
Simple Provider Hub - Direct provider management without pooling complexity

A simplified hub that creates providers on-demand without pooling.
"""
import asyncio
import logging
from typing import Dict, Optional, Any, Set

from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse, JSONRPCError
from gleitzeit.core.errors import ErrorCode
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.hub.ollama_hub import OllamaHub

logger = logging.getLogger(__name__)


class SimpleProviderHub:
    """
    Simple provider hub that creates providers on-demand.
    
    This avoids the complexity of pooling while still allowing
    clients to connect to a central hub.
    """
    
    def __init__(self):
        self.providers = {}
        self._initialized = False
        logger.info("Created SimpleProviderHub")
    
    async def initialize(self):
        """Initialize the hub and create providers using factory"""
        if self._initialized:
            return
        
        # Use ProviderFactory for proper provider creation
        from gleitzeit.providers.factory import ProviderFactory
        
        factory = ProviderFactory(
            strict_validation=False,
            auto_fix=True,
            debug_mode=False
        )
        
        # Create Python provider with proper initialization
        python_provider = factory.create_provider(
            PythonProvider,
            provider_id="python",
            protocol_id="python/v1",
            validate=True
        )
        await python_provider.initialize()
        self.providers["python/v1"] = python_provider
        
        # Create Ollama provider with OllamaHub for resource management
        try:
            # First create and initialize OllamaHub
            ollama_hub = OllamaHub(
                hub_id="ollama-hub",
                auto_discover=True  # Auto-discover running Ollama instances
            )
            await ollama_hub.initialize()
            instances = ollama_hub.list_instances()
            # Check if it's a coroutine (async method)
            if asyncio.iscoroutine(instances):
                instances = await instances
            logger.info(f"OllamaHub initialized, discovered {len(instances) if instances else 0} Ollama instances")
            
            # Create Ollama provider with hub
            ollama_provider = factory.create_provider(
                OllamaProvider,
                provider_id="ollama",
                protocol_id="llm/v1",
                hub=ollama_hub,  # Pass the hub for resource management
                validate=True
            )
            await ollama_provider.initialize()
            self.providers["llm/v1"] = ollama_provider
            self.ollama_hub = ollama_hub  # Store hub for cleanup
            logger.info("Ollama provider initialized successfully with hub")
        except Exception as e:
            logger.warning(f"Failed to initialize Ollama provider: {e}")
            # Continue without Ollama if it fails (might not be installed)
        
        self._initialized = True
        logger.info(f"SimpleProviderHub initialized with {len(self.providers)} providers")
    
    async def execute_request(
        self,
        protocol_id: str,
        request: JSONRPCRequest
    ) -> JSONRPCResponse:
        """Execute a request through the appropriate provider"""
        provider = self.providers.get(protocol_id)
        
        if not provider:
            return JSONRPCResponse(
                error=JSONRPCError(
                    code=ErrorCode.PROVIDER_NOT_FOUND,
                    message=f"No provider for protocol: {protocol_id}"
                ),
                id=request.id
            )
        
        try:
            # Execute through provider - handle different interfaces
            if hasattr(provider, 'handle_request'):
                # Check if it expects JSONRPCRequest or (method, params)
                import inspect
                sig = inspect.signature(provider.handle_request)
                params = list(sig.parameters.keys())
                
                if len(params) >= 3 or 'method' in params:
                    # Expects (self, method, params) style
                    result = await provider.handle_request(request.method, request.params or {})
                    return JSONRPCResponse(result=result, id=request.id)
                else:
                    # Expects (self, request) style
                    return await provider.handle_request(request)
            elif hasattr(provider, 'execute'):
                # Try execute with different signatures
                try:
                    # Try (method, params) style first
                    result = await provider.execute(request.method, request.params or {})
                    return JSONRPCResponse(result=result, id=request.id)
                except TypeError:
                    # Fall back to (request) style
                    return await provider.execute(request)
            else:
                # Try direct method call
                method = getattr(provider, request.method, None)
                if method:
                    result = await method(**request.params)
                    return JSONRPCResponse(result=result, id=request.id)
                else:
                    return JSONRPCResponse(
                        error=JSONRPCError(
                            code=ErrorCode.METHOD_NOT_FOUND,
                            message=f"Method not found: {request.method}"
                        ),
                        id=request.id
                    )
        except Exception as e:
            logger.error(f"Error executing request: {e}")
            return JSONRPCResponse(
                error=JSONRPCError(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=str(e)
                ),
                id=request.id
            )
    
    async def cleanup(self):
        """Cleanup hub resources"""
        # Cleanup OllamaHub if it exists
        if hasattr(self, 'ollama_hub'):
            await self.ollama_hub.cleanup()
            logger.info("OllamaHub cleaned up")
        
        # Cleanup providers
        for provider in self.providers.values():
            if hasattr(provider, 'cleanup'):
                await provider.cleanup()
        logger.info("SimpleProviderHub cleaned up")


async def start_simple_hub_server(
    host: str = "127.0.0.1",
    port: int = 8090
):
    """Start a simple provider hub server"""
    try:
        from aiohttp import web
    except ImportError:
        logger.error("aiohttp required for hub server")
        raise
    
    # Create and initialize hub
    hub = SimpleProviderHub()
    await hub.initialize()
    
    # Define web handlers
    async def handle_execute(request):
        """Handle execution requests"""
        try:
            data = await request.json()
            protocol_id = data.get("protocol", "python/v1")
            jsonrpc_request = JSONRPCRequest(**data.get("request", {}))
            
            response = await hub.execute_request(protocol_id, jsonrpc_request)
            return web.json_response(response.dict())
        except Exception as e:
            logger.error(f"Request handling error: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def handle_health(request):
        """Health check"""
        return web.json_response({"status": "healthy"})
    
    async def handle_stats(request):
        """Get stats"""
        return web.json_response({
            "protocols": list(hub.providers.keys()),
            "initialized": hub._initialized
        })
    
    # Setup web app
    app = web.Application()
    app.router.add_post("/execute", handle_execute)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/stats", handle_stats)
    
    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    logger.info(f"SimpleProviderHub server running on {host}:{port}")
    
    # Keep server running
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await runner.cleanup()
        await hub.cleanup()