"""
Stateless Service Registry for dynamic service discovery and registration.

This is a stateless version without persistent loops.
All monitoring is done via external triggers.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent as Event, EventType
from ..events import StatelessEventBus
from ..core.errors import (
    ServiceRegistrationError, ServiceDiscoveryError, PersistenceError,
    HealthCheckError
)
from .models import (
    ServiceSpec,
    ServiceStatus,
    ServiceType,
    ServiceCriteria,
    HealthStatus,
)


logger = logging.getLogger(__name__)


class StatelessServiceRegistry:
    """
    Stateless registry for all services in the Gleitzeit system.

    Key differences from the original:
    - NO persistent loops or monitoring
    - Health checks triggered externally
    - Cleanup triggered externally
    - Single-check operations only

    Features:
    - Service registration and deregistration
    - Service discovery with filtering
    - On-demand health status checking
    - Load balancing metadata
    - Service dependency management
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[StatelessEventBus] = None,
        heartbeat_timeout: int = 60,
        stale_service_timeout: int = 180,
    ):
        """
        Initialize the StatelessServiceRegistry.

        Args:
            persistence: Persistence adapter for storing service data
            event_bus: Event bus for service events
            heartbeat_timeout: Seconds before marking service as unhealthy
            stale_service_timeout: Seconds before removing stale services
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.heartbeat_timeout = heartbeat_timeout
        self.stale_service_timeout = stale_service_timeout

        # Local cache for performance (rebuilt from persistence)
        self._services: Dict[str, ServiceSpec] = {}
        self._service_status: Dict[str, ServiceStatus] = {}
        self._services_by_type: Dict[ServiceType, Set[str]] = {}

    async def initialize(self):
        """
        Initialize the service registry.

        Note: This does NOT start any loops!
        It only loads existing services from persistence.
        """
        logger.info("Initializing StatelessServiceRegistry (no loops!)")

        # Load existing services from persistence
        await self._load_services()

        # Register event handlers if event bus is available
        if self.event_bus:
            await self._register_event_handlers()

        logger.info("StatelessServiceRegistry initialized")

    async def shutdown(self):
        """Shutdown the service registry."""
        logger.info("Shutting down StatelessServiceRegistry")
        # No loops to cancel!
        logger.info("StatelessServiceRegistry shutdown complete")

    async def register_service(self, service: ServiceSpec) -> bool:
        """
        Register a new service or update existing one.

        Args:
            service: Service specification

        Returns:
            True if registration successful
        """
        try:
            logger.info(f"Registering service: {service.service_id} ({service.service_type})")

            # Update registration time
            service.registered_at = datetime.utcnow()
            service.last_heartbeat = datetime.utcnow()

            # Store in persistence
            key = f"service:{service.service_id}"
            await self.persistence.set(key, service.__dict__)

            # Update local cache
            self._services[service.service_id] = service

            # Update type index
            if service.service_type not in self._services_by_type:
                self._services_by_type[service.service_type] = set()
            self._services_by_type[service.service_type].add(service.service_id)

            # Initialize status
            self._service_status[service.service_id] = ServiceStatus(
                service_id=service.service_id,
                health_status=HealthStatus.HEALTHY,
                is_active=True,
                last_check=datetime.utcnow(),
                uptime_seconds=0,
            )

            # Emit event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.SERVICE_REGISTERED,
                    data={
                        "service_id": service.service_id,
                        "service_type": service.service_type.value,
                        "endpoint": service.endpoint,
                    }
                ))

            logger.info(f"Service registered successfully: {service.service_id}")
            return True

        except PersistenceError as e:
            logger.error(f"Failed to register service {service.service_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error registering service {service.service_id}: {e}")
            raise ServiceRegistrationError(service.service_id, "register", cause=e)

    async def deregister_service(self, service_id: str) -> bool:
        """
        Deregister a service.

        Args:
            service_id: ID of service to deregister

        Returns:
            True if deregistration successful
        """
        try:
            logger.info(f"Deregistering service: {service_id}")

            # Get service info before removal
            service = self._services.get(service_id)
            if not service:
                logger.warning(f"Service not found: {service_id}")
                return False

            # Remove from persistence
            key = f"service:{service_id}"
            await self.persistence.delete(key)

            # Remove from local cache
            del self._services[service_id]

            # Remove from type index
            if service.service_type in self._services_by_type:
                self._services_by_type[service.service_type].discard(service_id)

            # Remove status
            if service_id in self._service_status:
                del self._service_status[service_id]

            # Emit event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.SERVICE_DEREGISTERED,
                    data={
                        "service_id": service_id,
                        "service_type": service.service_type.value,
                    }
                ))

            logger.info(f"Service deregistered successfully: {service_id}")
            return True

        except PersistenceError as e:
            logger.error(f"Failed to deregister service {service_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deregistering service {service_id}: {e}")
            raise ServiceRegistrationError(service_id, "deregister", cause=e)

    async def update_heartbeat(self, service_id: str) -> bool:
        """
        Update service heartbeat timestamp.

        Args:
            service_id: ID of service

        Returns:
            True if update successful
        """
        try:
            service = self._services.get(service_id)
            if not service:
                return False

            service.last_heartbeat = datetime.utcnow()

            # Update persistence
            key = f"service:{service_id}"
            await self.persistence.set(key, service.__dict__)

            # Update status
            if service_id in self._service_status:
                self._service_status[service_id].health_status = HealthStatus.HEALTHY
                self._service_status[service_id].last_check = datetime.utcnow()

            return True

        except PersistenceError as e:
            logger.error(f"Failed to update heartbeat for {service_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error updating heartbeat for {service_id}: {e}")
            raise ServiceRegistrationError(service_id, "heartbeat_update", cause=e)

    async def check_health_once(self) -> Dict[str, int]:
        """
        Check service health once (no loop).

        Can be called by external triggers (cron, Lambda, etc.).

        Returns:
            Statistics about health check
        """
        stats = {
            "checked": 0,
            "healthy": 0,
            "unhealthy": 0,
            "marked_unhealthy": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            now = datetime.utcnow()
            timeout_threshold = now - timedelta(seconds=self.heartbeat_timeout)

            for service_id, service in self._services.items():
                stats["checked"] += 1

                # Ensure last_heartbeat is a datetime object
                last_hb = service.last_heartbeat
                if last_hb:
                    if isinstance(last_hb, str):
                        try:
                            last_hb = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                        except:
                            continue

                    if last_hb < timeout_threshold:
                        # Mark service as unhealthy
                        current_status = self._service_status.get(service_id)

                        if current_status and current_status.health_status != HealthStatus.UNHEALTHY:
                            stats["marked_unhealthy"] += 1

                            await self.update_service_status(
                                service_id,
                                health_status=HealthStatus.UNHEALTHY
                            )

                            # Emit event
                            if self.event_bus:
                                await self.event_bus.emit(Event(
                                    event_type=EventType.SERVICE_HEALTH_CHANGED,
                                    data={
                                        "service_id": service_id,
                                        "health_status": HealthStatus.UNHEALTHY.value,
                                        "reason": "heartbeat_timeout"
                                    }
                                ))

                        stats["unhealthy"] += 1
                    else:
                        stats["healthy"] += 1

        except Exception as e:
            logger.error(f"Error in health check: {e}")
            stats["error"] = str(e)

        return stats

    async def cleanup_stale_once(self) -> Dict[str, int]:
        """
        Remove stale services once (no loop).

        Can be called by external triggers.

        Returns:
            Statistics about cleanup
        """
        stats = {
            "checked": 0,
            "removed": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            stale_services = []

            for service_id, status in self._service_status.items():
                stats["checked"] += 1

                if status.health_status == HealthStatus.UNHEALTHY:
                    # Check how long it's been unhealthy
                    unhealthy_duration = (datetime.utcnow() - status.last_check).total_seconds()
                    if unhealthy_duration > self.stale_service_timeout:
                        stale_services.append(service_id)

            for service_id in stale_services:
                logger.warning(f"Removing stale service: {service_id}")
                success = await self.deregister_service(service_id)
                if success:
                    stats["removed"] += 1

        except Exception as e:
            logger.error(f"Error in cleanup: {e}")
            stats["error"] = str(e)

        return stats

    async def discover_services(
        self,
        criteria: Optional[ServiceCriteria] = None
    ) -> List[ServiceSpec]:
        """
        Discover services matching criteria.

        Args:
            criteria: Optional filtering criteria

        Returns:
            List of matching services
        """
        services = list(self._services.values())

        if not criteria:
            return services

        # Filter by type
        if criteria.service_type:
            services = [s for s in services if s.service_type == criteria.service_type]

        # Filter by capabilities
        if criteria.capabilities:
            services = [
                s for s in services
                if all(
                    s.capabilities.get(k) == v
                    for k, v in criteria.capabilities.items()
                )
            ]

        # Filter by version
        if criteria.version:
            services = [s for s in services if s.version == criteria.version]

        # Filter by health status
        if criteria.health_status:
            healthy_ids = {
                sid for sid, status in self._service_status.items()
                if status.health_status == criteria.health_status
            }
            services = [s for s in services if s.service_id in healthy_ids]

        # Filter by load threshold
        if criteria.load_threshold is not None:
            low_load_ids = {
                sid for sid, status in self._service_status.items()
                if status.current_load <= criteria.load_threshold
            }
            services = [s for s in services if s.service_id in low_load_ids]

        return services

    async def get_service(self, service_id: str) -> Optional[ServiceSpec]:
        """
        Get a specific service by ID.

        Args:
            service_id: Service ID

        Returns:
            Service spec or None if not found
        """
        return self._services.get(service_id)

    async def get_service_status(self, service_id: str) -> Optional[ServiceStatus]:
        """
        Get current status of a service.

        Args:
            service_id: Service ID

        Returns:
            Service status or None if not found
        """
        return self._service_status.get(service_id)

    async def update_service_status(
        self,
        service_id: str,
        health_status: Optional[HealthStatus] = None,
        current_load: Optional[float] = None,
        metrics: Optional[Dict[str, float]] = None,
    ) -> bool:
        """
        Update service status information.

        Args:
            service_id: Service ID
            health_status: New health status
            current_load: Current load percentage
            metrics: Additional metrics

        Returns:
            True if update successful
        """
        try:
            status = self._service_status.get(service_id)
            if not status:
                return False

            if health_status:
                status.health_status = health_status

            if current_load is not None:
                status.current_load = current_load

            if metrics:
                status.metadata.update(metrics)

            status.last_check = datetime.utcnow()

            # Store in persistence
            key = f"service_status:{service_id}"
            await self.persistence.set(key, status.__dict__)

            return True

        except Exception as e:
            logger.error(f"Failed to update status for {service_id}: {e}")
            return False

    async def get_services_by_type(self, service_type: ServiceType) -> List[ServiceSpec]:
        """
        Get all services of a specific type.

        Args:
            service_type: Type of service

        Returns:
            List of services
        """
        service_ids = self._services_by_type.get(service_type, set())
        return [self._services[sid] for sid in service_ids if sid in self._services]

    async def get_healthy_services(self, service_type: Optional[ServiceType] = None) -> List[ServiceSpec]:
        """
        Get all healthy services, optionally filtered by type.

        Args:
            service_type: Optional service type filter

        Returns:
            List of healthy services
        """
        criteria = ServiceCriteria(
            service_type=service_type,
            health_status=HealthStatus.HEALTHY
        )
        return await self.discover_services(criteria)

    async def watch_services(
        self,
        service_type: Optional[ServiceType] = None,
        callback: Optional[callable] = None
    ):
        """
        Watch for service changes (streaming).

        Args:
            service_type: Optional filter by type
            callback: Callback for service changes
        """
        if not self.event_bus or not callback:
            return

        async def service_change_handler(event: Event):
            # Filter by service type if specified
            if service_type:
                service_id = event.data.get("service_id")
                service = self._services.get(service_id)
                if service and service.service_type != service_type:
                    return

            await callback(event)

        # Register handlers for service events
        await self.event_bus.register(
            EventType.SERVICE_REGISTERED,
            service_change_handler
        )
        await self.event_bus.register(
            EventType.SERVICE_DEREGISTERED,
            service_change_handler
        )
        await self.event_bus.register(
            EventType.SERVICE_HEALTH_CHANGED,
            service_change_handler
        )

    # Private methods

    async def _load_services(self):
        """Load services from persistence on startup."""
        try:
            # Get all service keys
            pattern = "service:*"
            keys = await self.persistence.keys(pattern)

            for key in keys:
                if ":status:" in key:
                    continue  # Skip status keys

                data = await self.persistence.get(key)
                if data:
                    service = ServiceSpec(**data)
                    self._services[service.service_id] = service

                    # Rebuild type index
                    if service.service_type not in self._services_by_type:
                        self._services_by_type[service.service_type] = set()
                    self._services_by_type[service.service_type].add(service.service_id)

            logger.info(f"Loaded {len(self._services)} services from persistence")

        except Exception as e:
            logger.error(f"Failed to load services: {e}")

    async def _register_event_handlers(self):
        """Register event handlers for service-related events."""
        # Could handle provider registration events, hub events, etc.
        pass

    def get_statistics(self) -> Dict[str, any]:
        """Get registry statistics."""
        return {
            "total_services": len(self._services),
            "services_by_type": {
                str(stype): len(sids)
                for stype, sids in self._services_by_type.items()
            },
            "healthy_count": sum(
                1 for status in self._service_status.values()
                if status.health_status == HealthStatus.HEALTHY
            ),
            "unhealthy_count": sum(
                1 for status in self._service_status.values()
                if status.health_status == HealthStatus.UNHEALTHY
            )
        }