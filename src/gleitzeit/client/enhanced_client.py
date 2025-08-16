"""
Enhanced Gleitzeit Client with Provider Auto-Discovery
Extends the base client with streamlined provider support
"""

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
import tempfile

from gleitzeit.client.api import GleitzeitClient
from gleitzeit.providers.ollama_pool_provider import OllamaPoolProvider
from gleitzeit.providers.ollama_provider_streamlined import OllamaProviderStreamlined
from gleitzeit.providers.python_provider_streamlined import PythonProviderStreamlined
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider

logger = logging.getLogger(__name__)


class EnhancedGleitzeitClient(GleitzeitClient):
    """
    Enhanced client with auto-discovery and streamlined provider support
    
    This extends the base GleitzeitClient with:
    - Auto-discovery of providers (Ollama, Docker, MCP)
    - Option to use streamlined providers
    - Automatic fallback to basic providers
    - Configuration file support
    
    Usage:
        # Auto-discover everything
        client = EnhancedGleitzeitClient(auto_discover=True)
        
        # Use streamlined providers
        client = EnhancedGleitzeitClient(use_streamlined=True)
        
        # Both options
        client = EnhancedGleitzeitClient(
            auto_discover=True,
            use_streamlined=True
        )
    """
    
    def __init__(
        self,
        persistence: str = "sqlite",
        db_path: Optional[str] = None,
        redis_url: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        debug: bool = False,
        auto_discover: bool = False,
        use_streamlined: bool = False,
        config_file: Optional[str] = None
    ):
        """
        Initialize enhanced client
        
        Args:
            persistence: Backend type ("sqlite", "redis", "memory")
            db_path: SQLite database path
            redis_url: Redis connection URL
            ollama_url: Default Ollama API endpoint
            debug: Enable debug mode
            auto_discover: Auto-discover available providers
            use_streamlined: Use streamlined providers instead of basic
            config_file: Path to configuration file (YAML/TOML)
        """
        super().__init__(
            persistence=persistence,
            db_path=db_path,
            redis_url=redis_url,
            ollama_url=ollama_url,
            debug=debug
        )
        
        self.auto_discover = auto_discover
        self.use_streamlined = use_streamlined
        self.config_file = config_file
        self.discovered_providers = []
    
    async def initialize(self):
        """Initialize with enhanced provider registration"""
        if self._initialized:
            return
        
        # Initialize base components (backend, registry, protocols)
        await self._initialize_base()
        
        # Register providers based on configuration
        if self.auto_discover:
            await self._auto_discover_providers()
        elif self.use_streamlined:
            await self._register_streamlined_providers()
        else:
            await self._register_basic_providers()
        
        # Setup execution engine and batch processor
        await self._setup_engine()
        
        self._initialized = True
        logger.info(f"Enhanced client initialized with {len(self.discovered_providers)} providers")
    
    async def _initialize_base(self):
        """Initialize backend and registry"""
        # Setup persistence
        if self.persistence_type == "redis":
            from gleitzeit.persistence.redis_backend import RedisBackend
            self.backend = RedisBackend(self.redis_url or "redis://localhost:6379/0")
        elif self.persistence_type == "memory":
            from gleitzeit.persistence.base import InMemoryBackend
            self.backend = InMemoryBackend()
        else:  # sqlite
            from gleitzeit.persistence.sqlite_backend import SQLiteBackend
            if not self.db_path:
                self.db_path = Path(tempfile.gettempdir()) / "gleitzeit.db"
            self.backend = SQLiteBackend(str(self.db_path))
        
        await self.backend.initialize()
        
        # Setup registry and protocols
        from gleitzeit.registry import ProtocolProviderRegistry
        from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1
        
        self.registry = ProtocolProviderRegistry()
        self.registry.register_protocol(PYTHON_PROTOCOL_V1)
        self.registry.register_protocol(LLM_PROTOCOL_V1)
        self.registry.register_protocol(MCP_PROTOCOL_V1)
    
    async def _auto_discover_providers(self):
        """Auto-discover and register available providers"""
        logger.info("Auto-discovering providers...")
        
        # Discover Ollama instances
        ollama_provider = await self._discover_ollama()
        if ollama_provider:
            await self._register_provider(ollama_provider, "llm/v1")
        
        # Discover Python/Docker
        python_provider = await self._discover_python()
        if python_provider:
            await self._register_provider(python_provider, "python/v1")
        
        # Always register MCP provider (built-in tools)
        mcp_provider = SimpleMCPProvider("mcp-auto")
        await self._register_provider(mcp_provider, "mcp/v1")
    
    async def _discover_ollama(self):
        """Discover Ollama instances and create appropriate provider"""
        try:
            if self.use_streamlined:
                # Use streamlined provider with auto-discovery
                provider = OllamaProviderStreamlined(
                    provider_id="ollama-auto",
                    auto_discover=True
                )
                await provider.initialize()
                
                # Check if any instances were found
                status = await provider.get_status()
                if status['details']['healthy_instances'] > 0:
                    logger.info(f"Discovered {status['details']['healthy_instances']} Ollama instances")
                    return provider
                else:
                    await provider.shutdown()
            else:
                # Use OllamaPoolProvider for multiple instances
                import aiohttp
                
                # Check for Ollama instances on common ports
                instances = []
                for port in [11434, 11435, 11436]:
                    url = f"http://localhost:{port}"
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(f"{url}/api/tags", timeout=2) as resp:
                                if resp.status == 200:
                                    instances.append({
                                        "id": f"ollama-{port}",
                                        "url": url,
                                        "max_concurrent": 5
                                    })
                    except:
                        continue
                
                if len(instances) > 1:
                    # Multiple instances - use pool provider
                    provider = OllamaPoolProvider(
                        provider_id="ollama-pool-auto",
                        instances=instances
                    )
                    await provider.initialize()
                    logger.info(f"Created OllamaPoolProvider with {len(instances)} instances")
                    return provider
                elif len(instances) == 1:
                    # Single instance - use basic provider
                    from gleitzeit.providers.ollama_provider import OllamaProvider
                    provider = OllamaProvider("ollama-auto", auto_discover=False)
                    await provider.initialize()
                    logger.info("Created OllamaProvider for single instance")
                    return provider
                    
        except Exception as e:
            logger.warning(f"Ollama discovery failed: {e}")
        
        return None
    
    async def _discover_python(self):
        """Discover Python execution capability"""
        try:
            if self.use_streamlined:
                # Use streamlined Python provider
                provider = PythonProviderStreamlined(
                    provider_id="python-auto",
                    max_containers=3,
                    enable_local=True
                )
                await provider.initialize()
                logger.info("Created streamlined Python provider")
                return provider
            else:
                # Use basic provider
                from gleitzeit.providers.python_function_provider import CustomFunctionProvider
                provider = CustomFunctionProvider("python-auto")
                await provider.initialize()
                logger.info("Created basic Python provider")
                return provider
                
        except Exception as e:
            logger.warning(f"Python provider creation failed: {e}")
            return None
    
    async def _register_streamlined_providers(self):
        """Register streamlined providers without auto-discovery"""
        # Ollama
        ollama = OllamaProviderStreamlined(
            provider_id="ollama-streamlined",
            auto_discover=False  # Don't auto-discover, just use default
        )
        await self._register_provider(ollama, "llm/v1")
        
        # Python
        python = PythonProviderStreamlined(
            provider_id="python-streamlined",
            max_containers=3
        )
        await self._register_provider(python, "python/v1")
        
        # MCP
        mcp = SimpleMCPProvider("mcp-streamlined")
        await self._register_provider(mcp, "mcp/v1")
    
    async def _register_basic_providers(self):
        """Register basic providers (fallback to parent behavior)"""
        from gleitzeit.providers.ollama_provider import OllamaProvider
        from gleitzeit.providers.python_function_provider import CustomFunctionProvider
        
        # Ollama
        ollama = OllamaProvider("ollama-1", auto_discover=False)
        await self._register_provider(ollama, "llm/v1")
        
        # Python
        python = CustomFunctionProvider("python-1")
        await self._register_provider(python, "python/v1")
        
        # MCP
        mcp = SimpleMCPProvider("mcp-1")
        await self._register_provider(mcp, "mcp/v1")
    
    async def _register_provider(self, provider, protocol_id):
        """Register a provider with the registry"""
        try:
            await provider.initialize()
            self.registry.register_provider(
                provider_id=provider.provider_id,
                protocol_id=protocol_id,
                provider_instance=provider
            )
            self.discovered_providers.append(provider)
            logger.info(f"Registered provider: {provider.provider_id} for {protocol_id}")
        except Exception as e:
            logger.error(f"Failed to register provider {provider.provider_id}: {e}")
    
    async def _setup_engine(self):
        """Setup execution engine and batch processor"""
        from gleitzeit.core import ExecutionEngine
        from gleitzeit.task_queue import QueueManager, DependencyResolver
        from gleitzeit.core.batch_processor import BatchProcessor
        
        self.engine = ExecutionEngine(
            registry=self.registry,
            queue_manager=QueueManager(),
            dependency_resolver=DependencyResolver(),
            persistence=self.backend,
            max_concurrent_tasks=5
        )
        
        self.batch_processor = BatchProcessor()
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about registered providers"""
        info = {
            'total': len(self.discovered_providers),
            'providers': []
        }
        
        for provider in self.discovered_providers:
            provider_info = {
                'id': provider.provider_id,
                'type': provider.__class__.__name__
            }
            
            # Add status if available
            if hasattr(provider, 'get_status'):
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    status = loop.run_until_complete(provider.get_status())
                    provider_info['status'] = status
                except:
                    pass
            
            info['providers'].append(provider_info)
        
        return info


def create_enhanced_client(**kwargs) -> EnhancedGleitzeitClient:
    """
    Factory function to create an enhanced client
    
    Examples:
        # Auto-discover everything
        client = create_enhanced_client(auto_discover=True)
        
        # Use streamlined providers
        client = create_enhanced_client(use_streamlined=True)
        
        # Both
        client = create_enhanced_client(
            auto_discover=True,
            use_streamlined=True
        )
    """
    return EnhancedGleitzeitClient(**kwargs)