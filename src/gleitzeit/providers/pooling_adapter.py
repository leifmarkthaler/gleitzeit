"""
Pooling Adapter for Integration with Existing Components

Provides compatibility layer between new pooled provider system
and existing registry-based components.
"""

import logging
from typing import Optional, Any, Dict, Set
from datetime import datetime

from gleitzeit.providers.provider_pool_manager import ProviderPoolManager
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.models import Task, TaskResult, TaskStatus
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse, JSONRPCError
from gleitzeit.core.errors import ErrorCode, ProviderNotFoundError
from gleitzeit.registry import ProviderInfo, ProviderStatus

logger = logging.getLogger(__name__)


class PoolingAdapter:
    """
    Adapter that bridges between components expecting registry interface
    and the actual provider implementation (ProviderHub or pools).
    
    For scalability:
    - Delegates to ProviderHub for all discovered/managed providers
    - Only creates pools for explicitly registered provider classes
    - Maintains stateless operation by not holding provider instances
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
        provider_hub=None
    ):
        """
        Initialize pooling adapter.
        
        Args:
            persistence: Backend for provider state
            min_pool_size: Default minimum pool size (for pooled providers)
            max_pool_size: Default maximum pool size (for pooled providers)
            provider_hub: ProviderHub that manages actual providers
        """
        self.persistence = persistence
        self.pool_manager = ProviderPoolManager(
            persistence=persistence,
            default_min_size=min_pool_size,
            default_max_size=max_pool_size
        )
        
        # Track which protocols are available
        self._registered_protocols: Set[str] = set()
        
        # Reference to the single source of truth for providers
        self.provider_hub = provider_hub
        
        logger.info(f"Created PoolingAdapter (pools: {min_pool_size}-{max_pool_size})")
    
    async def initialize(self):
        """Initialize the adapter"""
        await self.pool_manager.initialize()
        logger.info("PoolingAdapter initialized")
    
    def is_protocol_available(self, protocol: str) -> bool:
        """
        Check if a protocol has registered providers.
        
        Checks both:
        1. Hub-managed providers (from ProviderHub)
        2. Pooled providers (registered directly)
        
        Args:
            protocol: Protocol identifier
            
        Returns:
            True if protocol has providers
        """
        # Check if available in ProviderHub
        if self.provider_hub and hasattr(self.provider_hub, 'providers'):
            if protocol in self.provider_hub.providers:
                return True
        
        # Check if registered as pooled provider
        return protocol in self._registered_protocols
    
    async def validate_provider_availability(self, protocol: str) -> tuple[bool, str]:
        """
        Validate if a provider can actually be allocated for the protocol.
        This checks not just registration but actual resource availability.
        
        Args:
            protocol: Protocol identifier
            
        Returns:
            Tuple of (is_available, error_message)
        """
        # First check if protocol is available at all
        if not self.is_protocol_available(protocol):
            return False, f"Protocol '{protocol}' is not registered"
        
        # Check hub-managed providers first
        if self.provider_hub and hasattr(self.provider_hub, 'providers'):
            if protocol in self.provider_hub.providers:
                provider = self.provider_hub.providers[protocol]
                # Validate if the provider is actually available
                if hasattr(provider, 'validate_availability'):
                    try:
                        is_available = await provider.validate_availability()
                        if not is_available:
                            return False, f"Provider for '{protocol}' is not running (check if service is started)"
                        return True, ""
                    except Exception as e:
                        return False, f"Provider for '{protocol}' validation failed: {str(e)}"
                return True, ""  # Assume available if no validation method
        
        # Check pooled providers
        try:
            provider = await self.pool_manager.get_provider(
                protocol=protocol,
                timeout=0.1  # Very short timeout just to check availability
            )
            if provider:
                await self.pool_manager.release_provider(provider)
                return True, ""
            else:
                return False, f"No available providers for protocol '{protocol}'"
        except Exception as e:
            # Provider not available
            return False, f"Provider for protocol '{protocol}' is not available: {str(e)}"
    
    async def register_provider(
        self,
        provider_id: str,
        protocol_id: str,
        provider_instance: Any,
        supported_methods: Optional[Set[str]] = None
    ) -> None:
        """
        Register a provider with the pooling system.
        
        Only registers providers that need pooling (Python, Shell).
        Discovered providers (Ollama) are managed by ProviderHub.
        
        Args:
            provider_id: Unique provider identifier
            protocol_id: Protocol this provider supports
            provider_instance: Provider instance or class
            supported_methods: Methods this provider supports
        """
        # Only register pooled providers (not discovered ones)
        if isinstance(provider_instance, type):
            # This is a class, create a pool for it
            await self.pool_manager.register_provider(
                provider_type=provider_id,
                provider_class=provider_instance,
                protocol=protocol_id,
                supported_methods=list(supported_methods) if supported_methods else None
            )
            logger.info(f"Registered pooled provider: {provider_id} for protocol: {protocol_id}")
        else:
            # Instance-based providers should be in ProviderHub
            logger.debug(f"Skipping instance registration for {provider_id} - should be in ProviderHub")
        
        # Track protocol
        self._registered_protocols.add(protocol_id)
    
    async def execute_request(
        self,
        protocol_id: str,
        request: JSONRPCRequest
    ) -> JSONRPCResponse:
        """
        Execute a JSONRPC request - main interface for all provider access.
        
        Routes requests to appropriate backend:
        1. Hub-managed providers (Ollama, etc.) - delegates to ProviderHub
        2. Pooled providers (Python, Shell) - uses ProviderPoolManager
        
        Args:
            protocol_id: Protocol to use
            request: JSONRPC request
            
        Returns:
            JSONRPC response
        """
        provider = None
        try:
            # Determine routing based on protocol
            hub_managed_protocols = ['llm/v1', 'vision/v1', 'embeddings/v1']  # Protocols that need hub management
            
            if protocol_id in hub_managed_protocols:
                # These need hub-based resource management (like OllamaHub)
                if self.provider_hub and hasattr(self.provider_hub, 'providers'):
                    if protocol_id in self.provider_hub.providers:
                        logger.debug(f"Routing {protocol_id} to ProviderHub (hub-managed)")
                        return await self.provider_hub.execute_request(protocol_id, request)
                    else:
                        raise ProviderNotFoundError(f"Hub-managed protocol {protocol_id} not available")
                else:
                    raise ProviderNotFoundError(f"No ProviderHub available for {protocol_id}")
            
            # For pooled providers (Python, Shell, etc.)
            logger.debug(f"Routing {protocol_id} to pool manager")
            provider = await self.pool_manager.get_provider(
                protocol=protocol_id,
                timeout=30.0
            )
            
            # Execute request through provider
            if hasattr(provider.instance, 'handle_request'):
                # Check signature - some providers expect (method, params), others expect (request)
                import inspect
                sig = inspect.signature(provider.instance.handle_request)
                if len(sig.parameters) >= 2:
                    # Expects (method, params) style
                    response = await provider.instance.handle_request(request.method, request.params or {})
                    if not isinstance(response, JSONRPCResponse):
                        response = JSONRPCResponse(result=response, id=request.id)
                else:
                    # Expects JSONRPCRequest
                    response = await provider.instance.handle_request(request)
            elif hasattr(provider.instance, 'execute'):
                # Similar check for execute
                response = await provider.instance.execute(request.method, request.params or {})
                if not isinstance(response, JSONRPCResponse):
                    response = JSONRPCResponse(result=response, id=request.id)
            else:
                # Try direct method call
                method = getattr(provider.instance, request.method, None)
                if method:
                    result = await method(**request.params)
                    response = JSONRPCResponse(
                        result=result,
                        id=request.id
                    )
                else:
                    response = JSONRPCResponse(
                        error=JSONRPCError(
                            code=ErrorCode.METHOD_NOT_FOUND,
                            message=f"Method not found: {request.method}"
                        ),
                        id=request.id
                    )
            
            return response
            
        except ProviderNotFoundError as e:
            return JSONRPCResponse(
                error=JSONRPCError(
                    code=ErrorCode.PROVIDER_NOT_FOUND,
                    message=str(e)
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
        finally:
            # Release provider back to pool
            if provider:
                await self.pool_manager.release_provider(provider)
    
    async def execute_task(self, task: Task) -> TaskResult:
        """
        Unified task execution - routes to appropriate backend.
        
        Args:
            task: Task to execute
            
        Returns:
            TaskResult
        """
        started_at = datetime.utcnow()
        
        try:
            # Convert task to JSONRPC request
            request = JSONRPCRequest(
                method=task.method,
                params=task.params or {},
                id=task.id
            )
            
            # Use unified execute_request method for routing
            response = await self.execute_request(task.protocol, request)
            
            completed_at = datetime.utcnow()
            
            # Convert response to TaskResult
            if response.error:
                return TaskResult(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    error=response.error.message,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=(completed_at - started_at).total_seconds()
                )
            else:
                return TaskResult(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    result=response.result,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=(completed_at - started_at).total_seconds()
                )
            
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            completed_at = datetime.utcnow()
            
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds()
            )
    
    async def get_provider_info(self, provider_id: str) -> Optional[ProviderInfo]:
        """
        Get provider information (compatibility method).
        
        Args:
            provider_id: Provider identifier
            
        Returns:
            ProviderInfo or None
        """
        # Get pool stats instead
        stats = self.pool_manager.get_stats()
        
        if provider_id in stats.get("pools", {}):
            pool_stats = stats["pools"][provider_id]
            
            # Create ProviderInfo from pool stats
            return ProviderInfo(
                provider_id=provider_id,
                protocol_id="unknown",  # Would need to track this
                provider_class=provider_id,
                status=ProviderStatus.HEALTHY if pool_stats["available"] > 0 else ProviderStatus.DEGRADED,
                total_requests=0,  # Would need to track
                successful_requests=0,  # Would need to track
                failed_requests=0,  # Would need to track
            )
        
        return None
    
    async def shutdown(self):
        """Shutdown the adapter and all pools"""
        await self.pool_manager.shutdown()
        logger.info("PoolingAdapter shutdown complete")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pooling statistics"""
        return self.pool_manager.get_stats()


