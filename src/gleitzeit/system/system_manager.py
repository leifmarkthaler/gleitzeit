"""
System Manager - Central orchestration and lifecycle management for Gleitzeit.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Type
from datetime import datetime

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..persistence.factory import PersistenceFactory
from ..events.stateless_bus import StatelessEventBus
from ..core.events import GleitzeitEvent as Event, EventType
from ..core.execution_engine_v2 import ExecutionEngineV2
from ..core.workflow_loader_v2 import WorkflowLoaderV2, WorkflowLoaderConfig
from ..registry import ProtocolProviderRegistry as Registry
from ..providers.base import ProtocolProvider
from ..client import ClientMode
from ..core.errors import (
    SystemManagerError, ServiceDiscoveryError, ResourceAllocationError,
    DistributedRegistryError, ConfigValidationError, HealthCheckError,
    ServiceRegistrationError, ClientPoolError, ProviderHubError,
    SharedResourceError, CoordinationError, PersistenceError
)

from .models import (
    SystemConfig,
    DeploymentSpec,
    ServiceSpec,
    ServiceType,
    HealthStatus,
    DeploymentMode,
)
from .service_registry import ServiceRegistry
from .health_monitor import HealthMonitor
from .config_manager import ConfigurationManager
from .resource_coordinator import ResourceCoordinator, ResourceRequest, AllocationStrategy
from .distributed_registry import DistributedComponentRegistry, ComponentInfo
from .leader_election import LeaderElection
from .deployment_validator import DeploymentValidator


logger = logging.getLogger(__name__)


class SystemManager:
    """
    Central system orchestration and management.
    
    Responsibilities:
    - Bootstrap and shutdown system components
    - Coordinate service lifecycle
    - Manage system configuration
    - Monitor system health
    - Coordinate resource allocation
    - Handle deployment orchestration
    """
    
    def __init__(
        self,
        config: Optional[SystemConfig] = None,
        persistence: Optional[UnifiedPersistenceAdapter] = None,
        event_bus: Optional[StatelessEventBus] = None,
        instance_id: Optional[str] = None,
    ):
        """
        Initialize the SystemManager.
        
        Args:
            config: System configuration
            persistence: Optional persistence adapter (will create if not provided)
            event_bus: Optional event bus (will create if not provided)
            instance_id: Unique instance identifier for distributed mode
        """
        self.config = config or SystemConfig()
        self.instance_id = instance_id or self._generate_instance_id()
        
        # Core infrastructure
        self.persistence = persistence
        self.event_bus = event_bus
        
        # System components
        self.service_registry: Optional[ServiceRegistry] = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.config_manager: Optional[ConfigurationManager] = None
        self.resource_coordinator: Optional[ResourceCoordinator] = None
        
        # Distributed components
        self.component_registry: Optional[DistributedComponentRegistry] = None
        self.leader_election: Optional[LeaderElection] = None
        
        # Managed components (now stored in distributed registry)
        self.execution_engine: Optional[ExecutionEngineV2] = None
        self.registry: Optional[Registry] = None
        self.workflow_manager: Optional[Any] = None  # WorkflowManager
        self.log_collector: Optional[Any] = None  # LogCollector
        self.workflow_loader: Optional[WorkflowLoaderV2] = None  # WorkflowLoader
        
        # System state
        self._initialized = False
        self._running = False
        self._start_time: Optional[datetime] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # Distributed resources
        self.provider_hub: Optional[Any] = None
        self.provider_hub_runner: Optional[Any] = None  # aiohttp AppRunner
        self.provider_hub_task: Optional[asyncio.Task] = None
        self.shared_client_pool: Optional[Any] = None
        
    def _generate_instance_id(self) -> str:
        """Generate a unique instance ID."""
        import socket
        import uuid
        hostname = socket.gethostname()
        unique_id = uuid.uuid4().hex[:8]
        return f"{hostname}_{unique_id}"
    
    async def initialize(self):
        """Initialize the System Manager and core infrastructure."""
        if self._initialized:
            logger.warning("System Manager already initialized")
            return
            
        logger.info(f"Initializing System Manager {self.instance_id} in {self.config.deployment_mode} mode")
        
        try:
            # Initialize persistence if not provided
            if not self.persistence:
                self.persistence = await self._create_persistence()
            
            # Validate deployment configuration
            DeploymentValidator.enforce_requirements(self.config, self.persistence)
                
            # Initialize event bus if not provided
            if not self.event_bus:
                self.event_bus = await self._create_event_bus()
            
            # Initialize OpenTelemetry if configured
            await self._initialize_telemetry()
            
            # Initialize LogCollector early for centralized logging
            await self._initialize_log_collector()
            
            # Initialize Workflow Loader with central error and logging
            await self._initialize_workflow_loader()
                
            # Initialize distributed component registry
            self.component_registry = DistributedComponentRegistry(
                persistence=self.persistence,
                instance_id=self.instance_id,
                heartbeat_interval=30,
                component_timeout=120
            )
            
            # Initialize leader election (only for distributed modes)
            if self.config.deployment_mode in [DeploymentMode.PRODUCTION, DeploymentMode.KUBERNETES]:
                self.leader_election = LeaderElection(
                    persistence=self.persistence,
                    instance_id=self.instance_id,
                    lease_duration=30,
                    renewal_interval=10,
                    election_check_interval=1.0  # Fast initial election
                )
                
                # Set leader callbacks
                self.leader_election.set_callbacks(
                    on_elected=self._on_became_leader,
                    on_demoted=self._on_lost_leadership
                )
                
                # Start leader election
                await self.leader_election.start()
            else:
                # Development mode - single instance, always leader
                self.leader_election = None
                logger.info(f"Development mode - {self.instance_id} operating as single instance")
            
            # Initialize service registry
            self.service_registry = ServiceRegistry(
                persistence=self.persistence,
                event_bus=self.event_bus,
                heartbeat_interval=self.config.service_heartbeat_interval,
                service_timeout=self.config.service_timeout,
            )
            await self.service_registry.initialize()
            
            # Initialize configuration manager
            config_dir = Path.home() / ".gleitzeit" / "config"
            self.config_manager = ConfigurationManager(
                persistence=self.persistence,
                event_bus=self.event_bus,
                config_dir=config_dir,
                environment=self.config.environment,
                watch_interval=self.config.config_watch_interval,
                enable_hot_reload=self.config.config_reload_enabled,
            )
            await self.config_manager.initialize()
            
            # Initialize health monitor
            self.health_monitor = HealthMonitor(
                service_registry=self.service_registry,
                persistence=self.persistence,
                event_bus=self.event_bus,
                check_interval=self.config.health_check_interval,
                check_timeout=self.config.health_check_timeout,
                max_recovery_attempts=self.config.max_recovery_attempts,
                recovery_backoff=self.config.recovery_backoff,
            )
            await self.health_monitor.initialize()
            
            # Initialize resource coordinator
            self.resource_coordinator = ResourceCoordinator(
                service_registry=self.service_registry,
                persistence=self.persistence,
                event_bus=self.event_bus,
                default_strategy=AllocationStrategy(self.config.resource_allocation_strategy),
                enable_quotas=self.config.enable_resource_limits,
            )
            await self.resource_coordinator.initialize()
            
            # Register System Manager itself as a service
            await self._register_self()
            
            # Start heartbeat task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            self._initialized = True
            self._start_time = datetime.utcnow()
            
            logger.info(f"System Manager {self.instance_id} initialized successfully")
            
        except (PersistenceError, ServiceRegistrationError, ConfigValidationError) as e:
            logger.error(f"Failed to initialize System Manager: {e}")
            await self.shutdown()
            raise SystemManagerError("System Manager initialization failed", cause=e)
        except Exception as e:
            logger.error(f"Unexpected error during System Manager initialization: {e}")
            await self.shutdown()
            raise SystemManagerError("System Manager initialization failed due to unexpected error", cause=e)
            
    async def start_system(
        self,
        deployment_spec: Optional[DeploymentSpec] = None
    ) -> bool:
        """
        Start the entire Gleitzeit system.
        
        Args:
            deployment_spec: Optional deployment specification
            
        Returns:
            True if successful
        """
        if not self._initialized:
            await self.initialize()
            
        if self._running:
            logger.warning("System already running")
            return True
            
        logger.info("Starting Gleitzeit system")
        
        try:
            # Start core components
            await self._start_core_components()
            
            # Start resource layer (hubs)
            await self._start_resource_layer()
            
            # Register and start providers
            await self._start_providers()
            
            # Start workers if configured
            if self.config.deployment_mode != DeploymentMode.KUBERNETES:
                await self._start_workers()
                
            # Apply deployment spec if provided
            if deployment_spec:
                await self._apply_deployment(deployment_spec)
                
            self._running = True
            
            # Emit system started event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.SYSTEM_STARTED,
                    data={
                        "deployment_mode": self.config.deployment_mode if isinstance(self.config.deployment_mode, str) else self.config.deployment_mode.value,
                        "environment": self.config.environment,
                        "start_time": self._start_time.isoformat() if self._start_time else None,
                    }
                ))
                
            logger.info("Gleitzeit system started successfully")
            return True
            
        except (SystemManagerError, ServiceDiscoveryError, ResourceAllocationError) as e:
            logger.error(f"Failed to start system: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error starting system: {e}")
            raise SystemManagerError("System startup failed due to unexpected error", cause=e)
            
    async def shutdown_system(self, graceful: bool = True) -> bool:
        """
        Shutdown the entire Gleitzeit system.
        
        Args:
            graceful: If True, wait for active tasks to complete
            
        Returns:
            True if successful
        """
        logger.info(f"Shutting down Gleitzeit system (graceful={graceful})")
        
        try:
            self._running = False
            
            # Stop accepting new workflows
            if self.execution_engine:
                # In real implementation, would stop accepting new workflows
                pass
                
            # Wait for active tasks if graceful
            if graceful:
                await self._wait_for_active_tasks()
                
            # Shutdown workers
            await self._shutdown_workers()
            
            # Shutdown providers
            await self._shutdown_providers()
            
            # Shutdown hubs
            await self._shutdown_hubs()
            
            # Shutdown core components
            await self._shutdown_core_components()
            
            # Emit system shutdown event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.SYSTEM_SHUTDOWN,
                    data={
                        "graceful": graceful,
                        "uptime_seconds": (
                            (datetime.utcnow() - self._start_time).total_seconds()
                            if self._start_time else 0
                        ),
                    }
                ))
                
            logger.info("Gleitzeit system shutdown complete")
            return True
            
        except SystemManagerError as e:
            logger.error(f"Error during system shutdown: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during system shutdown: {e}")
            # Don't raise during shutdown - log and continue
            return False
            
    async def _heartbeat_loop(self):
        """Update component heartbeats periodically."""
        while self._initialized:
            try:
                await asyncio.sleep(30)  # Heartbeat interval
                await self.component_registry.update_all_heartbeats()
                # Cleanup stale components if we're the leader
                if self.leader_election and self.leader_election.is_leader():
                    removed = await self.component_registry.cleanup_stale_components()
                    if removed > 0:
                        logger.info(f"Cleaned up {removed} stale components")
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
    
    async def _on_became_leader(self):
        """Handle becoming the leader."""
        logger.info(f"Instance {self.instance_id} became leader")
        # Optionally take over orphaned components
        if self.component_registry:
            components = await self.component_registry.list_components(active_only=False)
            for component in components:
                if component.instance_id != self.instance_id:
                    # Check if owning instance is still alive
                    instance_components = await self.component_registry.list_components(
                        instance_id=component.instance_id
                    )
                    if not instance_components:
                        # Instance is dead, take over component
                        await self.component_registry.transfer_ownership(
                            component.component_id,
                            self.instance_id
                        )
                        logger.info(f"Took over orphaned component {component.component_id}")
    
    async def _on_lost_leadership(self):
        """Handle losing leadership."""
        logger.info(f"Instance {self.instance_id} lost leadership")
        # No special action needed, just log
    
    async def shutdown(self):
        """Shutdown the System Manager itself."""
        logger.info(f"Shutting down System Manager {self.instance_id}")
        
        # Stop heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Stop leader election
        if self.leader_election:
            await self.leader_election.stop()
        
        # Clear components for this instance
        if self.component_registry:
            await self.component_registry.clear_instance()
        
        # Deregister self
        if self.service_registry:
            await self.service_registry.deregister_service(f"system_manager_{self.instance_id}")
            
        # Stop reconciliation service
        if hasattr(self, 'reconciliation_service') and self.reconciliation_service:
            await self.reconciliation_service.stop()
            logger.info("Stopped ReconciliationService")
        
        # Shutdown components
        for component in [
            self.log_collector,  # Shutdown LogCollector early to flush remaining logs
            self.resource_coordinator,
            self.health_monitor,
            self.config_manager,
            self.service_registry,
        ]:
            if component:
                try:
                    await component.shutdown()
                except Exception as e:
                    logger.error(f"Error shutting down {component.__class__.__name__}: {e}")
                    
        self._initialized = False
        logger.info("System Manager shutdown complete")
        
    async def register_provider(
        self,
        provider_class: Type[ProtocolProvider],
        provider_id: str,
        protocol_id: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Register and start a provider.
        
        Args:
            provider_class: Provider class
            provider_id: Unique provider ID
            protocol_id: Protocol ID
            config: Optional provider configuration
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Registering provider: {provider_id} ({protocol_id})")
            
            # Get provider configuration
            provider_config = await self.config_manager.get_component_config(provider_id)
            if config:
                provider_config.update(config)
                
            # Create provider instance
            provider = provider_class(
                provider_id=provider_id,
                protocol_id=protocol_id,
                **provider_config
            )
            
            # Initialize provider
            await provider.initialize()
            
            # Register with registry
            if self.registry:
                self.registry.register_provider(
                    provider_id=provider_id,
                    protocol_id=protocol_id,
                    provider_instance=provider,
                    supported_methods=set(provider.get_supported_methods()),
                )
                
            # Register in distributed registry
            await self.component_registry.register_component(
                component_id=provider_id,
                component_type="provider",
                metadata={
                    "protocol": protocol_id,
                    "class": provider_class.__name__,
                    "config": provider_config
                }
            )
            
            # Register as service
            service_spec = ServiceSpec(
                service_id=provider_id,
                service_type=ServiceType.PROVIDER,
                name=provider.__class__.__name__,
                version="1.0.0",
                capabilities={
                    "protocol": protocol_id,
                    "methods": list(provider.get_supported_methods()),
                },
            )
            await self.service_registry.register_service(service_spec)
            
            logger.info(f"Provider registered successfully: {provider_id}")
            return True
            
        except (ServiceRegistrationError, DistributedRegistryError) as e:
            logger.error(f"Failed to register provider {provider_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error registering provider {provider_id}: {e}")
            raise ServiceRegistrationError(provider_id, "register", cause=e)
            
    async def register_hub(
        self,
        hub_id: str,
        hub_instance: Any,
    ) -> bool:
        """
        Register a resource hub.
        
        Args:
            hub_id: Unique hub ID
            hub_instance: Hub instance
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Registering hub: {hub_id}")
            
            # Initialize hub if needed
            if hasattr(hub_instance, "initialize"):
                await hub_instance.initialize()
                
            # Register in distributed registry
            await self.component_registry.register_component(
                component_id=hub_id,
                component_type="hub",
                metadata={
                    "class": hub_instance.__class__.__name__,
                    "resource_type": getattr(hub_instance, "resource_type", "unknown")
                }
            )
            
            # Register as service
            service_spec = ServiceSpec(
                service_id=hub_id,
                service_type=ServiceType.HUB,
                name=hub_instance.__class__.__name__,
                version="1.0.0",
                capabilities={
                    "resource_type": getattr(hub_instance, "resource_type", "unknown"),
                },
            )
            await self.service_registry.register_service(service_spec)
            
            logger.info(f"Hub registered successfully: {hub_id}")
            return True
            
        except (ServiceRegistrationError, DistributedRegistryError) as e:
            logger.error(f"Failed to register hub {hub_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error registering hub {hub_id}: {e}")
            raise ServiceRegistrationError(hub_id, "register", cause=e)
            
    async def start_worker(
        self,
        worker_id: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Start a worker.
        
        Args:
            worker_id: Unique worker ID
            config: Optional worker configuration
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Starting worker: {worker_id}")
            
            # Get worker configuration
            worker_config = await self.config_manager.get_component_config(worker_id)
            if config:
                worker_config.update(config)
                
            # In real implementation, would start actual worker process
            # For now, just register it
            
            # Register as service
            service_spec = ServiceSpec(
                service_id=worker_id,
                service_type=ServiceType.WORKER,
                name="Worker",
                version="1.0.0",
                capabilities={
                    "max_tasks": worker_config.get("max_tasks", 10),
                },
            )
            await self.service_registry.register_service(service_spec)
            
            # Register in distributed registry
            await self.component_registry.register_component(
                component_id=worker_id,
                component_type="worker",
                metadata={
                    "config": worker_config,
                    "started": datetime.utcnow().isoformat()
                }
            )
            
            logger.info(f"Worker started successfully: {worker_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start worker {worker_id}: {e}")
            return False
            
    def get_workflow_loader(self) -> Optional[WorkflowLoaderV2]:
        """
        Get the workflow loader instance.
        
        Returns:
            WorkflowLoaderV2 instance or None if not initialized
        """
        return self.workflow_loader
    
    async def get_system_status(self) -> Dict[str, Any]:
        """
        Get comprehensive system status.
        
        Returns:
            System status information
        """
        # Get health summary
        health = await self.health_monitor.get_system_health()
        
        # Get service count by type
        services = await self.service_registry.discover_services()
        service_counts = {}
        for service in services:
            # service_type might be string or enum
            type_key = service.service_type.value if hasattr(service.service_type, 'value') else service.service_type
            service_counts[type_key] = service_counts.get(type_key, 0) + 1
            
        # Get resource allocations
        allocations = await self.resource_coordinator.get_allocations()
        
        return {
            "status": "running" if self._running else "stopped",
            "deployment_mode": self.config.deployment_mode if isinstance(self.config.deployment_mode, str) else self.config.deployment_mode.value,
            "environment": self.config.environment,
            "uptime_seconds": (
                (datetime.utcnow() - self._start_time).total_seconds()
                if self._start_time else 0
            ),
            "health": health,
            "services": {
                "total": len(services),
                "by_type": service_counts,
            },
            "resources": {
                "allocations": len(allocations),
                "providers": len(await self.component_registry.list_components(component_type="provider")),
                "hubs": len(await self.component_registry.list_components(component_type="hub")),
                "workers": len(await self.component_registry.list_components(component_type="worker")),
            },
        }
        
    async def perform_health_check(self) -> HealthStatus:
        """
        Perform system-wide health check.
        
        Returns:
            Overall health status
        """
        health = await self.health_monitor.get_system_health()
        return HealthStatus(health["status"])
        
    # Private helper methods
    
    async def _create_persistence(self) -> UnifiedPersistenceAdapter:
        """Create persistence adapter based on configuration."""
        backend = self.config.persistence_backend
        
        # For production/kubernetes, force proper backend
        if self.config.deployment_mode in [DeploymentMode.PRODUCTION, DeploymentMode.KUBERNETES]:
            # Must use distributed backend
            adapter = await PersistenceFactory.create()
            
            # Validate it's not in-memory
            backend_type = type(adapter).__name__
            if "InMemory" in backend_type:
                raise ValueError(
                    f"Deployment mode {self.config.deployment_mode} requires a distributed "
                    f"persistence backend (Redis, PostgreSQL). In-memory backend is not supported."
                )
            return adapter
        
        # Development mode can use any backend
        if backend == "unified":
            return await PersistenceFactory.create()
        else:
            # Default to in-memory for development
            from ..persistence.unified_persistence import UnifiedInMemoryAdapter
            adapter = UnifiedInMemoryAdapter()
            await adapter.initialize()
            return adapter
            
    async def _create_event_bus(self):
        """Create event bus - use Pub/Sub if Redis available."""
        # Check if we have real Redis for Pub/Sub (not mock)
        # Create EventStore for persisting events
        from ..events.store import EventStore
        event_store = EventStore(self.persistence)
        
        if hasattr(self.persistence, 'redis'):
            # Check if it's a real Redis client (has pubsub method)
            if hasattr(self.persistence.redis, 'pubsub'):
                from ..events.pubsub_event_bus import PubSubEventBus
                logger.info("Creating PubSubEventBus for truly stateless operation")
                event_bus = PubSubEventBus(self.persistence.redis, event_store=event_store)
                await event_bus.start()
                return event_bus
            else:
                # Mock Redis client, use stateless bus
                logger.info("Mock Redis client detected, using StatelessEventBus")
                from ..events.stateless_bus import StatelessEventBus
                event_bus = StatelessEventBus(persistence=self.persistence, event_store=event_store)
                return event_bus
        else:
            # Fallback to stateless bus (less ideal)
            from ..events.stateless_bus import StatelessEventBus
            logger.warning("Redis not available, using StatelessEventBus (has limitations)")
            event_bus = StatelessEventBus(persistence=self.persistence, event_store=event_store)
            return event_bus
    
    async def _initialize_workflow_loader(self):
        """Initialize WorkflowLoader with central error and logging systems."""
        try:
            # Configure loader based on deployment mode
            loader_config = WorkflowLoaderConfig()
            
            # Set resource limits based on deployment mode
            if self.config.deployment_mode == DeploymentMode.DEVELOPMENT:
                loader_config.MAX_TASKS_PER_WORKFLOW = 1000
                loader_config.MAX_WORKFLOW_SIZE_MB = 10
                loader_config.MAX_BATCH_FILES = 100
            elif self.config.deployment_mode == DeploymentMode.STAGING:
                loader_config.MAX_TASKS_PER_WORKFLOW = 5000
                loader_config.MAX_WORKFLOW_SIZE_MB = 50
                loader_config.MAX_BATCH_FILES = 1000
            else:  # Production/Kubernetes
                loader_config.MAX_TASKS_PER_WORKFLOW = 10000
                loader_config.MAX_WORKFLOW_SIZE_MB = 100
                loader_config.MAX_BATCH_FILES = 5000
            
            # Enable caching for better performance
            loader_config.ENABLE_CACHING = True
            loader_config.CACHE_TTL_SECONDS = 300
            
            # Initialize loader
            self.workflow_loader = WorkflowLoaderV2(config=loader_config)
            
            # Register with component registry if available
            if self.component_registry:
                await self.component_registry.register_component(
                    component_id="workflow_loader",
                    component_type="service",
                    instance_id=self.instance_id,
                    metadata={
                        "max_tasks": loader_config.MAX_TASKS_PER_WORKFLOW,
                        "max_size_mb": loader_config.MAX_WORKFLOW_SIZE_MB,
                        "caching_enabled": loader_config.ENABLE_CACHING
                    }
                )
            
            logger.info(
                f"WorkflowLoader initialized with limits: "
                f"max_tasks={loader_config.MAX_TASKS_PER_WORKFLOW}, "
                f"max_size={loader_config.MAX_WORKFLOW_SIZE_MB}MB"
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize WorkflowLoader: {e}")
            # Non-critical component, continue without it
            self.workflow_loader = None
    
    async def _initialize_telemetry(self):
        """Initialize OpenTelemetry for distributed tracing and observability."""
        try:
            from ..core.telemetry_simple import initialize_telemetry, TelemetryConfig
            
            # Check for telemetry configuration from environment or config
            telemetry_config = self._get_telemetry_config()
            
            if telemetry_config:
                logger.info(f"Initializing OpenTelemetry with {telemetry_config.exporter_type} exporter")
                success = initialize_telemetry(telemetry_config)
                
                if success:
                    logger.info("OpenTelemetry initialized successfully")
                else:
                    logger.warning("OpenTelemetry initialization failed")
            else:
                logger.debug("No telemetry configuration found, OpenTelemetry disabled")
                
        except ImportError:
            logger.debug("OpenTelemetry not available, telemetry disabled")
        except Exception as e:
            logger.error(f"Failed to initialize telemetry: {e}")
            # Telemetry failure shouldn't prevent system startup
    
    def _get_telemetry_config(self) -> Optional['TelemetryConfig']:
        """Get telemetry configuration from environment or config."""
        import os
        from ..core.telemetry_simple import TelemetryConfig
        
        # Check environment variables for telemetry configuration
        exporter_type = os.getenv("GLEITZEIT_TELEMETRY_EXPORTER", "").lower()
        if not exporter_type:
            return None
        
        # Default configuration
        config = TelemetryConfig(
            service_name=os.getenv("GLEITZEIT_SERVICE_NAME", "gleitzeit"),
            service_version=os.getenv("GLEITZEIT_SERVICE_VERSION", "0.0.6"),
            exporter_type=exporter_type,
            exporter_endpoint=os.getenv("GLEITZEIT_TELEMETRY_ENDPOINT"),
            enable_logging_instrumentation=os.getenv("GLEITZEIT_TELEMETRY_LOGGING", "true").lower() == "true",
            sample_rate=float(os.getenv("GLEITZEIT_TELEMETRY_SAMPLE_RATE", "1.0"))
        )
        
        return config
    
    async def _initialize_log_collector(self):
        """Initialize LogCollector for centralized logging."""
        try:
            from ..core.log_collector import LogCollector, set_log_collector
            
            # Initialize LogCollector with UnifiedPersistenceAdapter
            self.log_collector = LogCollector(
                event_bus=self.event_bus,
                persistence=self.persistence,  # Pass unified persistence directly
                buffer_size=100,
                flush_interval=1.0,
                enable_persistence=True,
                enable_streaming=True
            )
            
            # Start the LogCollector
            await self.log_collector.start()
            
            # Set as global log collector
            set_log_collector(self.log_collector)
            
            logger.info("LogCollector initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize LogCollector: {e}")
            # LogCollector failure shouldn't prevent system startup
            self.log_collector = None
        
    async def _register_self(self):
        """Register System Manager as a service."""
        service_spec = ServiceSpec(
            service_id=f"system_manager_{self.instance_id}",
            service_type=ServiceType.API,  # Using API type for system manager
            name="SystemManager",
            version="1.0.0",
            endpoint=f"http://localhost:{self.config.metrics_port}" if self.config.metrics_enabled else None,
            capabilities={
                "deployment_mode": self.config.deployment_mode if isinstance(self.config.deployment_mode, str) else self.config.deployment_mode.value,
                "environment": self.config.environment,
            },
            health_check_endpoint=f"http://localhost:{self.config.metrics_port}/health" if self.config.metrics_enabled else None,
        )
        
        await self.service_registry.register_service(service_spec)
        
    async def _start_core_components(self):
        """Start core system components."""
        logger.info("Starting core components")
        
        # Initialize Registry (kept for protocol definitions, not provider execution)
        from ..registry import ProtocolProviderRegistry as Registry
        self.registry = Registry()  # Protocol registry only, providers go through pooling adapter
        
        # Initialize Queue Manager with persistence and event bus
        from ..task_queue import QueueManager
        queue_manager = QueueManager(persistence=self.persistence, event_bus=self.event_bus)
        
        # ALWAYS use stateless components for production safety
        # Get Redis client for atomic operations if available
        redis_client = None
        if hasattr(self.persistence, 'redis') or hasattr(self.persistence, '_redis'):
            redis_client = getattr(self.persistence, 'redis', None) or getattr(self.persistence, '_redis', None)
            if redis_client:
                logger.info("Redis client available for atomic operations")
            else:
                logger.warning("No Redis client found - atomic operations unavailable!")
        else:
            logger.info("Using in-memory persistence without Redis")
        
        # Use fully stateless dependency manager with atomic operations
        from ..core.stateless_dependency_manager import StatelessDependencyManager
        dependency_manager = StatelessDependencyManager(self.persistence, redis_client)
        if redis_client:
            logger.info("Created StatelessDependencyManager with atomic operations support")
        else:
            logger.info("Created StatelessDependencyManager (limited atomic operations)")
        
        # Initialize PoolingAdapter BEFORE creating ExecutionEngine
        # This provides access to pooled providers for task execution
        from ..providers.pooling_adapter import PoolingAdapter
        from ..providers.python_provider import PythonProvider
        from ..providers.shell_provider import ShellProvider
        
        # Create PoolingAdapter but don't set provider_hub yet (will be set later)
        pooling_adapter = PoolingAdapter(
            persistence=self.persistence,
            min_pool_size=1,
            max_pool_size=5,
            provider_hub=None  # Will be set after provider_hub is created
        )
        await pooling_adapter.initialize()
        logger.info("Initialized PoolingAdapter for provider management")
        
        # Register only pooled providers (Python/Shell)
        default_providers = self.config.default_providers or ["python"]
        
        for provider_type in default_providers:
            if provider_type == "python":
                await pooling_adapter.register_provider(
                    provider_id="python_provider",
                    protocol_id="python/v1",
                    provider_instance=PythonProvider
                )
                logger.info("Registered Python provider with pooling adapter")
            elif provider_type == "shell":
                await pooling_adapter.register_provider(
                    provider_id="shell_provider",
                    protocol_id="shell/v1",
                    provider_instance=ShellProvider
                )
                logger.info("Registered Shell provider with pooling adapter")
        
        # Store pooling adapter for later use
        self.pooling_adapter = pooling_adapter
        
        # Initialize Execution Engine with pooling adapter as primary provider access
        from ..core.execution_engine_v2 import ExecutionEngineV2
        
        self.execution_engine = ExecutionEngineV2(
            pooling_adapter=pooling_adapter,  # Required for all provider access
            queue_manager=queue_manager,
            dependency_resolver=dependency_manager,  # Always use stateless manager
            persistence=self.persistence,
            event_bus=self.event_bus
        )
        await self.execution_engine.start()
        
        # Register as service
        service_spec = ServiceSpec(
            service_id="execution_engine",
            service_type=ServiceType.API,
            name="ExecutionEngine",
            version="2.0.0",
            capabilities={
                "max_concurrent_workflows": 100,
            },
        )
        await self.service_registry.register_service(service_spec)
        
        # Use unified workflow manager
        from ..core.workflow_manager import WorkflowManager
        self.workflow_manager = WorkflowManager(
            execution_engine=self.execution_engine,
            dependency_manager=dependency_manager,
            persistence=self.persistence,
            event_bus=self.event_bus
        )
        # Note: Provider validation happens through execution_engine.pooling_adapter
        logger.info("Created WorkflowManager")
        logger.info("Started WorkflowManager")
        
        # Register WorkflowManager in component registry if available
        if self.component_registry:
            await self.component_registry.register_component(
                component_id="workflow_manager",
                component_type="WorkflowManager",
                metadata={
                    "features": ["templates", "scheduling", "policies"],
                    "version": "1.0.0"
                }
            )
            logger.info("Registered WorkflowManager in component registry")
        
        # Start ReconciliationService for workflow/task recovery
        from .reconciliation_service import ReconciliationService, ReconciliationMode
        
        # Determine reconciliation mode based on deployment
        if self.config.deployment_mode == DeploymentMode.PRODUCTION:
            # In production, run periodic reconciliation
            reconciliation_mode = ReconciliationMode.PERIODIC
            reconciliation_interval = 300  # 5 minutes
        else:
            # In development, just run on startup
            reconciliation_mode = ReconciliationMode.STARTUP
            reconciliation_interval = 60  # Not used in startup mode
        
        # Get atomic ops if available
        atomic_ops = None
        if hasattr(self, 'atomic_ops'):
            atomic_ops = self.atomic_ops
        elif redis_client:
            # Create atomic ops if we have Redis
            from ..persistence.atomic_operations import AtomicPersistenceOperations
            atomic_ops = AtomicPersistenceOperations(redis_client)
        
        self.reconciliation_service = ReconciliationService(
            persistence=self.persistence,
            event_bus=self.event_bus,
            atomic_ops=atomic_ops,
            task_timeout=3600,  # 1 hour timeout for stuck tasks
            reconciliation_interval=reconciliation_interval,
            mode=reconciliation_mode
        )
        
        # Start the reconciliation service
        await self.reconciliation_service.start()
        logger.info(f"Started ReconciliationService in {reconciliation_mode.value} mode")
        
        # Register in component registry
        if self.component_registry:
            await self.component_registry.register_component(
                component_id="reconciliation_service",
                component_type="ReconciliationService",
                metadata={
                    "mode": reconciliation_mode.value,
                    "task_timeout": 3600,
                    "interval": reconciliation_interval if reconciliation_mode == ReconciliationMode.PERIODIC else None
                }
            )
            logger.info("Registered ReconciliationService in component registry")
        
    async def _start_resource_layer(self):
        """Start resource hubs and shared client pool."""
        logger.info("Starting resource layer")
        
        # 1. Start ProviderHub HTTP server for clients
        await self._start_provider_hub()
        
        # 2. Initialize SharedClientPool for API instances
        await self._start_shared_client_pool()
        
        # 3. Initialize HubFactory for protocol-specific execution backends
        from ..hub.hub_factory import HubFactory, ProtocolType
        
        self.hub_factory = HubFactory(persistence=self.persistence)
        
        # Determine which hubs to start based on providers
        protocols_to_init = []
        if "python" in (self.config.default_providers or []):
            protocols_to_init.append(ProtocolType.SHELL)  # Python uses shell execution
        if "ollama" in (self.config.default_providers or []):
            protocols_to_init.append(ProtocolType.LLM)
        if "docker" in (self.config.default_providers or []):
            protocols_to_init.append(ProtocolType.DOCKER)
        
        # Initialize hubs
        if protocols_to_init:
            await self.hub_factory.initialize(protocols=protocols_to_init)
            
            # Register hubs with service registry
            for protocol, hub in self.hub_factory.hubs.items():
                service_spec = ServiceSpec(
                    service_id=f"{protocol.value}_hub",
                    service_type=ServiceType.HUB,
                    name=f"{protocol.value.upper()}Hub",
                    version="1.0.0",
                    capabilities={"protocol": protocol.value, "resource_type": protocol.value}
                )
                await self.service_registry.register_service(service_spec)
                # Hub is already registered in component registry via register_hub
                
            logger.info(f"Started {len(self.hub_factory.hubs)} resource hubs")
        
    async def _start_providers(self):
        """Start additional provider pools using the new pooling architecture."""
        logger.info("Starting additional provider pools")
        
        # Note: Core providers (python, shell) are already registered in _start_core_components()
        # via the PoolingAdapter. This method now handles additional providers like Ollama.
        
        from ..providers.ollama_provider import OllamaProvider
        
        # Only handle non-core providers here
        default_providers = self.config.default_providers or ["python"]
        
        for provider_type in default_providers:
            try:
                # Skip core providers already handled in _start_core_components
                if provider_type in ["python", "shell"]:
                    logger.debug(f"Skipping {provider_type} provider - already registered in core components")
                    continue
                
                # Handle Ollama provider
                if provider_type == "ollama":
                    # Ollama is already handled by ProviderHub (discovered and initialized)
                    # No need to register with pooling adapter - it will use ProviderHub
                    logger.info("Ollama provider available via ProviderHub (llm/v1)")
                    
                    # Register with service registry
                    service_spec = ServiceSpec(
                        service_id="ollama_provider_pool",
                        service_type=ServiceType.PROVIDER,
                        name="OllamaProviderPool",
                        version="1.0.0",
                        capabilities={"protocol": "llm", "pooled": True}
                    )
                    await self.service_registry.register_service(service_spec)
                    
            except Exception as e:
                logger.error(f"Failed to start {provider_type} provider pool: {e}")
        
    async def _start_workers(self):
        """Start worker processes."""
        logger.info("Starting workers")
        
        # Start workers based on configuration
        for i in range(min(self.config.max_workers, 1)):  # Start at least 1 worker
            worker_id = f"worker_{i}"
            await self.start_worker(worker_id)
            
    async def _apply_deployment(self, deployment_spec: DeploymentSpec):
        """Apply a deployment specification."""
        logger.info(f"Applying deployment: {deployment_spec.deployment_id}")
        
        # Register components from deployment spec
        for component_spec in deployment_spec.components:
            await self.service_registry.register_service(component_spec)
            
        # Apply configuration
        for key, value in deployment_spec.configuration.items():
            await self.config_manager.set_config(key, value)
            
    async def _wait_for_active_tasks(self, timeout: int = 300):
        """Wait for active tasks to complete."""
        logger.info("Waiting for active tasks to complete")
        
        start_time = datetime.utcnow()
        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            # In real implementation, would check active task count
            # For now, just wait a bit
            await asyncio.sleep(1)
            break
            
    async def _shutdown_workers(self):
        """Shutdown all workers."""
        logger.info("Shutting down workers")
        
        # Get workers from distributed registry
        workers = await self.component_registry.list_components(
            component_type="worker",
            instance_id=self.instance_id
        )
        
        for worker in workers:
            try:
                # In real implementation, would stop actual worker
                await self.service_registry.deregister_service(worker.component_id)
                await self.component_registry.unregister_component(worker.component_id)
            except Exception as e:
                logger.error(f"Error shutting down worker {worker.component_id}: {e}")
                
    async def _shutdown_providers(self):
        """Shutdown provider pools."""
        logger.info("Shutting down provider pools")
        
        # Shutdown pooling adapter
        if hasattr(self, 'pooling_adapter'):
            try:
                await self.pooling_adapter.shutdown()
                logger.info("Shutdown pooling adapter")
            except Exception as e:
                logger.error(f"Error shutting down pooling adapter: {e}")
        
        # Shutdown provider pool manager if it exists
        if hasattr(self, 'provider_pool_manager'):
            try:
                await self.provider_pool_manager.shutdown()
                # Deregister pool services
                for protocol in ["python", "shell", "ollama"]:
                    service_id = f"{protocol}_provider_pool"
                    try:
                        await self.service_registry.deregister_service(service_id)
                    except:
                        pass
            except Exception as e:
                logger.error(f"Error shutting down provider pool manager: {e}")
        
        # Get providers from distributed registry
        providers = await self.component_registry.list_components(
            component_type="provider",
            instance_id=self.instance_id
        )
        
        for provider_info in providers:
            try:
                # Provider instances are managed by pool manager
                await self.component_registry.unregister_component(provider_info.component_id)
            except Exception as e:
                logger.error(f"Error shutting down provider {provider_info.component_id}: {e}")
                
    async def _start_provider_hub(self):
        """Start the ProviderHub HTTP server for client connections."""
        logger.info("Starting ProviderHub HTTP server")
        
        # Only start in non-Kubernetes deployments
        if self.config.deployment_mode == DeploymentMode.KUBERNETES:
            logger.info("Skipping ProviderHub in Kubernetes mode (handled by K8s)")
            return
            
        from ..hub.provider_hub_simple import SimpleProviderHub
        from aiohttp import web
        
        try:
            # Create and initialize hub
            self.provider_hub = SimpleProviderHub()
            await self.provider_hub.initialize()
            
            # Connect ProviderHub to PoolingAdapter for unified access
            # This creates a single source of truth for providers
            if hasattr(self, 'pooling_adapter'):
                self.pooling_adapter.provider_hub = self.provider_hub
                logger.info("Connected ProviderHub to PoolingAdapter for unified provider access")
                
                # Track discovered protocols in PoolingAdapter for availability checks
                for protocol_id in self.provider_hub.providers.keys():
                    self.pooling_adapter._registered_protocols.add(protocol_id)
                    logger.debug(f"Tracked protocol {protocol_id} from ProviderHub")
            
            # Define web handlers
            async def handle_execute(request):
                """Handle execution requests"""
                try:
                    data = await request.json()
                    protocol_id = data.get("protocol", "python/v1")
                    from ..core.jsonrpc import JSONRPCRequest
                    jsonrpc_request = JSONRPCRequest(**data.get("request", {}))
                    
                    response = await self.provider_hub.execute_request(protocol_id, jsonrpc_request)
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
                    "protocols": list(self.provider_hub.providers.keys()),
                    "initialized": self.provider_hub._initialized
                })
            
            # Create web app
            app = web.Application()
            app.router.add_post('/execute', handle_execute)
            app.router.add_get('/health', handle_health)
            app.router.add_get('/stats', handle_stats)
            
            # Start server
            self.provider_hub_runner = web.AppRunner(app)
            await self.provider_hub_runner.setup()
            
            port = self.config.provider_hub_port
            site = web.TCPSite(self.provider_hub_runner, '0.0.0.0', port)
            
            # Start in background
            self.provider_hub_task = asyncio.create_task(site.start())
            
            logger.info(f"ProviderHub HTTP server started on port {port}")
            
            # Register in component registry
            await self.component_registry.register_component(
                component_id="provider_hub_http",
                component_type="hub",
                metadata={
                    "url": f"http://localhost:{port}",
                    "protocols": ["python/v1", "shell/v1"]
                }
            )
            
        except (ServiceRegistrationError, ProviderHubError) as e:
            logger.error(f"Failed to start ProviderHub: {e}")
            # Continue without hub - clients will use local providers
        except Exception as e:
            logger.error(f"Unexpected error starting ProviderHub: {e}")
            raise ProviderHubError("Failed to start ProviderHub", cause=e)
    
    async def _start_shared_client_pool(self):
        """Initialize SharedClientPool for distributed API instances."""
        logger.info("Starting SharedClientPool")
        
        from ..api.shared_dependencies import SharedClientPool
        
        try:
            # Create shared pool with distributed coordination
            self.shared_client_pool = SharedClientPool(
                persistence=self.persistence,
                instance_id=self.instance_id,
                max_size=self.config.api_client_pool_size,
                mode=ClientMode.NATIVE,
                idle_timeout=300
            )
            
            await self.shared_client_pool.initialize()
            
            logger.info("SharedClientPool initialized for API instances")
            
            # Register in component registry
            await self.component_registry.register_component(
                component_id="shared_client_pool",
                component_type="resource",
                metadata={
                    "max_size": self.shared_client_pool.max_size,
                    "instance_id": self.instance_id
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize SharedClientPool: {e}")
    
    async def _shutdown_hubs(self):
        """Shutdown all hubs."""
        logger.info("Shutting down hubs")
        
        # Shutdown ProviderHub HTTP server
        if self.provider_hub_runner:
            try:
                logger.debug("Shutting down ProviderHub HTTP server")
                await self.provider_hub_runner.cleanup()
                self.provider_hub_runner = None
                logger.debug("ProviderHub HTTP server shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down ProviderHub: {e}")
        
        if self.provider_hub_task:
            self.provider_hub_task.cancel()
            try:
                await self.provider_hub_task
            except asyncio.CancelledError:
                pass
            self.provider_hub_task = None
        
        if self.provider_hub:
            try:
                if hasattr(self.provider_hub, 'cleanup'):
                    await self.provider_hub.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up ProviderHub: {e}")
            self.provider_hub = None
        
        # Shutdown HubFactory and all its hubs
        if hasattr(self, 'hub_factory'):
            try:
                await self.hub_factory.shutdown()
                # Deregister hub services from distributed registry
                hubs = await self.component_registry.list_components(
                    component_type="hub",
                    instance_id=self.instance_id
                )
                for hub in hubs:
                    try:
                        await self.service_registry.deregister_service(hub.component_id)
                        await self.component_registry.unregister_component(hub.component_id)
                    except:
                        pass
            except Exception as e:
                logger.error(f"Error shutting down hub factory: {e}")
                
    async def _shutdown_core_components(self):
        """Shutdown core components."""
        logger.info("Shutting down core components")
        
        # Shutdown SharedClientPool
        if self.shared_client_pool:
            try:
                logger.debug("Shutting down SharedClientPool")
                await self.shared_client_pool.shutdown()
                self.shared_client_pool = None
                logger.debug("SharedClientPool shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down SharedClientPool: {e}")
        
        # Shutdown WorkflowManager before ExecutionEngine
        if self.workflow_manager:
            try:
                logger.debug("Shutting down WorkflowManager")
                # Check if it's the regular WorkflowManager with stop_scheduler
                if hasattr(self.workflow_manager, 'stop_scheduler'):
                    await self.workflow_manager.stop_scheduler()
                # Unregister from component registry
                if self.component_registry:
                    await self.component_registry.unregister_component("workflow_manager")
                self.workflow_manager = None
                logger.debug("WorkflowManager shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down WorkflowManager: {e}")
        
        if self.execution_engine:
            try:
                await self.execution_engine.stop()
                await self.service_registry.deregister_service("execution_engine")
            except Exception as e:
                logger.error(f"Error shutting down execution engine: {e}")
                
        self.registry = None