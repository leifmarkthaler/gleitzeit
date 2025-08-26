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

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Query, Body, WebSocket
from fastapi.websockets import WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
import yaml
import json
import logging
import csv
import io
from datetime import timedelta

# Gleitzeit imports
from gleitzeit.core import Task, Workflow, Priority
from gleitzeit.core.models import RetryConfig
from gleitzeit.core.retry_manager import BackoffStrategy
from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow
from gleitzeit.core.log_collector import LogCollector, set_log_collector, get_log_collector
from gleitzeit.core.log_stream import LogStreamManager, set_log_stream_manager, get_log_stream_manager
from gleitzeit.core.logs import LogLevel, LogSource
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
    max_concurrent: int = Field(5, description="Maximum concurrent tasks")
    name: Optional[str] = Field(None, description="Batch job name")




class ChatRequest(BaseModel):
    """Request model for chat interaction"""
    message: str = Field(..., description="Message to send")
    model: str = Field("llama3.2:latest", description="Model to use")
    temperature: float = Field(0.7, description="Temperature for generation")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")


class TaskResponse(BaseModel):
    """Response model for task operations"""
    task_id: str
    name: Optional[str] = None
    status: str
    workflow_id: Optional[str] = None
    protocol: Optional[str] = None
    method: Optional[str] = None
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
        self.log_collector = None  # Log collection service
        self.log_stream_manager = None  # Real-time log streaming service


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
        from gleitzeit.core.execution_engine import ExecutionMode
        
        # Initialize GleitzeitClient in native mode to handle all the complexity
        app_state.client = GleitzeitClient(mode="native")
        await app_state.client.__aenter__()
        logger.info("GleitzeitClient initialized successfully")
        
        # Start the execution engine in event-driven mode
        # This allows it to process tasks as they are submitted
        if hasattr(app_state.client, '_execution_engine') and app_state.client._execution_engine:
            # Start the engine in a background task so it runs continuously
            asyncio.create_task(app_state.client._execution_engine.start(ExecutionMode.EVENT_DRIVEN))
            logger.info("Execution engine started in event-driven mode")
            
            # Initialize log collector with event bus and persistence
            event_bus = app_state.client._execution_engine.event_bus
            persistence = app_state.client._execution_engine.persistence
            
            # Check if we have Redis persistence
            redis_adapter = None
            if hasattr(persistence, '_adapters'):
                # Check if using hybrid adapter with Redis
                for adapter in persistence._adapters:
                    if hasattr(adapter, 'redis'):
                        redis_adapter = adapter
                        break
            elif hasattr(persistence, 'redis'):
                # Direct Redis adapter
                redis_adapter = persistence
            
            # Create and start log collector
            app_state.log_collector = LogCollector(
                event_bus=event_bus,
                persistence=persistence if not redis_adapter else None,
                redis_adapter=redis_adapter,
                enable_persistence=True,
                enable_streaming=True,
                prefer_redis=True  # Prefer Redis for logs when available
            )
            await app_state.log_collector.start()
            set_log_collector(app_state.log_collector)
            logger.info("LogCollector initialized and started")
            
            # Create and start log stream manager
            app_state.log_stream_manager = LogStreamManager(event_bus=event_bus)
            await app_state.log_stream_manager.start()
            set_log_stream_manager(app_state.log_stream_manager)
            logger.info("LogStreamManager initialized and started")
        
    except Exception as e:
        logger.error(f"System setup failed: {e}")
        raise


# Provider registration is now handled by GleitzeitClient
    


