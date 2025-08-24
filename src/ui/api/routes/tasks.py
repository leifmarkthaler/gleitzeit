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
                            "protocol": task.get("protocol"),
                            "method": task.get("method"),
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
    # Get real statistics from the API's queue status endpoint
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/tasks/queue/status") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Return the data directly from the API endpoint
                    return data
        except Exception as e:
            # Log the error for debugging
            print(f"Error fetching queue status: {e}")
    
    # Fallback to empty data if API is not available
    return {
        "timestamp": None,
        "statistics": {
            "total": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0
        },
        "engine_status": "unknown",
        "active_workers": 0,
        "queue_length": 0
    }

@router.get("/{task_id}/result")
async def get_task_result(request: Request, task_id: str) -> Dict[str, Any]:
    """
    Get the result of a specific task
    
    Args:
        task_id: Task identifier
    
    Returns:
        Task execution result
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Get task details from API
            async with session.get(f"{GLEITZEIT_API_URL}/tasks/{task_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "task_id": task_id,
                        "status": data.get("status"),
                        "result": data.get("result"),
                        "error": data.get("error"),
                        "completed_at": data.get("completed_at")
                    }
                elif resp.status == 404:
                    # Task might not be in API yet, check local tracking
                    if task_id in _ui_tasks:
                        task = _ui_tasks[task_id]
                        return {
                            "task_id": task_id,
                            "status": task.get("status", "pending"),
                            "result": task.get("result"),
                            "error": task.get("error")
                        }
                    raise HTTPException(status_code=404, detail="Task not found")
                else:
                    raise HTTPException(status_code=resp.status, detail="API error")
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")

@router.get("/{task_id}/logs")
async def get_task_logs(request: Request, task_id: str, tail: int = 50) -> Dict[str, Any]:
    """
    Get execution logs for a task
    
    Args:
        task_id: Task identifier
        tail: Number of recent log lines to return
    
    Returns:
        Task execution logs
    """
    # The API doesn't currently have a logs endpoint
    # For now, return a placeholder or fetch from result if available
    async with aiohttp.ClientSession() as session:
        try:
            # Try to get task details which might contain logs
            async with session.get(f"{GLEITZEIT_API_URL}/tasks/{task_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Extract any output or logs from the result
                    result = data.get("result", {})
                    logs = []
                    
                    if isinstance(result, dict):
                        # Check for output field
                        if "output" in result:
                            logs.append(f"[OUTPUT] {result['output']}")
                        # Check for logs field
                        if "logs" in result:
                            if isinstance(result["logs"], list):
                                logs.extend(result["logs"])
                            else:
                                logs.append(str(result["logs"]))
                        # Check for stdout/stderr
                        if "stdout" in result:
                            logs.append(f"[STDOUT] {result['stdout']}")
                        if "stderr" in result:
                            logs.append(f"[STDERR] {result['stderr']}")
                    
                    # If no logs found, add status message
                    if not logs:
                        logs.append(f"Task {task_id} - Status: {data.get('status', 'unknown')}")
                        if data.get("error"):
                            logs.append(f"Error: {data['error']}")
                    
                    # Limit to requested tail size
                    if len(logs) > tail:
                        logs = logs[-tail:]
                    
                    return {
                        "task_id": task_id,
                        "logs": logs,
                        "total_lines": len(logs),
                        "tail": tail
                    }
                elif resp.status == 404:
                    return {
                        "task_id": task_id,
                        "logs": [f"Task {task_id} not found"],
                        "total_lines": 1,
                        "tail": tail
                    }
                else:
                    return {
                        "task_id": task_id,
                        "logs": [f"Error fetching logs: HTTP {resp.status}"],
                        "total_lines": 1,
                        "tail": tail
                    }
        except Exception as e:
            return {
                "task_id": task_id,
                "logs": [f"Error fetching logs: {e}"],
                "total_lines": 1,
                "tail": tail
            }