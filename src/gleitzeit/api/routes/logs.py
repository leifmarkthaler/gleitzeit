"""
Logging API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Query, Depends
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from .base import APIRouteBase

router = APIRouter(prefix="/logs", tags=["logs"])


# Create route handler instance (stateless - just contains logic)
log_routes = APIRouteBase()


@router.get("/", response_model=List[Dict[str, Any]])
async def get_logs(
    level: Optional[str] = Query(None, description="Log level filter (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
    source: Optional[str] = Query(None, description="Source/component filter"),
    start_time: Optional[datetime] = Query(None, description="Start time for log range"),
    end_time: Optional[datetime] = Query(None, description="End time for log range"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get logs with optional filtering."""
    return await log_routes.handle_client_call(
        "get_logs",
        level=level,
        source=source,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
        client=client
    )


@router.get("/levels", response_model=List[str])
async def get_log_levels(
    client: GleitzeitClient = Depends(get_client)
):
    """Get available log levels."""
    return await log_routes.handle_client_call("get_log_levels", client=client)


@router.get("/sources", response_model=List[str])
async def get_log_sources(
    client: GleitzeitClient = Depends(get_client)
):
    """Get available log sources."""
    return await log_routes.handle_client_call("get_log_sources", client=client)


@router.get("/task/{task_id}", response_model=List[Dict[str, Any]])
async def get_task_logs(
    task_id: str,
    level: Optional[str] = Query(None, description="Log level filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get logs for a specific task."""
    return await log_routes.handle_client_call(
        "get_task_logs",
        task_id=task_id,
        level=level,
        limit=limit,
        offset=offset,
        client=client
    )


@router.get("/workflow/{workflow_id}", response_model=List[Dict[str, Any]])
async def get_workflow_logs(
    workflow_id: str,
    level: Optional[str] = Query(None, description="Log level filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get logs for a specific workflow."""
    return await log_routes.handle_client_call(
        "get_workflow_logs",
        workflow_id=workflow_id,
        level=level,
        limit=limit,
        offset=offset,
        client=client
    )


@router.delete("/", response_model=Dict[str, Any])
async def clear_logs(
    req: Request,
    before: Optional[datetime] = Query(None, description="Clear logs before this time"),
    level: Optional[str] = Query(None, description="Only clear logs of this level"),
    source: Optional[str] = Query(None, description="Only clear logs from this source"),
    client: GleitzeitClient = Depends(get_client)
):
    """Clear logs with optional filters (admin only)."""
    log_routes.require_admin(req)
    return await log_routes.handle_client_call(
        "clear_logs",
        before=before,
        level=level,
        source=source,
        client=client
    )


@router.get("/stats", response_model=Dict[str, Any])
async def get_log_statistics(
    start_time: Optional[datetime] = Query(None, description="Start time for stats"),
    end_time: Optional[datetime] = Query(None, description="End time for stats"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get log statistics."""
    return await log_routes.handle_client_call(
        "get_log_statistics",
        start_time=start_time,
        end_time=end_time,
        client=client
    )


@router.post("/export", response_model=Dict[str, Any])
async def export_logs(
    format: str = Query("json", description="Export format (json, csv, txt)"),
    level: Optional[str] = Query(None, description="Log level filter"),
    source: Optional[str] = Query(None, description="Source filter"),
    start_time: Optional[datetime] = Query(None, description="Start time"),
    end_time: Optional[datetime] = Query(None, description="End time"),
    client: GleitzeitClient = Depends(get_client)
):
    """Export logs in specified format."""
    return await log_routes.handle_client_call(
        "export_logs",
        format=format,
        level=level,
        source=source,
        start_time=start_time,
        end_time=end_time,
        client=client
    )


@router.get("/stream", response_model=List[Dict[str, Any]])
async def stream_logs(
    level: Optional[str] = Query(None, description="Log level filter"),
    source: Optional[str] = Query(None, description="Source filter"),
    tail: int = Query(100, description="Number of recent logs to return"),
    client: GleitzeitClient = Depends(get_client)
):
    """Stream recent logs with optional filtering."""
    return await log_routes.handle_client_call(
        "stream_logs",
        level=level,
        source=source,
        tail=tail,
        client=client
    )