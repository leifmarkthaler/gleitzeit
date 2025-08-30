"""
Error management API routes that delegate to client methods.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel
from .base import APIRouteBase, get_shared_client

router = APIRouter(prefix="/errors", tags=["errors"])


class ErrorUpdateRequest(BaseModel):
    status: Optional[str] = None
    resolution: Optional[str] = None
    notes: Optional[str] = None


# Create a single instance to use for all routes
_error_routes = None

def _get_routes() -> APIRouteBase:
    """Get the error routes instance."""
    global _error_routes
    if _error_routes is None:
        _error_routes = APIRouteBase(get_shared_client())
    return _error_routes


@router.get("/", response_model=List[Dict[str, Any]])
async def get_event_errors(
    status: Optional[str] = Query(None, description="Status filter (new, acknowledged, resolved, ignored)"),
    severity: Optional[str] = Query(None, description="Severity filter (low, medium, high, critical)"),
    start_time: Optional[datetime] = Query(None, description="Start time for error range"),
    end_time: Optional[datetime] = Query(None, description="End time for error range"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of errors"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    req: Request = None
):
    """Get event errors with optional filtering."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_event_errors",
        status=status,
        severity=severity,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset
    )

@router.get("/stats", response_model=Dict[str, Any])
async def get_error_statistics(
    start_time: Optional[datetime] = Query(None, description="Start time for stats"),
    end_time: Optional[datetime] = Query(None, description="End time for stats"),
    req: Request = None
):
    """Get error statistics."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_error_statistics",
        start_time=start_time,
        end_time=end_time
    )

@router.get("/task/{task_id}", response_model=List[Dict[str, Any]])
async def get_task_errors(
    task_id: str,
    severity: Optional[str] = Query(None, description="Severity filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of errors"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    req: Request = None
):
    """Get errors for a specific task."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_task_errors",
        task_id=task_id,
        severity=severity,
        limit=limit,
        offset=offset
    )

@router.get("/workflow/{workflow_id}", response_model=List[Dict[str, Any]])
async def get_workflow_errors(
    workflow_id: str,
    severity: Optional[str] = Query(None, description="Severity filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of errors"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    req: Request = None
):
    """Get errors for a specific workflow."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "get_workflow_errors",
        workflow_id=workflow_id,
        severity=severity,
        limit=limit,
        offset=offset
    )

@router.get("/{error_id}", response_model=Dict[str, Any])
async def get_event_error(error_id: str, req: Request):
    """Get details of a specific event error."""
    routes = _get_routes()
    return await routes.handle_client_call("get_event_error", error_id)

@router.put("/{error_id}", response_model=Dict[str, Any])
async def update_event_error(
    error_id: str,
    request: ErrorUpdateRequest,
    req: Request
):
    """Update event error status or details."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "update_event_error",
        error_id,
        status=request.status,
        resolution=request.resolution,
        notes=request.notes
    )

@router.post("/{error_id}/acknowledge", response_model=Dict[str, Any])
async def acknowledge_error(error_id: str, req: Request):
    """Acknowledge an event error."""
    routes = _get_routes()
    return await routes.handle_client_call("acknowledge_error", error_id)

@router.post("/{error_id}/resolve", response_model=Dict[str, Any])
async def resolve_error(
    error_id: str,
    resolution: str = Query(..., description="Resolution description"),
    req: Request = None
):
    """Resolve an event error."""
    routes = _get_routes()
    return await routes.handle_client_call("resolve_error", error_id, resolution)

@router.post("/{error_id}/ignore", response_model=Dict[str, Any])
async def ignore_error(error_id: str, req: Request):
    """Ignore an event error."""
    routes = _get_routes()
    return await routes.handle_client_call("ignore_error", error_id)

@router.post("/{error_id}/retry", response_model=Dict[str, Any])
async def retry_failed_event(error_id: str, req: Request):
    """Retry the failed event that caused this error."""
    routes = _get_routes()
    return await routes.handle_client_call("retry_failed_event", error_id)


@router.delete("/", response_model=Dict[str, Any])
async def clear_errors(
    before: Optional[datetime] = Query(None, description="Clear errors before this time"),
    status: Optional[str] = Query(None, description="Only clear errors with this status"),
    severity: Optional[str] = Query(None, description="Only clear errors of this severity"),
    req: Request = None
):
    """Clear errors with optional filters (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call(
        "clear_errors",
        before=before,
        status=status,
        severity=severity
    )

# Export router for inclusion in main API
__all__ = ["router"]