"""
Protocol Registry for Gleitzeit V4

Centralized registry for protocols and their providers,
with discovery, validation, and routing capabilities.
"""

from typing import Dict, List, Set, Optional, Any, Type
from dataclasses import dataclass, field
from datetime import datetime
import logging
import asyncio
from enum import Enum

from gleitzeit.core.protocol import ProtocolSpec, get_protocol_registry
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.core.errors import ErrorCode, ProtocolError, ProviderNotFoundError

logger = logging.getLogger(__name__)


class ProviderStatus(str, Enum):
    """Provider status states"""
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISCONNECTED = "disconnected"


@dataclass
class ProviderInfo:
    """Information about a registered protocol provider"""
    provider_id: str
    protocol_id: str
    provider_class: str
    status: ProviderStatus = ProviderStatus.INITIALIZING
    supported_methods: Set[str] = field(default_factory=set)
    
    # Connection info
    registered_at: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    
    # Performance metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    
    # Configuration
    max_concurrent_requests: int = 10
    timeout_seconds: int = 30
    
    # Health check
    health_check_interval: int = 60
    consecutive_failures: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100.0
    
    @property
    def is_healthy(self) -> bool:
        """Check if provider is considered healthy"""
        return self.status in [ProviderStatus.HEALTHY, ProviderStatus.DEGRADED]
    
    def update_stats(self, success: bool, response_time: float):
        """Update provider statistics"""
        self.total_requests += 1
        self.last_seen = datetime.utcnow()
        
        if success:
            self.successful_requests += 1
            self.consecutive_failures = 0
        else:
            self.failed_requests += 1
            self.consecutive_failures += 1
        
        # Update rolling average response time
        alpha = 0.1  # Exponential smoothing factor
        self.average_response_time = (
            alpha * response_time + 
            (1 - alpha) * self.average_response_time
        )


