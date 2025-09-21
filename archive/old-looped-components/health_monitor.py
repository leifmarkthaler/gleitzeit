"""
Health Monitor for system-wide component health checking.
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Callable, Any
from dataclasses import dataclass, field

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent as Event, EventType
from ..events import StatelessEventBus
from ..core.errors import (
    HealthCheckError, SystemManagerError, PersistenceError,
    NetworkError, ConnectionTimeoutError
)
from .models import (
    ComponentHealth,
    HealthStatus,
    ServiceType,
    ServiceSpec,
)
from .service_registry import ServiceRegistry


logger = logging.getLogger(__name__)


@dataclass
class HealthCheck:
    """Health check configuration."""
    name: str
    check_fn: Callable
    timeout: float = 5.0
    critical: bool = True  # If True, failure marks component unhealthy
    

class HealthMonitor:
    """
    Monitors health of all system components.
    
    Features:
    - Periodic health checks
    - Dependency health aggregation
    - Automatic recovery attempts
    - Alert generation on failures
    - Health metrics collection
    """
    
    def __init__(
        self,
        service_registry: ServiceRegistry,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[StatelessEventBus] = None,
        check_interval: int = 10,
        check_timeout: int = 5,
        max_recovery_attempts: int = 3,
        recovery_backoff: float = 2.0,
        scheduler=None  # StatelessScheduler for stateless health monitoring
    ):
        """
        Initialize the HealthMonitor.
        
        Args:
            service_registry: Service registry for component discovery
            persistence: Persistence adapter
            event_bus: Event bus for health events
            check_interval: Seconds between health checks
            check_timeout: Timeout for health checks
            max_recovery_attempts: Max recovery attempts before giving up
            recovery_backoff: Exponential backoff multiplier for recovery
        """
        self.service_registry = service_registry
        self.persistence = persistence
        self.event_bus = event_bus
        self.check_interval = check_interval
        self.check_timeout = check_timeout
        self.max_recovery_attempts = max_recovery_attempts
        self.recovery_backoff = recovery_backoff
        self.scheduler = scheduler  # For stateless health check scheduling
        
        # Health check registry
        self._health_checks: Dict[ServiceType, List[HealthCheck]] = {}
        self._component_health: Dict[str, ComponentHealth] = {}
        
        # Recovery tracking
        self._recovery_attempts: Dict[str, int] = {}
        self._recovery_tasks: Dict[str, asyncio.Task] = {}
        
        # Background tasks
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
        # HTTP session for health checks
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def initialize(self):
        """Initialize the health monitor."""
        logger.info("Initializing HealthMonitor")
        
        # Create HTTP session
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.check_timeout)
        )
        
        # Register default health checks
        self._register_default_checks()
        
        # Load existing health data
        await self._load_health_data()
        
        # Start monitoring
        self._running = True
        if self.scheduler:
            # Use stateless scheduler-based monitoring
            await self._start_stateless_monitoring_loop()
            logger.info("HealthMonitor started with stateless scheduler-based monitoring")
        else:
            # Fallback to persistent loop
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("HealthMonitor started with persistent monitor loop (scheduler not available)")
        
        # Register event handlers
        if self.event_bus:
            await self._register_event_handlers()
            
        logger.info("HealthMonitor initialized")
        
    async def shutdown(self):
        """Shutdown the health monitor."""
        logger.info("Shutting down HealthMonitor")
        
        self._running = False
        
        # Cancel monitoring task
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
                
        # Cancel recovery tasks (create a list copy to avoid dictionary modification during iteration)
        recovery_tasks = list(self._recovery_tasks.values())
        for task in recovery_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
                
        # Close HTTP session
        if self._session:
            await self._session.close()
            
        logger.info("HealthMonitor shutdown complete")
        
    async def check_component_health(
        self,
        component_id: str,
        component_type: Optional[ServiceType] = None
    ) -> ComponentHealth:
        """
        Check health of a specific component.
        
        Args:
            component_id: Component ID
            component_type: Optional component type
            
        Returns:
            Component health status
        """
        try:
            # Get service info
            service = await self.service_registry.get_service(component_id)
            if not service:
                return ComponentHealth(
                    component_id=component_id,
                    component_type=component_type or ServiceType.WORKER,
                    status=HealthStatus.UNKNOWN,
                    error_message="Component not found in registry"
                )
                
            component_type = service.service_type
            
            # Initialize health object
            health = ComponentHealth(
                component_id=component_id,
                component_type=component_type,
                status=HealthStatus.HEALTHY,
                checks={},
                dependencies_health={},
                metrics={},
            )
            
            # Run type-specific health checks
            checks = self._health_checks.get(component_type, [])
            for check in checks:
                try:
                    result = await asyncio.wait_for(
                        check.check_fn(service),
                        timeout=check.timeout
                    )
                    health.checks[check.name] = result
                    
                    if not result and check.critical:
                        health.status = HealthStatus.UNHEALTHY
                        
                except asyncio.TimeoutError:
                    health.checks[check.name] = False
                    if check.critical:
                        health.status = HealthStatus.UNHEALTHY
                    logger.warning(f"Health check timeout: {check.name} for {component_id}")
                    
                except Exception as e:
                    health.checks[check.name] = False
                    if check.critical:
                        health.status = HealthStatus.UNHEALTHY
                    logger.error(f"Health check failed: {check.name} for {component_id}: {e}")
                    
            # Check dependencies health
            if service.dependencies:
                for dep_id in service.dependencies:
                    dep_health = self._component_health.get(dep_id)
                    if dep_health:
                        health.dependencies_health[dep_id] = dep_health.status
                        if dep_health.status == HealthStatus.UNHEALTHY:
                            # Degraded if dependency is unhealthy
                            if health.status == HealthStatus.HEALTHY:
                                health.status = HealthStatus.DEGRADED
                                
            # HTTP endpoint health check if available
            if service.health_check_endpoint:
                endpoint_healthy = await self._check_http_endpoint(service.health_check_endpoint)
                health.checks["endpoint"] = endpoint_healthy
                if not endpoint_healthy:
                    health.status = HealthStatus.UNHEALTHY
                    
            # Update cached health
            self._component_health[component_id] = health
            
            # Store in persistence
            await self._save_health(component_id, health)
            
            return health
            
        except Exception as e:
            logger.error(f"Failed to check health for {component_id}: {e}")
            return ComponentHealth(
                component_id=component_id,
                component_type=component_type or ServiceType.WORKER,
                status=HealthStatus.UNKNOWN,
                error_message=str(e)
            )
            
    async def get_system_health(self) -> Dict[str, Any]:
        """
        Get overall system health summary.
        
        Returns:
            System health summary
        """
        services = await self.service_registry.discover_services()
        
        total = len(services)
        healthy = 0
        degraded = 0
        unhealthy = 0
        unknown = 0
        
        component_summary = {}
        
        for service in services:
            health = self._component_health.get(service.service_id)
            if health:
                if health.status == HealthStatus.HEALTHY:
                    healthy += 1
                elif health.status == HealthStatus.DEGRADED:
                    degraded += 1
                elif health.status == HealthStatus.UNHEALTHY:
                    unhealthy += 1
                else:
                    unknown += 1
                    
                # Group by component type
                # service_type might be string or enum
                type_key = service.service_type.value if hasattr(service.service_type, 'value') else service.service_type
                if type_key not in component_summary:
                    component_summary[type_key] = {
                        "total": 0,
                        "healthy": 0,
                        "degraded": 0,
                        "unhealthy": 0,
                    }
                    
                component_summary[type_key]["total"] += 1
                status_key = health.status.value if hasattr(health.status, 'value') else health.status
                component_summary[type_key][status_key] += 1
                
        # Calculate overall status
        if unhealthy > 0:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded > 0:
            overall_status = HealthStatus.DEGRADED
        elif unknown > 0:
            overall_status = HealthStatus.UNKNOWN
        else:
            overall_status = HealthStatus.HEALTHY
            
        return {
            "status": overall_status.value,
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total": total,
                "healthy": healthy,
                "degraded": degraded,
                "unhealthy": unhealthy,
                "unknown": unknown,
            },
            "components": component_summary,
            "recovery_in_progress": list(self._recovery_tasks.keys()),
        }
        
    async def attempt_recovery(self, component_id: str) -> bool:
        """
        Attempt to recover an unhealthy component.
        
        Args:
            component_id: Component ID
            
        Returns:
            True if recovery initiated
        """
        try:
            # Check if already recovering
            if component_id in self._recovery_tasks:
                logger.info(f"Recovery already in progress for {component_id}")
                return False
                
            # Check recovery attempts
            attempts = self._recovery_attempts.get(component_id, 0)
            if attempts >= self.max_recovery_attempts:
                logger.error(f"Max recovery attempts reached for {component_id}")
                await self._alert_component_failure(component_id)
                return False
                
            # Start recovery task
            self._recovery_attempts[component_id] = attempts + 1
            self._recovery_tasks[component_id] = asyncio.create_task(
                self._recover_component(component_id)
            )
            
            logger.info(f"Recovery initiated for {component_id} (attempt {attempts + 1})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initiate recovery for {component_id}: {e}")
            return False
            
    async def register_health_check(
        self,
        service_type: ServiceType,
        check: HealthCheck
    ):
        """
        Register a custom health check for a service type.
        
        Args:
            service_type: Type of service
            check: Health check configuration
        """
        if service_type not in self._health_checks:
            self._health_checks[service_type] = []
            
        self._health_checks[service_type].append(check)
        logger.info(f"Registered health check '{check.name}' for {service_type}")
        
    # Private methods
    
    def _register_default_checks(self):
        """Register default health checks for each service type."""
        
        # Provider health checks
        self._health_checks[ServiceType.PROVIDER] = [
            HealthCheck(
                name="initialized",
                check_fn=self._check_provider_initialized,
                critical=True
            ),
        ]
        
        # Hub health checks
        self._health_checks[ServiceType.HUB] = [
            HealthCheck(
                name="resources_available",
                check_fn=self._check_hub_resources,
                critical=False
            ),
        ]
        
        # Worker health checks
        self._health_checks[ServiceType.WORKER] = [
            HealthCheck(
                name="capacity",
                check_fn=self._check_worker_capacity,
                critical=False
            ),
        ]
        
        # API health checks
        self._health_checks[ServiceType.API] = [
            HealthCheck(
                name="responsive",
                check_fn=self._check_api_responsive,
                critical=True
            ),
        ]
        
    async def _check_provider_initialized(self, service: ServiceSpec) -> bool:
        """Check if provider is initialized."""
        # In real implementation, would check provider status
        return True
        
    async def _check_hub_resources(self, service: ServiceSpec) -> bool:
        """Check if hub has available resources."""
        # In real implementation, would check hub resource availability
        return True
        
    async def _check_worker_capacity(self, service: ServiceSpec) -> bool:
        """Check if worker has capacity."""
        # In real implementation, would check worker task queue
        return True
        
    async def _check_api_responsive(self, service: ServiceSpec) -> bool:
        """Check if API is responsive."""
        if service.endpoint:
            return await self._check_http_endpoint(f"{service.endpoint}/health")
        return True
        
    async def _check_http_endpoint(self, url: str) -> bool:
        """Check if HTTP endpoint is healthy."""
        try:
            if not self._session:
                return False
                
            async with self._session.get(url) as response:
                return response.status == 200
                
        except Exception as e:
            logger.debug(f"HTTP health check failed for {url}: {e}")
            return False
            
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                
                # Get all services
                services = await self.service_registry.discover_services()
                
                # Check each service health
                tasks = []
                for service in services:
                    tasks.append(
                        self.check_component_health(
                            service.service_id,
                            service.service_type
                        )
                    )
                    
                # Run health checks concurrently
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Process results
                    for service, result in zip(services, results):
                        if isinstance(result, Exception):
                            logger.error(f"Health check error for {service.service_id}: {result}")
                            continue
                            
                        # Update service registry with health status
                        await self.service_registry.update_service_status(
                            service.service_id,
                            health_status=result.status
                        )
                        
                        # Check if recovery needed
                        if result.status == HealthStatus.UNHEALTHY:
                            await self.attempt_recovery(service.service_id)
                            
                        # Emit health change event
                        if self.event_bus:
                            previous = self._component_health.get(service.service_id)
                            if not previous or previous.status != result.status:
                                await self.event_bus.emit(Event(
                                    event_type=EventType.SERVICE_HEALTH_CHANGED,
                                    data={
                                        "service_id": service.service_id,
                                        "previous_status": previous.status.value if previous else None,
                                        "new_status": result.status.value,
                                        "checks": result.checks,
                                    }
                                ))
                                
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                
    async def _recover_component(self, component_id: str):
        """Attempt to recover a component."""
        try:
            logger.info(f"Starting recovery for {component_id}")
            
            # Get service info
            service = await self.service_registry.get_service(component_id)
            if not service:
                logger.error(f"Component {component_id} not found")
                return
                
            # Type-specific recovery logic
            if service.service_type == ServiceType.PROVIDER:
                # Try to reinitialize provider
                pass  # Would call provider.initialize()
                
            elif service.service_type == ServiceType.HUB:
                # Try to reconnect to resources
                pass  # Would call hub.reconnect()
                
            elif service.service_type == ServiceType.WORKER:
                # Try to restart worker
                pass  # Would restart worker process
                
            # Wait with backoff
            wait_time = self.recovery_backoff ** self._recovery_attempts[component_id]
            await asyncio.sleep(wait_time)
            
            # Check health again
            health = await self.check_component_health(component_id)
            
            if health.status == HealthStatus.HEALTHY:
                logger.info(f"Recovery successful for {component_id}")
                self._recovery_attempts[component_id] = 0
            else:
                logger.warning(f"Recovery failed for {component_id}, status: {health.status}")
                
        except Exception as e:
            logger.error(f"Recovery error for {component_id}: {e}")
            
        finally:
            # Remove from active recovery tasks
            if component_id in self._recovery_tasks:
                del self._recovery_tasks[component_id]
                
    async def _alert_component_failure(self, component_id: str):
        """Send alert for component failure."""
        if self.event_bus:
            await self.event_bus.emit(Event(
                event_type=EventType.COMPONENT_FAILURE,
                data={
                    "component_id": component_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "recovery_attempts": self._recovery_attempts.get(component_id, 0),
                }
            ))
            
        logger.error(f"ALERT: Component {component_id} has failed after {self.max_recovery_attempts} recovery attempts")
        
    async def _load_health_data(self):
        """Load health data from persistence."""
        try:
            pattern = "health:*"
            keys = await self.persistence.keys(pattern)
            
            for key in keys:
                data = await self.persistence.get(key)
                if data:
                    component_id = key.split(":", 1)[1]
                    health = ComponentHealth(**data)
                    self._component_health[component_id] = health
                    
            logger.info(f"Loaded health data for {len(self._component_health)} components")
            
        except Exception as e:
            logger.error(f"Failed to load health data: {e}")
            
    async def _save_health(self, component_id: str, health: ComponentHealth):
        """Save health data to persistence."""
        try:
            key = f"health:{component_id}"
            await self.persistence.set(key, health.__dict__)
        except Exception as e:
            logger.error(f"Failed to save health for {component_id}: {e}")
            
    async def _register_event_handlers(self):
        """Register event handlers for health-related events."""
        # Could handle service registration/deregistration events
        pass

    async def _start_stateless_monitoring_loop(self):
        """Start stateless monitoring loop using scheduler events"""
        if not self.scheduler:
            logger.warning("No scheduler available for stateless monitoring loop")
            return

        # Register event handler first
        await self.scheduler.register_handler(
            event_type="health_monitor.check",
            handler=self._handle_health_check_event
        )

        # Schedule first health check event
        await self.scheduler.schedule_event(
            event_type="health_monitor.check",
            delay_seconds=self.check_interval,
            payload={"instance_id": id(self)}
        )
        logger.debug(f"Registered health check handler and scheduled first check in {self.check_interval}s")

    async def _handle_health_check_event(self, event_data: dict):
        """Handle scheduled health check events"""
        try:
            if not self._running:
                logger.debug("HealthMonitor not running, skipping health check event")
                return

            # Perform health check (same logic as _monitor_loop but without the while loop)
            # Get all services
            services = await self.service_registry.discover_services()

            # Check each service health
            tasks = []
            for service in services:
                tasks.append(
                    self.check_component_health(
                        service.service_id,
                        service.service_type
                    )
                )

            # Execute health checks concurrently
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Log any exceptions
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Health check failed for service {services[i].service_id}: {result}")

            # Schedule next health check if still running
            if self._running and self.scheduler:
                await self.scheduler.schedule_event(
                    event_type="health_monitor.check",
                    delay_seconds=self.check_interval,
                    payload={"instance_id": id(self)}
                )

        except Exception as e:
            logger.error(f"Error in health check event handler: {e}")
            # Reschedule even on error to prevent stopping
            if self._running and self.scheduler:
                await self.scheduler.schedule_event(
                    event_type="health_monitor.check",
                    delay_seconds=self.check_interval,
                    payload={"instance_id": id(self), "error_recovery": True}
                )