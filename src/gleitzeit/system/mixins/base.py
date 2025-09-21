"""
Base system manager mixin providing core infrastructure.
"""

import asyncio
import logging
import socket
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from ...persistence.unified_persistence import UnifiedPersistenceAdapter
from ...events.streamlined_event_bus import StreamlinedEventBus
from ..models import SystemConfig, DeploymentMode
# Archived components - removed for stateless architecture
# from ..service_registry import ServiceRegistry
# from ..health_monitor import HealthMonitor
# from ..distributed_registry import DistributedComponentRegistry
# from ..leader_election import LeaderElection
# from ..deployment_validator import DeploymentValidator  # May not exist after cleanup
from ...core.errors import SystemManagerError, PersistenceError, ServiceRegistrationError, ConfigValidationError

logger = logging.getLogger(__name__)


class BaseSystemMixin:
    """
    Base mixin providing core system infrastructure.

    This mixin handles:
    - Basic initialization and lifecycle
    - Persistence and event bus setup
    - Service registry and health monitoring
    - Leader election for distributed deployments
    - Component registry management
    """

    def __init__(self,
                 config: Optional[SystemConfig] = None,
                 persistence: Optional[UnifiedPersistenceAdapter] = None,
                 event_bus: Optional[StreamlinedEventBus] = None,
                 instance_id: Optional[str] = None,
                 **kwargs):
        """Initialize base system infrastructure."""
        self.config = config or SystemConfig()
        self.instance_id = instance_id or self._generate_instance_id()

        # Core infrastructure
        self.persistence = persistence
        self.event_bus = event_bus

        # System components - archived for stateless architecture
        self.service_registry = None  # Archived: ServiceRegistry had heartbeat loops
        self.health_monitor = None  # Archived: HealthMonitor had monitoring loops
        self.component_registry = None  # Archived: DistributedComponentRegistry had loops
        self.leader_election = None  # Archived: LeaderElection had election loops

        # System state
        self._initialized = False
        self._running = False
        self._start_time: Optional[datetime] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Continue the mixin chain with remaining kwargs
        super().__init__(**kwargs)

    def _generate_instance_id(self) -> str:
        """Generate a unique instance ID."""
        hostname = socket.gethostname()
        unique_id = uuid.uuid4().hex[:8]
        return f"{hostname}_{unique_id}"

    async def initialize_base(self):
        """Initialize base system infrastructure."""
        if self._initialized:
            logger.warning("Base system already initialized")
            return

        logger.info(f"Initializing base system infrastructure for {self.instance_id}")

        try:
            # Initialize persistence if not provided
            if not self.persistence:
                self.persistence = await self._create_persistence()

            # Deployment validation skipped in stateless mode
            logger.debug("Stateless mode - skipping deployment validation")

            # Initialize event bus if not provided
            if not self.event_bus:
                self.event_bus = await self._create_event_bus()

            # Component registry archived - had heartbeat loops
            # Stateless architecture doesn't need component tracking
            self.component_registry = None

            # Leader election archived - had election loops
            # Stateless architecture doesn't need leader election
            self.leader_election = None
            logger.info(f"Stateless mode - {self.instance_id} operating without leader election")

            # Service registry and health monitor archived - had loops
            # Stateless architecture handles health checks externally
            self.service_registry = None
            self.health_monitor = None
            logger.info("Stateless mode - service registry and health monitoring disabled")

            # Health monitor events disabled in stateless mode
            pass

            # Service registration disabled in stateless mode
            logger.debug("Skipping service registration in stateless mode")

            # Start heartbeat task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            self._initialized = True
            self._start_time = datetime.utcnow()

            logger.info(f"Base system infrastructure initialized for {self.instance_id}")

        except (PersistenceError, ServiceRegistrationError, ConfigValidationError) as e:
            logger.error(f"Failed to initialize base system: {e}")
            await self.shutdown_base()
            raise SystemManagerError("Base system initialization failed", cause=e)

    async def _create_persistence(self) -> UnifiedPersistenceAdapter:
        """Create persistence adapter based on configuration."""
        from ...persistence.factory import PersistenceFactory
        return await PersistenceFactory.create()

    async def _create_event_bus(self):
        """Create event bus - always use streamlined version."""
        from ...events.streamlined_event_bus import StreamlinedEventBus

        # Get Redis client from persistence
        redis_client = None
        if hasattr(self.persistence, 'redis'):
            redis_client = self.persistence.redis

        if not redis_client:
            logger.warning("No Redis available - event bus will be limited")
            # Could return a mock/noop bus here if needed

        # Create the ONE streamlined event bus
        event_bus = StreamlinedEventBus(
            redis_client=redis_client,
            instance_id=self.instance_id
        )

        # Ensure consumer groups exist
        if redis_client:
            await event_bus.ensure_consumer_groups()

        logger.info(f"Created StreamlinedEventBus for {self.instance_id}")
        return event_bus

    async def _register_self(self):
        """Service registration disabled in stateless mode."""
        pass  # No-op in stateless architecture

    async def _heartbeat_loop(self):
        """Heartbeat loop disabled in stateless mode."""
        pass  # No loops in stateless architecture

    async def shutdown_base(self):
        """Shutdown base system infrastructure."""
        logger.info("Shutting down base system infrastructure")

        # Stop heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Archived components - no shutdown needed in stateless mode
        logger.debug("Stateless mode - no service registry or health monitor to shutdown")

        self._initialized = False
        logger.info("Base system infrastructure shutdown complete")

    # Property accessors
    @property
    def is_initialized(self) -> bool:
        """Check if base system is initialized."""
        return self._initialized

    @property
    def is_running(self) -> bool:
        """Check if system is running."""
        return self._running

    @property
    def start_time(self) -> Optional[datetime]:
        """Get system start time."""
        return self._start_time

    def get_instance_id(self) -> str:
        """Get instance ID."""
        return self.instance_id

    async def _handle_health_monitor_check(self, event):
        """Health monitor disabled in stateless mode."""
        pass  # No-op in stateless architecture