async def cleanup_system():
    """Clean up system resources"""
    # Stop log services
    if app_state.log_stream_manager:
        await app_state.log_stream_manager.stop()
    
    if app_state.log_collector:
        await app_state.log_collector.stop()
    
    # Clean up client
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
        
        # Get actual providers from execution engine if available
        providers = {}
        if hasattr(app_state.client, '_execution_engine') and app_state.client._execution_engine:
            engine = app_state.client._execution_engine
            if hasattr(engine, 'registry') and engine.registry:
                # The registry has providers dict and provider_instances dict
                if hasattr(engine.registry, 'providers'):
                    # Iterate through all registered providers
                    for provider_id, provider_info in engine.registry.providers.items():
                        # Get provider instance
                        provider_instance = engine.registry.provider_instances.get(provider_id)
                        if provider_instance:
                            provider_name = provider_instance.name if hasattr(provider_instance, 'name') else provider_id
                            provider_type = provider_instance.__class__.__name__
                            providers[provider_name] = {
                                "status": "healthy",
                                "type": provider_type,
                                "protocol": provider_info.protocol_id
                            }
                            # Check if it's an ollama provider
                            if 'ollama' in provider_type.lower():
                                providers[provider_name]["is_ollama"] = True
        
        # Add client as a provider if no other providers found
        if not providers:
            providers = {"client": {"status": "healthy", "type": "GleitzeitClient"}}
        
        # Determine persistence backend
        persistence_backend = "GleitzeitClient"
        if hasattr(app_state.client, '_execution_engine') and app_state.client._execution_engine:
            if hasattr(app_state.client._execution_engine, 'persistence'):
                persistence = app_state.client._execution_engine.persistence
                if persistence:
                    persistence_backend = persistence.__class__.__name__
        
        return SystemStatus(
            status="running",
            providers=providers,
            persistence_backend=persistence_backend, 
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
        # Create Workflow and Task objects directly
        workflow_id = f"workflow-{uuid.uuid4().hex[:8]}"
        
        # Create Task objects from the request
        tasks = []
        name_to_id_map = {}  # Map task names to their generated IDs
        
        # First pass: create tasks and build name-to-ID mapping
        for task_req in workflow.tasks:
            task_id = f"task_{uuid.uuid4().hex[:8]}"  # Always generate unique ID
            task_name = task_req.name  # Use the provided name
            
            # Store mapping for dependency resolution using task name
            # Also store by ID if it was provided (for backward compatibility)
            if task_name:
                name_to_id_map[task_name] = task_id
            if task_req.id:
                name_to_id_map[task_req.id] = task_id
            
            task = Task(
                id=task_id,
                name=task_name,
                protocol=task_req.protocol,
                method=task_req.method,
                params=task_req.params,
                dependencies=[],  # Will be resolved in second pass
                priority=Priority[task_req.priority.upper()] if task_req.priority else Priority.NORMAL,
                workflow_id=workflow_id,
                created_at=datetime.now()  # Add created_at for tasks too
            )
            
            # Add retry config - use provided or default from Gleitzeit config
            if task_req.retry:
                task.retry_config = RetryConfig(
                    max_attempts=task_req.retry.get("max_attempts", 3),
                    base_delay=task_req.retry.get("base_delay", 1.0),
                    backoff_strategy=BackoffStrategy[task_req.retry.get("backoff_strategy", "exponential").upper()]
                )
            else:
                # Use default retry config from Gleitzeit configuration
                task.retry_config = RetryConfig(
                    max_attempts=3,
                    base_delay=2.0,
                    max_delay=60.0,
                    backoff_strategy="exponential",
                    jitter=True
                )
            
            tasks.append(task)
        
        # Second pass: resolve dependencies (map task names to IDs)
        for i, task_req in enumerate(workflow.tasks):
            if task_req.dependencies:
                resolved_deps = []
                for dep_name in task_req.dependencies:
                    if dep_name in name_to_id_map:
                        resolved_deps.append(name_to_id_map[dep_name])
                    else:
                        # Keep original dependency if not found (for error reporting)
                        resolved_deps.append(dep_name)
                tasks[i].dependencies = resolved_deps
        
        # Create Workflow object with proper datetime
        workflow_obj = Workflow(
            id=workflow_id,
            name=workflow.name,
            description=workflow.description,
            tasks=tasks,
            metadata=workflow.metadata,
            created_at=datetime.now()
        )
        
        # Submit workflow to the execution engine through the client
        # The client in native mode has the execution engine
        if hasattr(app_state.client, '_execution_engine') and app_state.client._execution_engine:
            # Submit to execution engine which will handle persistence
            # Note: submit_workflow saves the workflow and tasks to persistence
            await app_state.client._execution_engine.submit_workflow(workflow_obj)
            
            # Don't execute immediately - let the engine handle it asynchronously
            # The execution engine will process tasks based on queue and dependencies
        else:
            # Fallback to run_workflow if execution engine not available
            import tempfile
            import yaml
            
            workflow_dict = {
                "name": workflow.name,
                "description": workflow.description,
                "tasks": [
                    {
                        "id": task.id,
                        "name": task.name,
                        "protocol": task.protocol,
                        "method": task.method,
                        "parameters": task.params,
                        "dependencies": task.dependencies,
                        "priority": task.priority.value
                    }
                    for task in tasks
                ],
                "metadata": workflow.metadata
            }
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                yaml.dump(workflow_dict, temp_file, default_flow_style=False)
                temp_file_path = temp_file.name
            
            # Submit workflow without waiting for completion (watch=False)
            result = await app_state.client.run_workflow(temp_file_path, watch=False)
            workflow_id = result.get("workflow_id", workflow_id)
            
            import os
            try:
                os.unlink(temp_file_path)
            except:
                pass
        
        # Create response
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
        # Get workflow status from persistence (QueueManager is authoritative source for workflow status)
        workflow = await app_state.client.get_workflow(workflow_id)
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Get workflow status from QueueManager via persistence
        status = str(workflow.status.value) if hasattr(workflow.status, 'value') else str(workflow.status)
        status = status.lower() if status else "pending"
        
        # Get tasks for the workflow
        result = await app_state.client.list_tasks(workflow_id=workflow_id)
        
        # Handle the response format from client
        if isinstance(result, dict) and "tasks" in result:
            tasks = result["tasks"]
        else:
            tasks = result if isinstance(result, list) else []
        
        # Calculate task counts from workflow object (more reliable)
        tasks_completed = len(workflow.completed_tasks) if hasattr(workflow, 'completed_tasks') else 0
        tasks_failed = len(workflow.failed_tasks) if hasattr(workflow, 'failed_tasks') else 0
        
        # Get task results from persistence
        results = {}
        for task in tasks:
            if hasattr(task, 'id'):
                # Get the most current task object from persistence for accurate status
                current_task = await app_state.client.get_task(task.id)
                task_result = await app_state.client.get_task_result(task.id)
                
                # Use the current task status if available, otherwise infer from result
                if current_task and hasattr(current_task, 'status'):
                    task_status = str(current_task.status.value) if hasattr(current_task.status, 'value') else str(current_task.status)
                elif task_result and task_result.result:
                    # If we have a result, the task is completed
                    task_status = "completed"
                else:
                    task_status = "pending"
                
                results[task.id] = {
                    "status": task_status,
                    "result": task_result.result if task_result else None,
                    "error": current_task.error_message if current_task and hasattr(current_task, 'error_message') else None
                }
        
        response = WorkflowResponse(
            workflow_id=workflow_id,
            status=status,
            tasks_total=len(tasks),
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            created_at=workflow.created_at if workflow and hasattr(workflow, 'created_at') else datetime.now(),
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
                    "protocol": getattr(task, 'protocol', None),
                    "method": getattr(task, 'method', None),
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
        
        # Get task result from persistence if available
        task_result = None
        if hasattr(app_state.client, '_persistence_adapter') and app_state.client._persistence_adapter:
            result = await app_state.client._persistence_adapter.get_task_result(task_id)
            if result and hasattr(result, 'result'):
                task_result = result.result
        
        # Convert to TaskResponse format, handling attribute access safely
        return TaskResponse(
            task_id=task.id,
            name=task.name if hasattr(task, 'name') else None,
            status=task.status.value if hasattr(task.status, 'value') else str(task.status),
            workflow_id=task.workflow_id if hasattr(task, 'workflow_id') else None,
            protocol=task.protocol if hasattr(task, 'protocol') else None,
            method=task.method if hasattr(task, 'method') else None,
            result=task_result,
            error=task.error_message if hasattr(task, 'error_message') else None,
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


@app.get("/tasks/queue/status")
async def get_queue_status():
    """Get queue status and statistics"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get queue statistics from client
        queue_stats = await app_state.client.get_queue_statistics()
        
        # Get task count by status
        task_counts = await app_state.client.get_task_statistics()
        
        # Build statistics
        statistics = {
            "total": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0
        }
        
        # Update from task counts
        for status, count in task_counts.items():
            status_str = status.lower() if isinstance(status, str) else str(status).lower()
            if status_str in statistics:
                statistics[status_str] = count
                statistics["total"] += count
            elif status_str == "executing":
                statistics["running"] = count
                statistics["total"] += count
        
        # Get execution engine status
        engine_status = "idle"
        active_workers = 0
        
        if queue_stats:
            # Extract info from queue statistics
            active_workers = queue_stats.get("active_tasks", 0)
            if active_workers > 0:
                engine_status = "running"
        
        return {
            "timestamp": datetime.now().isoformat(),
            "statistics": statistics,
            "engine_status": engine_status,
            "active_workers": active_workers,
            "queue_length": statistics["pending"]
        }
        
    except Exception as e:
        logger.error(f"Failed to get queue status: {e}")
        raise HTTPException(status_code=500, detail=str(e))



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
                "error": task.error_message if hasattr(task, 'error_message') else None
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
            "error": task.error_message if hasattr(task, 'error_message') else None,
            "completed_at": task.completed_at.isoformat() if hasattr(task, 'completed_at') and task.completed_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task result: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task result: {str(e)}")


@app.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, tail: int = 50, level: Optional[str] = None):
    """Get execution logs for a task"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # First try to get logs from the log collector (Redis/SQL)
        if app_state.log_collector and app_state.log_collector.log_redis:
            # Parse log level if provided
            log_level = None
            if level:
                try:
                    from gleitzeit.core.logs import LogLevel
                    log_level = LogLevel(level.lower())
                except:
                    pass
            
            # Get logs from Redis
            log_entries = await app_state.log_collector.log_redis.get_logs(
                task_id=task_id,
                level=log_level,
                limit=tail
            )
            
            # Format logs for response
            logs = []
            for entry in log_entries:
                timestamp = entry.get('timestamp', '')
                level_str = entry.get('level', 'info').upper()
                source = entry.get('source', 'unknown')
                message = entry.get('message', '')
                logs.append(f"[{timestamp}][{level_str}][{source}] {message}")
            
            if logs:
                return {
                    "task_id": task_id,
                    "logs": logs,
                    "total_lines": len(logs),
                    "tail": tail,
                    "backend": "redis"
                }
        
        # Fallback to getting logs from task result
        task = await app_state.client.get_task(task_id)
        
        if not task:
            return {
                "task_id": task_id,
                "logs": [f"Task {task_id} not found"],
                "total_lines": 1,
                "tail": tail,
                "backend": "none"
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
            if hasattr(task, 'error_message') and task.error_message:
                logs.append(f"Error: {task.error_message}")
        
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


# ============================================================================
# WebSocket Endpoints for Real-time Log Streaming
# ============================================================================

@app.websocket("/ws/logs/task/{task_id}")
async def stream_task_logs(websocket: WebSocket, task_id: str):
    """
    WebSocket endpoint for streaming task logs in real-time
    
    Connect to this endpoint to receive live log updates for a specific task.
    
    Message types sent:
    - log:subscribed - Confirmation of subscription
    - log:history - Historical logs (if any)
    - log:message - New log message
    - log:stream_start - Log streaming started
    - log:stream_end - Log streaming ended
    """
    await websocket.accept()
    
    if not app_state.log_stream_manager:
        await websocket.send_json({
            "type": "error",
            "message": "Log streaming not available"
        })
        await websocket.close()
        return
    
    try:
        # Subscribe to task logs
        stream_key = await app_state.log_stream_manager.subscribe(
            websocket=websocket,
            task_id=task_id,
            send_buffer=True
        )
        
        logger.info(f"WebSocket client subscribed to task logs: {task_id}")
        
        # Keep connection alive and handle ping/pong
        while True:
            try:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
                elif message == "unsubscribe":
                    break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning(f"Error in WebSocket message handling: {e}")
                break
    
    finally:
        # Unsubscribe on disconnect
        await app_state.log_stream_manager.unsubscribe(websocket)
        logger.info(f"WebSocket client unsubscribed from task logs: {task_id}")


@app.websocket("/ws/logs/workflow/{workflow_id}")
async def stream_workflow_logs(websocket: WebSocket, workflow_id: str):
    """
    WebSocket endpoint for streaming workflow logs in real-time
    
    Connect to this endpoint to receive live log updates for all tasks in a workflow.
    
    Message types sent:
    - log:subscribed - Confirmation of subscription
    - log:history - Historical logs (if any)
    - log:message - New log message
    - log:stream_start - Log streaming started for a task
    - log:stream_end - Log streaming ended for a task
    """
    await websocket.accept()
    
    if not app_state.log_stream_manager:
        await websocket.send_json({
            "type": "error",
            "message": "Log streaming not available"
        })
        await websocket.close()
        return
    
    try:
        # Subscribe to workflow logs
        stream_key = await app_state.log_stream_manager.subscribe(
            websocket=websocket,
            workflow_id=workflow_id,
            send_buffer=True
        )
        
        logger.info(f"WebSocket client subscribed to workflow logs: {workflow_id}")
        
        # Keep connection alive and handle ping/pong
        while True:
            try:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
                elif message == "unsubscribe":
                    break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning(f"Error in WebSocket message handling: {e}")
                break
    
    finally:
        # Unsubscribe on disconnect
        await app_state.log_stream_manager.unsubscribe(websocket)
        logger.info(f"WebSocket client unsubscribed from workflow logs: {workflow_id}")


@app.websocket("/ws/logs")
async def stream_all_logs(websocket: WebSocket, level: Optional[str] = None):
    """
    WebSocket endpoint for streaming all system logs
    
    Connect to this endpoint to receive all log messages from the system.
    
    Query parameters:
    - level: Minimum log level to stream (debug, info, warning, error, critical)
    
    Message types sent:
    - log:subscribed - Confirmation of subscription
    - log:message - New log message
    """
    await websocket.accept()
    
    if not app_state.log_stream_manager:
        await websocket.send_json({
            "type": "error",
            "message": "Log streaming not available"
        })
        await websocket.close()
        return
    
    try:
        # Parse log level filter
        filter_level = None
        if level:
            try:
                filter_level = LogLevel(level.lower())
            except ValueError:
                logger.warning(f"Invalid log level filter: {level}")
        
        # Subscribe to global logs
        stream_key = await app_state.log_stream_manager.subscribe(
            websocket=websocket,
            send_buffer=False,  # Don't send history for global stream
            filter_level=filter_level
        )
        
        logger.info(f"WebSocket client subscribed to global logs (level: {level})")
        
        # Keep connection alive and handle ping/pong
        while True:
            try:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
                elif message == "unsubscribe":
                    break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning(f"Error in WebSocket message handling: {e}")
                break
    
    finally:
        # Unsubscribe on disconnect
        await app_state.log_stream_manager.unsubscribe(websocket)
        logger.info("WebSocket client unsubscribed from global logs")


# ============================================================================
# Task Control Endpoints
# ============================================================================

@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a queued or pending task"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        success = await app_state.client.cancel_task(task_id)
        if success:
            return {"message": f"Task {task_id} cancelled successfully"}
        else:
            raise HTTPException(status_code=400, detail=f"Could not cancel task {task_id} - may be already executing or completed")
    except Exception as e:
        logger.error(f"Failed to cancel task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(e)}")

@app.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """Retry a failed task"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get the task
        task = await app_state.client.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        if task.status not in ["failed", "cancelled"]:
            raise HTTPException(status_code=400, detail=f"Task {task_id} is not in a retryable state (current: {task.status})")
        
        # Resubmit the task with the same parameters
        new_task = await app_state.client.submit_task(
            name=task.name,
            protocol=task.protocol,
            method=task.method,
            params=task.params,
            priority=task.priority if hasattr(task, 'priority') else Priority.NORMAL
        )
        
        return {
            "message": f"Task {task_id} retried",
            "new_task_id": new_task.id,
            "status": "submitted"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retry task: {str(e)}")

# ============================================================================
# Workflow Control Endpoints
# ============================================================================

@app.post("/workflows/{workflow_id}/pause")
async def pause_workflow(workflow_id: str):
    """Pause a running workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        workflow = await app_state.client.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        if workflow.status != "running":
            raise HTTPException(status_code=400, detail=f"Workflow {workflow_id} is not running (current: {workflow.status})")
        
        # Update workflow status to paused
        workflow.status = "paused"
        if app_state.client._persistence_adapter:
            await app_state.client._persistence_adapter.save_workflow(workflow)
        
        # Cancel all pending tasks in the workflow
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        cancelled = 0
        for task in tasks:
            if task.status in ["pending", "queued"]:
                if await app_state.client.cancel_task(task.id):
                    cancelled += 1
        
        return {
            "message": f"Workflow {workflow_id} paused",
            "cancelled_tasks": cancelled
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pause workflow: {str(e)}")

@app.post("/workflows/{workflow_id}/resume")
async def resume_workflow(workflow_id: str):
    """Resume a paused workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        workflow = await app_state.client.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        if workflow.status != "paused":
            raise HTTPException(status_code=400, detail=f"Workflow {workflow_id} is not paused (current: {workflow.status})")
        
        # Update workflow status to running
        workflow.status = "running"
        if app_state.client._persistence_adapter:
            await app_state.client._persistence_adapter.save_workflow(workflow)
        
        # Resubmit cancelled tasks
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        resubmitted = 0
        for task in tasks:
            if task.status == "cancelled":
                # Resubmit the task
                new_task = await app_state.client.submit_task(
                    name=task.name,
                    protocol=task.protocol,
                    method=task.method,
                    params=task.params,
                    priority=task.priority if hasattr(task, 'priority') else Priority.NORMAL
                )
                # Link to workflow
                new_task.workflow_id = workflow_id
                resubmitted += 1
        
        return {
            "message": f"Workflow {workflow_id} resumed",
            "resubmitted_tasks": resubmitted
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume workflow: {str(e)}")

@app.post("/workflows/{workflow_id}/retry")
async def retry_workflow(workflow_id: str):
    """Retry failed tasks in a workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        workflow = await app_state.client.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        # Get all failed tasks in the workflow
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        failed_tasks = [t for t in tasks if t.status == "failed"]
        
        if not failed_tasks:
            return {
                "message": f"No failed tasks to retry in workflow {workflow_id}",
                "retried_tasks": []
            }
        
        # Retry each failed task
        retried = []
        for task in failed_tasks:
            new_task = await app_state.client.submit_task(
                name=task.name,
                protocol=task.protocol,
                method=task.method,
                params=task.params,
                priority=task.priority if hasattr(task, 'priority') else Priority.NORMAL
            )
            # Link to workflow
            new_task.workflow_id = workflow_id
            retried.append({"old_task_id": task.id, "new_task_id": new_task.id})
        
        return {
            "message": f"Retried {len(retried)} failed tasks in workflow {workflow_id}",
            "retried_tasks": retried
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retry workflow: {str(e)}")

# ============================================================================
# Queue Management Endpoints
# ============================================================================

@app.get("/queues")
async def list_queues():
    """List all task queues and their status"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        stats = await app_state.client.get_queue_statistics()
        return stats
    except Exception as e:
        logger.error(f"Failed to get queue statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get queue statistics: {str(e)}")

@app.get("/queues/{queue_name}")
async def get_queue_details(queue_name: str):
    """Get detailed statistics for a specific queue"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        stats = await app_state.client.get_queue_statistics()
        if queue_name not in stats.get("queues", {}):
            raise HTTPException(status_code=404, detail=f"Queue {queue_name} not found")
        
        return stats["queues"][queue_name]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get queue details: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get queue details: {str(e)}")


# Advanced Queue Control Endpoints

@app.post("/queues/{queue_name}/pause")
async def pause_queue(queue_name: str):
    """Pause processing of a specific queue"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Check if queue exists
        stats = await app_state.client.get_queue_statistics()
        if queue_name not in stats.get("queues", {}):
            raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
        
        # Pause queue processing (this would need to be implemented in the queue manager)
        # For now, we'll return a message indicating this is a planned feature
        return {
            "message": f"Queue pause functionality is a planned feature",
            "queue": queue_name,
            "status": "not_implemented"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause queue: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pause queue: {str(e)}")


@app.post("/queues/{queue_name}/resume")
async def resume_queue(queue_name: str):
    """Resume processing of a paused queue"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Check if queue exists
        stats = await app_state.client.get_queue_statistics()
        if queue_name not in stats.get("queues", {}):
            raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
        
        # Resume queue processing (this would need to be implemented in the queue manager)
        return {
            "message": f"Queue resume functionality is a planned feature",
            "queue": queue_name,
            "status": "not_implemented"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume queue: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume queue: {str(e)}")


@app.post("/queues/{queue_name}/clear")
async def clear_queue(queue_name: str):
    """Clear all pending tasks from a queue"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Check if queue exists
        stats = await app_state.client.get_queue_statistics()
        if queue_name not in stats.get("queues", {}):
            raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
        
        # Get all pending tasks and cancel them
        tasks = await app_state.client.list_tasks(status="pending")
        cleared_count = 0
        
        for task in tasks:
            # Only cancel tasks in the specified queue (assuming default queue for now)
            if queue_name == "default":
                try:
                    await app_state.client.cancel_task(task["id"])
                    cleared_count += 1
                except Exception as e:
                    logger.warning(f"Failed to cancel task {task['id']}: {e}")
        
        return {
            "message": f"Cleared {cleared_count} tasks from queue '{queue_name}'",
            "queue": queue_name,
            "tasks_cleared": cleared_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear queue: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear queue: {str(e)}")


@app.put("/queues/{queue_name}/config")
async def update_queue_config(
    queue_name: str,
    max_size: Optional[int] = None,
    max_concurrent: Optional[int] = None,
    priority_mode: Optional[str] = None
):
    """Update queue configuration (size, concurrency, priority mode)"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Check if queue exists
        stats = await app_state.client.get_queue_statistics()
        if queue_name not in stats.get("queues", {}):
            raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
        
        # Queue configuration updates would need to be implemented in the queue manager
        config_updates = {}
        if max_size is not None:
            config_updates["max_size"] = max_size
        if max_concurrent is not None:
            config_updates["max_concurrent"] = max_concurrent
        if priority_mode is not None:
            config_updates["priority_mode"] = priority_mode
        
        return {
            "message": f"Queue configuration update is a planned feature",
            "queue": queue_name,
            "requested_updates": config_updates,
            "status": "not_implemented"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update queue config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update queue config: {str(e)}")


# ============================================================================
# System Statistics Endpoints
# ============================================================================

@app.get("/statistics/tasks")
async def get_task_statistics():
    """Get task execution statistics"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        stats = await app_state.client.get_task_statistics()
        return stats
    except Exception as e:
        logger.error(f"Failed to get task statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task statistics: {str(e)}")

@app.get("/statistics/system")
async def get_system_statistics():
    """Get overall system statistics"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        task_stats = await app_state.client.get_task_statistics()
        queue_stats = await app_state.client.get_queue_statistics()
        
        return {
            "tasks": task_stats,
            "queues": queue_stats,
            "uptime_seconds": (datetime.now() - app_state.start_time).total_seconds()
        }
    except Exception as e:
        logger.error(f"Failed to get system statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get system statistics: {str(e)}")

# ============================================================================
# Provider Management Endpoints  
# ============================================================================

@app.get("/providers/{provider_id}")
async def get_provider_details(provider_id: str):
    """Get details about a specific provider"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get provider from registry
        registry = app_state.client._registry if hasattr(app_state.client, '_registry') else None
        if not registry:
            raise HTTPException(status_code=503, detail="Provider registry not available")
        
        provider = registry.get_provider_instance(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")
        
        # Get provider info
        info = {
            "id": provider_id,
            "name": getattr(provider, 'name', provider_id),
            "protocol": getattr(provider, 'protocol_id', 'unknown'),
            "description": getattr(provider, 'description', ''),
            "capabilities": getattr(provider, 'capabilities', {}),
            "status": "active" if hasattr(provider, 'health_check') and await provider.health_check() else "unknown"
        }
        
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get provider details: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get provider details: {str(e)}")

@app.post("/providers/{provider_id}/health")
async def check_provider_health(provider_id: str):
    """Check health status of a provider"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        registry = app_state.client._registry if hasattr(app_state.client, '_registry') else None
        if not registry:
            raise HTTPException(status_code=503, detail="Provider registry not available")
        
        provider = registry.get_provider_instance(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")
        
        # Check health if method exists
        if hasattr(provider, 'health_check'):
            is_healthy = await provider.health_check()
            return {
                "provider_id": provider_id,
                "healthy": is_healthy,
                "status": "healthy" if is_healthy else "unhealthy",
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "provider_id": provider_id,
                "healthy": True,
                "status": "no_health_check",
                "message": "Provider does not implement health check",
                "timestamp": datetime.now().isoformat()
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check provider health: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check provider health: {str(e)}")

# ============================================================================
# Bulk Operations Endpoints
# ============================================================================

@app.post("/tasks/bulk/cancel")
async def bulk_cancel_tasks(task_ids: List[str] = Body(..., description="List of task IDs to cancel")):
    """Cancel multiple tasks at once"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    results = []
    for task_id in task_ids:
        try:
            success = await app_state.client.cancel_task(task_id)
            results.append({
                "task_id": task_id,
                "cancelled": success,
                "message": "Cancelled" if success else "Failed to cancel"
            })
        except Exception as e:
            results.append({
                "task_id": task_id,
                "cancelled": False,
                "error": str(e)
            })
    
    cancelled_count = sum(1 for r in results if r.get('cancelled'))
    return {
        "message": f"Cancelled {cancelled_count} out of {len(task_ids)} tasks",
        "results": results
    }

@app.post("/tasks/bulk/retry")
async def bulk_retry_tasks(task_ids: List[str] = Body(..., description="List of task IDs to retry")):
    """Retry multiple failed tasks at once"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    results = []
    for task_id in task_ids:
        try:
            # Get the task
            task = await app_state.client.get_task(task_id)
            if not task:
                results.append({
                    "task_id": task_id,
                    "retried": False,
                    "error": "Task not found"
                })
                continue
            
            if task.status not in ["failed", "cancelled"]:
                results.append({
                    "task_id": task_id,
                    "retried": False,
                    "error": f"Task not in retryable state (current: {task.status})"
                })
                continue
            
            # Resubmit the task
            new_task = await app_state.client.submit_task(
                name=task.name,
                protocol=task.protocol,
                method=task.method,
                params=task.params,
                priority=task.priority if hasattr(task, 'priority') else Priority.NORMAL
            )
            
            results.append({
                "task_id": task_id,
                "retried": True,
                "new_task_id": new_task.id
            })
        except Exception as e:
            results.append({
                "task_id": task_id,
                "retried": False,
                "error": str(e)
            })
    
    retried_count = sum(1 for r in results if r.get('retried'))
    return {
        "message": f"Retried {retried_count} out of {len(task_ids)} tasks",
        "results": results
    }

@app.get("/tasks/bulk/status")
async def bulk_task_status(task_ids: List[str] = Query(..., description="Task IDs to check")):
    """Get status of multiple tasks at once"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    results = {}
    for task_id in task_ids:
        try:
            task = await app_state.client.get_task(task_id)
            if task:
                results[task_id] = {
                    "status": task.status,
                    "name": task.name,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None
                }
            else:
                results[task_id] = {"status": "not_found"}
        except Exception as e:
            results[task_id] = {"status": "error", "error": str(e)}
    
    return results

@app.post("/workflows/bulk/cancel")
async def bulk_cancel_workflows(workflow_ids: List[str] = Body(..., description="List of workflow IDs to cancel")):
    """Cancel multiple workflows at once"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    results = []
    for workflow_id in workflow_ids:
        try:
            # Get workflow tasks and cancel them
            tasks = await app_state.client.get_workflow_tasks(workflow_id)
            cancelled = 0
            for task in tasks:
                if task.status in ["pending", "queued"]:
                    if await app_state.client.cancel_task(task.id):
                        cancelled += 1
            
            # Update workflow status
            workflow = await app_state.client.get_workflow(workflow_id)
            if workflow:
                workflow.status = "cancelled"
                if app_state.client._persistence_adapter:
                    await app_state.client._persistence_adapter.save_workflow(workflow)
            
            results.append({
                "workflow_id": workflow_id,
                "cancelled": True,
                "tasks_cancelled": cancelled
            })
        except Exception as e:
            results.append({
                "workflow_id": workflow_id,
                "cancelled": False,
                "error": str(e)
            })
    
    cancelled_count = sum(1 for r in results if r.get('cancelled'))
    return {
        "message": f"Cancelled {cancelled_count} out of {len(workflow_ids)} workflows",
        "results": results
    }

@app.delete("/workflows/bulk")
async def bulk_delete_workflows(
    workflow_ids: List[str] = Body(..., description="List of workflow IDs to delete"),
    only_completed: bool = Query(True, description="Only delete completed workflows")
):
    """Delete multiple workflows at once"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    results = []
    for workflow_id in workflow_ids:
        try:
            workflow = await app_state.client.get_workflow(workflow_id)
            if not workflow:
                results.append({
                    "workflow_id": workflow_id,
                    "deleted": False,
                    "error": "Workflow not found"
                })
                continue
            
            if only_completed and workflow.status not in ["completed", "failed", "cancelled"]:
                results.append({
                    "workflow_id": workflow_id,
                    "deleted": False,
                    "error": f"Workflow not completed (status: {workflow.status})"
                })
                continue
            
            success = await app_state.client.delete_workflow(workflow_id)
            results.append({
                "workflow_id": workflow_id,
                "deleted": success
            })
        except Exception as e:
            results.append({
                "workflow_id": workflow_id,
                "deleted": False,
                "error": str(e)
            })
    
    deleted_count = sum(1 for r in results if r.get('deleted'))
    return {
        "message": f"Deleted {deleted_count} out of {len(workflow_ids)} workflows",
        "results": results
    }

# ============================================================================
# Import/Export Endpoints
# ============================================================================

@app.get("/workflows/{workflow_id}/export")
async def export_workflow(workflow_id: str, format: str = Query("yaml", enum=["yaml", "json"])):
    """Export workflow definition as YAML or JSON"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        workflow = await app_state.client.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        # Get all tasks in the workflow
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        
        # Build workflow definition
        workflow_def = {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "tasks": [
                {
                    "id": task.id,
                    "name": task.name,
                    "protocol": task.protocol,
                    "method": task.method,
                    "params": task.params,
                    "dependencies": task.dependencies if hasattr(task, 'dependencies') else []
                }
                for task in tasks
            ]
        }
        
        if format == "yaml":
            content = yaml.dump(workflow_def, default_flow_style=False)
            return Response(content, media_type="application/x-yaml")
        else:
            return JSONResponse(workflow_def)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export workflow: {str(e)}")

@app.post("/workflows/{workflow_id}/clone")
async def clone_workflow(workflow_id: str, new_name: Optional[str] = None):
    """Clone an existing workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get original workflow
        workflow = await app_state.client.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        # Get all tasks
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        
        # Create new workflow with new ID
        new_workflow_id = str(uuid.uuid4())
        new_workflow = Workflow(
            id=new_workflow_id,
            name=new_name or f"{workflow.name} (Clone)",
            description=f"Clone of {workflow.name}",
            status="pending"
        )
        
        # Submit new workflow
        if app_state.client._persistence_adapter:
            await app_state.client._persistence_adapter.save_workflow(new_workflow)
        
        # Clone and submit tasks
        task_mapping = {}  # Map old task IDs to new ones
        new_tasks = []
        
        for task in tasks:
            new_task = await app_state.client.submit_task(
                name=task.name,
                protocol=task.protocol,
                method=task.method,
                params=task.params,
                priority=task.priority if hasattr(task, 'priority') else Priority.NORMAL
            )
            new_task.workflow_id = new_workflow_id
            task_mapping[task.id] = new_task.id
            new_tasks.append(new_task)
        
        return {
            "message": f"Cloned workflow {workflow_id}",
            "new_workflow_id": new_workflow_id,
            "tasks_cloned": len(new_tasks)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clone workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clone workflow: {str(e)}")

# ============================================================================
# Resource Management Endpoints
# ============================================================================

@app.get("/resources/limits")
async def get_resource_limits():
    """Get current resource limits"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get limits from execution engine if available
        engine = app_state.client._execution_engine if hasattr(app_state.client, '_execution_engine') else None
        
        limits = {
            "max_concurrent_tasks": engine.max_concurrent_tasks if engine else 10,
            "max_memory_mb": 512,  # From config
            "max_queue_size": 1000,
            "max_workflow_depth": 10
        }
        
        return limits
    except Exception as e:
        logger.error(f"Failed to get resource limits: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get resource limits: {str(e)}")

@app.get("/resources/usage")
async def get_resource_usage():
    """Get current resource usage statistics"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Get metrics from resource manager if available
        metrics = await app_state.client.get_resource_metrics() if hasattr(app_state.client, 'get_resource_metrics') else {}
        
        # Add system stats
        task_stats = await app_state.client.get_task_statistics()
        
        usage = {
            "active_tasks": task_stats.get('running', 0),
            "queued_tasks": task_stats.get('queued', 0),
            "memory_usage_mb": metrics.get('memory_usage_mb', 0),
            "cpu_usage_percent": metrics.get('cpu_usage', 0),
            "resource_pools": metrics.get('pools', {})
        }
        
        return usage
    except Exception as e:
        logger.error(f"Failed to get resource usage: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get resource usage: {str(e)}")

# ============================================================================
# Workflow Dependencies Endpoints
# ============================================================================

@app.get("/workflows/{workflow_id}/dependencies")
async def get_workflow_dependencies(workflow_id: str):
    """Get dependency graph for a workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        workflow = await app_state.client.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        
        # Build dependency graph
        graph = {
            "workflow_id": workflow_id,
            "nodes": [],
            "edges": []
        }
        
        for task in tasks:
            graph["nodes"].append({
                "id": task.id,
                "name": task.name,
                "status": task.status,
                "protocol": task.protocol
            })
            
            # Add edges for dependencies
            if hasattr(task, 'dependencies') and task.dependencies:
                for dep_id in task.dependencies:
                    graph["edges"].append({
                        "from": dep_id,
                        "to": task.id
                    })
        
        return graph
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workflow dependencies: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflow dependencies: {str(e)}")

@app.get("/workflows/{workflow_id}/critical-path")
async def get_workflow_critical_path(workflow_id: str):
    """Get the critical path through a workflow"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        workflow = await app_state.client.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        tasks = await app_state.client.get_workflow_tasks(workflow_id)
        
        # Simple critical path: tasks without dependencies to tasks with most dependencies
        # This is a simplified version - a real implementation would calculate actual paths
        critical_path = []
        
        # Find tasks without dependencies (start nodes)
        start_tasks = [t for t in tasks if not hasattr(t, 'dependencies') or not t.dependencies]
        
        # Find tasks that others depend on
        dependency_counts = {}
        for task in tasks:
            if hasattr(task, 'dependencies') and task.dependencies:
                for dep_id in task.dependencies:
                    dependency_counts[dep_id] = dependency_counts.get(dep_id, 0) + 1
        
        # Sort tasks by dependency count (simplified critical path)
        sorted_tasks = sorted(tasks, key=lambda t: dependency_counts.get(t.id, 0), reverse=True)
        
        for task in sorted_tasks[:5]:  # Top 5 critical tasks
            critical_path.append({
                "task_id": task.id,
                "name": task.name,
                "status": task.status,
                "dependents": dependency_counts.get(task.id, 0)
            })
        
        return {
            "workflow_id": workflow_id,
            "critical_path": critical_path,
            "total_tasks": len(tasks),
            "start_tasks": len(start_tasks)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get critical path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get critical path: {str(e)}")

# ============================================================================
# Data Management Endpoints
# ============================================================================

@app.delete("/cleanup")
async def cleanup_old_data(days: int = 30):
    """Clean up old data from the system"""
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        deleted = await app_state.client.cleanup_old_data(days)
        return {
            "message": f"Cleaned up data older than {days} days",
            "items_deleted": deleted
        }
    except Exception as e:
        logger.error(f"Failed to cleanup old data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup: {str(e)}")

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