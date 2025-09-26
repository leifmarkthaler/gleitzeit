"""
Service Discovery API for Gleitzeit Multi-Machine Deployments

Provides REST API endpoints for discovering services, machines,
and topology information across distributed deployments.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
import redis.asyncio as aioredis
import logging

from ..core.process_manager import SmartProcessManager
from ..core.instance import get_current_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryService:
    """Service discovery implementation"""

    def __init__(self):
        self.instance = get_current_instance()
        self.process_manager: Optional[SmartProcessManager] = None
        self.redis: Optional[aioredis.Redis] = None

    async def initialize(self, redis_url: str = "redis://localhost:6379"):
        """Initialize discovery service"""
        if not self.process_manager:
            self.process_manager = SmartProcessManager(redis_url=redis_url)
            await self.process_manager.initialize()
            self.redis = self.process_manager.redis

    async def get_service_instances(self, service_type: str) -> List[Dict[str, Any]]:
        """Get all instances of a service type"""
        if not self.process_manager:
            await self.initialize()

        return await self.process_manager.discover_services(service_type)

    async def get_machines(
        self,
        datacenter: Optional[str] = None,
        rack: Optional[str] = None,
        zone: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get machines based on location criteria"""
        if not self.process_manager:
            await self.initialize()

        return await self.process_manager.discover_machines(
            datacenter=datacenter,
            rack=rack,
            zone=zone
        )

    async def get_topology(self) -> Dict[str, Any]:
        """Get complete topology map"""
        if not self.process_manager:
            await self.initialize()

        return await self.process_manager.get_topology_map()

    async def get_nearest_service(self, service_type: str) -> Optional[Dict[str, Any]]:
        """Get nearest/preferred service instance"""
        services = await self.get_service_instances(service_type)

        if not services:
            return None

        # Sort by preference:
        # 1. Same machine
        # 2. Same rack
        # 3. Same datacenter
        # 4. Same network zone
        # 5. Can communicate (network tags)

        def score_service(service: Dict[str, Any]) -> int:
            score = 0

            # Same machine is best
            if service.get("machine_id") == self.instance.machine_id:
                score += 1000

            # Same datacenter/rack/zone
            service_meta = service.get("metadata", {})
            if service_meta.get("datacenter") == self.instance.metadata.datacenter:
                score += 100
            if service_meta.get("rack") == self.instance.metadata.rack:
                score += 50
            if service_meta.get("network_zone") == self.instance.metadata.network_zone:
                score += 25

            # Can communicate
            if service.get("can_communicate", False):
                score += 10

            return score

        # Sort by score (highest first)
        services.sort(key=score_service, reverse=True)

        return services[0]


# Global discovery service instance
discovery_service = DiscoveryService()


@router.get("/services/{service_type}")
async def get_service_instances(
    service_type: str,
    nearest_only: bool = Query(False, description="Return only the nearest/preferred instance")
) -> Any:
    """
    Discover instances of a service type

    Args:
        service_type: Type of service (api, ui, worker, etc)
        nearest_only: If true, return only the nearest/preferred instance

    Returns:
        List of service instances or single instance if nearest_only
    """
    try:
        if nearest_only:
            result = await discovery_service.get_nearest_service(service_type)
            if not result:
                raise HTTPException(
                    status_code=404,
                    detail=f"No instances of service '{service_type}' found"
                )
            return result
        else:
            services = await discovery_service.get_service_instances(service_type)
            return {"services": services, "count": len(services)}
    except Exception as e:
        logger.error(f"Error discovering services: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/machines")
async def get_machines(
    datacenter: Optional[str] = Query(None, description="Filter by datacenter"),
    rack: Optional[str] = Query(None, description="Filter by rack"),
    zone: Optional[str] = Query(None, description="Filter by network zone")
) -> Dict[str, Any]:
    """
    Discover machines in the deployment

    Args:
        datacenter: Optional datacenter filter
        rack: Optional rack filter
        zone: Optional network zone filter

    Returns:
        List of machines with their information
    """
    try:
        machines = await discovery_service.get_machines(
            datacenter=datacenter,
            rack=rack,
            zone=zone
        )
        return {
            "machines": machines,
            "count": len(machines),
            "filters": {
                "datacenter": datacenter,
                "rack": rack,
                "zone": zone
            }
        }
    except Exception as e:
        logger.error(f"Error discovering machines: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topology")
async def get_topology() -> Dict[str, Any]:
    """
    Get complete topology map of the deployment

    Returns:
        Hierarchical topology map (datacenters -> racks -> machines -> instances)
    """
    try:
        return await discovery_service.get_topology()
    except Exception as e:
        logger.error(f"Error getting topology: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/{service_type}")
async def get_service_health(service_type: str) -> Dict[str, Any]:
    """
    Get health status of all instances of a service type

    Args:
        service_type: Type of service

    Returns:
        Health status for each instance
    """
    try:
        services = await discovery_service.get_service_instances(service_type)

        health_status = {
            "service_type": service_type,
            "total_instances": len(services),
            "healthy_instances": 0,
            "instances": []
        }

        for service in services:
            # TODO: Implement actual health checks
            # For now, assume all discovered services are healthy
            instance_health = {
                "instance_id": service["instance_id"],
                "machine_id": service["machine_id"],
                "url": service["url"],
                "healthy": True,
                "reachable": service.get("can_communicate", False)
            }
            health_status["instances"].append(instance_health)
            if instance_health["healthy"]:
                health_status["healthy_instances"] += 1

        health_status["overall_health"] = (
            "healthy" if health_status["healthy_instances"] > 0 else "unhealthy"
        )

        return health_status
    except Exception as e:
        logger.error(f"Error checking service health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instance/current")
async def get_current_instance_info() -> Dict[str, Any]:
    """
    Get information about the current instance

    Returns:
        Current instance information including machine details
    """
    try:
        instance = get_current_instance()
        if not instance:
            raise HTTPException(status_code=500, detail="Instance not initialized")

        return {
            "instance_id": instance.instance_id,
            "instance_name": instance.instance_name,
            "role": instance.role,
            "deployment_id": instance.deployment_id,
            "machine": instance.machine_info.to_dict(),
            "capabilities": instance.capabilities.to_dict(),
            "metadata": instance.metadata.to_dict(),
            "uptime_seconds": instance.get_uptime_seconds()
        }
    except Exception as e:
        logger.error(f"Error getting current instance: {e}")
        raise HTTPException(status_code=500, detail=str(e))