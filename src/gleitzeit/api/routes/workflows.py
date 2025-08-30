"""
Workflow API routes that delegate to client methods.
"""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from gleitzeit.core.models import Workflow
from .base import APIRouteBase, get_shared_client

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowSubmissionRequest(BaseModel):
    workflow: Dict[str, Any]


# Create a single instance to use for all routes
_workflow_routes = None

def _get_routes() -> APIRouteBase:
    """Get the workflow routes instance."""
    global _workflow_routes
    if _workflow_routes is None:
        _workflow_routes = APIRouteBase(get_shared_client())
    return _workflow_routes


@router.post("/", response_model=Dict[str, Any])
async def submit_workflow(request: WorkflowSubmissionRequest, req: Request):
    """Submit a workflow for execution."""
    workflow = Workflow(**request.workflow)
    routes = _get_routes()
    return await routes.handle_client_call("submit_workflow", workflow)

@router.post("/run", response_model=Dict[str, Any])
async def run_workflow_from_file(
    workflow_file: str,
    watch: bool = False,
    req: Request = None
):
    """Run a workflow from a file."""
    routes = _get_routes()
    return await routes.handle_client_call("run_workflow", workflow_file, watch)

@router.get("/{workflow_id}", response_model=Optional[Workflow])
async def get_workflow(workflow_id: str, req: Request):
    """Get workflow by ID."""
    routes = _get_routes()
    return await routes.handle_client_call("get_workflow", workflow_id)

@router.get("/", response_model=Dict[str, Any])
async def list_workflows(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    req: Request = None
):
    """List workflows with optional filters."""
    routes = _get_routes()
    return await routes.handle_client_call("list_workflows", status, limit, offset)

@router.post("/{workflow_id}/cancel", response_model=Dict[str, Any])
async def cancel_workflow(workflow_id: str, req: Request):
    """Cancel a workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("cancel_workflow", workflow_id)

@router.post("/{workflow_id}/pause", response_model=Dict[str, Any])
async def pause_workflow(workflow_id: str, req: Request):
    """Pause a running workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("pause_workflow", workflow_id)

@router.post("/{workflow_id}/resume", response_model=Dict[str, Any])
async def resume_workflow(workflow_id: str, req: Request):
    """Resume a paused workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("resume_workflow", workflow_id)

@router.delete("/{workflow_id}", response_model=bool)
async def delete_workflow(workflow_id: str, req: Request):
    """Delete a workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("delete_workflow", workflow_id)

@router.get("/{workflow_id}/tasks", response_model=List[Dict[str, Any]])
async def get_workflow_tasks(workflow_id: str, req: Request):
    """Get all tasks for a workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("get_workflow_tasks", workflow_id)

@router.post("/{workflow_id}/wait", response_model=Dict[str, Any])
async def wait_for_workflow(
    workflow_id: str,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
    req: Request = None
):
    """Wait for workflow to complete."""
    routes = _get_routes()
    return await routes.handle_client_call("wait_for_workflow", workflow_id, timeout, poll_interval)

@router.post("/{workflow_id}/clone", response_model=Dict[str, Any])
async def clone_workflow(
    workflow_id: str,
    new_name: Optional[str] = None,
    req: Request = None
):
    """Clone an existing workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("clone_workflow", workflow_id, new_name)

@router.get("/statistics/summary", response_model=Dict[str, Any])
async def get_workflow_statistics(req: Request):
    """Get workflow execution statistics."""
    routes = _get_routes()
    return await routes.handle_client_call("get_workflow_statistics")

@router.get("/{workflow_id}/timeline", response_model=Dict[str, Any])
async def get_workflow_timeline(workflow_id: str, req: Request):
    """Get execution timeline for a workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("get_workflow_timeline", workflow_id)

@router.get("/{workflow_id}/dependencies", response_model=Dict[str, Any])
async def get_workflow_dependencies(workflow_id: str, req: Request):
    """Get dependency graph for a workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("get_workflow_dependencies", workflow_id)

@router.get("/{workflow_id}/critical-path", response_model=Dict[str, Any])
async def get_workflow_critical_path(workflow_id: str, req: Request):
    """Get critical path analysis for a workflow."""
    routes = _get_routes()
    return await routes.handle_client_call("get_workflow_critical_path", workflow_id)

# Export router for inclusion in main API
__all__ = ["router"]