class RegistryCompatibilityAdapter:
    """
    Provides full compatibility with ProtocolProviderRegistry interface
    while using pooled providers underneath.
    """
    
    def __init__(self, pooling_adapter: PoolingAdapter):
        """
        Initialize compatibility adapter.
        
        Args:
            pooling_adapter: Underlying pooling adapter
        """
        self.pooling_adapter = pooling_adapter
        self._running = False
    
    async def start(self):
        """Start the registry (compatibility)"""
        await self.pooling_adapter.initialize()
        self._running = True
        logger.info("Registry compatibility adapter started")
    
    async def stop(self):
        """Stop the registry (compatibility)"""
        self._running = False
        await self.pooling_adapter.shutdown()
        logger.info("Registry compatibility adapter stopped")
    
    def register_provider(
        self,
        provider_id: str,
        protocol_id: str,
        provider_instance: Any,
        supported_methods: Optional[Set[str]] = None
    ) -> None:
        """
        Register provider (synchronous for compatibility).
        
        Note: This creates an async task to register with the pool.
        """
        import asyncio
        
        async def _register():
            await self.pooling_adapter.register_provider(
                provider_id=provider_id,
                protocol_id=protocol_id,
                provider_instance=provider_instance,
                supported_methods=supported_methods
            )
        
        # Schedule registration
        asyncio.create_task(_register())
    
    async def execute_request(
        self,
        protocol_id: str,
        request: JSONRPCRequest
    ) -> JSONRPCResponse:
        """Execute request through pooled providers"""
        return await self.pooling_adapter.execute_request(protocol_id, request)
    
    def get_provider_info(self, provider_id: str) -> Optional[ProviderInfo]:
        """Get provider info (synchronous for compatibility)"""
        import asyncio
        
        async def _get_info():
            return await self.pooling_adapter.get_provider_info(provider_id)
        
        # Run async method synchronously
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_get_info())
        except:
            return None
    
    def get_providers_for_protocol(self, protocol_id: str) -> Set[str]:
        """Get providers for a protocol"""
        # This would need to query the pool manager's registry
        # For now, return empty set
        return set()
    
    def select_provider(self, protocol_id: str) -> Optional[str]:
        """Select a provider for a protocol"""
        # Pool manager handles selection internally
        return protocol_id