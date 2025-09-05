"""
Resource Coordinator for global resource allocation policies.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent as Event, EventType
from ..events.stateless_bus import StatelessEventBus
from ..core.errors import (
    ResourceAllocationError, SystemManagerError, PersistenceError,
    ResourceExhaustedError
)
from .models import (
    ServiceType,
    ServiceSpec,
    ResourcePolicy,
    HealthStatus,
)
from .service_registry import ServiceRegistry


logger = logging.getLogger(__name__)


class AllocationStrategy(str, Enum):
    """Resource allocation strategies."""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    BEST_FIT = "best_fit"
    RANDOM = "random"
    WEIGHTED = "weighted"


@dataclass
class ResourceRequest:
    """Request for resource allocation."""
    request_id: str
    resource_type: str  # provider, hub, worker, etc.
    requirements: Dict[str, Any]
    priority: int = 0
    timeout: Optional[float] = None
    requester: Optional[str] = None
    

@dataclass
class ResourceAllocation:
    """Allocated resource information."""
    allocation_id: str
    request_id: str
    service_id: str
    service_type: ServiceType
    allocated_at: datetime
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    

@dataclass
class ResourceUsage:
    """Resource usage metrics."""
    service_id: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    network_mbps: float = 0.0
    active_connections: int = 0
    task_count: int = 0
    error_rate: float = 0.0
    

class ResourceCoordinator:
    """
    Coordinates resource allocation across the system.
    
    Features:
    - Global resource policies
    - Allocation strategies (round-robin, least-loaded, etc.)
    - Resource quotas and limits
    - Multi-tenant isolation
    - Load balancing
    - Resource usage tracking
    """
    
    def __init__(
        self,
        service_registry: ServiceRegistry,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[StatelessEventBus] = None,
        default_strategy: AllocationStrategy = AllocationStrategy.LEAST_LOADED,
        enable_quotas: bool = True,
    ):
        """
        Initialize the ResourceCoordinator.
        
        Args:
            service_registry: Service registry for resource discovery
            persistence: Persistence adapter
            event_bus: Event bus for resource events
            default_strategy: Default allocation strategy
            enable_quotas: Enable resource quotas
        """
        self.service_registry = service_registry
        self.persistence = persistence
        self.event_bus = event_bus
        self.default_strategy = default_strategy
        self.enable_quotas = enable_quotas
        
        # Resource tracking
        self._allocations: Dict[str, ResourceAllocation] = {}
        self._usage: Dict[str, ResourceUsage] = {}
        self._policies: Dict[str, ResourcePolicy] = {}
        
        # Allocation strategies
        self._strategies: Dict[AllocationStrategy, Callable] = {
            AllocationStrategy.ROUND_ROBIN: self._allocate_round_robin,
            AllocationStrategy.LEAST_LOADED: self._allocate_least_loaded,
            AllocationStrategy.BEST_FIT: self._allocate_best_fit,
            AllocationStrategy.RANDOM: self._allocate_random,
            AllocationStrategy.WEIGHTED: self._allocate_weighted,
        }
        
        # Round-robin state
        self._round_robin_indices: Dict[str, int] = {}
        
        # Quotas
        self._quotas: Dict[str, Dict[str, float]] = {}  # tenant -> resource -> limit
        self._usage_by_tenant: Dict[str, Dict[str, float]] = {}
        
        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._usage_monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
    async def initialize(self):
        """Initialize the resource coordinator."""
        logger.info("Initializing ResourceCoordinator")
        
        # Load existing allocations and policies
        await self._load_state()
        
        # Start background tasks
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_allocations())
        self._usage_monitor_task = asyncio.create_task(self._monitor_usage())
        
        # Register event handlers
        if self.event_bus:
            await self._register_event_handlers()
            
        logger.info("ResourceCoordinator initialized")
        
    async def shutdown(self):
        """Shutdown the resource coordinator."""
        logger.info("Shutting down ResourceCoordinator")
        
        self._running = False
        
        # Cancel background tasks
        for task in [self._cleanup_task, self._usage_monitor_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        logger.info("ResourceCoordinator shutdown complete")
        
    async def allocate_resource(
        self,
        request: ResourceRequest,
        strategy: Optional[AllocationStrategy] = None
    ) -> Optional[ResourceAllocation]:
        """
        Allocate a resource based on request and strategy.
        
        Args:
            request: Resource allocation request
            strategy: Optional allocation strategy override
            
        Returns:
            Resource allocation or None if unavailable
        """
        try:
            logger.info(f"Allocating resource for request {request.request_id}")
            
            # Check quotas if enabled
            if self.enable_quotas and request.requester:
                if not await self._check_quota(request.requester, request.resource_type):
                    logger.warning(f"Quota exceeded for {request.requester}")
                    return None
                    
            # Get available resources
            candidates = await self._find_candidates(request)
            if not candidates:
                logger.warning(f"No candidates found for request {request.request_id}")
                return None
                
            # Apply allocation strategy
            strategy = strategy or self.default_strategy
            allocator = self._strategies.get(strategy, self._allocate_least_loaded)
            selected = await allocator(candidates, request)
            
            if not selected:
                logger.warning(f"No resource selected for request {request.request_id}")
                return None
                
            # Create allocation
            allocation = ResourceAllocation(
                allocation_id=f"alloc_{request.request_id}",
                request_id=request.request_id,
                service_id=selected.service_id,
                service_type=selected.service_type,
                allocated_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(seconds=request.timeout) if request.timeout else None,
                metadata={
                    "requester": request.requester,
                    "requirements": request.requirements,
                }
            )
            
            # Store allocation
            self._allocations[allocation.allocation_id] = allocation
            await self._persist_allocation(allocation)
            
            # Update usage tracking
            if request.requester:
                await self._update_tenant_usage(request.requester, request.resource_type, 1)
                
            # Emit event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.RESOURCE_ALLOCATED,
                    data={
                        "allocation_id": allocation.allocation_id,
                        "service_id": selected.service_id,
                        "requester": request.requester,
                    }
                ))
                
            logger.info(f"Allocated {selected.service_id} for request {request.request_id}")
            return allocation
            
        except Exception as e:
            logger.error(f"Failed to allocate resource: {e}")
            return None
            
    async def release_resource(self, allocation_id: str) -> bool:
        """
        Release an allocated resource.
        
        Args:
            allocation_id: Allocation ID
            
        Returns:
            True if successful
        """
        try:
            allocation = self._allocations.get(allocation_id)
            if not allocation:
                logger.warning(f"Allocation not found: {allocation_id}")
                return False
                
            # Remove allocation
            del self._allocations[allocation_id]
            
            # Remove from persistence
            await self.persistence.delete(f"allocation:{allocation_id}")
            
            # Update usage tracking
            requester = allocation.metadata.get("requester")
            if requester:
                resource_type = allocation.service_type.value
                await self._update_tenant_usage(requester, resource_type, -1)
                
            # Emit event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.RESOURCE_RELEASED,
                    data={
                        "allocation_id": allocation_id,
                        "service_id": allocation.service_id,
                    }
                ))
                
            logger.info(f"Released allocation {allocation_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to release resource: {e}")
            return False
            
    async def set_policy(self, policy: ResourcePolicy) -> bool:
        """
        Set a resource allocation policy.
        
        Args:
            policy: Resource policy
            
        Returns:
            True if successful
        """
        try:
            self._policies[policy.policy_id] = policy
            
            # Persist policy
            await self.persistence.set(
                f"policy:{policy.policy_id}",
                policy.__dict__
            )
            
            logger.info(f"Set resource policy: {policy.policy_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set policy: {e}")
            return False
            
    async def set_quota(
        self,
        tenant: str,
        resource_type: str,
        limit: float
    ) -> bool:
        """
        Set resource quota for a tenant.
        
        Args:
            tenant: Tenant identifier
            resource_type: Type of resource
            limit: Resource limit
            
        Returns:
            True if successful
        """
        try:
            if tenant not in self._quotas:
                self._quotas[tenant] = {}
                
            self._quotas[tenant][resource_type] = limit
            
            # Persist quota
            await self.persistence.set(
                f"quota:{tenant}:{resource_type}",
                {"limit": limit}
            )
            
            logger.info(f"Set quota for {tenant}: {resource_type} = {limit}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set quota: {e}")
            return False
            
    async def get_resource_usage(
        self,
        service_id: Optional[str] = None
    ) -> Dict[str, ResourceUsage]:
        """
        Get resource usage information.
        
        Args:
            service_id: Optional specific service
            
        Returns:
            Resource usage by service
        """
        if service_id:
            usage = self._usage.get(service_id)
            return {service_id: usage} if usage else {}
            
        return dict(self._usage)
        
    async def get_allocations(
        self,
        requester: Optional[str] = None,
        service_id: Optional[str] = None
    ) -> List[ResourceAllocation]:
        """
        Get current resource allocations.
        
        Args:
            requester: Filter by requester
            service_id: Filter by service
            
        Returns:
            List of allocations
        """
        allocations = list(self._allocations.values())
        
        if requester:
            allocations = [
                a for a in allocations
                if a.metadata.get("requester") == requester
            ]
            
        if service_id:
            allocations = [
                a for a in allocations
                if a.service_id == service_id
            ]
            
        return allocations
        
    async def update_resource_usage(
        self,
        service_id: str,
        usage: ResourceUsage
    ):
        """
        Update resource usage metrics.
        
        Args:
            service_id: Service ID
            usage: Resource usage metrics
        """
        self._usage[service_id] = usage
        
        # Persist usage
        await self.persistence.set(
            f"usage:{service_id}",
            usage.__dict__
        )
        
    # Private allocation strategies
    
    async def _allocate_round_robin(
        self,
        candidates: List[ServiceSpec],
        request: ResourceRequest
    ) -> Optional[ServiceSpec]:
        """Round-robin allocation strategy."""
        if not candidates:
            return None
            
        key = request.resource_type
        index = self._round_robin_indices.get(key, 0)
        
        selected = candidates[index % len(candidates)]
        self._round_robin_indices[key] = index + 1
        
        return selected
        
    async def _allocate_least_loaded(
        self,
        candidates: List[ServiceSpec],
        request: ResourceRequest
    ) -> Optional[ServiceSpec]:
        """Least-loaded allocation strategy."""
        if not candidates:
            return None
            
        # Sort by load
        candidates_with_load = []
        for candidate in candidates:
            usage = self._usage.get(candidate.service_id)
            if usage:
                # Calculate composite load score
                load = (
                    usage.cpu_percent * 0.4 +
                    usage.memory_percent * 0.3 +
                    usage.task_count * 0.3
                )
            else:
                load = 0  # No usage data means no load
                
            candidates_with_load.append((candidate, load))
            
        # Sort by load (ascending)
        candidates_with_load.sort(key=lambda x: x[1])
        
        return candidates_with_load[0][0] if candidates_with_load else None
        
    async def _allocate_best_fit(
        self,
        candidates: List[ServiceSpec],
        request: ResourceRequest
    ) -> Optional[ServiceSpec]:
        """Best-fit allocation strategy based on requirements."""
        if not candidates:
            return None
            
        # Score each candidate based on requirement matching
        best_score = -1
        best_candidate = None
        
        for candidate in candidates:
            score = 0
            
            # Check capability matching
            for req_key, req_value in request.requirements.items():
                if req_key in candidate.capabilities:
                    if candidate.capabilities[req_key] == req_value:
                        score += 10  # Exact match
                    elif isinstance(req_value, (int, float)) and \
                         isinstance(candidate.capabilities[req_key], (int, float)):
                        # Numeric comparison
                        if candidate.capabilities[req_key] >= req_value:
                            score += 5
                            
            # Factor in current load (inverse)
            usage = self._usage.get(candidate.service_id)
            if usage:
                load_factor = 1.0 - (usage.cpu_percent / 100.0)
                score *= load_factor
                
            if score > best_score:
                best_score = score
                best_candidate = candidate
                
        return best_candidate
        
    async def _allocate_random(
        self,
        candidates: List[ServiceSpec],
        request: ResourceRequest
    ) -> Optional[ServiceSpec]:
        """Random allocation strategy."""
        if not candidates:
            return None
            
        import random
        return random.choice(candidates)
        
    async def _allocate_weighted(
        self,
        candidates: List[ServiceSpec],
        request: ResourceRequest
    ) -> Optional[ServiceSpec]:
        """Weighted allocation based on capacity."""
        if not candidates:
            return None
            
        # Calculate weights based on available capacity
        weights = []
        for candidate in candidates:
            usage = self._usage.get(candidate.service_id)
            if usage:
                # Available capacity (inverse of usage)
                weight = max(0.1, 1.0 - (usage.cpu_percent / 100.0))
            else:
                weight = 1.0  # Full weight if no usage data
                
            weights.append(weight)
            
        # Weighted random selection
        import random
        total_weight = sum(weights)
        r = random.uniform(0, total_weight)
        
        cumulative = 0
        for candidate, weight in zip(candidates, weights):
            cumulative += weight
            if r <= cumulative:
                return candidate
                
        return candidates[-1] if candidates else None
        
    # Private helper methods
    
    async def _find_candidates(
        self,
        request: ResourceRequest
    ) -> List[ServiceSpec]:
        """Find candidate services for allocation."""
        # Map resource type to service type
        service_type_map = {
            "provider": ServiceType.PROVIDER,
            "hub": ServiceType.HUB,
            "worker": ServiceType.WORKER,
        }
        
        service_type = service_type_map.get(
            request.resource_type,
            ServiceType.WORKER
        )
        
        # Get healthy services of the required type
        candidates = await self.service_registry.get_healthy_services(service_type)
        
        # Filter by requirements
        filtered = []
        for candidate in candidates:
            # Check if candidate meets all requirements
            meets_requirements = True
            
            for req_key, req_value in request.requirements.items():
                if req_key in candidate.capabilities:
                    cap_value = candidate.capabilities[req_key]
                    
                    # Handle different comparison types
                    if isinstance(req_value, bool):
                        if cap_value != req_value:
                            meets_requirements = False
                            break
                    elif isinstance(req_value, (int, float)):
                        if isinstance(cap_value, (int, float)):
                            if cap_value < req_value:
                                meets_requirements = False
                                break
                    elif cap_value != req_value:
                        meets_requirements = False
                        break
                        
            if meets_requirements:
                filtered.append(candidate)
                
        return filtered
        
    async def _check_quota(
        self,
        tenant: str,
        resource_type: str
    ) -> bool:
        """Check if tenant has quota available."""
        if tenant not in self._quotas:
            return True  # No quota set means unlimited
            
        limit = self._quotas[tenant].get(resource_type)
        if limit is None:
            return True  # No limit for this resource type
            
        current_usage = self._usage_by_tenant.get(tenant, {}).get(resource_type, 0)
        return current_usage < limit
        
    async def _update_tenant_usage(
        self,
        tenant: str,
        resource_type: str,
        delta: int
    ):
        """Update tenant resource usage."""
        if tenant not in self._usage_by_tenant:
            self._usage_by_tenant[tenant] = {}
            
        current = self._usage_by_tenant[tenant].get(resource_type, 0)
        self._usage_by_tenant[tenant][resource_type] = max(0, current + delta)
        
        # Persist usage
        await self.persistence.set(
            f"tenant_usage:{tenant}:{resource_type}",
            {"count": self._usage_by_tenant[tenant][resource_type]}
        )
        
    async def _cleanup_expired_allocations(self):
        """Clean up expired resource allocations."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                now = datetime.utcnow()
                expired = []
                
                for alloc_id, allocation in self._allocations.items():
                    if allocation.expires_at and allocation.expires_at < now:
                        expired.append(alloc_id)
                        
                for alloc_id in expired:
                    logger.info(f"Cleaning up expired allocation: {alloc_id}")
                    await self.release_resource(alloc_id)
                    
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                
    async def _monitor_usage(self):
        """Monitor resource usage across services."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Update every 30 seconds
                
                # Get all services
                services = await self.service_registry.discover_services()
                
                for service in services:
                    # In real implementation, would query actual metrics
                    # For now, simulate usage data
                    usage = ResourceUsage(
                        service_id=service.service_id,
                        cpu_percent=0.0,
                        memory_percent=0.0,
                        task_count=0,
                    )
                    
                    # Count active allocations for this service
                    active_count = sum(
                        1 for a in self._allocations.values()
                        if a.service_id == service.service_id
                    )
                    usage.task_count = active_count
                    
                    await self.update_resource_usage(service.service_id, usage)
                    
            except Exception as e:
                logger.error(f"Error in usage monitor: {e}")
                
    async def _load_state(self):
        """Load allocations and policies from persistence."""
        try:
            # Load allocations
            alloc_keys = await self.persistence.keys("allocation:*")
            for key in alloc_keys:
                data = await self.persistence.get(key)
                if data:
                    allocation = ResourceAllocation(**data)
                    self._allocations[allocation.allocation_id] = allocation
                    
            # Load policies
            policy_keys = await self.persistence.keys("policy:*")
            for key in policy_keys:
                data = await self.persistence.get(key)
                if data:
                    policy = ResourcePolicy(**data)
                    self._policies[policy.policy_id] = policy
                    
            # Load quotas
            quota_keys = await self.persistence.keys("quota:*")
            for key in quota_keys:
                parts = key.split(":")
                if len(parts) == 3:
                    _, tenant, resource_type = parts
                    data = await self.persistence.get(key)
                    if data and "limit" in data:
                        if tenant not in self._quotas:
                            self._quotas[tenant] = {}
                        self._quotas[tenant][resource_type] = data["limit"]
                        
            logger.info(f"Loaded {len(self._allocations)} allocations, "
                       f"{len(self._policies)} policies, {len(self._quotas)} quotas")
                       
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            
    async def _persist_allocation(self, allocation: ResourceAllocation):
        """Persist allocation to storage."""
        await self.persistence.set(
            f"allocation:{allocation.allocation_id}",
            allocation.__dict__
        )
        
    async def _register_event_handlers(self):
        """Register event handlers for resource events."""
        # Could handle service health changes, etc.
        pass