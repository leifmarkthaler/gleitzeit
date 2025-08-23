"""
Task monitoring and management endpoints - proxies to Gleitzeit API
"""

from fastapi import APIRouter, Request, HTTPException
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import aiohttp

router = APIRouter()

# Get Gleitzeit API URL from environment or use default
GLEITZEIT_API_URL = os.getenv('GLEITZEIT_API_URL', 'http://localhost:8000')

# Track tasks submitted through this UI session
_ui_tasks = {}

@router.get("")
async def list_tasks(
    request: Request,
    status: Optional[str] = None,
    workflow_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List all tasks - now uses the API's list endpoint
    
    Args:
        status: Filter by status (running, completed, failed, pending)
        workflow_id: Filter by workflow ID
        limit: Maximum number of tasks to return
        offset: Pagination offset
    
    Returns:
        List of tasks with metadata
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
            if workflow_id:
                params["workflow_id"] = workflow_id
            
            # Get tasks from API list endpoint
            async with session.get(f"{GLEITZEIT_API_URL}/tasks", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Transform API response to UI format
                    tasks = []
                    for task in data.get("tasks", []):
                        tasks.append({
                            "id": task.get("task_id"),
                            "name": task.get("name", "Unnamed"),
                            "status": task.get("status", "unknown"),
                            "workflow_id": task.get("workflow_id"),
                            "created_at": task.get("created_at"),
                            "completed_at": task.get("completed_at"),
                            "execution_time": task.get("execution_time"),
                            "error": task.get("error")
                        })
                    return {
                        "tasks": tasks,
                        "total": data.get("total", 0),
                        "limit": limit,
                        "offset": offset
                    }
                else:
                    # API list endpoint not available, fallback to empty
                    return {
                        "tasks": [],
                        "total": 0,
                        "limit": limit,
                        "offset": offset
                    }
        except Exception as e:
            print(f"Error listing tasks: {e}")
            return {
                "tasks": [],
                "total": 0,
                "limit": limit,
                "offset": offset
            }

@router.get("/{task_id}")
async def get_task(request: Request, task_id: str) -> Dict[str, Any]:
    """
    Get detailed task information from API
    
    Args:
        task_id: Unique task identifier
    
    Returns:
        Task details including results and status
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/tasks/{task_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Task not found")
                else:
                    raise HTTPException(status_code=resp.status, detail="API error")
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")

@router.post("/execute")
async def execute_task(request: Request, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a single task via Gleitzeit API
    
    Args:
        task_data: Task definition
    
    Returns:
        Execution response with task ID
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Parse method to get protocol and method
            method_parts = task_data.get("method", "").split("/")
            if len(method_parts) >= 2:
                protocol = f"{method_parts[0]}/v1"
                method = "/".join(method_parts)
            else:
                protocol = "llm/v1"
                method = task_data.get("method", "llm/chat")
            
            # Convert to API format
            api_task = {
                "id": task_data.get("id"),
                "name": task_data.get("name", "UI Task"),
                "protocol": protocol,
                "method": method,
                "params": task_data.get("parameters", {}),
                "dependencies": task_data.get("dependencies", []),
                "priority": task_data.get("priority", "normal")
            }
            
            if "retry" in task_data:
                api_task["retry"] = task_data["retry"]
            
            # Submit to API
            async with session.post(
                f"{GLEITZEIT_API_URL}/tasks",
                json=api_task
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Track this task in UI
                    _ui_tasks[data["task_id"]] = {
                        "id": data["task_id"],
                        "name": api_task["name"],
                        "status": data["status"],
                        "created_at": data.get("created_at")
                    }
                    
                    return data
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=f"API error: {error_text}")
                    
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")

@router.delete("/{task_id}")
async def cancel_task(request: Request, task_id: str) -> Dict[str, Any]:
    """
    Cancel a running task via API
    
    Args:
        task_id: Task to cancel
    
    Returns:
        Cancellation result
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.delete(f"{GLEITZEIT_API_URL}/tasks/{task_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Update UI tracking
                    if task_id in _ui_tasks:
                        _ui_tasks[task_id]["status"] = "cancelled"
                    
                    return data
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail="Task not found")
                else:
                    raise HTTPException(status_code=resp.status, detail="API error")
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")

@router.get("/queue/status")
async def get_queue_status(request: Request) -> Dict[str, Any]:
    """
    Get task queue status from API
    
    Returns:
        Queue statistics and pending tasks
    """
    # The API doesn't have a queue status endpoint yet
    # Return basic stats based on tracked tasks
    pending_count = sum(1 for t in _ui_tasks.values() if t.get("status") == "pending")
    running_count = sum(1 for t in _ui_tasks.values() if t.get("status") == "running")
    completed_count = sum(1 for t in _ui_tasks.values() if t.get("status") == "completed")
    failed_count = sum(1 for t in _ui_tasks.values() if t.get("status") == "failed")
    
    return {
        "pending": pending_count,
        "running": running_count,
        "completed": completed_count,
        "failed": failed_count,
        "total": len(_ui_tasks),
        "queue_depth": pending_count + running_count
    }