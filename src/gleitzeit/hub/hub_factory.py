"""
Hub Factory - Unified layer for protocol-specific execution environments

Creates and manages protocol-specific hubs (Ollama, Docker, Shell, HTTP)
and provides a common interface for the provider pool.
"""

import asyncio
import logging
from typing import Dict, Optional, Any, Type, Protocol, runtime_checkable
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from gleitzeit.hub.base import ResourceHub
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.docker_hub import DockerHub
from gleitzeit.persistence.base import PersistenceBackend

logger = logging.getLogger(__name__)


class ProtocolType(str, Enum):
    """Supported protocol types"""
    LLM = "llm"          # Language models (Ollama)
    DOCKER = "docker"    # Container execution
    SHELL = "shell"      # Local shell/process execution
    HTTP = "http"        # HTTP API endpoints
    PYTHON = "python"    # Python code execution (local)
    MCP = "mcp"          # Model Context Protocol


@dataclass
class HubConfig:
    """Configuration for a protocol hub"""
    protocol_type: ProtocolType
    auto_discover: bool = True
    max_instances: int = 10
    enable_pooling: bool = True
    health_check_interval: int = 60
    custom_config: Optional[Dict[str, Any]] = None


@runtime_checkable
class ProtocolHub(Protocol):
    """Protocol interface that all hubs must implement"""
    
    async def initialize(self) -> None:
        """Initialize the hub"""
        ...
    
    async def allocate_resource(self, requirements: Dict[str, Any]) -> Optional[Any]:
        """Allocate a resource for task execution"""
        ...
    
    async def release_resource(self, resource_id: str) -> None:
        """Release an allocated resource"""
        ...
    
    async def health_check(self) -> bool:
        """Check hub health"""
        ...
    
    async def cleanup(self) -> None:
        """Cleanup hub resources"""
        ...
    
    def get_stats(self) -> Dict[str, Any]:
        """Get hub statistics"""
        ...


