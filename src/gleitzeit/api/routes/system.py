"""
System API routes that delegate to client methods.
"""

from typing import Dict, Any, List
from fastapi import APIRouter, Request
from .base import APIRouteBase, get_shared_client

router = APIRouter(prefix="/system", tags=["system"])


# Create a single instance to use for all routes
_system_routes = None

def _get_routes() -> APIRouteBase:
    """Get the system routes instance."""
    global _system_routes
    if _system_routes is None:
        _system_routes = APIRouteBase(get_shared_client())
    return _system_routes


@router.get("/health", response_model=Dict[str, Any])
async def health_check(req: Request):
    """Get system health status."""
    routes = _get_routes()
    return await routes.handle_client_call("health_check")

@router.get("/status", response_model=Dict[str, Any])
async def get_system_status(req: Request):
    """Get detailed system status."""
    routes = _get_routes()
    return await routes.handle_client_call("get_system_status")

@router.get("/info", response_model=Dict[str, Any])
async def get_system_info(req: Request):
    """Get system information."""
    routes = _get_routes()
    return await routes.handle_client_call("get_system_info")

@router.get("/metrics", response_model=Dict[str, Any])
async def get_system_metrics(req: Request):
    """Get system performance metrics."""
    routes = _get_routes()
    return await routes.handle_client_call("get_system_metrics")

@router.post("/shutdown", response_model=Dict[str, str])
async def shutdown_system(req: Request):
    """Shutdown the system gracefully."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("shutdown_system")

@router.post("/maintenance/start", response_model=Dict[str, Any])
async def start_maintenance_mode(req: Request):
    """Start maintenance mode."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("start_maintenance_mode")

@router.post("/maintenance/stop", response_model=Dict[str, Any])
async def stop_maintenance_mode(req: Request):
    """Stop maintenance mode."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("stop_maintenance_mode")

@router.get("/config", response_model=Dict[str, Any])
async def get_system_config(req: Request):
    """Get system configuration."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("get_system_config")

# Export router for inclusion in main API
__all__ = ["router"]