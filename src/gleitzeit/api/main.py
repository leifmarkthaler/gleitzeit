"""
Gleitzeit REST API

FastAPI-based REST API for workflow orchestration with Gleitzeit.
Provides endpoints for workflow submission, task execution, monitoring, and batch processing.
"""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Query, Body
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import yaml
import json
import logging

# Gleitzeit imports
from gleitzeit.core import Task, Workflow, Priority
from gleitzeit.core.models import RetryConfig
from gleitzeit.core.retry_manager import BackoffStrategy
from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow
# Import GleitzeitClient at runtime to avoid circular imports
from gleitzeit.common.shutdown import unified_shutdown

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Pydantic models for API requests/responses
class TaskRequest(BaseModel):
    """Request model for task submission"""
    id: Optional[str] = Field(None, description="Task ID (auto-generated if not provided)")
    name: str = Field(..., description="Task name")
    protocol: str = Field(..., description="Protocol ID (e.g., 'llm/v1', 'python/v1')")
    method: str = Field(..., description="Method to call")
    params: Dict[str, Any] = Field(default_factory=dict, description="Method parameters")
    dependencies: List[str] = Field(default_factory=list, description="Task dependencies")
    priority: str = Field("normal", description="Task priority (low, normal, high, critical)")
    retry: Optional[Dict[str, Any]] = Field(None, description="Retry configuration")


class WorkflowRequest(BaseModel):
    """Request model for workflow submission"""
    name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    tasks: List[TaskRequest] = Field(..., description="List of tasks in the workflow")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Workflow metadata")


class BatchRequest(BaseModel):
    """Request model for batch processing"""
    directory: str = Field(..., description="Directory containing files to process")
    pattern: str = Field("*", description="File pattern to match")
    method: str = Field("llm/chat", description="Method to use for processing")
    prompt: str = Field(..., description="Prompt for each file")
    model: str = Field("llama3.2:latest", description="Model to use")




class ChatRequest(BaseModel):
    """Request model for chat interaction"""
    message: str = Field(..., description="Message to send")
    model: str = Field("llama3.2:latest", description="Model to use")
    temperature: float = Field(0.7, description="Temperature for generation")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")


class TaskResponse(BaseModel):
    """Response model for task operations"""
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class WorkflowResponse(BaseModel):
    """Response model for workflow operations"""
    workflow_id: str
    status: str
    tasks_total: int
    tasks_completed: int
    tasks_failed: int
    results: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    completed_at: Optional[datetime] = None


class SystemStatus(BaseModel):
    """System status response"""
    status: str
    version: str = "0.0.5"
    providers: Dict[str, Dict[str, Any]]
    persistence_backend: str
    task_statistics: Dict[str, int]
    uptime_seconds: float


# Global application state
class AppState:
    """Application state container - holds GleitzeitClient and temporary tracking"""
    def __init__(self):
        self.client = None  # Will be GleitzeitClient instance
        self.start_time = datetime.now()
        self.active_tasks = {}  # Track active tasks by ID
        self.active_workflows = {}  # Track active workflows by ID


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Gleitzeit API...")
    await setup_system()
    yield
    # Shutdown
    logger.info("Shutting down Gleitzeit API...")
    await cleanup_system()


# Create FastAPI app
app = FastAPI(
    title="Gleitzeit API",
    description="REST API for Gleitzeit workflow orchestration system",
    version="0.0.5",
    lifespan=lifespan
)


async def setup_system():
    """Initialize the Gleitzeit system using GleitzeitClient"""
    try:
        # Import GleitzeitClient here to avoid circular imports
        from gleitzeit.client import GleitzeitClient
        
        # Initialize GleitzeitClient in native mode to handle all the complexity
        app_state.client = GleitzeitClient(mode="native")
        await app_state.client.__aenter__()
        logger.info("GleitzeitClient initialized successfully")
        
    except Exception as e:
        logger.error(f"System setup failed: {e}")
        raise