class ShellHub(ResourceHub):
    """
    Hub for managing local shell/process execution.
    
    Manages local process pools, resource limits, and sandboxing.
    """
    
    def __init__(
        self,
        hub_id: str = "shell-hub",
        max_processes: int = 10,
        enable_sandbox: bool = True,
        persistence: Optional[PersistenceBackend] = None
    ):
        from gleitzeit.hub.base import ResourceType
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.CUSTOM,
            persistence=persistence
        )
        self.max_processes = max_processes
        self.enable_sandbox = enable_sandbox
        self.active_processes: Dict[str, Any] = {}
        
    async def initialize(self) -> None:
        """Initialize shell hub"""
        logger.info(f"ShellHub initialized with max_processes={self.max_processes}")
    
    async def allocate_resource(self, requirements: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Allocate a shell process resource"""
        if len(self.active_processes) >= self.max_processes:
            return None
            
        # Return shell execution context
        return {
            "type": "shell",
            "sandbox": self.enable_sandbox,
            "cwd": requirements.get("cwd", "/tmp"),
            "env": requirements.get("env", {})
        }
    
    async def check_health(self, instance) -> bool:
        """Check health of a shell instance"""
        # Shell processes are managed on-demand, always healthy
        return True
    
    async def collect_metrics(self, instance):
        """Collect metrics from shell instance"""
        from gleitzeit.hub.base import ResourceMetrics
        return ResourceMetrics()
    
    async def start_instance(self, config):
        """Start a new shell instance"""
        # Shell processes are created on-demand
        from gleitzeit.hub.base import ResourceInstance, ResourceType, ResourceStatus
        return ResourceInstance(
            id="shell-local",
            name="Local Shell",
            type=ResourceType.CUSTOM,
            endpoint="local",
            status=ResourceStatus.HEALTHY
        )
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a shell instance"""
        # Cleanup any active processes
        if instance_id in self.active_processes:
            del self.active_processes[instance_id]
        return True
    
    async def restart_instance(self, instance_id: str) -> bool:
        """Restart a shell instance"""
        # Shell processes are stateless, restart is a no-op
        return True


class HTTPHub(ResourceHub):
    """
    Hub for managing HTTP endpoint connections.
    
    Manages connection pools, rate limiting, and endpoint health.
    """
    
    def __init__(
        self,
        hub_id: str = "http-hub",
        max_connections: int = 100,
        rate_limit: Optional[int] = None,
        persistence: Optional[PersistenceBackend] = None
    ):
        from gleitzeit.hub.base import ResourceType
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.CUSTOM,
            persistence=persistence
        )
        self.max_connections = max_connections
        self.rate_limit = rate_limit
        self.endpoints: Dict[str, Any] = {}
        
    async def initialize(self) -> None:
        """Initialize HTTP hub with connection pool"""
        import aiohttp
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=self.max_connections)
        )
        logger.info(f"HTTPHub initialized with max_connections={self.max_connections}")
    
    async def allocate_resource(self, requirements: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Allocate HTTP connection resource"""
        endpoint = requirements.get("endpoint")
        if not endpoint:
            return None
            
        return {
            "type": "http",
            "session": self.session,
            "endpoint": endpoint,
            "rate_limit": self.rate_limit
        }
    
    async def check_health(self, instance) -> bool:
        """Check health of an HTTP endpoint"""
        return True  # HTTP endpoints are managed externally
    
    async def collect_metrics(self, instance):
        """Collect metrics from HTTP endpoint"""
        from gleitzeit.hub.base import ResourceMetrics
        return ResourceMetrics()
    
    async def start_instance(self, config):
        """Start a new HTTP instance"""
        from gleitzeit.hub.base import ResourceInstance, ResourceType, ResourceStatus
        return ResourceInstance(
            id="http-pool",
            name="HTTP Connection Pool",
            type=ResourceType.CUSTOM,
            endpoint="http",
            status=ResourceStatus.HEALTHY
        )
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop an HTTP instance"""
        return True
    
    async def restart_instance(self, instance_id: str) -> bool:
        """Restart an HTTP instance"""
        return True


class HubFactory:
    """
    Factory for creating and managing protocol-specific hubs.
    
    This is the unified layer that:
    1. Creates appropriate hubs for each protocol
    2. Manages hub lifecycle
    3. Provides resource allocation across protocols
    4. Integrates with the provider pool
    """
    
    # Registry of protocol to hub class mappings
    HUB_REGISTRY: Dict[ProtocolType, Type[ResourceHub]] = {
        ProtocolType.LLM: OllamaHub,
        ProtocolType.DOCKER: DockerHub,
        ProtocolType.SHELL: ShellHub,
        ProtocolType.HTTP: HTTPHub,
        # Python and MCP don't need resource hubs (direct execution)
    }
    
    def __init__(
        self,
        persistence: Optional[PersistenceBackend] = None,
        default_config: Optional[HubConfig] = None
    ):
        """
        Initialize the hub factory.
        
        Args:
            persistence: Persistence backend for hub state
            default_config: Default configuration for hubs
        """
        self.persistence = persistence
        self.default_config = default_config or HubConfig(
            protocol_type=ProtocolType.PYTHON,
            auto_discover=True,
            enable_pooling=True
        )
        
        # Active hubs by protocol
        self.hubs: Dict[ProtocolType, ResourceHub] = {}
        
        # Hub configurations
        self.hub_configs: Dict[ProtocolType, HubConfig] = {}
        
        self._initialized = False
        
        logger.info("HubFactory created")
    
    async def initialize(self, protocols: Optional[list[ProtocolType]] = None) -> None:
        """
        Initialize the factory and create hubs for specified protocols.
        
        Args:
            protocols: List of protocols to initialize hubs for.
                      If None, initializes all available protocols.
        """
        if self._initialized:
            return
        
        # Determine which protocols to initialize
        if protocols is None:
            protocols = [
                ProtocolType.LLM,
                ProtocolType.SHELL,
                ProtocolType.HTTP,
                # Docker is optional (requires Docker daemon)
            ]
        
        # Create and initialize hubs
        for protocol in protocols:
            try:
                hub = await self.create_hub(protocol)
                if hub:
                    await hub.initialize()
                    self.hubs[protocol] = hub
                    logger.info(f"Initialized hub for protocol: {protocol}")
            except Exception as e:
                logger.warning(f"Failed to initialize hub for {protocol}: {e}")
        
        self._initialized = True
        logger.info(f"HubFactory initialized with {len(self.hubs)} protocol hubs")
    
    async def create_hub(
        self,
        protocol: ProtocolType,
        config: Optional[HubConfig] = None
    ) -> Optional[ResourceHub]:
        """
        Create a hub for a specific protocol.
        
        Args:
            protocol: Protocol type to create hub for
            config: Optional configuration override
            
        Returns:
            Created hub instance or None if protocol doesn't need a hub
        """
        # Some protocols don't need resource hubs
        if protocol in [ProtocolType.PYTHON, ProtocolType.MCP]:
            logger.debug(f"Protocol {protocol} doesn't require a resource hub")
            return None
        
        # Get hub class
        hub_class = self.HUB_REGISTRY.get(protocol)
        if not hub_class:
            logger.warning(f"No hub implementation for protocol: {protocol}")
            return None
        
        # Use provided config or default
        hub_config = config or self.hub_configs.get(protocol) or self.default_config
        
        # Create hub based on protocol type
        if protocol == ProtocolType.LLM:
            hub = OllamaHub(
                hub_id=f"{protocol}-hub",
                auto_discover=hub_config.auto_discover,
                max_instances=hub_config.max_instances,
                persistence=self.persistence
            )
        elif protocol == ProtocolType.DOCKER:
            hub = DockerHub(
                hub_id=f"{protocol}-hub",
                auto_discover=hub_config.auto_discover,
                max_containers=hub_config.max_instances,
                persistence=self.persistence
            )
        elif protocol == ProtocolType.SHELL:
            hub = ShellHub(
                hub_id=f"{protocol}-hub",
                max_processes=hub_config.max_instances,
                persistence=self.persistence
            )
        elif protocol == ProtocolType.HTTP:
            hub = HTTPHub(
                hub_id=f"{protocol}-hub",
                max_connections=hub_config.max_instances * 10,
                persistence=self.persistence
            )
        else:
            logger.warning(f"Unknown protocol type: {protocol}")
            return None
        
        # Store configuration
        self.hub_configs[protocol] = hub_config
        
        return hub
    
    def get_hub(self, protocol: ProtocolType) -> Optional[ResourceHub]:
        """
        Get hub for a protocol.
        
        Args:
            protocol: Protocol to get hub for
            
        Returns:
            Hub instance or None
        """
        return self.hubs.get(protocol)
    
    async def allocate_resource(
        self,
        protocol: ProtocolType,
        requirements: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """
        Allocate a resource from the appropriate hub.
        
        Args:
            protocol: Protocol to allocate resource for
            requirements: Resource requirements
            
        Returns:
            Allocated resource or None
        """
        hub = self.get_hub(protocol)
        if not hub:
            # Protocol doesn't need resource allocation
            return {"type": protocol.value, "direct": True}
        
        # Allocate from hub
        resource = await hub.allocate_resource(requirements or {})
        if resource:
            logger.debug(f"Allocated {protocol} resource: {resource}")
        else:
            logger.warning(f"Failed to allocate {protocol} resource")
        
        return resource
    
    async def release_resource(
        self,
        protocol: ProtocolType,
        resource_id: str
    ) -> None:
        """
        Release a resource back to its hub.
        
        Args:
            protocol: Protocol of the resource
            resource_id: Resource identifier
        """
        hub = self.get_hub(protocol)
        if hub and hasattr(hub, 'release_resource'):
            await hub.release_resource(resource_id)
            logger.debug(f"Released {protocol} resource: {resource_id}")
    
    async def cleanup(self) -> None:
        """Cleanup all hubs"""
        for protocol, hub in self.hubs.items():
            try:
                await hub.cleanup()
                logger.info(f"Cleaned up hub for {protocol}")
            except Exception as e:
                logger.error(f"Error cleaning up {protocol} hub: {e}")
        
        self.hubs.clear()
        self._initialized = False
        logger.info("HubFactory cleaned up")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all hubs"""
        stats = {
            "initialized": self._initialized,
            "active_protocols": list(self.hubs.keys()),
            "hubs": {}
        }
        
        for protocol, hub in self.hubs.items():
            if hasattr(hub, 'get_stats'):
                stats["hubs"][protocol.value] = hub.get_stats()
            else:
                stats["hubs"][protocol.value] = {"status": "active"}
        
        return stats
    
    def register_hub_class(
        self,
        protocol: ProtocolType,
        hub_class: Type[ResourceHub]
    ) -> None:
        """
        Register a custom hub class for a protocol.
        
        Args:
            protocol: Protocol to register hub for
            hub_class: Hub class to register
        """
        self.HUB_REGISTRY[protocol] = hub_class
        logger.info(f"Registered hub class {hub_class.__name__} for protocol {protocol}")
    
    async def shutdown(self) -> None:
        """
        Shutdown all hubs and cleanup resources.
        
        This method ensures all protocol hubs are properly cleaned up
        when the HubFactory is shutting down.
        """
        logger.info("Shutting down HubFactory and all protocol hubs")
        
        # Shutdown each hub
        for protocol, hub in self.hubs.items():
            try:
                logger.debug(f"Shutting down {protocol.value} hub")
                if hasattr(hub, 'cleanup'):
                    await hub.cleanup()
                elif hasattr(hub, 'stop'):
                    await hub.stop()
                logger.debug(f"Successfully shut down {protocol.value} hub")
            except Exception as e:
                logger.error(f"Error shutting down {protocol.value} hub: {e}")
        
        # Clear the hubs dictionary
        self.hubs.clear()
        self._initialized = False
        
        logger.info("HubFactory shutdown complete")


# Singleton instance for global access
_hub_factory: Optional[HubFactory] = None


def get_hub_factory() -> HubFactory:
    """Get or create the global hub factory instance"""
    global _hub_factory
    if _hub_factory is None:
        _hub_factory = HubFactory()
    return _hub_factory


async def initialize_hub_factory(
    protocols: Optional[list[ProtocolType]] = None,
    persistence: Optional[PersistenceBackend] = None
) -> HubFactory:
    """
    Initialize the global hub factory.
    
    Args:
        protocols: Protocols to initialize
        persistence: Persistence backend
        
    Returns:
        Initialized hub factory
    """
    factory = get_hub_factory()
    if persistence:
        factory.persistence = persistence
    await factory.initialize(protocols)
    return factory