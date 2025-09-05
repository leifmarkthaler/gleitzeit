"""
Task API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from gleitzeit.core.models import Task, TaskResult
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from .base import APIRouteBase

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskSubmissionRequest(BaseModel):
    task: Dict[str, Any]


class TaskUpdateRequest(BaseModel):
    updates: Dict[str, Any]


# Create route handler instance (stateless - just contains logic)
task_routes = APIRouteBase()


@router.post("/", response_model=Dict[str, Any])
async def submit_task(
    request: TaskSubmissionRequest,
    client: GleitzeitClient = Depends(get_client)
):
    """Submit a task for execution."""
    task = Task(**request.task)
    return await task_routes.handle_client_call("submit_task", task, client=client)


@router.get("/{task_id}", response_model=Optional[Task])
async def get_task(
    task_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get task by ID."""
    return await task_routes.handle_client_call("get_task", task_id, client=client)


@router.get("/", response_model=Dict[str, Any])
async def list_tasks(
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    client: GleitzeitClient = Depends(get_client)
):
    """List tasks with optional filters."""
    return await task_routes.handle_client_call(
        "list_tasks", 
        workflow_id, 
        status, 
        limit, 
        offset,
        client=client
    )


@router.post("/{task_id}/cancel", response_model=Dict[str, Any])
async def cancel_task(
    task_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Cancel a task."""
    return await task_routes.handle_client_call("cancel_task", task_id, client=client)


@router.post("/{task_id}/pause", response_model=Dict[str, Any])
async def pause_task(
    task_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Pause a running task."""
    return await task_routes.handle_client_call("pause_task", task_id, client=client)


@router.post("/{task_id}/resume", response_model=Dict[str, Any])
async def resume_task(
    task_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Resume a paused task."""
    return await task_routes.handle_client_call("resume_task", task_id, client=client)


@router.put("/{task_id}", response_model=Dict[str, Any])
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    client: GleitzeitClient = Depends(get_client)
):
    """Update task properties."""
    return await task_routes.handle_client_call(
        "update_task", 
        task_id, 
        request.updates,
        client=client
    )


@router.post("/{task_id}/wait", response_model=Dict[str, Any])
async def wait_for_task(
    task_id: str,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
    client: GleitzeitClient = Depends(get_client)
):
    """Wait for task to complete."""
    return await task_routes.handle_client_call(
        "wait_for_task", 
        task_id, 
        timeout, 
        poll_interval,
        client=client
    )


@router.get("/{task_id}/result", response_model=Optional[TaskResult])
async def get_task_result(
    task_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get the execution result of a task."""
    return await task_routes.handle_client_call("get_task_result", task_id, client=client)


@router.post("/{task_id}/retry", response_model=Dict[str, Any])
async def retry_task(
    task_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Retry a failed task."""
    return await task_routes.handle_client_call("retry_task", task_id, client=client)


@router.get("/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    tail: int = 20,
    client: GleitzeitClient = Depends(get_client)
):
    """Get logs for a task execution."""
    # Get logs from the client
    logs = await client.get_task_logs(task_id)
    # Return logs or empty list
    return logs if logs else []


@router.delete("/{task_id}", response_model=bool)
async def delete_task(
    task_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Delete a task."""
    return await task_routes.handle_client_call("delete_task", task_id, client=client)