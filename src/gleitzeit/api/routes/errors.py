"""
Error management API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Query, Depends
from pydantic import BaseModel
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from .base import APIRouteBase

router = APIRouter(prefix="/errors", tags=["errors"])


class ErrorUpdateRequest(BaseModel):
    status: Optional[str] = None
    resolution: Optional[str] = None
    notes: Optional[str] = None


# Create route handler instance (stateless - just contains logic)
error_routes = APIRouteBase()


@router.get("/", response_model=List[Dict[str, Any]])
async def get_event_errors(
    status: Optional[str] = Query(None, description="Status filter (new, acknowledged, resolved, ignored)"),
    severity: Optional[str] = Query(None, description="Severity filter (low, medium, high, critical)"),
    start_time: Optional[datetime] = Query(None, description="Start time for error range"),
    end_time: Optional[datetime] = Query(None, description="End time for error range"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of errors"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get event errors with optional filtering."""
    return await error_routes.handle_client_call(
        "get_event_errors",
        status=status,
        severity=severity,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
        client=client
    )


@router.get("/stats", response_model=Dict[str, Any])
async def get_error_statistics(
    start_time: Optional[datetime] = Query(None, description="Start time for stats"),
    end_time: Optional[datetime] = Query(None, description="End time for stats"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get error statistics."""
    return await error_routes.handle_client_call(
        "get_error_statistics",
        start_time=start_time,
        end_time=end_time,
        client=client
    )


@router.get("/task/{task_id}", response_model=List[Dict[str, Any]])
async def get_task_errors(
    task_id: str,
    severity: Optional[str] = Query(None, description="Severity filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of errors"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get errors for a specific task."""
    return await error_routes.handle_client_call(
        "get_task_errors",
        task_id=task_id,
        severity=severity,
        limit=limit,
        offset=offset,
        client=client
    )


@router.get("/workflow/{workflow_id}", response_model=List[Dict[str, Any]])
async def get_workflow_errors(
    workflow_id: str,
    severity: Optional[str] = Query(None, description="Severity filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of errors"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    client: GleitzeitClient = Depends(get_client)
):
    """Get errors for a specific workflow."""
    return await error_routes.handle_client_call(
        "get_workflow_errors",
        workflow_id=workflow_id,
        severity=severity,
        limit=limit,
        offset=offset,
        client=client
    )


@router.get("/{error_id}", response_model=Dict[str, Any])
async def get_event_error(
    error_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get details of a specific event error."""
    return await error_routes.handle_client_call("get_event_error", error_id, client=client)


@router.put("/{error_id}", response_model=Dict[str, Any])
async def update_event_error(
    error_id: str,
    request: ErrorUpdateRequest,
    client: GleitzeitClient = Depends(get_client)
):
    """Update event error status or details."""
    return await error_routes.handle_client_call(
        "update_event_error",
        error_id,
        status=request.status,
        resolution=request.resolution,
        notes=request.notes,
        client=client
    )


@router.post("/{error_id}/acknowledge", response_model=Dict[str, Any])
async def acknowledge_error(
    error_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Acknowledge an event error."""
    return await error_routes.handle_client_call("acknowledge_error", error_id, client=client)


@router.post("/{error_id}/resolve", response_model=Dict[str, Any])
async def resolve_error(
    error_id: str,
    resolution: str = Query(..., description="Resolution description"),
    client: GleitzeitClient = Depends(get_client)
):
    """Resolve an event error."""
    return await error_routes.handle_client_call("resolve_error", error_id, resolution, client=client)


@router.post("/{error_id}/ignore", response_model=Dict[str, Any])
async def ignore_error(
    error_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Ignore an event error."""
    return await error_routes.handle_client_call("ignore_error", error_id, client=client)


@router.post("/{error_id}/retry", response_model=Dict[str, Any])
async def retry_failed_event(
    error_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Retry the failed event that caused this error."""
    return await error_routes.handle_client_call("retry_failed_event", error_id, client=client)


@router.delete("/", response_model=Dict[str, Any])
async def clear_errors(
    req: Request,
    before: Optional[datetime] = Query(None, description="Clear errors before this time"),
    status: Optional[str] = Query(None, description="Only clear errors with this status"),
    severity: Optional[str] = Query(None, description="Only clear errors of this severity"),
    client: GleitzeitClient = Depends(get_client)
):
    """Clear errors with optional filters (admin only)."""
    error_routes.require_admin(req)
    return await error_routes.handle_client_call(
        "clear_errors",
        before=before,
        status=status,
        severity=severity,
        client=client
    )


@router.post("/bulk/acknowledge", response_model=Dict[str, Any])
async def bulk_acknowledge_errors(
    error_ids: List[str],
    client: GleitzeitClient = Depends(get_client)
):
    """Acknowledge multiple errors at once."""
    return await error_routes.handle_client_call("bulk_acknowledge_errors", error_ids, client=client)


@router.post("/bulk/resolve", response_model=Dict[str, Any])
async def bulk_resolve_errors(
    error_ids: List[str],
    resolution: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Resolve multiple errors at once."""
    return await error_routes.handle_client_call("bulk_resolve_errors", error_ids, resolution, client=client)