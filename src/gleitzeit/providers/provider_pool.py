"""
Provider Pool Management for Stateless Operation

Replaces singleton provider management with pooled instances,
enabling horizontal scaling and resource isolation.
"""

import asyncio
import logging
from typing import Dict, List, Set, Optional, Any, Type
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import uuid

from gleitzeit.core.protocol import ProtocolSpec
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.errors import SystemError, ResourceExhaustedError

logger = logging.getLogger(__name__)


class ProviderState(str, Enum):
    """State of a provider instance in the pool"""
    INITIALIZING = "initializing"
    AVAILABLE = "available"
    IN_USE = "in_use"
    UNHEALTHY = "unhealthy"
    TERMINATING = "terminating"


@dataclass
class PooledProvider:
    """Wrapper for a provider instance in the pool"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider_type: str = ""
    instance: Any = None
    state: ProviderState = ProviderState.INITIALIZING
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: datetime = field(default_factory=datetime.utcnow)
    use_count: int = 0
    error_count: int = 0
    current_task_id: Optional[str] = None
    
    @property
    def age_seconds(self) -> float:
        """Age of the provider in seconds"""
        return (datetime.utcnow() - self.created_at).total_seconds()
    
    @property
    def idle_seconds(self) -> float:
        """Time since last use in seconds"""
        return (datetime.utcnow() - self.last_used).total_seconds()
    
    @property
    def health_score(self) -> float:
        """Calculate health score (0-100)"""
        if self.use_count == 0:
            return 100.0
        error_rate = self.error_count / self.use_count
        return max(0, (1 - error_rate) * 100)


class ProviderPool:
    """
    Pool for a specific provider type.
    Manages lifecycle and resource allocation for provider instances.
    """
    
    def __init__(
        self,
        provider_type: str,
        provider_class: Type[Any],
        min_size: int = 1,
        max_size: int = 10,
        max_idle_time: int = 300,
        health_check_interval: int = 60,
        persistence: Optional[PersistenceBackend] = None,
        protocol_id: Optional[str] = None
    ):
        """
        Initialize provider pool.

        Args:
            provider_type: Type identifier for the provider
            provider_class: Class to instantiate for new providers
            min_size: Minimum number of providers to maintain
            max_size: Maximum number of providers allowed
            max_idle_time: Maximum idle time before provider cleanup (seconds)
            health_check_interval: Interval between health checks (seconds)
            persistence: Optional persistence backend for state
            protocol_id: Protocol ID for the provider (e.g. "python/v1")
        """
        self.provider_type = provider_type
        self.provider_class = provider_class
        self.protocol_id = protocol_id or f"{provider_type}/v1"  # Fallback for compatibility
        self.min_size = min_size
        self.max_size = max_size
        self.max_idle_time = max_idle_time
        self.health_check_interval = health_check_interval
        self.persistence = persistence
        
        # Pool state
        self.available: List[PooledProvider] = []
        self.in_use: Dict[str, PooledProvider] = {}  # provider_id -> provider
        self.unhealthy: Set[str] = set()
        
        # Synchronization
        self._lock = asyncio.Lock()
        self._acquire_semaphore = asyncio.Semaphore(max_size)
        self._initialized = False
        self._shutdown = False
        
        # Monitoring
        # No health check task - stateless operation
        
        logger.info(f"Created provider pool for {provider_type} "
                   f"(min={min_size}, max={max_size})")
    
    async def initialize(self):
        """Initialize the pool with minimum providers"""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            # Create minimum number of providers
            create_tasks = []
            for _ in range(self.min_size):
                create_tasks.append(self._create_provider())
            
            if create_tasks:
                providers = await asyncio.gather(*create_tasks, return_exceptions=True)
                for provider in providers:
                    if isinstance(provider, PooledProvider):
                        self.available.append(provider)
                    else:
                        logger.error(f"Failed to create provider: {provider}")
            
            # Health checks will be triggered externally (stateless)
            
            self._initialized = True
            logger.info(f"Initialized pool with {len(self.available)} providers")
    
    async def acquire(self, timeout: Optional[float] = None) -> PooledProvider:
        """
        Acquire a provider from the pool.
        
        Args:
            timeout: Optional timeout in seconds
            
        Returns:
            PooledProvider instance
            
        Raises:
            TimeoutError: If timeout is reached
            RuntimeError: If pool is shutdown
        """
        if self._shutdown:
            raise SystemError("Provider pool is shutdown")
        
        if not self._initialized:
            await self.initialize()
        
        # Use semaphore to enforce max size
        acquire_coro = self._acquire_semaphore.acquire()
        if timeout:
            try:
                await asyncio.wait_for(acquire_coro, timeout)
            except asyncio.TimeoutError:
                raise TimeoutError(f"Failed to acquire provider within {timeout}s")
        else:
            await acquire_coro
        
        try:
            async with self._lock:
                # Try to get an available provider
                if self.available:
                    provider = self.available.pop(0)
                    provider.state = ProviderState.IN_USE
                    provider.last_used = datetime.utcnow()
                    provider.use_count += 1
                    self.in_use[provider.id] = provider
                    
                    logger.debug(f"Acquired provider {provider.id} from pool")
                    return provider
                
                # No available providers, create new one if under limit
                current_total = len(self.available) + len(self.in_use)
                if current_total < self.max_size:
                    logger.info(f"Pool exhausted, creating new provider (current: {current_total}/{self.max_size})")
                    try:
                        provider = await self._create_provider()
                        provider.state = ProviderState.IN_USE
                        provider.use_count = 1
                        self.in_use[provider.id] = provider
                        
                        logger.info(f"Successfully created and acquired new provider {provider.id}")
                        return provider
                    except Exception as e:
                        logger.error(f"Failed to create new provider: {e}")
                        # Let the exception propagate - semaphore will be released in outer except block
                        raise
                else:
                    logger.warning(f"Pool at maximum capacity ({current_total}/{self.max_size}), cannot create more providers")
        
        except Exception:
            # Release semaphore if we fail to provide a provider
            self._acquire_semaphore.release()
            raise
        
        # Should not reach here
        self._acquire_semaphore.release()
        raise ResourceExhaustedError("Failed to acquire provider from pool", "provider_pool")
    
    async def release(self, provider: PooledProvider):
        """
        Return a provider to the pool.
        
        Args:
            provider: Provider to release back to pool
        """
        if not provider or provider.id not in self.in_use:
            logger.warning(f"Attempted to release unknown provider: {provider}")
            return
        
        async with self._lock:
            # Remove from in-use
            del self.in_use[provider.id]
            
            # Check health before returning to available pool
            if provider.error_count > 5 or provider.health_score < 50:
                logger.warning(f"Destroying unhealthy provider {provider.id} "
                              f"(health_score={provider.health_score})")
                await self._destroy_provider(provider)
            else:
                # Return to available pool
                provider.state = ProviderState.AVAILABLE
                provider.current_task_id = None
                self.available.append(provider)
                logger.debug(f"Released provider {provider.id} back to pool")
        
        # Release semaphore
        self._acquire_semaphore.release()
        
        # Ensure minimum pool size
        await self._ensure_min_size()
    
    async def _create_provider(self) -> PooledProvider:
        """Create a new provider instance using ProviderFactory with timeout protection"""
        try:
            # Wrap entire provider creation in timeout to prevent hanging
            return await asyncio.wait_for(
                self._create_provider_impl(),
                timeout=30.0  # 30s timeout for provider creation
            )
        except asyncio.TimeoutError:
            logger.error(f"Provider creation timed out after 30s for type {self.provider_type}")
            raise ResourceExhaustedError(
                f"Provider creation timed out after 30 seconds", 
                "provider_creation_timeout"
            )
        except Exception as e:
            logger.error(f"Failed to create provider: {e}")
            raise
    
    async def _create_provider_impl(self) -> PooledProvider:
        """Internal implementation of provider creation without timeout"""
        start_time = datetime.utcnow()
        logger.info(f"Creating new provider of type {self.provider_type}")
        
        try:
            # Use ProviderFactory for proper validation and creation
            from gleitzeit.providers.factory import ProviderFactory
            
            # Create factory with auto-fix enabled for better compatibility
            factory = ProviderFactory(
                strict_validation=False,  # Be lenient for now
                auto_fix=True,  # Fix common issues automatically
                debug_mode=True
            )
            
            # Create provider with factory
            # Pass default args that most providers expect
            instance = factory.create_provider(
                self.provider_class,
                provider_id=self.provider_type,
                protocol_id=self.protocol_id,  # Use the protocol from config
                validate=True
            )
            
            # Initialize if needed (factory may have already done this)
            if hasattr(instance, 'initialize') and not hasattr(instance, '_initialized'):
                await instance.initialize()
            
            # Wrap in pooled provider
            provider = PooledProvider(
                provider_type=self.provider_type,
                instance=instance,
                state=ProviderState.AVAILABLE
            )
            
            creation_time = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Created provider {provider.id} of type {self.provider_type} in {creation_time:.2f}s")
            return provider
            
        except Exception as e:
            creation_time = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Failed to create provider with factory after {creation_time:.2f}s: {e}")
            raise
    
    async def _destroy_provider(self, provider: PooledProvider):
        """Destroy a provider instance"""
        try:
            provider.state = ProviderState.TERMINATING
            
            # Cleanup provider if it has cleanup method
            if provider.instance and hasattr(provider.instance, 'cleanup'):
                await provider.instance.cleanup()
            
            logger.debug(f"Destroyed provider {provider.id}")
            
        except Exception as e:
            logger.error(f"Error destroying provider {provider.id}: {e}")
    
    async def _ensure_min_size(self):
        """Ensure pool has minimum number of providers"""
        async with self._lock:
            current_total = len(self.available) + len(self.in_use)
            
            if current_total < self.min_size:
                needed = self.min_size - current_total
                logger.info(f"Creating {needed} providers to maintain minimum pool size")
                
                for _ in range(needed):
                    try:
                        provider = await self._create_provider()
                        self.available.append(provider)
                    except Exception as e:
                        logger.error(f"Failed to create provider: {e}")
    
    async def trigger_health_check(self):
        """Trigger health check externally (stateless)"""
        await self._perform_health_check()
    
    async def _perform_health_check(self):
        """Perform health check and cleanup"""
        async with self._lock:
            # Check idle providers
            to_remove = []
            for provider in self.available:
                if provider.idle_seconds > self.max_idle_time:
                    # Keep minimum pool size
                    current_total = len(self.available) + len(self.in_use)
                    if current_total > self.min_size:
                        to_remove.append(provider)
            
            # Remove idle providers
            for provider in to_remove:
                self.available.remove(provider)
                await self._destroy_provider(provider)
                logger.info(f"Removed idle provider {provider.id}")
            
            # Log pool status
            logger.debug(f"Pool status for {self.provider_type}: "
                        f"available={len(self.available)}, "
                        f"in_use={len(self.in_use)}")
    
    async def shutdown(self):
        """Shutdown the pool and cleanup all providers"""
        self._shutdown = True
        
        # No health check task to cancel (stateless)
        
        # Destroy all providers
        async with self._lock:
            all_providers = self.available + list(self.in_use.values())
            
            destroy_tasks = []
            for provider in all_providers:
                destroy_tasks.append(self._destroy_provider(provider))
            
            if destroy_tasks:
                await asyncio.gather(*destroy_tasks, return_exceptions=True)
            
            self.available.clear()
            self.in_use.clear()
        
        logger.info(f"Shutdown provider pool for {self.provider_type}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics"""
        return {
            "provider_type": self.provider_type,
            "available": len(self.available),
            "in_use": len(self.in_use),
            "unhealthy": len(self.unhealthy),
            "total": len(self.available) + len(self.in_use),
            "min_size": self.min_size,
            "max_size": self.max_size,
            "utilization": len(self.in_use) / self.max_size * 100 if self.max_size > 0 else 0
        }


