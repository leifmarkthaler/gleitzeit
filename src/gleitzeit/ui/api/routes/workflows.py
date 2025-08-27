"""
Workflow monitoring and management endpoints - proxies to Gleitzeit API
"""

from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import yaml
import tempfile
import os
import uuid
import aiohttp

router = APIRouter()

# Get Gleitzeit API URL from environment or use default
GLEITZEIT_API_URL = os.getenv('GLEITZEIT_API_URL', 'http://localhost:8000')

# Track workflows submitted through this UI session
_ui_workflows = {}

@router.get("")
async def list_workflows(
    request: Request,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List all workflows - now uses the API's list endpoint
    
    Args:
        status: Filter by status (running, completed, failed, pending)
        limit: Maximum number of workflows to return
        offset: Pagination offset
    
    Returns:
        List of workflows with metadata
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Build query parameters
            params = {
                "limit": limit,
                "offset": offset
            }
            if status:
                params["status"] = status
            
            # Get workflows from API list endpoint
            async with session.get(f"{GLEITZEIT_API_URL}/workflows", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Transform API response to UI format
                    workflows = []
                    for wf in data.get("workflows", []):
                        workflows.append({
                            "id": wf.get("id") or wf.get("workflow_id"),  # Handle both field names
                            "name": wf.get("name", "Unnamed"),
                            "status": wf.get("status", "unknown"),
                            "created_at": wf.get("created_at"),
                            "completed_at": wf.get("completed_at"),
                            "tasks_total": wf.get("tasks_total", 0),
                            "tasks_completed": wf.get("tasks_completed", 0),
                            "tasks_failed": wf.get("tasks_failed", 0)
                        })
                    return {
                        "workflows": workflows,
                        "total": data.get("total", 0),
                        "limit": limit,
                        "offset": offset
                    }
                else:
                    # API list endpoint not available, fallback to empty
                    return {
                        "workflows": [],
                        "total": 0,
                        "limit": limit,
                        "offset": offset
                    }
        except Exception as e:
            print(f"Error listing workflows: {e}")
            return {
                "workflows": [],
                "total": 0,
                "limit": limit,
                "offset": offset
            }

@router.get("/{workflow_id}")
async def get_workflow(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Get detailed workflow information from API
    
    Args:
        workflow_id: Unique workflow identifier
    
    Returns:
        Workflow details including tasks and status
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    raise HTTPException(status_code=resp.status, detail="API error")
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")

@router.post("/submit")
async def submit_workflow(request: Request, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Submit a workflow to Gleitzeit API for execution
    
    Args:
        workflow_data: Workflow definition (YAML or JSON)
    
    Returns:
        Submission response with workflow ID
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Convert workflow data to API format
            api_workflow = {
                "name": workflow_data.get("name", "UI Workflow"),
                "description": workflow_data.get("description"),
                "tasks": [],
                "metadata": workflow_data.get("metadata", {})
            }
            
            # Convert tasks to API format
            for task in workflow_data.get("tasks", []):
                # Parse method to get protocol and method
                method_parts = task.get("method", "").split("/")
                if len(method_parts) >= 2:
                    protocol = f"{method_parts[0]}/v1"
                    method = "/".join(method_parts)
                else:
                    protocol = "llm/v1"
                    method = task.get("method", "llm/chat")
                
                api_task = {
                    "id": task.get("id"),
                    "name": task.get("name", task.get("id", "task")),
                    "protocol": protocol,
                    "method": method,
                    "params": task.get("parameters", {}),
                    "dependencies": task.get("dependencies", []),
                    "priority": task.get("priority", "normal")
                }
                
                if "retry" in task:
                    api_task["retry"] = task["retry"]
                
                api_workflow["tasks"].append(api_task)
            
            # Submit to API
            async with session.post(
                f"{GLEITZEIT_API_URL}/workflows",
                json=api_workflow
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Track this workflow in UI
                    _ui_workflows[data["workflow_id"]] = {
                        "id": data["workflow_id"],
                        "name": api_workflow["name"],
                        "status": data["status"],
                        "created_at": data.get("created_at"),
                        "tasks_total": data.get("tasks_total", 0)
                    }
                    
                    return data
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=f"API error: {error_text}")
                    
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")

@router.post("/submit-file")
async def submit_workflow_file(request: Request) -> Dict[str, Any]:
    """
    Submit a workflow file to API
    
    Returns:
        Submission response with workflow ID
    """
    # Get file content from request
    body = await request.body()
    
    # Parse as YAML
    try:
        workflow_data = yaml.safe_load(body)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")
    
    # Submit using the regular submit endpoint
    return await submit_workflow(request, workflow_data)

@router.post("/upload")
async def batch_upload_workflows(request: Request) -> Dict[str, Any]:
    """
    Upload multiple workflows from a file (JSON or YAML)
    
    Returns:
        Upload results with created workflow IDs and errors
    """
    from fastapi import UploadFile, File, Form
    import io
    
    # Get form data
    form_data = await request.form()
    file = form_data.get("file")
    
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Read file content
    content = await file.read()
    
    # Parse content based on file extension
    try:
        if file.filename.endswith('.json'):
            data = json.loads(content)
        elif file.filename.endswith(('.yaml', '.yml')):
            data = yaml.safe_load(content)
        else:
            # Try JSON first, then YAML
            try:
                data = json.loads(content)
            except:
                data = yaml.safe_load(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file format: {e}")
    
    # Check if it's a list of workflows or a single workflow
    if isinstance(data, dict):
        workflows = [data]
    elif isinstance(data, list):
        workflows = data
    else:
        raise HTTPException(status_code=400, detail="File must contain workflow(s)")
    
    # Submit each workflow
    results = {
        "created": 0,
        "failed": 0,
        "workflows": [],
        "errors": []
    }
    
    for idx, workflow in enumerate(workflows):
        try:
            # Submit workflow
            result = await submit_workflow(request, workflow)
            results["created"] += 1
            results["workflows"].append({
                "index": idx,
                "workflow_id": result.get("workflow_id"),
                "name": workflow.get("name", f"Workflow {idx}")
            })
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "index": idx,
                "name": workflow.get("name", f"Workflow {idx}"),
                "error": str(e)
            })
    
    return results

@router.delete("/{workflow_id}")
async def cancel_workflow(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Cancel a running workflow via API
    
    Args:
        workflow_id: Workflow to cancel
    
    Returns:
        Cancellation result
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.delete(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Update UI tracking
                    if workflow_id in _ui_workflows:
                        _ui_workflows[workflow_id]["status"] = "cancelled"
                    
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    raise HTTPException(status_code=resp.status, detail="API error")
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")

@router.get("/{workflow_id}/download")
async def download_workflow_results(request: Request, workflow_id: str):
    """
    Download workflow results as JSON
    
    Args:
        workflow_id: Workflow ID
    
    Returns:
        JSON file with results
    """
    # Get workflow details from API
    workflow = await get_workflow(request, workflow_id)
    
    # Create temp file with results
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(workflow, f, indent=2, default=str)
        temp_path = f.name
    
    return FileResponse(
        path=temp_path,
        filename=f"workflow_{workflow_id}_results.json",
        media_type="application/json"
    )

@router.get("/{workflow_id}/tasks")
async def get_workflow_tasks(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Get all tasks for a specific workflow
    
    Args:
        workflow_id: Workflow identifier
    
    Returns:
        List of tasks belonging to the workflow
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Get tasks filtered by workflow_id
            params = {"workflow_id": workflow_id, "limit": 1000}
            async with session.get(f"{GLEITZEIT_API_URL}/tasks", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "workflow_id": workflow_id,
                        "tasks": data.get("tasks", []),
                        "total": data.get("total", 0)
                    }
                else:
                    return {"workflow_id": workflow_id, "tasks": [], "total": 0}
        except Exception as e:
            print(f"Error getting workflow tasks: {e}")
            return {"workflow_id": workflow_id, "tasks": [], "total": 0}

@router.get("/{workflow_id}/timeline")
async def get_workflow_timeline(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Get execution timeline for a workflow
    
    Args:
        workflow_id: Workflow identifier
    
    Returns:
        Timeline data showing task execution order and timing
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Get tasks for this workflow
            params = {"workflow_id": workflow_id, "limit": 1000}
            async with session.get(f"{GLEITZEIT_API_URL}/tasks", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get("tasks", [])
                    
                    # Build timeline from task data
                    timeline = []
                    for task in tasks:
                        timeline.append({
                            "task_id": task.get("task_id") or task.get("id"),
                            "name": task.get("name"),
                            "status": task.get("status"),
                            "started_at": task.get("created_at"),
                            "completed_at": task.get("completed_at"),
                            "duration": task.get("execution_time")
                        })
                    
                    # Sort by start time
                    timeline.sort(key=lambda x: x.get("started_at") or "")
                    
                    return {
                        "workflow_id": workflow_id,
                        "timeline": timeline,
                        "total_tasks": len(timeline)
                    }
                else:
                    return {"workflow_id": workflow_id, "timeline": [], "total_tasks": 0}
        except Exception as e:
            print(f"Error getting workflow timeline: {e}")
            return {"workflow_id": workflow_id, "timeline": [], "total_tasks": 0}

@router.get("/{workflow_id}/results")
async def get_workflow_results(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Get aggregated results for a workflow
    
    Args:
        workflow_id: Workflow identifier
    
    Returns:
        Workflow results including all task outputs
    """
    async with aiohttp.ClientSession() as session:
        try:
            # First try to get workflow status from API
            async with session.get(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}") as resp:
                if resp.status == 200:
                    workflow_data = await resp.json()
                    # Return the results if available
                    return {
                        "workflow_id": workflow_id,
                        "status": workflow_data.get("status"),
                        "results": workflow_data.get("results", {}),
                        "created_at": workflow_data.get("created_at"),
                        "completed_at": workflow_data.get("completed_at")
                    }
        except:
            pass
        
        # Fallback: Get tasks and build results from them
        try:
            params = {"workflow_id": workflow_id, "limit": 1000}
            async with session.get(f"{GLEITZEIT_API_URL}/tasks", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get("tasks", [])
                    
                    # Build results from task data
                    results = {}
                    workflow_status = "pending"
                    
                    for task in tasks:
                        task_id = task.get("task_id") or task.get("id")
                        results[task_id] = {
                            "status": task.get("status"),
                            "result": task.get("result"),
                            "error": task.get("error")
                        }
                        
                        # Update workflow status based on tasks
                        if task.get("status") == "failed":
                            workflow_status = "failed"
                        elif task.get("status") == "completed" and workflow_status != "failed":
                            workflow_status = "completed"
                        elif task.get("status") in ["running", "executing"] and workflow_status not in ["failed"]:
                            workflow_status = "running"
                    
                    return {
                        "workflow_id": workflow_id,
                        "status": workflow_status,
                        "results": results,
                        "total_tasks": len(tasks)
                    }
                else:
                    return {
                        "workflow_id": workflow_id,
                        "status": "unknown",
                        "results": {},
                        "total_tasks": 0
                    }
        except Exception as e:
            print(f"Error getting workflow results: {e}")
            return {
                "workflow_id": workflow_id,
                "status": "error",
                "results": {},
                "error": str(e)
            }


# New Workflow Control Endpoints

@router.post("/{workflow_id}/pause")
async def pause_workflow(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Pause a running workflow
    
    Args:
        workflow_id: Workflow to pause
    
    Returns:
        Pause result
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}/pause") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Update UI tracking
                    if workflow_id in _ui_workflows:
                        _ui_workflows[workflow_id]["status"] = "paused"
                    
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.post("/{workflow_id}/resume")
async def resume_workflow(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Resume a paused workflow
    
    Args:
        workflow_id: Workflow to resume
    
    Returns:
        Resume result
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}/resume") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Update UI tracking
                    if workflow_id in _ui_workflows:
                        _ui_workflows[workflow_id]["status"] = "running"
                    
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.post("/{workflow_id}/retry")
async def retry_workflow(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Retry all failed tasks in a workflow
    
    Args:
        workflow_id: Workflow to retry
    
    Returns:
        Retry result with retried task information
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}/retry") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Update UI tracking
                    if workflow_id in _ui_workflows:
                        _ui_workflows[workflow_id]["status"] = "running"
                    
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.get("/{workflow_id}/export")
async def export_workflow(request: Request, workflow_id: str, format: str = "json") -> Response:
    """
    Export workflow definition
    
    Args:
        workflow_id: Workflow to export
        format: Export format (json or yaml)
    
    Returns:
        Workflow definition in requested format
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{GLEITZEIT_API_URL}/workflows/{workflow_id}/export",
                params={"format": format}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if format == "yaml":
                        content = yaml.dump(data, default_flow_style=False)
                        return Response(content=content, media_type="text/yaml")
                    else:
                        return JSONResponse(content=data)
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.post("/{workflow_id}/clone")
async def clone_workflow(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Clone an existing workflow
    
    Args:
        workflow_id: Workflow to clone
    
    Returns:
        Information about the cloned workflow
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}/clone") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Track the new workflow in UI
                    new_workflow_id = data.get("new_workflow_id")
                    if new_workflow_id:
                        _ui_workflows[new_workflow_id] = {
                            "id": new_workflow_id,
                            "name": f"Clone of {workflow_id}",
                            "status": "pending",
                            "created_at": datetime.now().isoformat()
                        }
                    
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.get("/{workflow_id}/dependencies")
async def get_workflow_dependencies(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Get workflow dependency graph
    
    Args:
        workflow_id: Workflow identifier
    
    Returns:
        Dependency graph with nodes and edges
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}/dependencies") as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.get("/{workflow_id}/critical-path")
async def get_workflow_critical_path(request: Request, workflow_id: str) -> Dict[str, Any]:
    """
    Get workflow critical path analysis
    
    Args:
        workflow_id: Workflow identifier
    
    Returns:
        Critical path information
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/workflows/{workflow_id}/critical-path") as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Workflow not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")