class ProtocolProviderRegistry:
    """Registry for protocol providers with health monitoring and load balancing"""
    
    def __init__(self):
        self.protocol_registry = get_protocol_registry()
        self.providers: Dict[str, ProviderInfo] = {}  # provider_id -> info
        self.protocol_providers: Dict[str, Set[str]] = {}  # protocol_id -> set of provider_ids
        self.provider_instances: Dict[str, Any] = {}  # provider_id -> instance
        
        # Health monitoring
        # Event-driven health tracking instead of polling task
        self._running = False
    
    async def start(self):
        """Start the registry and health monitoring"""
        self._running = True
        # Event-driven health monitoring - no polling loop
        # Health checks triggered by provider events: failures, timeouts, connection issues
        logger.info("Protocol Provider Registry started")
    
    async def stop(self):
        """Stop the registry and health monitoring"""
        self._running = False
        
        # Cleanup all provider instances
        await self._cleanup_all_providers()
        
        logger.info("Protocol Provider Registry stopped")
    
    async def _cleanup_all_providers(self):
        """Cleanup all registered provider instances"""
        logger.info("Cleaning up all provider instances...")
        
        for provider_id, provider_instance in self.provider_instances.items():
            await self._cleanup_provider(provider_id, provider_instance)
        
        # Clear the instances after cleanup
        self.provider_instances.clear()
        logger.info("Provider cleanup completed")
    
    def register_protocol(self, protocol: ProtocolSpec) -> None:
        """Register a protocol specification"""
        self.protocol_registry.register(protocol)
        
        # Initialize provider set for this protocol
        if protocol.protocol_id not in self.protocol_providers:
            self.protocol_providers[protocol.protocol_id] = set()
        
        logger.info(f"Registered protocol: {protocol.protocol_id}")
    
    def register_provider(
        self, 
        provider_id: str,
        protocol_id: str,
        provider_instance: Any,
        supported_methods: Optional[Set[str]] = None
    ) -> None:
        """
        Register a protocol provider instance
        
        Args:
            provider_id: Unique identifier for the provider
            protocol_id: Protocol this provider implements
            provider_instance: The actual provider instance
            supported_methods: Methods this provider supports (auto-detected if None)
        """
        # Validate protocol exists
        protocol = self.protocol_registry.get(protocol_id)
        if not protocol:
            raise ProtocolError(f"Protocol not registered: {protocol_id}")
        
        # Auto-detect supported methods if not provided
        if supported_methods is None:
            if hasattr(provider_instance, 'get_supported_methods'):
                supported_methods = set(provider_instance.get_supported_methods())
            else:
                # Default to all methods in protocol
                supported_methods = set(protocol.methods.keys())
        
        # Create provider info
        provider_info = ProviderInfo(
            provider_id=provider_id,
            protocol_id=protocol_id,
            provider_class=provider_instance.__class__.__name__,
            supported_methods=supported_methods,
            status=ProviderStatus.HEALTHY  # Start as healthy for now
        )
        
        # Register provider
        self.providers[provider_id] = provider_info
        self.provider_instances[provider_id] = provider_instance
        
        # Add to protocol mapping
        if protocol_id not in self.protocol_providers:
            self.protocol_providers[protocol_id] = set()
        self.protocol_providers[protocol_id].add(provider_id)
        
        logger.info(f"Registered provider: {provider_id} for protocol {protocol_id}")
    
    async def unregister_provider(self, provider_id: str) -> None:
        """Unregister a provider and cleanup its resources"""
        if provider_id not in self.providers:
            return
        
        provider_info = self.providers[provider_id]
        protocol_id = provider_info.protocol_id
        
        # Cleanup provider instance before removing
        if provider_id in self.provider_instances:
            provider_instance = self.provider_instances[provider_id]
            await self._cleanup_provider(provider_id, provider_instance)
        
        # Remove from mappings
        del self.providers[provider_id]
        self.provider_instances.pop(provider_id, None)
        
        if protocol_id in self.protocol_providers:
            self.protocol_providers[protocol_id].discard(provider_id)
        
        logger.info(f"Unregistered provider: {provider_id}")
    
    async def _cleanup_provider(self, provider_id: str, provider_instance: Any):
        """Cleanup a single provider instance"""
        try:
            # Try cleanup method first (for pooling compatibility)
            if hasattr(provider_instance, 'cleanup'):
                await provider_instance.cleanup()
                logger.debug(f"✅ Cleaned up provider {provider_id}")
            # Fall back to shutdown method
            elif hasattr(provider_instance, 'shutdown'):
                await provider_instance.shutdown()
                logger.debug(f"✅ Shut down provider {provider_id}")
            else:
                logger.debug(f"⚠️  Provider {provider_id} has no cleanup/shutdown method")
        except Exception as e:
            logger.warning(f"❌ Failed to cleanup provider {provider_id}: {e}")
    
    def get_providers_for_protocol(self, protocol_id: str, method: str = None) -> List[ProviderInfo]:
        """
        Get available providers for a protocol/method
        
        Args:
            protocol_id: Protocol identifier
            method: Specific method name (optional)
            
        Returns:
            List of healthy providers that support the protocol/method
        """
        provider_ids = self.protocol_providers.get(protocol_id, set())
        providers = []
        
        for provider_id in provider_ids:
            provider_info = self.providers.get(provider_id)
            if not provider_info:
                continue
            
            # Check if provider is healthy
            if not provider_info.is_healthy:
                continue
            
            # Check if provider supports the specific method
            if method and method not in provider_info.supported_methods:
                continue
            
            providers.append(provider_info)
        
        # Sort by success rate and response time
        providers.sort(key=lambda p: (-p.success_rate, p.average_response_time))
        
        return providers
    
    def select_provider(self, protocol_id: str, method: str) -> Optional[ProviderInfo]:
        """
        Select the best provider for a protocol/method using load balancing
        
        Args:
            protocol_id: Protocol identifier
            method: Method name
            
        Returns:
            Selected provider info or None if no providers available
        """
        providers = self.get_providers_for_protocol(protocol_id, method)
        
        if not providers:
            return None
        
        # Simple load balancing: select provider with best performance
        # In production, could use more sophisticated algorithms
        return providers[0]
    
    def get_provider_instance(self, provider_id: str) -> Optional[Any]:
        """Get provider instance by ID"""
        return self.provider_instances.get(provider_id)
    
    async def execute_request(
        self, 
        protocol_id: str,
        request: JSONRPCRequest
    ) -> JSONRPCResponse:
        """
        Execute a JSON-RPC request using the best available provider
        
        Args:
            protocol_id: Protocol to use
            request: JSON-RPC request
            
        Returns:
            JSON-RPC response
        """
        # Select provider
        provider_info = self.select_provider(protocol_id, request.method)
        if not provider_info:
            return JSONRPCResponse.create_error(
                request_id=request.id,
                error_code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                error_message=f"No providers available for {protocol_id}::{request.method}"
            )
        
        # Get provider instance
        provider_instance = self.get_provider_instance(provider_info.provider_id)
        if not provider_instance:
            return JSONRPCResponse.create_error(
                request_id=request.id,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message=f"Provider instance not found: {provider_info.provider_id}"
            )
        
        # Execute request
        start_time = asyncio.get_event_loop().time()
        try:
            # Preprocess parameters first (handles directory/file_pattern -> files conversion)
            processed_params = request.params or {}
            if hasattr(provider_instance, '_preprocess_params'):
                processed_params = await provider_instance._preprocess_params(request.method, processed_params)
            
            # Validate processed parameters against protocol
            protocol = self.protocol_registry.get(protocol_id)
            if protocol:
                protocol.validate_method_call(request.method, processed_params)
            
            # Execute via provider with processed parameters
            # Note: execute_with_stats will also call _preprocess_params, but it's idempotent
            if hasattr(provider_instance, 'execute_with_stats'):
                result = await provider_instance.execute_with_stats(request.method, request.params or {})
            else:
                result = await provider_instance.handle_request(request.method, processed_params)
            
            # Update success stats
            response_time = asyncio.get_event_loop().time() - start_time
            provider_info.update_stats(success=True, response_time=response_time)
            
            return JSONRPCResponse.success(request.id, result)
            
        except Exception as e:
            # Update failure stats
            response_time = asyncio.get_event_loop().time() - start_time
            provider_info.update_stats(success=False, response_time=response_time)
            
            # Event-driven health check on failure
            asyncio.create_task(
                self._check_provider_health_on_event(provider_info.provider_id, f"method_failure: {str(e)[:100]}")
            )
            
            # Determine appropriate error code
            if "timeout" in str(e).lower():
                error_code = ErrorCode.PROVIDER_TIMEOUT
            elif "validation" in str(e).lower():
                error_code = ErrorCode.TASK_VALIDATION_FAILED
            else:
                error_code = ErrorCode.INTERNAL_ERROR
            
            return JSONRPCResponse.create_error(
                request_id=request.id,
                error_code=error_code,
                error_message=str(e)
            )
    
    async def _check_provider_health_on_event(self, provider_id: str, trigger_reason: str) -> None:
        """Check provider health when events occur - event-driven alternative to polling"""
        try:
            if provider_id not in self.providers:
                return
                
            provider_info = self.providers[provider_id]
            provider_instance = self.provider_instances.get(provider_id)
            current_time = datetime.utcnow()
            
            if not provider_instance:
                provider_info.status = ProviderStatus.DISCONNECTED
                logger.warning(f"Provider {provider_id} disconnected (trigger: {trigger_reason})")
                return
            
            # Check if provider has been silent too long
            silence_duration = (current_time - provider_info.last_seen).total_seconds()
            if silence_duration > 300:  # 5 minutes
                provider_info.status = ProviderStatus.DISCONNECTED
                logger.warning(f"Provider {provider_id} silent for {silence_duration}s (trigger: {trigger_reason})")
                return
            
            # Perform health check if provider supports it
            if hasattr(provider_instance, 'health_check'):
                health_result = await provider_instance.health_check()
                
                if isinstance(health_result, dict):
                    status = health_result.get('status', 'unknown')
                    if status == 'healthy':
                        provider_info.status = ProviderStatus.HEALTHY
                    elif status == 'degraded':
                        provider_info.status = ProviderStatus.DEGRADED
                    else:
                        provider_info.status = ProviderStatus.UNHEALTHY
                else:
                    # Simple boolean health check
                    provider_info.status = (
                        ProviderStatus.HEALTHY if health_result 
                        else ProviderStatus.UNHEALTHY
                    )
                
                logger.debug(f"Health check for {provider_id}: {provider_info.status.value} (trigger: {trigger_reason})")
            else:
                # No health check method, use consecutive failures
                if provider_info.consecutive_failures > 5:
                    provider_info.status = ProviderStatus.UNHEALTHY
                elif provider_info.consecutive_failures > 2:
                    provider_info.status = ProviderStatus.DEGRADED
                else:
                    provider_info.status = ProviderStatus.HEALTHY
            
        except Exception as e:
            logger.error(f"Health check failed for {provider_id}: {e} (trigger: {trigger_reason})")
            if provider_id in self.providers:
                self.providers[provider_id].status = ProviderStatus.UNHEALTHY
    
    async def list_providers(self) -> Dict[str, Dict[str, Any]]:
        """List all registered providers with their status and metrics"""
        result = {}
        for provider_id, info in self.providers.items():
            result[provider_id] = {
                "protocol_id": info.protocol_id,
                "status": info.status.value,
                "health_status": info.status.value,
                "success_rate": info.success_rate,
                "avg_response_time": info.average_response_time,
                "total_requests": info.total_requests,
                "supported_methods": list(info.supported_methods),
                "last_seen": info.last_seen.isoformat(),
                "consecutive_failures": info.consecutive_failures
            }
        return result
    
    async def check_provider_health(self, provider_id: str) -> Dict[str, Any]:
        """Check health of a specific provider"""
        if provider_id not in self.providers:
            raise ProviderNotFoundError(provider_id)
        
        provider_info = self.providers[provider_id]
        provider_instance = self.provider_instances.get(provider_id)
        
        # Trigger health check
        await self._check_provider_health_on_event(provider_id, "manual_health_check")
        
        # Get updated status
        provider_info = self.providers[provider_id]
        
        health_details = {
            "provider_id": provider_id,
            "status": provider_info.status.value,
            "details": {
                "success_rate": f"{provider_info.success_rate:.1f}%",
                "avg_response_time": f"{provider_info.average_response_time:.3f}s",
                "total_requests": provider_info.total_requests,
                "consecutive_failures": provider_info.consecutive_failures,
                "last_seen": provider_info.last_seen.isoformat(),
                "is_connected": provider_instance is not None,
                "supported_methods": list(provider_info.supported_methods)
            }
        }
        
        # Additional health check if provider supports it
        if provider_instance and hasattr(provider_instance, 'health_check'):
            try:
                health_result = await provider_instance.health_check()
                health_details["details"]["provider_health"] = health_result
            except Exception as e:
                health_details["details"]["health_check_error"] = str(e)
        
        return health_details

    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        total_providers = len(self.providers)
        healthy_providers = sum(1 for p in self.providers.values() if p.is_healthy)
        
        protocol_stats = {}
        for protocol_id, provider_ids in self.protocol_providers.items():
            healthy_count = sum(
                1 for pid in provider_ids 
                if pid in self.providers and self.providers[pid].is_healthy
            )
            protocol_stats[protocol_id] = {
                "total_providers": len(provider_ids),
                "healthy_providers": healthy_count
            }
        
        return {
            "total_protocols": len(self.protocol_providers),
            "total_providers": total_providers,
            "healthy_providers": healthy_providers,
            "protocol_stats": protocol_stats,
            "provider_details": [
                {
                    "provider_id": info.provider_id,
                    "protocol_id": info.protocol_id,
                    "status": info.status.value,
                    "success_rate": info.success_rate,
                    "avg_response_time": info.average_response_time,
                    "total_requests": info.total_requests
                }
                for info in self.providers.values()
            ]
        }


# Global registry instance
_provider_registry = ProtocolProviderRegistry()


def get_provider_registry() -> ProtocolProviderRegistry:
    """Get the global provider registry"""
    return _provider_registry