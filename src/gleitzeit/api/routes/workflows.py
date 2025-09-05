"""
Workflow API routes that delegate to client methods.

This module uses dependency injection for client management,
eliminating the singleton pattern for better scalability.
"""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Depends
from pydantic import BaseModel
from gleitzeit.core.models import Workflow
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from ..worker_router import get_worker_router
from .base import APIRouteBase
import logging

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)


class WorkflowSubmissionRequest(BaseModel):
    workflow: Dict[str, Any]


# Create route handler instance (stateless - just contains logic)
workflow_routes = APIRouteBase()


@router.post("/", response_model=Dict[str, Any])
async def submit_workflow(
    request: WorkflowSubmissionRequest,
    client: GleitzeitClient = Depends(get_client)
):
    """Submit a workflow for execution."""
    workflow = Workflow(**request.workflow)
    
    # Try to route to worker service first
    worker_router = get_worker_router()
    if worker_router.enabled:
        result = await worker_router.route_workflow(workflow)
        if result:
            logger.info(f"Workflow {workflow.id} executed via worker service")
            return result
    
    # Fall back to local execution
    logger.info(f"Workflow {workflow.id} executing locally")
    return await workflow_routes.handle_client_call("submit_workflow", workflow, client=client)


@router.post("/run", response_model=Dict[str, Any])
async def run_workflow_from_file(
    workflow_file: str,
    watch: bool = False,
    client: GleitzeitClient = Depends(get_client)
):
    """Run a workflow from a file."""
    return await workflow_routes.handle_client_call("run_workflow", workflow_file, watch, client=client)


@router.get("/{workflow_id}", response_model=Optional[Workflow])
async def get_workflow(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get workflow by ID."""
    return await workflow_routes.handle_client_call("get_workflow", workflow_id, client=client)


@router.get("/", response_model=Dict[str, Any])
async def list_workflows(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    client: GleitzeitClient = Depends(get_client)
):
    """List workflows with optional filters."""
    return await workflow_routes.handle_client_call("list_workflows", status, limit, offset, client=client)


@router.post("/{workflow_id}/cancel", response_model=Dict[str, Any])
async def cancel_workflow(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Cancel a workflow."""
    return await workflow_routes.handle_client_call("cancel_workflow", workflow_id, client=client)


@router.post("/{workflow_id}/pause", response_model=Dict[str, Any])
async def pause_workflow(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Pause a running workflow."""
    return await workflow_routes.handle_client_call("pause_workflow", workflow_id, client=client)


@router.post("/{workflow_id}/resume", response_model=Dict[str, Any])
async def resume_workflow(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Resume a paused workflow."""
    return await workflow_routes.handle_client_call("resume_workflow", workflow_id, client=client)


@router.delete("/{workflow_id}", response_model=bool)
async def delete_workflow(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Delete a workflow."""
    return await workflow_routes.handle_client_call("delete_workflow", workflow_id, client=client)


@router.get("/workers/status", response_model=Dict[str, Any])
async def get_worker_status():
    """Get status of worker services."""
    worker_router = get_worker_router()
    return await worker_router.get_worker_status()


@router.get("/{workflow_id}/tasks", response_model=List[Dict[str, Any]])
async def get_workflow_tasks(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get all tasks for a workflow."""
    return await workflow_routes.handle_client_call("get_workflow_tasks", workflow_id, client=client)


@router.post("/{workflow_id}/wait", response_model=Dict[str, Any])
async def wait_for_workflow(
    workflow_id: str,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
    client: GleitzeitClient = Depends(get_client)
):
    """Wait for workflow to complete."""
    return await workflow_routes.handle_client_call(
        "wait_for_workflow",
        workflow_id,
        timeout=timeout,
        poll_interval=poll_interval,
        client=client
    )


@router.get("/{workflow_id}/results", response_model=Dict[str, Any])
async def get_workflow_results(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get results for all tasks in a workflow."""
    return await workflow_routes.handle_client_call("get_workflow_results", workflow_id, client=client)


@router.post("/batch", response_model=List[Dict[str, Any]])
async def submit_workflows_batch(
    workflows: List[WorkflowSubmissionRequest],
    client: GleitzeitClient = Depends(get_client)
):
    """Submit multiple workflows in batch."""
    workflow_objects = [Workflow(**w.workflow) for w in workflows]
    return await workflow_routes.handle_client_call("submit_workflows_batch", workflow_objects, client=client)


@router.post("/from-yaml", response_model=Dict[str, Any])
async def submit_workflow_from_yaml(
    yaml_file: UploadFile = File(...),
    client: GleitzeitClient = Depends(get_client)
):
    """Submit a workflow from uploaded YAML file."""
    content = await yaml_file.read()
    return await workflow_routes.handle_client_call("submit_workflow_yaml", content.decode(), client=client)


@router.get("/{workflow_id}/dag", response_model=Dict[str, Any])
async def get_workflow_dag(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get workflow DAG structure."""
    return await workflow_routes.handle_client_call("get_workflow_dag", workflow_id, client=client)


@router.post("/{workflow_id}/retry", response_model=Dict[str, Any])
async def retry_workflow(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Retry all failed tasks in a workflow."""
    return await workflow_routes.handle_client_call("retry_workflow", workflow_id, client=client)


@router.get("/{workflow_id}/export", response_model=Dict[str, Any])
async def export_workflow(
    workflow_id: str,
    format: str = "json",
    client: GleitzeitClient = Depends(get_client)
):
    """Export workflow definition in JSON or YAML format."""
    return await workflow_routes.handle_client_call("export_workflow", workflow_id, format=format, client=client)


@router.post("/{workflow_id}/clone", response_model=Dict[str, Any])
async def clone_workflow(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Clone an existing workflow."""
    return await workflow_routes.handle_client_call("clone_workflow", workflow_id, client=client)


@router.get("/{workflow_id}/dependencies", response_model=Dict[str, Any])
async def get_workflow_dependencies(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get workflow dependency graph."""
    return await workflow_routes.handle_client_call("get_workflow_dependencies", workflow_id, client=client)


@router.get("/{workflow_id}/critical-path", response_model=Dict[str, Any])
async def get_workflow_critical_path(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)
):
    """Get workflow critical path analysis."""
    return await workflow_routes.handle_client_call("get_workflow_critical_path", workflow_id, client=client)