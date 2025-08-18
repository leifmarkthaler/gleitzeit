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
from gleitzeit.core import Task, Workflow, Priority, ExecutionEngine, ExecutionMode
from gleitzeit.core.models import RetryConfig
from gleitzeit.core.retry_manager import BackoffStrategy
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.providers.template_provider import TemplateProvider
from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1, TEMPLATE_PROTOCOL_V1
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.batch_processor import BatchProcessor
from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow

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


class ExecuteCodeRequest(BaseModel):
    """Request model for direct code execution"""
    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(30, description="Execution timeout in seconds")


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
    """Application state container"""
    def __init__(self):
        self.execution_engine: Optional[ExecutionEngine] = None
        self.persistence_backend = None
        self.registry: Optional[ProtocolProviderRegistry] = None
        self.batch_processor: Optional[BatchProcessor] = None
        self.active_workflows: Dict[str, WorkflowResponse] = {}
        self.active_tasks: Dict[str, TaskResponse] = {}
        self.start_time = datetime.now()


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
    """Initialize the Gleitzeit system"""
    try:
        # Initialize persistence
        app_state.persistence_backend = await PersistenceFactory.create()
        logger.info(f"Persistence initialized: {type(app_state.persistence_backend).__name__}")
        
        # Setup execution components
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        app_state.registry = ProtocolProviderRegistry()
        
        app_state.execution_engine = ExecutionEngine(
            registry=app_state.registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=app_state.persistence_backend,
            max_concurrent_tasks=5
        )
        
        # Register protocols and providers
        await register_providers()
        
        # Initialize batch processor
        app_state.batch_processor = BatchProcessor()
        
        logger.info("System setup complete")
        
    except Exception as e:
        logger.error(f"System setup failed: {e}")
        raise


async def register_providers():
    """Register all protocol providers"""
    registry = app_state.registry
    
    # Python provider
    try:
        registry.register_protocol(PYTHON_PROTOCOL_V1)
        python_provider = PythonProvider("api-python-provider", allow_local=True)
        await python_provider.initialize()
        registry.register_provider("api-python-provider", "python/v1", python_provider)
        logger.info("Python provider registered")
    except Exception as e:
        logger.warning(f"Python provider registration failed: {e}")
    
    # Ollama provider
    try:
        registry.register_protocol(LLM_PROTOCOL_V1)
        ollama_provider = OllamaProvider("api-ollama-provider", auto_discover=False)
        await ollama_provider.initialize()
        registry.register_provider("api-ollama-provider", "llm/v1", ollama_provider)
        logger.info("Ollama provider registered")
    except Exception as e:
        logger.warning(f"Ollama provider registration failed: {e}")
    
    # MCP provider
    try:
        registry.register_protocol(MCP_PROTOCOL_V1)
        mcp_provider = SimpleMCPProvider("api-mcp-provider")
        await mcp_provider.initialize()
        registry.register_provider("api-mcp-provider", "mcp/v1", mcp_provider)
        logger.info("MCP provider registered")
    except Exception as e:
        logger.warning(f"MCP provider registration failed: {e}")
    
    # Template provider
    try:
        registry.register_protocol(TEMPLATE_PROTOCOL_V1)
        template_provider = TemplateProvider("api-template-provider", execution_engine=app_state.execution_engine)
        await template_provider.initialize()
        registry.register_provider("api-template-provider", "template/v1", template_provider)
        logger.info("Template provider registered")
    except Exception as e:
        logger.warning(f"Template provider registration failed: {e}")


async def cleanup_system():
    """Clean up system resources"""
    if app_state.execution_engine and app_state.registry:
        for provider_id, provider in app_state.registry.provider_instances.items():
            if hasattr(provider, 'shutdown'):
                await provider.shutdown()
    
    if app_state.persistence_backend:
        await app_state.persistence_backend.shutdown()


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
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    # Get provider status
    providers = {}
    for provider_id, provider_instance in app_state.registry.provider_instances.items():
        providers[provider_id] = {
            "protocol": provider_instance.protocol_id,
            "status": "healthy" if provider_instance.is_running() else "unhealthy",
            "methods": provider_instance.get_supported_methods()
        }
    
    # Get task statistics
    try:
        task_stats = await app_state.persistence_backend.get_task_count_by_status()
    except:
        task_stats = {}
    
    uptime = (datetime.now() - app_state.start_time).total_seconds()
    
    return SystemStatus(
        status="running",
        providers=providers,
        persistence_backend=type(app_state.persistence_backend).__name__,
        task_statistics=task_stats,
        uptime_seconds=uptime
    )


