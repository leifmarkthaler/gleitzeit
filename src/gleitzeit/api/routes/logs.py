"""
Logging API routes that delegate to client methods.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Query
from .base import APIRouteBase, get_shared_client

router = APIRouter(prefix="/logs", tags=["logs"])


# Create a single instance to use for all routes
_log_routes = None

def _get_routes() -> APIRouteBase:
    """Get the log routes instance."""
    global _log_routes
    if _log_routes is None:
        _log_routes = APIRouteBase(get_shared_client())
    return _log_routes


@router.get("/", response_model=List[Dict[str, Any]])
async def get_logs(
    level: Optional[str] = Query(None, description="Log level filter (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
    source: Optional[str] = Query(None, description="Source/component filter"),
    start_time: Optional[datetime] = Query(None, description="Start time for log range"),
    end_time: Optional[datetime] = Query(None, description="End time for log range"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    req: Request = None
):
    """Get logs with optional filtering."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_logs",
        level=level,
        source=source,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset
    )

@router.get("/levels", response_model=List[str])
async def get_log_levels(req: Request):
    """Get available log levels."""
    routes = _get_routes()
    return await routes.handle_client_call("get_log_levels")

@router.get("/sources", response_model=List[str])
async def get_log_sources(req: Request):
    """Get available log sources."""
    routes = _get_routes()
    return await routes.handle_client_call("get_log_sources")

@router.get("/task/{task_id}", response_model=List[Dict[str, Any]])
async def get_task_logs(
    task_id: str,
    level: Optional[str] = Query(None, description="Log level filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    req: Request = None
):
    """Get logs for a specific task."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_task_logs",
        task_id=task_id,
        level=level,
        limit=limit,
        offset=offset
    )

@router.get("/workflow/{workflow_id}", response_model=List[Dict[str, Any]])
async def get_workflow_logs(
    workflow_id: str,
    level: Optional[str] = Query(None, description="Log level filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    req: Request = None
):
    """Get logs for a specific workflow."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_workflow_logs",
        workflow_id=workflow_id,
        level=level,
        limit=limit,
        offset=offset
    )

@router.delete("/", response_model=Dict[str, Any])
async def clear_logs(
    before: Optional[datetime] = Query(None, description="Clear logs before this time"),
    level: Optional[str] = Query(None, description="Only clear logs of this level"),
    source: Optional[str] = Query(None, description="Only clear logs from this source"),
    req: Request = None
):
    """Clear logs with optional filters (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call(
        "clear_logs",
        before=before,
        level=level,
        source=source
    )

@router.get("/stats", response_model=Dict[str, Any])
async def get_log_statistics(
    start_time: Optional[datetime] = Query(None, description="Start time for stats"),
    end_time: Optional[datetime] = Query(None, description="End time for stats"),
    req: Request = None
):
    """Get log statistics."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_log_statistics",
        start_time=start_time,
        end_time=end_time
    )

@router.post("/export", response_model=Dict[str, Any])
async def export_logs(
    format: str = Query("json", description="Export format (json, csv, txt)"),
    level: Optional[str] = Query(None, description="Log level filter"),
    source: Optional[str] = Query(None, description="Source filter"),
    start_time: Optional[datetime] = Query(None, description="Start time"),
    end_time: Optional[datetime] = Query(None, description="End time"),
    req: Request = None
):
    """Export logs in specified format."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "export_logs",
        format=format,
        level=level,
        source=source,
        start_time=start_time,
        end_time=end_time
    )

# Export router for inclusion in main API
__all__ = ["router"]