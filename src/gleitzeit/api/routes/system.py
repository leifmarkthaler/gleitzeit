"""
System API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, List
import time
from fastapi import APIRouter, Request, Depends, Response
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from ..auth_dependencies import get_current_user_auto, get_current_user_required
from .base import APIRouteBase
from ..metrics import metrics_collector

router = APIRouter(prefix="/system", tags=["system"])


# Create route handler instance (stateless - just contains logic)
system_routes = APIRouteBase()


@router.get("/health", response_model=Dict[str, Any])
async def health_check(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """Get system health status."""
    return await system_routes.handle_client_call("health_check", client=client)


@router.get("/health/live", response_model=Dict[str, Any])
async def liveness_probe():
    """Kubernetes liveness probe - checks if service is alive."""
    return {
        "status": "healthy",
        "timestamp": str(time.time()),
        "service": "gleitzeit-api"
    }


@router.get("/health/ready", response_model=Dict[str, Any])
async def readiness_probe(
    client: GleitzeitClient = Depends(get_client)
):
    """Kubernetes readiness probe - checks if service is ready to handle requests."""
    try:
        # Check Redis connectivity
        health_status = await system_routes.handle_client_call("health_check", client=client)
        
        # Check if Redis is accessible
        if health_status.get("redis", {}).get("status") != "connected":
            return {
                "status": "not_ready",
                "reason": "Redis not connected",
                "timestamp": str(time.time())
            }
        
        # Check system components
        components_ready = True
        not_ready_components = []
        
        system_status = await system_routes.handle_client_call("get_system_status", client=client)
        
        # Check critical components
        for component in ["timer_manager", "reconciliation_manager"]:
            if system_status.get(component, {}).get("status") not in ["running", "active"]:
                components_ready = False
                not_ready_components.append(component)
        
        if not components_ready:
            return {
                "status": "not_ready",
                "reason": f"Components not ready: {', '.join(not_ready_components)}",
                "timestamp": str(time.time())
            }
        
        return {
            "status": "ready",
            "timestamp": str(time.time()),
            "service": "gleitzeit-api",
            "components": {
                "redis": "connected",
                "timer_manager": "active",
                "reconciliation_manager": "active"
            }
        }
    except Exception as e:
        return {
            "status": "not_ready",
            "reason": str(e),
            "timestamp": str(time.time())
        }


@router.get("/status", response_model=Dict[str, Any])
async def get_system_status(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """Get detailed system status."""
    return await system_routes.handle_client_call("get_system_status", client=client)


@router.get("/info", response_model=Dict[str, Any])
async def get_system_info(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """Get system information."""
    return await system_routes.handle_client_call("get_system_info", client=client)


@router.get("/metrics", response_model=Dict[str, Any])
async def get_system_metrics(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """Get system performance metrics."""
    return await system_routes.handle_client_call("get_system_metrics", client=client)


@router.get("/metrics/prometheus")
async def get_prometheus_metrics(
    client: GleitzeitClient = Depends(get_client)
):
    """Get metrics in Prometheus format for monitoring."""
    # Collect Gleitzeit-specific metrics
    await metrics_collector.collect_gleitzeit_metrics(client)
    
    # Format as Prometheus text
    prometheus_text = await metrics_collector.format_prometheus()
    
    # Return with proper content type
    return Response(
        content=prometheus_text,
        media_type="text/plain; version=0.0.4"
    )


@router.post("/shutdown", response_model=Dict[str, str])
async def shutdown_system(
    req: Request,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_required)
):
    """Shutdown the system gracefully."""
    if current_user.get('role') != 'admin':
        raise SystemError("Admin access required")
    return await system_routes.handle_client_call("shutdown_system", client=client)


@router.post("/maintenance/start", response_model=Dict[str, Any])
async def start_maintenance_mode(
    req: Request,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_required)
):
    """Start maintenance mode."""
    if current_user.get('role') != 'admin':
        raise SystemError("Admin access required")
    return await system_routes.handle_client_call("start_maintenance_mode", client=client)


@router.post("/maintenance/stop", response_model=Dict[str, Any])
async def stop_maintenance_mode(
    req: Request,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_required)
):
    """Stop maintenance mode."""
    if current_user.get('role') != 'admin':
        raise SystemError("Admin access required")
    return await system_routes.handle_client_call("stop_maintenance_mode", client=client)


@router.get("/config", response_model=Dict[str, Any])
async def get_system_config(
    req: Request,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_required)
):
    """Get system configuration."""
    if current_user.get('role') != 'admin':
        raise SystemError("Admin access required")
    return await system_routes.handle_client_call("get_system_config", client=client)


@router.get("/resources", response_model=Dict[str, Any])
async def get_system_resources(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """Get system resource usage."""
    return await system_routes.handle_client_call("get_system_resources", client=client)


@router.post("/cache/clear", response_model=Dict[str, Any])
async def clear_cache(
    req: Request,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_required)
):
    """Clear system caches (admin only)."""
    if current_user.get('role') != 'admin':
        raise SystemError("Admin access required")
    return await system_routes.handle_client_call("clear_cache", client=client)