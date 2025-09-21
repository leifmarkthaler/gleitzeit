"""
Stateless Protocol Registry for Gleitzeit

This registry doesn't store providers in memory but queries them dynamically
from persistence to ensure true stateless operation and horizontal scalability.
"""

from typing import Dict, List, Set, Optional, Any, Type
import logging
import asyncio
from gleitzeit.core.protocol import ProtocolSpec, get_protocol_registry
from gleitzeit.core.errors import ProviderNotFoundError

logger = logging.getLogger(__name__)


class StatelessProtocolRegistry:
    """
    Stateless registry that discovers providers dynamically from persistence.
    
    Instead of storing providers in memory, it queries persistence to discover
    available providers across the distributed system. This enables horizontal
    scaling where any instance can discover providers registered by other instances.
    """
    
    def __init__(self, persistence=None, pooling_adapter=None, provider_hub=None):
        """
        Initialize with persistence and optional local provider sources.
        
        Args:
            persistence: Persistence adapter for distributed provider discovery
            pooling_adapter: Optional local PoolingAdapter (fallback)
            provider_hub: Optional local ProviderHub (fallback)
        """
        self.protocol_registry = get_protocol_registry()
        self.persistence = persistence
        self.pooling_adapter = pooling_adapter
        self.provider_hub = provider_hub
        
    def set_persistence(self, persistence):
        """Set or update the persistence adapter."""
        self.persistence = persistence
        
    def set_pooling_adapter(self, pooling_adapter):
        """Set or update the pooling adapter reference."""
        self.pooling_adapter = pooling_adapter
        
    def set_provider_hub(self, provider_hub):
        """Set or update the provider hub reference."""
        self.provider_hub = provider_hub
        
    def is_protocol_registered(self, protocol_id: str) -> bool:
        """
        Check if a protocol has any available provider.
        
        This queries persistence first for distributed provider discovery,
        then falls back to local sources if needed.
        """
        # First check persistence for distributed provider registry
        if self.persistence:
            try:
                # Check for registered providers in persistence
                # Format: provider:registry:protocol:{protocol_id}
                key = f"provider:registry:protocol:{protocol_id}"
                if asyncio.iscoroutinefunction(self.persistence.exists):
                    # Handle async persistence
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # We're in an async context but can't await
                        # This is a limitation we need to handle
                        pass
                    else:
                        exists = loop.run_until_complete(self.persistence.exists(key))
                        if exists:
                            return True
                else:
                    # Sync persistence
                    if self.persistence.exists(key):
                        return True
            except Exception as e:
                logger.debug(f"Failed to check persistence for protocol {protocol_id}: {e}")
        
        # Fallback to local sources
        # Check pooling adapter (for pooled providers like python/shell)
        if self.pooling_adapter:
            if protocol_id in self.pooling_adapter._registered_protocols:
                return True
                
        # Check provider hub (for hub-based providers like llm)
        if self.provider_hub:
            if hasattr(self.provider_hub, 'providers'):
                if protocol_id in self.provider_hub.providers:
                    return True
                    
        # Signal protocol handled by SignalProvider + SignalWorker
        if protocol_id == "signal/v1":
            # SignalProvider registers tasks, SignalWorker processes signals
            # Check if SignalProvider is registered in the hub
            if self.provider_hub and hasattr(self.provider_hub, 'providers'):
                return protocol_id in self.provider_hub.providers
            # Or check pooling adapter
            if self.pooling_adapter:
                return protocol_id in self.pooling_adapter._registered_protocols
            return False

        # Also check if it's a known protocol in the protocol registry
        if self.protocol_registry and self.protocol_registry.get(protocol_id):
            # Known protocol but no provider available yet
            logger.debug(f"Protocol {protocol_id} is known but no provider available")
            return False

        return False

    def is_protocol_available(self, protocol_id: str) -> bool:
        """
        Check if a protocol has any available provider.
        This is an alias for is_protocol_registered for compatibility.
        """
        # Signal protocol handled by SignalProvider + SignalWorker
        if protocol_id == "signal/v1":
            logger.debug(f"Signal protocol {protocol_id} is handled by SignalProvider + SignalWorker")

        return self.is_protocol_registered(protocol_id)

    def get_provider(self, protocol_id: str) -> Optional[Any]:
        """
        Get a provider for the protocol.
        
        Returns a reference that can be used to check if provider exists,
        but not the actual provider instance (stateless).
        """
        if self.is_protocol_registered(protocol_id):
            # Return a marker object indicating provider is available
            # The actual provider will be allocated when needed
            return {"protocol": protocol_id, "available": True}
        return None
        
    def list_available_protocols(self) -> Set[str]:
        """List all protocols that have available providers."""
        protocols = set()
        
        # Get from pooling adapter
        if self.pooling_adapter:
            protocols.update(self.pooling_adapter._registered_protocols)
            
        # Get from provider hub
        if self.provider_hub and hasattr(self.provider_hub, 'providers'):
            protocols.update(self.provider_hub.providers.keys())
            
        return protocols
        
    def validate_protocol_method(self, protocol_id: str, method: str) -> bool:
        """
        Validate if a method is supported by the protocol.
        
        This checks the protocol spec and optionally queries the provider.
        """
        # First check if protocol is available
        if not self.is_protocol_registered(protocol_id):
            return False
            
        # Check protocol spec if available
        if protocol_id in self.protocol_registry:
            spec = self.protocol_registry[protocol_id]
            if hasattr(spec, 'methods') and spec.methods:
                return method in spec.methods
                
        # For dynamic protocols, assume method is valid if provider exists
        # The provider itself will validate at execution time
        return True
    
    async def register_provider_in_persistence(self, protocol_id: str, provider_info: Dict[str, Any]):
        """
        Register a provider in persistence for distributed discovery.
        
        Args:
            protocol_id: Protocol identifier (e.g., 'python/v1', 'llm/v1')
            provider_info: Provider metadata (instance_id, capabilities, etc.)
        """
        if not self.persistence:
            logger.debug(f"No persistence available to register provider {protocol_id}")
            return
            
        try:
            # Store provider registration in persistence
            # Format: provider:registry:protocol:{protocol_id}
            key = f"provider:registry:protocol:{protocol_id}"
            
            # Store provider info
            await self.persistence.set(key, provider_info)
            
            # Set TTL if persistence supports it (Redis)
            if hasattr(self.persistence, 'expire'):
                ttl = 300  # 5 minutes TTL, providers should re-register periodically
                await self.persistence.expire(key, ttl)
                logger.info(f"Registered provider {protocol_id} in persistence (TTL={ttl}s)")
            else:
                logger.info(f"Registered provider {protocol_id} in persistence")
            
            # Also store in a set for listing all protocols
            await self.persistence.sadd("provider:registry:protocols", protocol_id)
            
        except Exception as e:
            logger.error(f"Failed to register provider {protocol_id} in persistence: {e}")
    
    async def list_available_protocols_from_persistence(self) -> Set[str]:
        """List all protocols available in the distributed system."""
        protocols = set()
        
        if self.persistence:
            try:
                # Get all registered protocols from persistence
                stored_protocols = await self.persistence.smembers("provider:registry:protocols")
                if stored_protocols:
                    protocols.update(stored_protocols)
            except Exception as e:
                logger.debug(f"Failed to list protocols from persistence: {e}")
        
        return protocols
    
    async def deregister_provider_from_persistence(self, protocol_id: str, instance_id: str = None):
        """
        Deregister a provider from persistence.
        
        Args:
            protocol_id: Protocol identifier to deregister
            instance_id: Optional instance ID for multi-instance tracking
        """
        if not self.persistence:
            logger.debug(f"No persistence available to deregister provider {protocol_id}")
            return
            
        try:
            # Remove main provider registration
            key = f"provider:registry:protocol:{protocol_id}"
            await self.persistence.delete(key)
            
            # Check if any other instances have this protocol registered
            # In a multi-instance setup, we'd check instance-specific keys
            instance_key = f"provider:registry:instance:{instance_id}:protocol:{protocol_id}" if instance_id else None
            if instance_key:
                await self.persistence.delete(instance_key)
            
            # Only remove from set if no other instances have it
            # For now, we'll remove it (single instance assumption)
            await self.persistence.srem("provider:registry:protocols", protocol_id)
            
            logger.info(f"Deregistered provider {protocol_id} from persistence")
            
        except Exception as e:
            logger.error(f"Failed to deregister provider {protocol_id}: {e}")
    
    async def refresh_provider_registration(self, protocol_id: str, provider_info: Dict[str, Any]):
        """
        Refresh provider registration to prevent TTL expiration.
        
        This should be called periodically by active providers to maintain
        their registration in the distributed system.
        """
        await self.register_provider_in_persistence(protocol_id, provider_info)