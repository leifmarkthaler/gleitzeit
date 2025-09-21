"""
Stateless Modular Stream System Manager using mixins without loops.

This system manager is built using composable mixins, each providing specific
functionality without any loops or background tasks. It focuses purely on Redis
Streams for all event processing in a stateless, trigger-based manner.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Union
from datetime import datetime

from .mixins import (
    BaseSystemMixin,
    StreamExecutionMixin,
    StreamMonitoringMixin,
    StreamProvidersMixin,
    StreamAuthMixin
)
from .mixins.stateless_stream_core import StatelessStreamCoreMixin
from .mixins.stateless_stream_timers import StatelessStreamTimersMixin
# StatelessStreamSignalsMixin removed - signals now handled by SignalWorker
from .models import SystemConfig, DeploymentSpec
from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..events import StatelessEventBus
from ..core.errors import (
    SystemManagerError, AuthenticationError, AuthorizationError,
    WorkflowValidationError, SystemError, ErrorCode
)
from ..core.events import EventType, GleitzeitEvent

logger = logging.getLogger(__name__)


class ModularStreamSystemManager(
    BaseSystemMixin,
    StatelessStreamCoreMixin,      # Stateless stream core (no loops!)
    StreamExecutionMixin,
    StatelessStreamTimersMixin,    # Stateless timers (no loops!)
    # StatelessStreamSignalsMixin removed - signals now handled by SignalWorker
    StreamMonitoringMixin,
    StreamProvidersMixin,
    StreamAuthMixin
):
    """
    Stateless modular streaming-only system manager using composable mixins.

    This system manager provides:
    - Pure Redis Streams architecture (no polling, no loops)
    - Completely stateless operation
    - External trigger-based processing
    - Full workflow and task execution
    - Timer and signal management via stateless components
    - Comprehensive monitoring and observability
    - Authentication and authorization
    - Provider management and pooling

    Each functional area is implemented as a separate mixin without any loops
    or background tasks. All processing is trigger-based.
    """

    @classmethod
    async def create(
        cls,
        config: Optional[SystemConfig] = None,
        persistence: Optional[UnifiedPersistenceAdapter] = None,
        instance_id: Optional[str] = None,
        stream_config: Optional[Dict[str, Any]] = None,
        create_if_missing: bool = True,
        start_system: bool = True
    ) -> Optional["ModularStreamSystemManager"]:
        """
        Factory method to create and initialize a ModularStreamSystemManager.

        Args:
            config: System configuration
            persistence: Optional persistence adapter
            instance_id: Instance identifier
            stream_config: Stream-specific configuration
            create_if_missing: Create new system if none exists
            start_system: Start the system after creation

        Returns:
            Initialized ModularStreamSystemManager
        """
        # Get or create persistence
        if not persistence:
            from ..persistence.factory import PersistenceFactory
            persistence = await PersistenceFactory.create()

        # Generate instance ID if not provided
        if not instance_id:
            import socket
            import uuid
            hostname = socket.gethostname()
            unique_id = uuid.uuid4().hex[:8]
            instance_id = f"{hostname}_{unique_id}"

        # Check for existing system managers
        existing_system = False
        try:
            if hasattr(persistence, 'keys'):
                registry_pattern = "distributed_registry:component:system_manager:*"
                system_managers = await persistence.keys(registry_pattern)
                if system_managers:
                    existing_system = True
                    logger.info(f"Discovered {len(system_managers)} active SystemManager(s)")
        except Exception as e:
            logger.warning(f"Could not discover SystemManagers: {e}")

        # Create new instance (always stateless)
        manager = cls(
            config=config,
            persistence=persistence,
            instance_id=instance_id,
            stream_config=stream_config
        )

        # Initialize the manager
        await manager.initialize()

        # Start system if needed
        if not existing_system:
            if not create_if_missing:
                logger.warning("No existing system found and create_if_missing=False")
                return None

            if start_system:
                await manager.start_system()
                logger.info(f"Started new stateless modular stream system with {instance_id}")
        else:
            logger.info(f"ModularStreamSystemManager {instance_id} connected to existing system")

        return manager

    def __init__(
        self,
        config: Optional[SystemConfig] = None,
        persistence: Optional[UnifiedPersistenceAdapter] = None,
        event_bus: Optional[StatelessEventBus] = None,
        instance_id: Optional[str] = None,
        stream_config: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        Initialize the stateless modular stream system manager.

        Args:
            config: System configuration
            persistence: Persistence adapter
            event_bus: Event bus
            instance_id: Instance identifier
            stream_config: Stream-specific configuration
            **kwargs: Additional configuration
        """
        # Initialize all mixins with shared parameters
        super().__init__(
            config=config,
            persistence=persistence,
            event_bus=event_bus,
            instance_id=instance_id,
            stream_config=stream_config,
            **kwargs
        )

        # No background tasks or loops!
        self._trigger_processing = False

        logger.info(f"Initialized Stateless ModularStreamSystemManager {self.instance_id}")

    async def initialize(self):
        """Initialize the stateless modular stream system manager."""
        if self._initialized:
            logger.warning("ModularStreamSystemManager already initialized")
            return

        logger.info(f"Initializing Stateless ModularStreamSystemManager {self.instance_id}")

        try:
            # Phase 1: Initialize base infrastructure
            logger.info("Phase 1: Initializing base infrastructure")
            await self.initialize_base()

            # Phase 2: Initialize stateless stream core
            logger.info("Phase 2: Initializing stateless stream core (NO LOOPS!)")
            await self.initialize_stateless_stream_core()

            # Phase 3: Initialize execution infrastructure
            logger.info("Phase 3: Initializing execution infrastructure")
            await self.initialize_stream_execution()

            # Phase 4: Initialize providers
            logger.info("Phase 4: Initializing providers")
            await self.initialize_stream_providers()

            # Phase 4.5: Initialize additional resource layers
            logger.info("Phase 4.5: Initializing resource layers")
            await self._initialize_resource_layers()

            # Phase 5: Initialize stateless specialized components
            logger.info("Phase 5: Initializing stateless components (NO LOOPS!)")
            await self.initialize_stateless_stream_timers()
            # Signals now handled by SignalWorker, no initialization needed here

            # Phase 5.5: Initialize workflow support components
            logger.info("Phase 5.5: Initializing workflow support components")
            await self._initialize_workflow_support()

            # Phase 6: Initialize monitoring and auth
            logger.info("Phase 6: Initializing monitoring and auth")
            await self.initialize_stream_monitoring()
            await self.initialize_stream_auth()

            # NO provider heartbeat loop - use external triggers instead!

            self._initialized = True
            logger.info(f"Stateless ModularStreamSystemManager {self.instance_id} initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize ModularStreamSystemManager: {e}")
            await self.shutdown()
            raise SystemManagerError("ModularStreamSystemManager initialization failed", cause=e)

    async def _initialize_resource_layers(self):
        """Initialize additional resource layers (HubFactory, SharedClientPool)."""
        try:
            # Initialize HubFactory for protocol-specific execution backends
            from ..hub.hub_factory import HubFactory, ProtocolType

            self.hub_factory = HubFactory(persistence=self.persistence)

            # Determine which hubs to start based on providers
            config = getattr(self, 'config', None)
            default_providers = config.default_providers if config else ["python"]
            protocols_to_init = []

            if "python" in default_providers:
                protocols_to_init.append(ProtocolType.SHELL)
            if "ollama" in default_providers:
                protocols_to_init.append(ProtocolType.LLM)
            if "docker" in default_providers:
                protocols_to_init.append(ProtocolType.DOCKER)

            # Initialize hubs
            if protocols_to_init:
                await self.hub_factory.initialize(protocols=protocols_to_init)
                logger.info(f"Started {len(self.hub_factory.hubs)} resource hubs")

            # Initialize SharedClientPool for distributed API instances
            from ..api.shared_dependencies import SharedClientPool
            from ..client import ClientMode

            self.shared_client_pool = SharedClientPool(
                persistence=self.persistence,
                instance_id=self.instance_id,
                max_size=getattr(self.config, 'api_client_pool_size', 10),
                mode=ClientMode.NATIVE,
                idle_timeout=300
            )

            await self.shared_client_pool.initialize()
            logger.info("SharedClientPool initialized")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="shared_client_pool",
                    component_type="resource",
                    metadata={
                        "max_size": self.shared_client_pool.max_size,
                        "instance_id": self.instance_id,
                        "stateless": True
                    }
                )

        except Exception as e:
            logger.error(f"Failed to initialize resource layers: {e}")
            # Non-critical, continue

    async def _initialize_workflow_support(self):
        """Initialize workflow support components (reconciliation, progress handler)."""
        try:
            # Initialize WorkflowProgressHandler for event-driven workflow progress tracking
            from ..core.workflow_progress_handler import WorkflowProgressHandler

            self.workflow_progress_handler = WorkflowProgressHandler(
                event_bus=self.event_bus,
                persistence=self.persistence,
                instance_id=self.instance_id
            )
            await self.workflow_progress_handler.start()
            logger.info("Started WorkflowProgressHandler")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="workflow_progress_handler",
                    component_type="service",
                    metadata={
                        "instance_id": self.instance_id,
                        "event_driven": True,
                        "handles_events": ["TASK_COMPLETED", "TASK_FAILED"]
                    }
                )

            # Start StatelessReconciliationManager for distributed workflow/task recovery
            from .stateless_reconciliation_manager import StatelessReconciliationManager

            self.reconciliation_service = StatelessReconciliationManager(
                persistence=self.persistence,
                event_bus=self.event_bus,
                instance_id=self.instance_id,
                reconciliation_ttl=300
            )

            await self.reconciliation_service.initialize()
            logger.info("Initialized StatelessReconciliationManager")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="reconciliation_manager",
                    component_type="service",
                    metadata={
                        "stateless": True,
                        "no_loops": True,
                        "reconciliation_ttl": 300,
                        "instance_id": self.instance_id
                    }
                )

        except Exception as e:
            logger.error(f"Failed to initialize workflow support: {e}")
            # Non-critical, continue

    async def process_all_once(self) -> Dict[str, Any]:
        """
        Process all components once - NO LOOPS!
        This is the main entry point for stateless processing.

        Returns:
            Processing statistics
        """
        stats = {
            "streams": {},
            "timers": {},
            "signals": {},
            "scheduler": {},
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            # Process streams
            if hasattr(self, 'process_streams_once'):
                stats["streams"] = await self.process_streams_once()

            # Process timers
            if hasattr(self, 'process_timers_once'):
                stats["timers"] = await self.process_timers_once()

            # Signal processing now handled by SignalWorker, not here

            # Process scheduled events
            if hasattr(self, 'redis_client'):
                from ..scheduler.stateless_scheduler import StatelessScheduler
                stats["scheduler"] = await StatelessScheduler.process_all_once(self.redis_client)

            logger.debug(f"Processed all components: {stats}")

        except Exception as e:
            logger.error(f"Error in stateless processing: {e}")
            stats["error"] = str(e)

        return stats

    def register_event_handler(self, event_type: str, handler, component_name: str = None):
        """
        Register an event handler for compatibility with workflow manager.

        In stateless mode, handlers are registered with the event bus adapter.

        Args:
            event_type: Type of event to handle
            handler: Handler function
            component_name: Component registering the handler
        """
        try:
            if hasattr(self, 'event_bus') and self.event_bus:
                # Register with stateless event bus
                self.event_bus.register_handler(event_type, handler)
                logger.debug(f"Registered handler for {event_type} from {component_name}")
            else:
                logger.warning(f"Cannot register handler for {event_type} - no event bus available")
        except Exception as e:
            logger.error(f"Failed to register event handler: {e}")

    async def trigger_processing(self, action: str = "consume") -> bool:
        """
        Trigger processing of all components.

        Args:
            action: Trigger action

        Returns:
            True if triggered successfully
        """
        try:
            # Send trigger to stream consumer
            if hasattr(self, 'trigger_processing'):
                result = await super().trigger_processing(action)

            # Process all components once
            await self.process_all_once()

            return True

        except Exception as e:
            logger.error(f"Error triggering processing: {e}")
            return False

    async def refresh_provider_registrations(self) -> int:
        """
        Refresh provider registrations (called by external trigger, not a loop).

        Returns:
            Number of providers refreshed
        """
        if not hasattr(self, 'registry') or not self.registry:
            return 0

        refreshed = 0
        protocols_to_refresh = []

        try:
            # Collect all registered protocols
            if hasattr(self, 'pooling_adapter') and self.pooling_adapter:
                for protocol_id in self.pooling_adapter._registered_protocols:
                    if protocol_id == "python/v1":
                        protocols_to_refresh.append((protocol_id, {
                            "provider_id": "python_provider",
                            "instance_id": self.instance_id,
                            "capabilities": ["python/execute", "python/validate", "python/info"]
                        }))
                    elif protocol_id == "shell/v1":
                        protocols_to_refresh.append((protocol_id, {
                            "provider_id": "shell_provider",
                            "instance_id": self.instance_id,
                            "capabilities": ["shell/execute", "shell/validate", "shell/info"]
                        }))

            # Check provider hub for registered protocols
            if hasattr(self, 'provider_hub') and self.provider_hub:
                if hasattr(self.provider_hub, 'providers'):
                    for protocol_id, provider in self.provider_hub.providers.items():
                        protocols_to_refresh.append((protocol_id, {
                            "provider_id": f"{protocol_id}_provider",
                            "instance_id": self.instance_id,
                            "hub_based": True,
                            "capabilities": provider.get_supported_methods()
                                          if hasattr(provider, 'get_supported_methods')
                                          else []
                        }))

            # Refresh each protocol registration
            for protocol_id, provider_info in protocols_to_refresh:
                try:
                    await self.registry.refresh_provider_registration(protocol_id, provider_info)
                    logger.debug(f"Refreshed provider registration for {protocol_id}")
                    refreshed += 1
                except Exception as e:
                    logger.error(f"Failed to refresh provider {protocol_id}: {e}")

            if refreshed > 0:
                logger.info(f"Refreshed {refreshed} provider registrations")

        except Exception as e:
            logger.error(f"Error refreshing provider registrations: {e}")

        return refreshed

    async def start_system(self, deployment_spec: Optional[DeploymentSpec] = None) -> bool:
        """Start the stateless modular stream system."""
        if not self._initialized:
            await self.initialize()

        if self._running:
            logger.warning("System already running")
            return True

        logger.info("Starting stateless modular stream-based Gleitzeit system")

        try:
            # Phase 1: Register all event handlers
            logger.info("Phase 1: Registering event handlers")
            await self._register_all_event_handlers()

            # Phase 2: NO stream consumer to start - it's triggered externally!
            logger.info("Phase 2: Stream processing ready (waiting for triggers)")

            # Phase 3: Apply deployment spec if provided
            if deployment_spec:
                logger.info("Phase 3: Applying deployment specification")
                await self._apply_deployment(deployment_spec)

            self._running = True

            # Phase 4: NO monitoring loops - everything is trigger-based!
            logger.info("Phase 4: System ready for external triggers (NO LOOPS!)")

            # Phase 5: Emit system started event
            if hasattr(self, 'emit_system_event'):
                await self.emit_system_event(
                    EventType.SYSTEM_STARTED,
                    {
                        "deployment_mode": (
                            self.config.deployment_mode
                            if isinstance(self.config.deployment_mode, str)
                            else self.config.deployment_mode.value
                        ),
                        "environment": self.config.environment,
                        "start_time": self._start_time.isoformat() if self._start_time else None,
                        "stream_based": True,
                        "modular": True,
                        "stateless": True,
                        "has_loops": False
                    }
                )

            logger.info("Stateless modular stream-based Gleitzeit system started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to start stateless modular stream system: {e}")
            return False

    async def _register_all_event_handlers(self):
        """Register all event handlers from components."""
        # Implementation depends on other mixins
        pass

    async def _apply_deployment(self, deployment_spec: DeploymentSpec):
        """Apply deployment specification."""
        # Implementation depends on deployment requirements
        pass

    async def shutdown(self):
        """Shutdown the stateless modular stream system."""
        logger.info("Shutting down stateless modular stream system")

        try:
            # Phase 1: Mark as not running
            self._running = False

            # Phase 2: Send shutdown triggers
            if hasattr(self, 'trigger_processing'):
                await self.trigger_processing("shutdown")

            # Phase 3: Shutdown stateless components (no loops to stop!)
            if hasattr(self, 'shutdown_stateless_stream_core'):
                await self.shutdown_stateless_stream_core()

            if hasattr(self, 'shutdown_stateless_stream_timers'):
                await self.shutdown_stateless_stream_timers()

            # Signals now handled by SignalWorker, no shutdown needed here

            # Phase 4: Shutdown other components
            if hasattr(self, 'shutdown_stream_execution'):
                await self.shutdown_stream_execution()

            if hasattr(self, 'shutdown_stream_monitoring'):
                await self.shutdown_stream_monitoring()

            if hasattr(self, 'shutdown_stream_providers'):
                await self.shutdown_stream_providers()

            if hasattr(self, 'shutdown_stream_auth'):
                await self.shutdown_stream_auth()

            # Phase 5: Cleanup resources
            if hasattr(self, 'hub_factory') and self.hub_factory:
                await self.hub_factory.shutdown()

            if hasattr(self, 'shared_client_pool') and self.shared_client_pool:
                await self.shared_client_pool.cleanup()

            if hasattr(self, 'workflow_progress_handler') and self.workflow_progress_handler:
                await self.workflow_progress_handler.stop()

            if hasattr(self, 'reconciliation_service') and self.reconciliation_service:
                await self.reconciliation_service.shutdown()

            # Phase 6: Emit shutdown event
            if hasattr(self, 'emit_system_event'):
                await self.emit_system_event(
                    EventType.SYSTEM_SHUTDOWN,
                    {
                        "instance_id": self.instance_id,
                        "clean_shutdown": True,
                        "stateless": True
                    }
                )

            logger.info("Stateless modular stream system shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    # Workflow management methods (delegated to mixins)

    async def submit_workflow(
        self,
        workflow: Union['Workflow', Dict[str, Any]]
    ) -> str:
        """Submit a workflow for execution."""
        # Delegate to the stream_execution mixin's submit_workflow method
        # which properly uses WorkflowLoaderV2 for validation
        return await super().submit_workflow(workflow)

    async def submit_workflow_authenticated(
        self,
        workflow: Union['Workflow', Dict[str, Any]],
        session_id: str
    ) -> str:
        """Submit workflow with authentication."""
        # Verify session
        if hasattr(self, 'verify_session'):
            is_valid = await self.verify_session(session_id)
            if not is_valid:
                raise AuthenticationError("Invalid session")

        return await self.submit_workflow(workflow)

    async def get_workflow(self, workflow_id: str) -> Optional['Workflow']:
        """Get workflow by ID."""
        if hasattr(self, 'get_workflow_stream'):
            return await self.get_workflow_stream(workflow_id)
        else:
            return await self.persistence.get_workflow(workflow_id)

    async def get_workflow_authenticated(
        self,
        workflow_id: str,
        session_id: str
    ) -> Optional['Workflow']:
        """Get workflow with authentication."""
        # Verify session
        if hasattr(self, 'verify_session'):
            is_valid = await self.verify_session(session_id)
            if not is_valid:
                raise AuthenticationError("Invalid session")

        return await self.get_workflow(workflow_id)

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a workflow."""
        if hasattr(self, 'cancel_workflow_stream'):
            return await self.cancel_workflow_stream(workflow_id)
        else:
            raise NotImplementedError("Workflow cancellation not available")

    async def get_task_result(self, task_id: str) -> Optional['TaskResult']:
        """Get task result."""
        if hasattr(self, 'get_task_result_stream'):
            return await self.get_task_result_stream(task_id)
        else:
            return await self.persistence.get_task_result(task_id)

    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        stats = {
            "instance_id": self.instance_id,
            "initialized": self._initialized,
            "running": self._running,
            "stateless": True,
            "has_loops": False
        }

        # Add statistics from mixins
        if hasattr(self, 'get_stream_statistics'):
            stats["streams"] = self.get_stream_statistics()

        if hasattr(self, 'get_timer_statistics'):
            stats["timers"] = self.get_timer_statistics()

        if hasattr(self, 'get_signal_statistics'):
            stats["signals"] = self.get_signal_statistics()

        if hasattr(self, 'get_execution_statistics'):
            stats["execution"] = self.get_execution_statistics()

        if hasattr(self, 'get_monitoring_statistics'):
            stats["monitoring"] = self.get_monitoring_statistics()

        return stats