"""
Workflow API routes that delegate to client methods.

This module uses dependency injection for client management,
eliminating the singleton pattern for better scalability.
"""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File, Depends, Body
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from gleitzeit.core.models import Workflow
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client, get_system_manager
from .base import APIRouteBase
from ..auth_dependencies import (
    get_current_user_auto,
    get_current_user_required,
    require_workflow_create,
    security
)
from ..authorization import (
    check_workflow_ownership,
    filter_workflows_by_ownership
)
import logging

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)


class WorkflowSubmissionRequest(BaseModel):
    workflow: Dict[str, Any]


# Create route handler instance (stateless - just contains logic)
workflow_routes = APIRouteBase()


@router.post("/", response_model=Dict[str, Any])
async def submit_workflow(
    *,
    req: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager),
    workflow: Dict[str, Any] = Body(..., embed=True)
):
    """Submit a workflow for execution."""
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    
    # Get or create session ID
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Pass workflow dict to SystemManager
    # SystemManager will use WorkflowLoaderV2 to:
    # 1. Generate workflow ID
    # 2. Validate workflow structure and protocols
    # 3. Set user ownership
    try:
        workflow_id = await system_manager.submit_workflow_authenticated(workflow, session_id)
        return {"success": True, "workflow_id": workflow_id}
    except Exception as e:
        import traceback
        logger.error(f"Error submitting workflow: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise


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
    req: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """Get workflow by ID - with ownership check."""
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    
    # Get or create session ID
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Get through SystemManager with authentication
    workflow = await system_manager.get_workflow_authenticated(workflow_id, session_id)
    
    return workflow


@router.get("/", response_model=Dict[str, Any])
async def list_workflows(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """List workflows - filtered by ownership.
    
    Auto-logs in as basic user if no credentials provided.
    """
    # User already provided by dependency
    
    # Get all workflows
    result = await workflow_routes.handle_client_call("list_workflows", status, limit, offset, client=client)
    
    # Filter by ownership
    if result and isinstance(result, dict) and 'workflows' in result:
        result['workflows'] = await filter_workflows_by_ownership(
            result['workflows'],
            current_user,
            client
        )
        result['count'] = len(result['workflows'])
    
    return result


@router.post("/{workflow_id}/cancel", response_model=Dict[str, Any])
async def cancel_workflow(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """Cancel a workflow - requires ownership or admin.
    
    Auto-logs in as basic user if no credentials provided.
    """
    # User already provided by dependency
    
    # Check ownership (cancel is a modify operation)
    await check_workflow_ownership(workflow_id, current_user, client, "cancel")
    
    return await workflow_routes.handle_client_call("cancel_workflow", workflow_id, client=client)


@router.post("/{workflow_id}/pause", response_model=Dict[str, Any])
async def pause_workflow(
    workflow_id: str,
    req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """Pause a running workflow - requires ownership or admin."""
    # Get current user
    current_user = await get_current_user(req, credentials, system_manager)
    
    # Check ownership
    await check_workflow_ownership(workflow_id, current_user, client, "pause")
    
    return await workflow_routes.handle_client_call("pause_workflow", workflow_id, client=client)


@router.post("/{workflow_id}/resume", response_model=Dict[str, Any])
async def resume_workflow(
    workflow_id: str,
    req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """Resume a paused workflow - requires ownership or admin."""
    # Get current user
    current_user = await get_current_user(req, credentials, system_manager)
    
    # Check ownership
    await check_workflow_ownership(workflow_id, current_user, client, "resume")
    
    return await workflow_routes.handle_client_call("resume_workflow", workflow_id, client=client)


@router.delete("/{workflow_id}", response_model=bool)
async def delete_workflow(
    workflow_id: str,
    req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """Delete a workflow - requires ownership or admin."""
    # Get current user
    current_user = await get_current_user(req, credentials, system_manager)
    
    # Check ownership
    await check_workflow_ownership(workflow_id, current_user, client, "delete")
    
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
    req: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Submit multiple workflows in batch with parallel processing.
    
    Processes up to 10 workflows concurrently for better performance.
    Returns results in the same order as input.
    """
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    import asyncio
    
    # Get or create session ID - authentication managed by SystemManager/AuthManager
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Semaphore to limit concurrent submissions (avoid overwhelming the system)
    semaphore = asyncio.Semaphore(10)
    
    async def submit_single(index: int, workflow_req: WorkflowSubmissionRequest):
        """Submit a single workflow with error handling."""
        async with semaphore:
            try:
                # Each workflow goes through SystemManager for validation, ID generation, and authentication
                workflow_id = await system_manager.submit_workflow_authenticated(
                    workflow_req.workflow, session_id
                )
                return index, {"success": True, "workflow_id": workflow_id}
            except Exception as e:
                # Include failed workflows in batch response
                return index, {"success": False, "error": str(e)}
    
    # Submit all workflows in parallel
    tasks = [submit_single(i, req) for i, req in enumerate(workflows)]
    results_with_indices = await asyncio.gather(*tasks)
    
    # Sort results back to original order
    results_with_indices.sort(key=lambda x: x[0])
    results = [result for _, result in results_with_indices]
    
    return results


@router.post("/from-yaml", response_model=Dict[str, Any])
async def submit_workflow_from_yaml(
    req: Request,
    response: Response,
    yaml_file: UploadFile = File(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Submit a workflow from uploaded YAML file."""
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    import yaml
    
    # Get or create session ID - authentication managed by SystemManager/AuthManager
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Read and validate file size
    content = await yaml_file.read()
    if len(content) > 10_000_000:  # 10MB limit
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    
    try:
        # Parse YAML content
        workflow_dict = yaml.safe_load(content.decode('utf-8'))
        if not isinstance(workflow_dict, dict):
            raise HTTPException(status_code=400, detail="Invalid YAML: must be a dictionary")
            
        # Submit through SystemManager for validation, ID generation, and authentication
        workflow_id = await system_manager.submit_workflow_authenticated(workflow_dict, session_id)
        
        return {"success": True, "workflow_id": workflow_id}
        
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML format: {e}")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid file encoding: {e}")


@router.post("/upload")
async def upload_workflows(
    req: Request,
    response: Response,
    file: UploadFile = File(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Upload file containing one or more workflows (JSON or YAML).
    
    Supports:
    - Single workflow in JSON/YAML format
    - Array of workflows in JSON format
    - Multiple YAML documents (separated by ---)
    
    Returns array of results for consistency with batch endpoint.
    """
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    import yaml
    import json
    
    # Get or create session ID
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Read and validate file size
    content = await file.read()
    if len(content) > 10_000_000:  # 10MB limit
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    
    # Detect format based on content and filename
    filename = file.filename.lower() if file.filename else ""
    text_content = content.decode('utf-8')
    
    workflows = []
    
    try:
        # Try JSON first (works for both .json files and JSON content)
        if filename.endswith('.json') or text_content.strip().startswith(('[', '{')):
            try:
                data = json.loads(text_content)
                if isinstance(data, list):
                    workflows = data
                elif isinstance(data, dict):
                    workflows = [data]
                else:
                    raise HTTPException(status_code=400, detail="Invalid JSON: must be object or array")
            except json.JSONDecodeError:
                # If JSON parsing fails and it looked like JSON, fail fast
                if filename.endswith('.json'):
                    raise HTTPException(status_code=400, detail="Invalid JSON format")
                # Otherwise try YAML
        
        # Try YAML if not already parsed
        if not workflows:
            # Load all YAML documents (supports multiple docs with ---)
            yaml_docs = list(yaml.safe_load_all(text_content))
            for doc in yaml_docs:
                if doc is None:
                    continue
                if isinstance(doc, list):
                    workflows.extend(doc)
                elif isinstance(doc, dict):
                    workflows.append(doc)
                else:
                    raise HTTPException(status_code=400, detail="Invalid YAML: each document must be object or array")
    
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML format: {e}")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid file encoding: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")
    
    if not workflows:
        raise HTTPException(status_code=400, detail="No workflows found in file")
    
    # Submit all workflows (best-effort approach)
    results = []
    for i, workflow_dict in enumerate(workflows):
        try:
            if not isinstance(workflow_dict, dict):
                results.append({
                    "success": False, 
                    "error": f"Workflow {i+1}: Must be a dictionary/object"
                })
                continue
                
            workflow_id = await system_manager.submit_workflow_authenticated(workflow_dict, session_id)
            results.append({"success": True, "workflow_id": workflow_id})
        except Exception as e:
            results.append({"success": False, "error": f"Workflow {i+1}: {str(e)}"})
    
    return results


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


class PauseRequest(BaseModel):
    """Request model for pausing workflows."""
    rewind_to: Optional[str] = None
    rewind_to_step: Optional[int] = None
    reason: Optional[str] = None


@router.post("/{workflow_id}/pause", response_model=Dict[str, Any])
async def pause_workflow(
    workflow_id: str,
    request: PauseRequest,
    req: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """
    Pause workflow with optional rewind.
    
    Requires authentication and ownership of the workflow.
    """
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    
    # Get or create session ID
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Get user info for auth tracking
    user_info = await system_manager.auth_manager.get_session(session_id)
    if not user_info or not user_info.get("user"):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    user_id = user_info["user"]["id"]
    
    # Check workflow ownership
    workflow = await system_manager.get_workflow_authenticated(workflow_id, session_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Call persistence layer with pause
    persistence = system_manager.persistence
    
    # Determine if we need rewind
    rewind_to = request.rewind_to or request.rewind_to_step
    
    if rewind_to:
        result = await persistence.pause_workflow_with_rewind(
            workflow_id=workflow_id,
            user_id=user_id,
            rewind_to=rewind_to,
            reason=request.reason
        )
    else:
        result = await persistence.pause_workflow(
            workflow_id=workflow_id,
            user_id=user_id
        )
    
    return result


@router.post("/{workflow_id}/resume", response_model=Dict[str, Any])
async def resume_workflow(
    workflow_id: str,
    req: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """
    Resume a paused workflow.
    
    Requires authentication and ownership of the workflow.
    """
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    
    # Get or create session ID
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Check workflow ownership
    workflow = await system_manager.get_workflow_authenticated(workflow_id, session_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Call persistence layer to resume
    persistence = system_manager.persistence
    result = await persistence.resume_workflow(workflow_id)
    
    return result


@router.get("/{workflow_id}/pause-status", response_model=Dict[str, Any])
async def get_pause_status(
    workflow_id: str,
    req: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    """
    Get pause metadata including rewind information.
    
    Requires authentication and ownership of the workflow.
    """
    # Import here to avoid circular dependency
    from .auth import get_or_create_session_id
    
    # Get or create session ID
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    # Check workflow ownership
    workflow = await system_manager.get_workflow_authenticated(workflow_id, session_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Get pause metadata
    persistence = system_manager.persistence
    pause_key = persistence._key(f"workflow:pause:{workflow_id}")
    pause_data = await persistence._execute("hgetall", pause_key)
    
    if not pause_data:
        return {"paused": False}
    
    # Decode pause data
    if isinstance(pause_data, dict):
        if any(isinstance(k, bytes) for k in pause_data.keys()):
            pause_data = {
                k.decode() if isinstance(k, bytes) else k: 
                v.decode() if isinstance(v, bytes) else v
                for k, v in pause_data.items()
            }
    
    # Parse JSON fields
    import json
    for field in ["cancelled_tasks", "queued_tasks", "reset_tasks", "preserved_results"]:
        if field in pause_data:
            try:
                pause_data[field] = json.loads(pause_data[field])
            except:
                pass
    
    pause_data["paused"] = True
    
    # Mask sensitive data if not owner (future enhancement)
    # For now, return all data to authenticated users
    
    return pause_data