# Provider registration is now handled by GleitzeitClient
    


async def cleanup_system():
    """Clean up system resources"""
    if app_state.client:
        await app_state.client.__aexit__(None, None, None)


# API Endpoints

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Gleitzeit API",
        "version": "0.0.5",
        "status": "running",
        "documentation": "/docs"
    }


@app.get("/status", response_model=SystemStatus)
async def get_status():
    """Get system status"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get available statistics from client
        task_stats = await app_state.client.get_task_statistics()
        uptime = (datetime.now() - app_state.start_time).total_seconds()
        
        return SystemStatus(
            status="running",
            providers={"client": {"status": "healthy", "type": "GleitzeitClient"}},
            persistence_backend="GleitzeitClient", 
            task_statistics=task_stats,
            uptime_seconds=uptime
        )
    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        raise HTTPException(status_code=503, detail="Failed to get status")


@app.get("/resources")
async def get_resources_status():
    """Get resource manager and hub status"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Try to get resource information from client if available
        if hasattr(app_state.client, 'get_resources'):
            resources = await app_state.client.get_resources()
            return JSONResponse(content=resources)
        else:
            # Fallback to basic response if client doesn't have this method
            return JSONResponse(
                status_code=200,
                content={
                    "message": "Resource management not enabled",
                    "resource_manager": None,
                    "hubs": {}
                }
            )
    except Exception as e:
        logger.error(f"Failed to get resources: {e}")
        return JSONResponse(
            status_code=200,
            content={
                "message": "Resource information not available",
                "resource_manager": None,
                "hubs": {},
                "error": str(e)
            }
        )


