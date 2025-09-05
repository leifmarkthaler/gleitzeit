"""
System API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, List
from fastapi import APIRouter, Request, Depends
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from .base import APIRouteBase

router = APIRouter(prefix="/system", tags=["system"])


# Create route handler instance (stateless - just contains logic)
system_routes = APIRouteBase()


@router.get("/health", response_model=Dict[str, Any])
async def health_check(
    client: GleitzeitClient = Depends(get_client)
):
    """Get system health status."""
    return await system_routes.handle_client_call("health_check", client=client)


@router.get("/status", response_model=Dict[str, Any])
async def get_system_status(
    client: GleitzeitClient = Depends(get_client)
):
    """Get detailed system status."""
    return await system_routes.handle_client_call("get_system_status", client=client)


@router.get("/info", response_model=Dict[str, Any])
async def get_system_info(
    client: GleitzeitClient = Depends(get_client)
):
    """Get system information."""
    return await system_routes.handle_client_call("get_system_info", client=client)


@router.get("/metrics", response_model=Dict[str, Any])
async def get_system_metrics(
    client: GleitzeitClient = Depends(get_client)
):
    """Get system performance metrics."""
    return await system_routes.handle_client_call("get_system_metrics", client=client)


@router.post("/shutdown", response_model=Dict[str, str])
async def shutdown_system(
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Shutdown the system gracefully."""
    system_routes.require_admin(req)
    return await system_routes.handle_client_call("shutdown_system", client=client)


@router.post("/maintenance/start", response_model=Dict[str, Any])
async def start_maintenance_mode(
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Start maintenance mode."""
    system_routes.require_admin(req)
    return await system_routes.handle_client_call("start_maintenance_mode", client=client)


@router.post("/maintenance/stop", response_model=Dict[str, Any])
async def stop_maintenance_mode(
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Stop maintenance mode."""
    system_routes.require_admin(req)
    return await system_routes.handle_client_call("stop_maintenance_mode", client=client)


@router.get("/config", response_model=Dict[str, Any])
async def get_system_config(
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Get system configuration."""
    system_routes.require_admin(req)
    return await system_routes.handle_client_call("get_system_config", client=client)


@router.get("/resources", response_model=Dict[str, Any])
async def get_system_resources(
    client: GleitzeitClient = Depends(get_client)
):
    """Get system resource usage."""
    return await system_routes.handle_client_call("get_system_resources", client=client)


@router.post("/cache/clear", response_model=Dict[str, Any])
async def clear_cache(
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Clear system caches (admin only)."""
    system_routes.require_admin(req)
    return await system_routes.handle_client_call("clear_cache", client=client)