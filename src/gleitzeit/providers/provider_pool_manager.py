"""
Provider Pool Manager for Stateless Provider Management

Manages multiple provider pools and routes tasks to appropriate providers.
Replaces singleton ProviderHub with pooled, stateless approach.
"""

import asyncio
import logging
from typing import Dict, Optional, Any, Type, List
from dataclasses import dataclass
import json

from gleitzeit.providers.provider_pool import ProviderPool, PooledProvider
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.models import Task
from gleitzeit.core.protocol import ProtocolSpec
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse, JSONRPCError
from gleitzeit.core.errors import ProviderNotFoundError, ErrorCode

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Configuration for a provider type"""
    provider_type: str
    provider_class: Type[Any]
    protocol: str
    min_pool_size: int = 1
    max_pool_size: int = 10
    max_idle_time: int = 300
    health_check_interval: int = 60
    supported_methods: List[str] = None


class ProviderRegistry:
    """
    Stateless provider registry using persistence.
    All provider metadata stored in persistence layer.
    """
    
    def __init__(self, persistence: PersistenceBackend):
        """
        Initialize stateless registry.
        
        Args:
            persistence: Backend for storing provider metadata
        """
        self.persistence = persistence
        self._registry_prefix = "provider:registry:"
        self._config_prefix = "provider:config:"
    
    async def register_provider_type(
        self,
        provider_type: str,
        config: ProviderConfig
    ):
        """
        Register a new provider type configuration.
        
        Args:
            provider_type: Unique identifier for provider type
            config: Provider configuration
        """
        # Store configuration in persistence
        config_data = {
            "provider_type": config.provider_type,
            "provider_class": f"{config.provider_class.__module__}.{config.provider_class.__name__}",
            "protocol": config.protocol,
            "min_pool_size": config.min_pool_size,
            "max_pool_size": config.max_pool_size,
            "max_idle_time": config.max_idle_time,
            "health_check_interval": config.health_check_interval,
            "supported_methods": config.supported_methods or []
        }
        
        key = f"{self._config_prefix}{provider_type}"
        await self.persistence.set(key, json.dumps(config_data))
        
        # Register protocol mapping
        protocol_key = f"{self._registry_prefix}{config.protocol}"
        existing = await self.persistence.get(protocol_key)
        
        if existing:
            # Handle both cases: already deserialized list or JSON string
            if isinstance(existing, list):
                providers = existing
            else:
                providers = json.loads(existing)
            if provider_type not in providers:
                providers.append(provider_type)
        else:
            providers = [provider_type]
        
        await self.persistence.set(protocol_key, json.dumps(providers))
        
        logger.info(f"Registered provider type: {provider_type} for protocol: {config.protocol}")
    
    async def get_provider_config(self, provider_type: str) -> Optional[Dict[str, Any]]:
        """
        Get provider configuration from persistence.
        
        Args:
            provider_type: Provider type identifier
            
        Returns:
            Provider configuration or None if not found
        """
        key = f"{self._config_prefix}{provider_type}"
        data = await self.persistence.get(key)
        
        if data:
            # Handle both cases: already deserialized dict or JSON string
            if isinstance(data, dict):
                return data
            else:
                return json.loads(data)
        return None
    
    async def get_providers_for_protocol(self, protocol: str) -> List[str]:
        """
        Get all provider types supporting a protocol.
        
        Args:
            protocol: Protocol identifier
            
        Returns:
            List of provider type identifiers
        """
        key = f"{self._registry_prefix}{protocol}"
        data = await self.persistence.get(key)
        
        if data:
            # Handle both cases: already deserialized list or JSON string
            if isinstance(data, list):
                return data
            else:
                return json.loads(data)
        return []
    
    async def list_provider_types(self) -> List[str]:
        """
        List all registered provider types.
        
        Returns:
            List of provider type identifiers
        """
        # Get all config keys
        pattern = f"{self._config_prefix}*"
        keys = await self.persistence.list_keys(pattern)
        
        # Extract provider types from keys
        provider_types = []
        for key in keys:
            provider_type = key.replace(self._config_prefix, "")
            provider_types.append(provider_type)
        
        return provider_types


class ProviderPoolManager:
    """
    Manages pools of provider instances for stateless operation.
    Each provider type has its own pool with configurable sizing.
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        default_min_size: int = 1,
        default_max_size: int = 10
    ):
        """
        Initialize provider pool manager.
        
        Args:
            persistence: Backend for provider registry and state
            default_min_size: Default minimum pool size
            default_max_size: Default maximum pool size
        """
        self.persistence = persistence
        self.registry = ProviderRegistry(persistence)
        self.default_min_size = default_min_size
        self.default_max_size = default_max_size
        
        # Provider pools by type
        self.provider_pools: Dict[str, ProviderPool] = {}
        
        # Protocol to provider mapping cache
        self._protocol_cache: Dict[str, List[str]] = {}
        
        # Lock for pool creation
        self._pool_lock = asyncio.Lock()
        
        self._initialized = False
        self._shutdown = False
        
        logger.info(f"Created ProviderPoolManager with defaults "
                   f"(min={default_min_size}, max={default_max_size})")
    
    async def initialize(self):
        """Initialize the pool manager"""
        if self._initialized:
            return
        
        self._initialized = True
        logger.info("ProviderPoolManager initialized")
    
    async def register_provider(
        self,
        provider_type: str,
        provider_class: Type[Any],
        protocol: str,
        min_pool_size: Optional[int] = None,
        max_pool_size: Optional[int] = None,
        **kwargs
    ):
        """
        Register a provider type and create its pool.
        
        Args:
            provider_type: Unique identifier for provider type
            provider_class: Class to instantiate for providers
            protocol: Protocol this provider supports
            min_pool_size: Minimum pool size (or use default)
            max_pool_size: Maximum pool size (or use default)
            **kwargs: Additional provider configuration
        """
        # Create configuration
        config = ProviderConfig(
            provider_type=provider_type,
            provider_class=provider_class,
            protocol=protocol,
            min_pool_size=min_pool_size or self.default_min_size,
            max_pool_size=max_pool_size or self.default_max_size,
            **kwargs
        )
        
        # Register in persistence
        await self.registry.register_provider_type(provider_type, config)
        
        # Create pool if not exists
        if provider_type not in self.provider_pools:
            await self._create_pool(provider_type, config)
        
        # Clear protocol cache
        self._protocol_cache.clear()
    
    async def _create_pool(self, provider_type: str, config: ProviderConfig):
        """Create a provider pool"""
        async with self._pool_lock:
            if provider_type in self.provider_pools:
                return
            
            pool = ProviderPool(
                provider_type=provider_type,
                provider_class=config.provider_class,
                min_size=config.min_pool_size,
                max_size=config.max_pool_size,
                max_idle_time=config.max_idle_time,
                health_check_interval=config.health_check_interval,
                persistence=self.persistence
            )
            
            await pool.initialize()
            self.provider_pools[provider_type] = pool
            
            logger.info(f"Created pool for provider type: {provider_type}")
    
    async def get_provider(
        self,
        protocol: str,
        provider_type: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> PooledProvider:
        """
        Get a provider instance for a protocol.
        
        Args:
            protocol: Protocol the provider must support
            provider_type: Specific provider type (optional)
            timeout: Acquisition timeout in seconds
            
        Returns:
            PooledProvider instance
            
        Raises:
            ProviderNotFoundError: If no suitable provider found
            TimeoutError: If acquisition times out
        """
        if self._shutdown:
            raise RuntimeError("ProviderPoolManager is shutdown")
        
        # If specific provider type requested
        if provider_type:
            if provider_type not in self.provider_pools:
                raise ProviderNotFoundError(f"Provider type not found: {provider_type}")
            
            pool = self.provider_pools[provider_type]
            return await pool.acquire(timeout)
        
        # Find providers for protocol
        if protocol not in self._protocol_cache:
            provider_types = await self.registry.get_providers_for_protocol(protocol)
            self._protocol_cache[protocol] = provider_types
        else:
            provider_types = self._protocol_cache[protocol]
        
        if not provider_types:
            raise ProviderNotFoundError(f"No providers found for protocol: {protocol}")
        
        # Try to acquire from first available pool
        # TODO: Add load balancing logic here
        for ptype in provider_types:
            if ptype in self.provider_pools:
                try:
                    pool = self.provider_pools[ptype]
                    return await pool.acquire(timeout)
                except TimeoutError:
                    continue
        
        raise ProviderNotFoundError(f"No available providers for protocol: {protocol}")
    
    async def release_provider(self, provider: PooledProvider):
        """
        Return a provider to its pool.
        
        Args:
            provider: Provider to release
        """
        if not provider or not provider.provider_type:
            logger.warning(f"Invalid provider for release: {provider}")
            return
        
        pool = self.provider_pools.get(provider.provider_type)
        if pool:
            await pool.release(provider)
        else:
            logger.warning(f"No pool found for provider type: {provider.provider_type}")
    
    async def execute_task(self, task: Task) -> Any:
        """
        Execute a task using a pooled provider.
        
        Args:
            task: Task to execute
            
        Returns:
            Task execution result
            
        Raises:
            ProviderNotFoundError: If no suitable provider found
            TaskExecutionError: If task execution fails
        """
        provider = None
        try:
            # Get provider for task protocol
            provider = await self.get_provider(
                protocol=task.protocol,
                timeout=30.0
            )
            
            # Mark provider with current task
            provider.current_task_id = task.id
            
            # Create JSONRPC request
            request = JSONRPCRequest(
                method=task.method,
                params=task.params,
                id=task.id
            )
            
            # Execute through provider instance
            # All ProtocolProvider subclasses should have handle_request(method, params)
            if hasattr(provider.instance, 'handle_request'):
                # Standard interface: handle_request(method, params)
                result = await provider.instance.handle_request(task.method, task.params)
            elif hasattr(provider.instance, 'execute'):
                # Fallback to execute method (legacy interface)
                result = await provider.instance.execute(task.method, task.params)
            else:
                # Try direct method call
                method = getattr(provider.instance, task.method, None)
                if method:
                    result = await method(**task.params)
                else:
                    raise AttributeError(f"Provider has no method: {task.method} or handle_request")
            
            return result
            
        except Exception as e:
            # Mark provider error
            if provider:
                provider.error_count += 1
            raise
            
        finally:
            # Always release provider
            if provider:
                provider.current_task_id = None
                await self.release_provider(provider)
    
    async def shutdown(self):
        """Shutdown all provider pools"""
        self._shutdown = True
        
        # Shutdown all pools
        shutdown_tasks = []
        for pool in self.provider_pools.values():
            shutdown_tasks.append(pool.shutdown())
        
        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks, return_exceptions=True)
        
        self.provider_pools.clear()
        self._protocol_cache.clear()
        
        logger.info("ProviderPoolManager shutdown complete")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all pools"""
        stats = {
            "total_pools": len(self.provider_pools),
            "pools": {}
        }
        
        for provider_type, pool in self.provider_pools.items():
            stats["pools"][provider_type] = pool.get_stats()
        
        return stats