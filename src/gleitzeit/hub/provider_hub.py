"""
Provider Hub - Centralized provider management with pooling

Manages provider pools and handles client connections without blocking.
"""
import asyncio
import logging
from typing import Dict, Optional, Any, Type, Set
from datetime import datetime

from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceStatus, ResourceType
from gleitzeit.providers.provider_pool_manager import ProviderPoolManager
from gleitzeit.providers.pooling_adapter import PoolingAdapter
from gleitzeit.persistence.unified_persistence import UnifiedPersistence
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.providers.python_provider import PythonProvider
try:
    from gleitzeit.providers.shell_provider import ShellProvider
except ImportError:
    ShellProvider = None

logger = logging.getLogger(__name__)


class ProviderHubConfig:
    """Configuration for provider hub"""
    def __init__(
        self,
        min_pool_size: int = 0,  # Start with 0 to avoid blocking
        max_pool_size: int = 10,
        enable_pooling: bool = True,
        auto_register_providers: bool = True
    ):
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.enable_pooling = enable_pooling
        self.auto_register_providers = auto_register_providers


class ProviderHub(ResourceHub):
    """
    Centralized hub for managing providers with pooling.
    
    This hub runs as a separate service that clients can connect to,
    avoiding the blocking issues of creating providers in the client.
    """
    
    def __init__(
        self,
        hub_id: str = "provider-hub",
        config: Optional[ProviderHubConfig] = None,
        persistence: Optional[Any] = None
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.CUSTOM,
            persistence=persistence
        )
        
        self.config = config or ProviderHubConfig()
        
        # Initialize pooling if enabled
        if self.config.enable_pooling:
            self.pooling_adapter = PoolingAdapter(
                persistence=persistence or UnifiedPersistence(),
                min_pool_size=self.config.min_pool_size,
                max_pool_size=self.config.max_pool_size
            )
        else:
            self.pooling_adapter = None
        
        self._initialized = False
        self._registered_protocols: Set[str] = set()
        
        logger.info(f"Created ProviderHub {hub_id} with pooling={config.enable_pooling if config else True}")
    
    async def initialize(self) -> None:
        """Initialize the hub and register default providers"""
        if self._initialized:
            return
        
        # Initialize pooling adapter
        if self.pooling_adapter:
            await self.pooling_adapter.initialize()
        
        # Auto-register default providers if configured
        if self.config.auto_register_providers:
            await self._register_default_providers()
        
        self._initialized = True
        logger.info(f"ProviderHub initialized with {len(self._registered_protocols)} protocols")
    
    async def _register_default_providers(self):
        """Register default providers with pooling"""
        if not self.pooling_adapter:
            return
        
        # Register Python provider with pooling
        # Pass the class, not an instance, to avoid constructor issues
        await self.pooling_adapter.register_provider(
            provider_id="python",
            protocol_id="python/v1",
            provider_instance=PythonProvider,  # Pass class, not instance
            supported_methods={"python/execute", "python/exec", "exec"}
        )
        self._registered_protocols.add("python/v1")
        
        # Register Shell provider with pooling
        if ShellProvider:  # Only if shell provider exists
            await self.pooling_adapter.register_provider(
                provider_id="shell",
                protocol_id="shell/v1", 
                provider_instance=ShellProvider,  # Pass class, not instance
                supported_methods={"shell/execute", "shell/exec"}
            )
            self._registered_protocols.add("shell/v1")
        
        logger.info(f"Registered default providers: {self._registered_protocols}")
    
    async def execute_request(
        self,
        protocol_id: str,
        request: JSONRPCRequest
    ) -> JSONRPCResponse:
        """
        Execute a request through pooled providers.
        
        This is the main entry point for clients to execute tasks.
        """
        if not self.pooling_adapter:
            raise RuntimeError("Pooling not enabled")
        
        return await self.pooling_adapter.execute_request(protocol_id, request)
    
    async def register_provider(
        self,
        provider_id: str,
        protocol_id: str,
        provider_class: Type[Any],
        supported_methods: Optional[Set[str]] = None
    ):
        """
        Register a new provider type with the hub.
        
        Args:
            provider_id: Unique provider identifier
            protocol_id: Protocol this provider supports
            provider_class: Provider class (not instance)
            supported_methods: Methods this provider supports
        """
        if self.pooling_adapter:
            await self.pooling_adapter.register_provider(
                provider_id=provider_id,
                protocol_id=protocol_id,
                provider_instance=provider_class,
                supported_methods=supported_methods
            )
            self._registered_protocols.add(protocol_id)
            logger.info(f"Registered provider {provider_id} for protocol {protocol_id}")
    
    def is_protocol_available(self, protocol: str) -> bool:
        """Check if a protocol has registered providers"""
        return protocol in self._registered_protocols
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get hub statistics"""
        stats = {
            "hub_id": self.hub_id,
            "initialized": self._initialized,
            "protocols": list(self._registered_protocols),
            "pooling_enabled": self.config.enable_pooling
        }
        
        if self.pooling_adapter:
            stats["pool_stats"] = self.pooling_adapter.get_stats()
        
        return stats
    
    async def cleanup(self) -> None:
        """Cleanup hub resources"""
        if self.pooling_adapter:
            await self.pooling_adapter.shutdown()
        
        await super().cleanup()
        logger.info(f"ProviderHub {self.hub_id} cleaned up")


async def start_provider_hub_server(
    host: str = "0.0.0.0",
    port: int = 8090,
    config: Optional[ProviderHubConfig] = None
) -> ProviderHub:
    """
    Start a standalone provider hub server.
    
    This can run as a separate process that clients connect to.
    """
    try:
        from aiohttp import web
    except ImportError:
        logger.error("aiohttp not installed - required for hub server")
        raise ImportError("Please install aiohttp: pip install aiohttp")
    
    # Create hub
    hub = ProviderHub(config=config)
    await hub.initialize()
    
    # Create web routes for hub API
    async def handle_execute(request):
        """Handle execution requests"""
        data = await request.json()
        protocol_id = data.get("protocol")
        jsonrpc_request = JSONRPCRequest(**data.get("request", {}))
        
        response = await hub.execute_request(protocol_id, jsonrpc_request)
        return web.json_response(response.dict())
    
    async def handle_stats(request):
        """Handle stats requests"""
        stats = await hub.get_stats()
        return web.json_response(stats)
    
    async def handle_health(request):
        """Health check endpoint"""
        return web.json_response({"status": "healthy"})
    
    # Setup web app
    app = web.Application()
    app.router.add_post("/execute", handle_execute)
    app.router.add_get("/stats", handle_stats)
    app.router.add_get("/health", handle_health)
    
    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    logger.info(f"ProviderHub server started on {host}:{port}")
    return hub