class StreamEnabledProviderPool(ProviderPool):
    """
    Enhanced provider pool with stream integration support.

    Extends ProviderPool to automatically enable stream integration
    for providers when a StreamSystemManager is available.
    """

    def __init__(
        self,
        provider_type: str,
        provider_class: Type[Any],
        min_size: int = 1,
        max_size: int = 10,
        max_idle_time: int = 300,
        health_check_interval: int = 60,
        persistence: Optional[PersistenceBackend] = None,
        stream_manager=None,
        enable_stream_integration: bool = True,
        protocol_id: Optional[str] = None
    ):
        """
        Initialize stream-enabled provider pool.

        Args:
            provider_type: Type identifier for the provider
            provider_class: Class to instantiate for new providers
            min_size: Minimum number of providers to maintain
            max_size: Maximum number of providers allowed
            max_idle_time: Maximum idle time before provider cleanup (seconds)
            health_check_interval: Interval between health checks (seconds)
            persistence: Optional persistence backend for state
            stream_manager: Optional StreamSystemManager for stream integration
            enable_stream_integration: Whether to enable stream integration
            protocol_id: Protocol ID for the provider (e.g. "python/v1")
        """
        super().__init__(
            provider_type, provider_class, min_size, max_size,
            max_idle_time, health_check_interval, persistence, protocol_id
        )

        self.stream_manager = stream_manager
        self.enable_stream_integration = enable_stream_integration

        logger.info(f"Created stream-enabled pool for {provider_type} "
                   f"(streams={'enabled' if stream_manager and enable_stream_integration else 'disabled'})")

    async def _create_provider_impl(self) -> PooledProvider:
        """Enhanced provider creation with stream integration"""
        # Call parent implementation
        provider = await super()._create_provider_impl()

        # Enable stream integration if available
        if (self.stream_manager and
            self.enable_stream_integration and
            provider.instance):

            try:
                from gleitzeit.providers.stream_integration import enable_stream_integration_for_provider

                # Enable stream integration for the provider instance
                await enable_stream_integration_for_provider(
                    provider.instance,
                    self.stream_manager,
                    enable_health_reporting=True
                )

                logger.debug(f"Enabled stream integration for provider {provider.id}")

            except Exception as e:
                logger.warning(f"Failed to enable stream integration for provider {provider.id}: {e}")
                # Continue without stream integration

        return provider

    async def _destroy_provider(self, provider: PooledProvider):
        """Enhanced provider destruction with stream cleanup"""
        try:
            # Shutdown stream integration if enabled
            if (provider.instance and
                hasattr(provider.instance, 'shutdown_stream_integration')):

                try:
                    await provider.instance.shutdown_stream_integration()
                except Exception as e:
                    logger.debug(f"Error shutting down stream integration for {provider.id}: {e}")

            # Call parent implementation
            await super()._destroy_provider(provider)

        except Exception as e:
            logger.error(f"Error in enhanced provider destruction for {provider.id}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Enhanced statistics including stream integration status"""
        base_stats = super().get_stats()

        # Add stream-specific stats
        base_stats.update({
            "stream_integration": {
                "enabled": self.enable_stream_integration,
                "stream_manager_available": self.stream_manager is not None,
                "stream_enabled_providers": self._count_stream_enabled_providers()
            }
        })

        return base_stats

    def _count_stream_enabled_providers(self) -> int:
        """Count how many providers have stream integration enabled"""
        count = 0

        # Check available providers
        for provider in self.available:
            if (provider.instance and
                hasattr(provider.instance, '_stream_enabled') and
                provider.instance._stream_enabled):
                count += 1

        # Check in-use providers
        for provider in self.in_use.values():
            if (provider.instance and
                hasattr(provider.instance, '_stream_enabled') and
                provider.instance._stream_enabled):
                count += 1

        return count