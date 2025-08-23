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
    if not app_state.resource_manager:
        return JSONResponse(
            status_code=200,
            content={"message": "Resource management not enabled"}
        )
    
    result = {
        "resource_manager": {
            "id": app_state.resource_manager.manager_id,
            "running": app_state.resource_manager.running,
            "stats": app_state.resource_manager.stats
        },
        "hubs": {}
    }
    
    # Get hub information
    hubs = await app_state.resource_manager.get_hubs()
    for hub_name, hub in hubs.items():
        instances = await hub.list_instances()
        from gleitzeit.hub.base import ResourceStatus
        healthy_count = sum(1 for i in instances if i.status == ResourceStatus.HEALTHY)
        
        result["hubs"][hub_name] = {
            "hub_id": hub.hub_id,
            "resource_type": hub.resource_type.value,
            "total_instances": len(instances),
            "healthy_instances": healthy_count,
            "instances": [
                {
                    "id": inst.id,
                    "name": inst.name,
                    "status": inst.status.value,
                    "endpoint": inst.endpoint
                }
                for inst in instances
            ]
        }
        
        # Try to get metrics if available
        try:
            metrics_summary = await hub.get_metrics_summary()
            if metrics_summary:
                result["hubs"][hub_name]["metrics"] = metrics_summary
        except:
            pass
    
    # Get global metrics
    try:
        global_metrics = await app_state.resource_manager.get_global_metrics()
        result["global_metrics"] = global_metrics
    except:
        pass
    
    return JSONResponse(content=result)


@app.post("/workflows", response_model=WorkflowResponse)
async def submit_workflow(workflow: WorkflowRequest, background_tasks: BackgroundTasks):
    """Submit a workflow for execution"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Generate workflow ID
        workflow_id = f"api_workflow_{uuid.uuid4().hex[:8]}"
        
        # Create response immediately with "submitted" status
        response = WorkflowResponse(
            workflow_id=workflow_id,
            status="submitted",
            tasks_total=len(workflow.tasks),
            tasks_completed=0,
            tasks_failed=0,
            created_at=datetime.now(),
            completed_at=None
        )
        
        # Schedule workflow execution in background
        background_tasks.add_task(execute_workflow_via_client, workflow, workflow_id)
        
        return response
        
    except Exception as e:
        logger.error(f"Workflow submission failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def execute_workflow_via_client(workflow: WorkflowRequest, workflow_id: str):
    """Execute workflow via GleitzeitClient in background"""
    try:
        import tempfile
        import yaml
        
        # Convert API request to workflow dictionary with API workflow ID
        workflow_dict = {
            "id": workflow_id,  # Use the API workflow ID
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
        
        try:
            # Delegate to GleitzeitClient
            result = await app_state.client.run_workflow(temp_file_path)
            
            # The workflow ID should be the same in both API and client
            client_workflow_id = result.get("workflow_id")
            if client_workflow_id == workflow_id:
                logger.info(f"Workflow {workflow_id} completed successfully")
            else:
                logger.warning(f"Workflow ID mismatch: API={workflow_id}, Client={client_workflow_id}")
            
        except Exception as e:
            logger.error(f"Workflow {workflow_id} execution failed: {e}")
            
        finally:
            # Clean up temporary file
            import os
            try:
                os.unlink(temp_file_path)
            except:
                pass
                
    except Exception as e:
        logger.error(f"Background workflow execution failed: {e}")
    
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        if workflow.id in app_state.active_workflows:
            response = app_state.active_workflows[workflow.id]
            response.status = "failed"
            response.completed_at = datetime.now()


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
        # Get workflow tasks (this works even if get_workflow doesn't)
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        if not tasks:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Calculate status from tasks
        tasks_completed = sum(1 for t in tasks if t.status == "completed")
        tasks_failed = sum(1 for t in tasks if t.status == "failed")
        
        # Determine overall workflow status
        if tasks_failed > 0:
            status = "failed"
        elif tasks_completed == len(tasks) and len(tasks) > 0:
            status = "completed"
        elif any(t.status == "executing" for t in tasks):
            status = "running"
        else:
            status = "pending"
        
        # Get task results from the client's persistence
        results = {}
        for task in tasks:
            task_result = await app_state.client.get_task_result(task.id)
            if task_result:
                results[task.id] = {
                    "status": task_result.status,
                    "result": task_result.result if hasattr(task_result, 'result') else None,
                    "error": task_result.error if hasattr(task_result, 'error') else None
                }
        
        response = WorkflowResponse(
            workflow_id=workflow_id,
            status=status,
            tasks_total=len(tasks),
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            created_at=datetime.now(),  # We don't have workflow creation time
            completed_at=datetime.now() if status == "completed" else None,
            results=results
        )
        
        return response
        
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
    if task_id not in app_state.active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return app_state.active_tasks[task_id]


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
        
        return {"message": f"Task {task_id} deleted", "deleted": True}
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
            "message": f"Workflow {workflow_id} and all associated tasks deleted",
            "deleted": True,
            "tasks_deleted": len(tasks_to_remove)
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