@app.post("/workflows", response_model=WorkflowResponse)
async def submit_workflow(workflow: WorkflowRequest):
    """Submit a workflow for execution"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Schedule workflow execution in background and get the client-generated ID
        # We'll store the workflow request and process it
        import tempfile
        import yaml
        
        # Convert API request to workflow dictionary
        workflow_dict = {
            "name": workflow.name,
            "description": workflow.description,
            "tasks": [
                {
                    "id": task.id or f"task_{uuid.uuid4().hex[:8]}",
                    "name": task.name,
                    "protocol": task.protocol,
                    "method": task.method,
                    "parameters": task.params,
                    "dependencies": task.dependencies,
                    "priority": task.priority,
                    **({"retry": task.retry} if task.retry else {})
                }
                for task in workflow.tasks
            ],
            "metadata": workflow.metadata
        }
        
        # Create temporary YAML file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
            yaml.dump(workflow_dict, temp_file, default_flow_style=False)
            temp_file_path = temp_file.name
        
        # Submit to client and get the client-generated workflow ID
        result = await app_state.client.run_workflow(temp_file_path)
        workflow_id = result.get("workflow_id")
        
        # Clean up temp file
        import os
        try:
            os.unlink(temp_file_path)
        except:
            pass
        
        # Create response with the client's workflow ID
        response = WorkflowResponse(
            workflow_id=workflow_id,
            status="submitted",
            tasks_total=len(workflow.tasks),
            tasks_completed=0,
            tasks_failed=0,
            created_at=datetime.now(),
            completed_at=None
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Workflow submission failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@app.get("/workflows")
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, le=100, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip")
):
    """List all workflows with optional filtering"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Use GleitzeitClient list_workflows method
        result = await app_state.client.list_workflows(
            status=status,
            limit=limit,
            offset=offset
        )
        return {
            "workflows": result.get("workflows", []),
            "total": result.get("total", 0),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Failed to list workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow_status(workflow_id: str):
    """Get workflow status"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Try to get workflow from client first
        workflow = await app_state.client.get_workflow(workflow_id)
        
        if workflow:
            # Build response from workflow object
            response = WorkflowResponse(
                workflow_id=workflow_id,
                status=workflow.status.value if hasattr(workflow.status, 'value') else str(workflow.status),
                tasks_total=workflow.tasks_total if hasattr(workflow, 'tasks_total') else 0,
                tasks_completed=workflow.tasks_completed if hasattr(workflow, 'tasks_completed') else 0,
                tasks_failed=workflow.tasks_failed if hasattr(workflow, 'tasks_failed') else 0,
                created_at=workflow.created_at if hasattr(workflow, 'created_at') else datetime.now(),
                completed_at=workflow.completed_at if hasattr(workflow, 'completed_at') else None,
                results=workflow.results if hasattr(workflow, 'results') else {}
            )
            return response
        
        # Fallback: Try to get tasks for this workflow ID
        result = await app_state.client.list_tasks(workflow_id=workflow_id)
        
        # Handle the response format from client
        if isinstance(result, dict) and "tasks" in result:
            tasks = result["tasks"]
        else:
            tasks = result if isinstance(result, list) else []
        
        if not tasks:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Calculate status from tasks
        tasks_completed = sum(1 for t in tasks if hasattr(t, 'status') and str(t.status) == "completed")
        tasks_failed = sum(1 for t in tasks if hasattr(t, 'status') and str(t.status) == "failed")
        
        # Determine overall workflow status
        if tasks_failed > 0:
            status = "failed"
        elif tasks_completed == len(tasks) and len(tasks) > 0:
            status = "completed"
        elif any(hasattr(t, 'status') and str(t.status) in ["executing", "running"] for t in tasks):
            status = "running"
        else:
            status = "pending"
        
        # Get task results from the tasks
        results = {}
        for task in tasks:
            if hasattr(task, 'id'):
                results[task.id] = {
                    "status": str(task.status) if hasattr(task, 'status') else "unknown",
                    "result": task.result if hasattr(task, 'result') else None,
                    "error": task.error if hasattr(task, 'error') else None
                }
        
        response = WorkflowResponse(
            workflow_id=workflow_id,
            status=status,
            tasks_total=len(tasks),
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            created_at=datetime.now(),
            completed_at=datetime.now() if status == "completed" else None,
            results=results
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/workflows/upload")
async def upload_workflow(file: UploadFile = File(...), execute: bool = Query(True)):
    """Upload and execute a workflow file"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    # Save uploaded file temporarily
    content = await file.read()
    temp_path = Path(f"/tmp/{file.filename}")
    temp_path.write_bytes(content)
    
    try:
        if execute:
            # Use client to run the workflow
            result = await app_state.client.run_workflow(str(temp_path))
            
            return {
                "workflow_id": result.get("workflow_id"),
                "status": result.get("status", "submitted"),
                "message": "Workflow uploaded and executed"
            }
        else:
            # Load and validate workflow
            workflow = load_workflow_from_file(str(temp_path))
            validation_errors = validate_workflow(workflow)
            if validation_errors:
                raise HTTPException(status_code=400, detail={"errors": validation_errors})
            
            # Just validate and return
            return {
                "workflow_id": workflow.id,
                "status": "validated",
                "name": workflow.name,
                "tasks": len(workflow.tasks),
                "valid": True
            }
    
    finally:
        # Clean up temp file
        temp_path.unlink(missing_ok=True)


@app.post("/tasks", response_model=TaskResponse)
async def execute_task(task: TaskRequest, background_tasks: BackgroundTasks):
    """Execute a single task"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    # Submit task to client immediately - let it generate the ID
    try:
        submitted_task = await app_state.client.submit_task(
            name=task.name,
            protocol=task.protocol,
            method=task.method,
            params=task.params,
            priority=Priority[task.priority.upper()]
        )
        
        # Create response with the actual task ID from client
        response = TaskResponse(
            task_id=submitted_task.id,
            status="submitted",
            created_at=datetime.now()
        )
        
        app_state.active_tasks[submitted_task.id] = response
        
        # Execute in background
        background_tasks.add_task(execute_task_background, submitted_task.id)
        
        return response
    except Exception as e:
        logger.error(f"Failed to submit task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit task: {str(e)}")


async def execute_task_background(task_id: str):
    """Monitor task execution in background"""
    try:
        # Wait for task completion
        task_result = await app_state.client.wait_for_task(task_id, timeout=300)
        
        # Update the response
        if task_id in app_state.active_tasks:
            response = app_state.active_tasks[task_id]
            
            if task_result:
                response.status = task_result.status
                response.result = task_result.result
                response.error = task_result.error
                response.completed_at = datetime.now()
            else:
                response.status = "failed"
                response.error = "No result returned"
                response.completed_at = datetime.now()
    
    except Exception as e:
        logger.error(f"Task execution failed: {e}")
        if task.id in app_state.active_tasks:
            response = app_state.active_tasks[task.id]
            response.status = "failed"
            response.error = str(e)
            response.completed_at = datetime.now()


@app.get("/tasks")
async def list_tasks(
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, le=500, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip")
):
    """List all tasks with optional filtering"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Use GleitzeitClient list_tasks method
        result = await app_state.client.list_tasks(
            status=status,
            workflow_id=workflow_id,
            limit=limit,
            offset=offset
        )
        
        # Transform task objects to JSON-serializable format if needed
        tasks = []
        for task in result.get("tasks", []):
            if hasattr(task, 'id'):  # Task object
                tasks.append({
                    "task_id": task.id,
                    "name": task.name,
                    "status": task.status,
                    "workflow_id": getattr(task, 'workflow_id', None),
                    "created_at": task.created_at.isoformat() if hasattr(task, 'created_at') and task.created_at else None,
                    "completed_at": task.completed_at.isoformat() if hasattr(task, 'completed_at') and task.completed_at else None,
                    "execution_time": (task.completed_at - task.created_at).total_seconds() if hasattr(task, 'created_at') and task.created_at and hasattr(task, 'completed_at') and task.completed_at else None,
                    "error": getattr(task, 'error', None)
                })
            else:  # Already a dict
                tasks.append(task)
        
        return {
            "tasks": tasks,
            "total": result.get("total", 0),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """Get task status"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get task from client
        task = await app_state.client.get_task(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Convert to TaskResponse format, handling attribute access safely
        return TaskResponse(
            task_id=task.id,
            status=task.status.value if hasattr(task.status, 'value') else str(task.status),
            result=task.result if hasattr(task, 'result') else None,
            error=task.error if hasattr(task, 'error') else None,
            created_at=task.created_at if hasattr(task, 'created_at') else datetime.now(),
            completed_at=task.completed_at if hasattr(task, 'completed_at') else None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task from persistence"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Use the client to delete the task
        deleted = await app_state.client.delete_task(task_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Remove from active tasks if present
        app_state.active_tasks.pop(task_id, None)
        
        return {"success": True, "message": "Task deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete task: {str(e)}")



@app.post("/chat")
async def chat(request: ChatRequest):
    """Chat with LLM"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Use client's chat method
        response = await app_state.client.chat(
            message=request.message,
            model=request.model,
            temperature=request.temperature,
            session_id=request.session_id
        )
        
        return {
            "status": "success",
            "response": response,
            "model": request.model,
            "session_id": request.session_id
        }
    except Exception as e:
        logger.error(f"Chat failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat failed: {str(e)}"
        )


@app.post("/batch")
async def batch_process(request: BatchRequest):
    """Process files in batch"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Use client's batch_process method
        result = await app_state.client.batch_process(
            directory=request.directory,
            pattern=request.pattern,
            method=request.method,
            prompt=request.prompt,
            model=request.model,
            max_concurrent=request.max_concurrent,
            name=request.name
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# These endpoints would need direct access to registry, which client doesn't expose
# Commenting out for now as API should be a thin layer over client
# @app.get("/providers")
# @app.get("/protocols")


# Template endpoint would need direct execution_engine access
# Commenting out for now as API should be a thin layer over client
# @app.post("/templates/{template_type}")


@app.get("/workflows/{workflow_id}/tasks")
async def get_workflow_tasks(workflow_id: str, limit: int = 1000, offset: int = 0):
    """Get all tasks for a specific workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get tasks filtered by workflow_id
        result = await app_state.client.list_tasks(
            workflow_id=workflow_id,
            limit=limit,
            offset=offset
        )
        
        # Handle the response format from client
        if isinstance(result, dict) and "tasks" in result:
            tasks = result["tasks"]
            total = result.get("total", len(tasks))
        else:
            tasks = result if isinstance(result, list) else []
            total = len(tasks)
        
        return {
            "workflow_id": workflow_id,
            "tasks": tasks,
            "total": total
        }
    except Exception as e:
        logger.error(f"Failed to get workflow tasks: {e}")
        return {
            "workflow_id": workflow_id,
            "tasks": [],
            "total": 0
        }


@app.get("/workflows/{workflow_id}/timeline")
async def get_workflow_timeline(workflow_id: str):
    """Get execution timeline for a workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get tasks for this workflow
        result = await app_state.client.list_tasks(workflow_id=workflow_id, limit=1000)
        
        # Handle the response format from client
        if isinstance(result, dict) and "tasks" in result:
            tasks = result["tasks"]
        else:
            tasks = result if isinstance(result, list) else []
        
        # Build timeline from task data
        timeline = []
        for task in tasks:
            timeline.append({
                "task_id": task.id,
                "name": task.name,
                "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                "started_at": task.created_at.isoformat() if task.created_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "duration": task.execution_time
            })
        
        # Sort by start time
        timeline.sort(key=lambda x: x.get("started_at") or "")
        
        return {
            "workflow_id": workflow_id,
            "timeline": timeline,
            "total_tasks": len(timeline)
        }
    except Exception as e:
        logger.error(f"Failed to get workflow timeline: {e}")
        return {
            "workflow_id": workflow_id,
            "timeline": [],
            "total_tasks": 0
        }


@app.get("/workflows/{workflow_id}/results")
async def get_workflow_results(workflow_id: str):
    """Get aggregated results for a workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Try to get workflow from client
        workflow = await app_state.client.get_workflow(workflow_id)
        
        if workflow:
            return {
                "workflow_id": workflow_id,
                "status": workflow.status.value if hasattr(workflow.status, 'value') else str(workflow.status),
                "results": workflow.results if hasattr(workflow, 'results') else {},
                "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
                "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None
            }
        
        # Fallback: Get tasks and build results from them
        result = await app_state.client.list_tasks(workflow_id=workflow_id, limit=1000)
        
        # Handle the response format from client
        if isinstance(result, dict) and "tasks" in result:
            tasks = result["tasks"]
        else:
            tasks = result if isinstance(result, list) else []
        
        # Build results from task data
        results = {}
        workflow_status = "pending"
        
        for task in tasks:
            results[task.id] = {
                "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                "result": task.result,
                "error": task.error
            }
            
            # Update workflow status based on tasks
            task_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
            if task_status == "failed":
                workflow_status = "failed"
            elif task_status == "completed" and workflow_status != "failed":
                workflow_status = "completed"
            elif task_status in ["running", "executing"] and workflow_status not in ["failed"]:
                workflow_status = "running"
        
        return {
            "workflow_id": workflow_id,
            "status": workflow_status,
            "results": results,
            "total_tasks": len(tasks)
        }
    except Exception as e:
        logger.error(f"Failed to get workflow results: {e}")
        return {
            "workflow_id": workflow_id,
            "status": "error",
            "results": {},
            "error": str(e)
        }


@app.get("/tasks/{task_id}/result")
async def get_task_result(task_id: str):
    """Get the result of a specific task"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get task details from client
        task = await app_state.client.get_task(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return {
            "task_id": task_id,
            "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
            "result": task.result if hasattr(task, 'result') else None,
            "error": task.error if hasattr(task, 'error') else None,
            "completed_at": task.completed_at.isoformat() if hasattr(task, 'completed_at') and task.completed_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task result: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task result: {str(e)}")


@app.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, tail: int = 50):
    """Get execution logs for a task"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get task details from client
        task = await app_state.client.get_task(task_id)
        
        if not task:
            return {
                "task_id": task_id,
                "logs": [f"Task {task_id} not found"],
                "total_lines": 1,
                "tail": tail
            }
        
        # Extract logs from task result if available
        logs = []
        
        if hasattr(task, 'result') and task.result and isinstance(task.result, dict):
            # Check for output field
            if "output" in task.result:
                logs.append(f"[OUTPUT] {task.result['output']}")
            # Check for logs field
            if "logs" in task.result:
                if isinstance(task.result["logs"], list):
                    logs.extend(task.result["logs"])
                else:
                    logs.append(str(task.result["logs"]))
            # Check for stdout/stderr
            if "stdout" in task.result:
                logs.append(f"[STDOUT] {task.result['stdout']}")
            if "stderr" in task.result:
                logs.append(f"[STDERR] {task.result['stderr']}")
        
        # If no logs found, add status message
        if not logs:
            status = task.status.value if hasattr(task, 'status') and hasattr(task.status, 'value') else str(task.status) if hasattr(task, 'status') else 'unknown'
            logs.append(f"Task {task_id} - Status: {status}")
            if hasattr(task, 'error') and task.error:
                logs.append(f"Error: {task.error}")
        
        # Limit to requested tail size
        if len(logs) > tail:
            logs = logs[-tail:]
        
        return {
            "task_id": task_id,
            "logs": logs,
            "total_lines": len(logs),
            "tail": tail
        }
    except Exception as e:
        logger.error(f"Failed to get task logs: {e}")
        return {
            "task_id": task_id,
            "logs": [f"Error fetching logs: {e}"],
            "total_lines": 1,
            "tail": tail
        }


@app.get("/providers")
async def list_providers():
    """List all registered providers"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get providers from client if available
        if hasattr(app_state.client, 'list_providers'):
            providers = await app_state.client.list_providers()
            return {"providers": providers}
        else:
            # Fallback to empty list
            return {"providers": []}
    except Exception as e:
        logger.error(f"Failed to list providers: {e}")
        return {"providers": [], "error": str(e)}


@app.get("/protocols")
async def list_protocols():
    """List all registered protocols"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get protocols from client if available
        if hasattr(app_state.client, 'list_protocols'):
            protocols = await app_state.client.list_protocols()
            return {"protocols": protocols}
        else:
            # Fallback to basic protocols
            return {
                "protocols": [
                    {"name": "llm/v1", "description": "Language Model Protocol"},
                    {"name": "exec/v1", "description": "Command Execution Protocol"},
                    {"name": "http/v1", "description": "HTTP Request Protocol"}
                ]
            }
    except Exception as e:
        logger.error(f"Failed to list protocols: {e}")
        return {"protocols": [], "error": str(e)}


@app.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow and all its associated tasks from persistence"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Use the client to delete the workflow (will also delete all associated tasks)
        deleted = await app_state.client.delete_workflow(workflow_id)
        
        if not deleted:
            # Return 404 if workflow wasn't found
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Remove from active workflows if present
        app_state.active_workflows.pop(workflow_id, None)
        
        # Remove all tasks associated with this workflow from active tasks
        tasks_to_remove = []
        for task_id, task in app_state.active_tasks.items():
            if hasattr(task, 'workflow_id') and task.workflow_id == workflow_id:
                tasks_to_remove.append(task_id)
        
        for task_id in tasks_to_remove:
            app_state.active_tasks.pop(task_id, None)
        
        return {
            "success": True,
            "message": "Workflow deleted successfully"
        }
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Failed to delete workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete workflow: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)