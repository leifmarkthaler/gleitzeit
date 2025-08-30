"""
Task API routes that delegate to client methods.
"""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request
from pydantic import BaseModel
from gleitzeit.core.models import Task
from .base import APIRouteBase, get_shared_client

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskSubmissionRequest(BaseModel):
    task: Dict[str, Any]


class TaskUpdateRequest(BaseModel):
    updates: Dict[str, Any]


# Create a single instance to use for all routes
_task_routes = None

def _get_routes() -> APIRouteBase:
    """Get the task routes instance."""
    global _task_routes
    if _task_routes is None:
        _task_routes = APIRouteBase(get_shared_client())
    return _task_routes


@router.post("/", response_model=Dict[str, Any])
async def submit_task(request: TaskSubmissionRequest, req: Request):
    """Submit a task for execution."""
    task = Task(**request.task)
    routes = _get_routes()
    return await routes.handle_client_call("submit_task", task)

@router.get("/{task_id}", response_model=Optional[Task])
async def get_task(task_id: str, req: Request):
    """Get task by ID."""
    routes = _get_routes()
    return await routes.handle_client_call("get_task", task_id)

@router.get("/", response_model=Dict[str, Any])
async def list_tasks(
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    req: Request = None
):
    """List tasks with optional filters."""
    routes = _get_routes()
    return await routes.handle_client_call("list_tasks", workflow_id, status, limit, offset)

@router.post("/{task_id}/cancel", response_model=Dict[str, Any])
async def cancel_task(task_id: str, req: Request):
    """Cancel a task."""
    routes = _get_routes()
    return await routes.handle_client_call("cancel_task", task_id)

@router.post("/{task_id}/pause", response_model=Dict[str, Any])
async def pause_task(task_id: str, req: Request):
    """Pause a running task."""
    routes = _get_routes()
    return await routes.handle_client_call("pause_task", task_id)

@router.post("/{task_id}/resume", response_model=Dict[str, Any])
async def resume_task(task_id: str, req: Request):
    """Resume a paused task."""
    routes = _get_routes()
    return await routes.handle_client_call("resume_task", task_id)

@router.put("/{task_id}", response_model=Dict[str, Any])
async def update_task(task_id: str, request: TaskUpdateRequest, req: Request):
    """Update task properties."""
    routes = _get_routes()
    return await routes.handle_client_call("update_task", task_id, request.updates)

@router.post("/{task_id}/wait", response_model=Dict[str, Any])
async def wait_for_task(
    task_id: str,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
    req: Request = None
):
    """Wait for task to complete."""
    routes = _get_routes()
    return await routes.handle_client_call("wait_for_task", task_id, timeout, poll_interval)

# Export router for inclusion in main API
__all__ = ["router"]