@app.post("/workflows", response_model=WorkflowResponse)
async def submit_workflow(workflow: WorkflowRequest, background_tasks: BackgroundTasks):
    """Submit a workflow for execution"""
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    # Create workflow object
    workflow_id = f"api_workflow_{uuid.uuid4().hex[:8]}"
    
    tasks = []
    for task_req in workflow.tasks:
        task = Task(
            id=task_req.id or f"task_{uuid.uuid4().hex[:8]}",
            name=task_req.name,
            protocol=task_req.protocol,
            method=task_req.method,
            params=task_req.params,
            dependencies=task_req.dependencies,
            priority=Priority[task_req.priority.upper()]
        )
        
        if task_req.retry:
            task.retry_config = RetryConfig(**task_req.retry)
        
        tasks.append(task)
    
    workflow_obj = Workflow(
        id=workflow_id,
        name=workflow.name,
        description=workflow.description,
        tasks=tasks,
        metadata=workflow.metadata
    )
    
    # Validate workflow
    validation_errors = validate_workflow(workflow_obj)
    if validation_errors:
        raise HTTPException(status_code=400, detail={"errors": validation_errors})
    
    # Create response object
    response = WorkflowResponse(
        workflow_id=workflow_id,
        status="submitted",
        tasks_total=len(tasks),
        tasks_completed=0,
        tasks_failed=0,
        created_at=datetime.now()
    )
    
    app_state.active_workflows[workflow_id] = response
    
    # Submit workflow in background
    background_tasks.add_task(execute_workflow_background, workflow_obj)
    
    return response


async def execute_workflow_background(workflow: Workflow):
    """Execute workflow in background"""
    try:
        await app_state.execution_engine.submit_workflow(workflow)
        await app_state.execution_engine._execute_workflow(workflow)
        
        # Update workflow status
        if workflow.id in app_state.active_workflows:
            response = app_state.active_workflows[workflow.id]
            response.status = "completed"
            response.completed_at = datetime.now()
            
            # Collect results
            for task in workflow.tasks:
                result = app_state.execution_engine.task_results.get(task.id)
                if result:
                    response.results[task.id] = {
                        "status": result.status,
                        "result": result.result,
                        "error": result.error
                    }
                    if result.status == "completed":
                        response.tasks_completed += 1
                    elif result.status == "failed":
                        response.tasks_failed += 1
    
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        if workflow.id in app_state.active_workflows:
            response = app_state.active_workflows[workflow.id]
            response.status = "failed"
            response.completed_at = datetime.now()


@app.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow_status(workflow_id: str):
    """Get workflow status"""
    if workflow_id not in app_state.active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    return app_state.active_workflows[workflow_id]


@app.post("/workflows/upload")
async def upload_workflow(file: UploadFile = File(...), execute: bool = Query(True)):
    """Upload and execute a workflow file"""
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    # Save uploaded file temporarily
    content = await file.read()
    temp_path = Path(f"/tmp/{file.filename}")
    temp_path.write_bytes(content)
    
    try:
        # Load workflow
        workflow = load_workflow_from_file(str(temp_path))
        
        # Validate
        validation_errors = validate_workflow(workflow)
        if validation_errors:
            raise HTTPException(status_code=400, detail={"errors": validation_errors})
        
        if execute:
            # Submit for execution
            await app_state.execution_engine.submit_workflow(workflow)
            
            # Execute in background
            asyncio.create_task(app_state.execution_engine._execute_workflow(workflow))
            
            return {
                "workflow_id": workflow.id,
                "status": "submitted",
                "name": workflow.name,
                "tasks": len(workflow.tasks)
            }
        else:
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
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    task_id = task.id or f"api_task_{uuid.uuid4().hex[:8]}"
    
    # Create task object
    task_obj = Task(
        id=task_id,
        name=task.name,
        protocol=task.protocol,
        method=task.method,
        params=task.params,
        dependencies=task.dependencies,
        priority=Priority[task.priority.upper()]
    )
    
    if task.retry:
        task_obj.retry_config = RetryConfig(**task.retry)
    
    # Create response
    response = TaskResponse(
        task_id=task_id,
        status="submitted",
        created_at=datetime.now()
    )
    
    app_state.active_tasks[task_id] = response
    
    # Execute in background
    background_tasks.add_task(execute_task_background, task_obj)
    
    return response


async def execute_task_background(task: Task):
    """Execute task in background"""
    try:
        await app_state.execution_engine.submit_task(task)
        await app_state.execution_engine.start(ExecutionMode.SINGLE_SHOT)
        
        # Update task status
        if task.id in app_state.active_tasks:
            response = app_state.active_tasks[task.id]
            result = app_state.execution_engine.task_results.get(task.id)
            
            if result:
                response.status = result.status
                response.result = result.result
                response.error = result.error
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


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """Get task status"""
    if task_id not in app_state.active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return app_state.active_tasks[task_id]


@app.post("/execute/python")
async def execute_python_code(request: ExecuteCodeRequest):
    """Execute Python code directly"""
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    task = Task(
        id=f"exec_{uuid.uuid4().hex[:8]}",
        name="API Code Execution",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": request.code,
            "timeout": request.timeout
        },
        priority=Priority.HIGH
    )
    
    await app_state.execution_engine.submit_task(task)
    await app_state.execution_engine.start(ExecutionMode.SINGLE_SHOT)
    
    result = app_state.execution_engine.task_results.get(task.id)
    
    if result and result.status == "completed":
        return {
            "status": "success",
            "output": result.result.get("output", ""),
            "result": result.result.get("result"),
            "execution_time": result.execution_time
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=result.error if result else "Execution failed"
        )


@app.post("/chat")
async def chat(request: ChatRequest):
    """Chat with LLM"""
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    task = Task(
        id=f"chat_{uuid.uuid4().hex[:8]}",
        name="API Chat",
        protocol="llm/v1",
        method="llm/chat",
        params={
            "model": request.model,
            "messages": [{"role": "user", "content": request.message}],
            "temperature": request.temperature
        },
        priority=Priority.HIGH
    )
    
    await app_state.execution_engine.submit_task(task)
    await app_state.execution_engine.start(ExecutionMode.SINGLE_SHOT)
    
    result = app_state.execution_engine.task_results.get(task.id)
    
    if result and result.status == "completed":
        return {
            "status": "success",
            "response": result.result.get("response", ""),
            "model": request.model,
            "session_id": request.session_id
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=result.error if result else "Chat failed"
        )


@app.post("/batch")
async def batch_process(request: BatchRequest):
    """Process files in batch"""
    if not app_state.execution_engine or not app_state.batch_processor:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.batch_processor.process_batch(
            execution_engine=app_state.execution_engine,
            directory=request.directory,
            pattern=request.pattern,
            method=request.method,
            prompt=request.prompt,
            model=request.model,
            max_concurrent=request.max_concurrent
        )
        
        return {
            "batch_id": result.batch_id,
            "total_files": result.total_files,
            "successful": result.successful,
            "failed": result.failed,
            "processing_time": result.processing_time,
            "results": result.results
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/providers")
async def list_providers():
    """List all registered providers"""
    if not app_state.registry:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    providers = []
    for provider_id, provider in app_state.registry.provider_instances.items():
        providers.append({
            "id": provider_id,
            "protocol": provider.protocol_id,
            "name": provider.name,
            "description": provider.description,
            "methods": provider.get_supported_methods(),
            "status": "healthy" if provider.is_running() else "unhealthy"
        })
    
    return {"providers": providers}


@app.get("/protocols")
async def list_protocols():
    """List all registered protocols"""
    if not app_state.registry:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    return {
        "protocols": app_state.registry.list_protocols()
    }


@app.post("/templates/{template_type}")
async def execute_template(
    template_type: str,
    params: Dict[str, Any] = Body(...)
):
    """Execute a workflow template"""
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    # Map template type to method
    method_map = {
        "research": "template/research",
        "code": "template/code",
        "analyze": "template/analyze",
        "chat": "template/chat"
    }
    
    if template_type not in method_map:
        raise HTTPException(status_code=400, detail=f"Unknown template type: {template_type}")
    
    task = Task(
        id=f"template_{uuid.uuid4().hex[:8]}",
        name=f"Template {template_type}",
        protocol="template/v1",
        method=method_map[template_type],
        params=params,
        priority=Priority.NORMAL
    )
    
    await app_state.execution_engine.submit_task(task)
    await app_state.execution_engine.start(ExecutionMode.SINGLE_SHOT)
    
    result = app_state.execution_engine.task_results.get(task.id)
    
    if result and result.status == "completed":
        return result.result
    else:
        raise HTTPException(
            status_code=500,
            detail=result.error if result else "Template execution failed"
        )


@app.delete("/workflows/{workflow_id}")
async def cancel_workflow(workflow_id: str):
    """Cancel a running workflow"""
    if workflow_id not in app_state.active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # TODO: Implement workflow cancellation in execution engine
    
    workflow = app_state.active_workflows[workflow_id]
    workflow.status = "cancelled"
    workflow.completed_at = datetime.now()
    
    return {"status": "cancelled", "workflow_id": workflow_id}


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