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
from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
from gleitzeit.hub.mcp_hub import MCPHub
from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.batch_processor import BatchProcessor
from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow
from gleitzeit.common.shutdown import unified_shutdown

# Hub architecture imports
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.docker_hub import DockerHub

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
    """Application state container"""
    def __init__(self):
        self.execution_engine: Optional[ExecutionEngine] = None
        self.persistence_backend = None
        self.registry: Optional[ProtocolProviderRegistry] = None
        self.batch_processor: Optional[BatchProcessor] = None
        self.resource_manager: Optional[ResourceManager] = None
        self.ollama_hub: Optional[OllamaHub] = None
        self.docker_hub: Optional[DockerHub] = None
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
    """Initialize the Gleitzeit system with hub architecture"""
    try:
        # Initialize persistence with configuration from environment
        import os
        factory_kwargs = {}
        
        # Redis configuration from environment
        redis_url = os.getenv('GLEITZEIT_REDIS_URL')
        if redis_url:
            factory_kwargs['redis_url'] = redis_url
        
        # SQL configuration from environment
        sql_db_path = os.getenv('GLEITZEIT_SQL_DB_PATH')
        if sql_db_path:
            factory_kwargs['sql_db_path'] = sql_db_path
        
        sql_connection = os.getenv('GLEITZEIT_SQL_CONNECTION')
        if sql_connection:
            factory_kwargs['sql_connection_string'] = sql_connection
        
        # Persistence type preference
        persistence_type = os.getenv('GLEITZEIT_PERSISTENCE_TYPE', 'auto')
        if persistence_type != 'auto':
            from gleitzeit.persistence.factory import PersistenceType
            factory_kwargs['persistence_type'] = PersistenceType(persistence_type)
        
        app_state.persistence_backend = await PersistenceFactory.create(**factory_kwargs)
        logger.info(f"Persistence initialized: {type(app_state.persistence_backend).__name__}")
        
        # Setup execution components
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        app_state.registry = ProtocolProviderRegistry()
        
        # Get max concurrent tasks from environment
        max_concurrent = int(os.getenv('GLEITZEIT_MAX_CONCURRENT_TASKS', '5'))
        
        app_state.execution_engine = ExecutionEngine(
            registry=app_state.registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=app_state.persistence_backend,
            max_concurrent_tasks=max_concurrent
        )
        
        # Initialize Resource Management (Hub Architecture)
        try:
            app_state.resource_manager = ResourceManager("api-resources")
            
            # Create and add OllamaHub with auto-discovery
            app_state.ollama_hub = OllamaHub(
                hub_id="ollama-hub",
                auto_discover=True,  # Auto-discover running Ollama instances
                persistence=app_state.persistence_backend
            )
            await app_state.ollama_hub.initialize()
            await app_state.resource_manager.add_hub("ollama", app_state.ollama_hub)
            logger.info("OllamaHub initialized with auto-discovery")
            
            # Optionally create DockerHub if Docker is available
            # app_state.docker_hub = DockerHub(
            #     hub_id="docker-hub",
            #     max_instances=5,
            #     persistence=app_state.persistence_backend
            # )
            # await app_state.docker_hub.initialize()
            # await app_state.resource_manager.add_hub("docker", app_state.docker_hub)
            
            await app_state.resource_manager.start()
            logger.info("Resource management enabled")
        except Exception as e:
            logger.warning(f"Resource management initialization failed: {e}")
            app_state.resource_manager = None
            app_state.ollama_hub = None
        
        # Register protocols and providers with hub support
        await register_providers()
        
        # Initialize batch processor
        app_state.batch_processor = BatchProcessor()
        
        # Don't start the engine here - it will block!
        # Tasks will be executed directly using _execute_task()
        
        logger.info("System setup complete")
        
    except Exception as e:
        logger.error(f"System setup failed: {e}")
        raise


async def register_providers():
    """Register all protocol providers with hub support"""
    registry = app_state.registry
    
    # Python provider
    try:
        registry.register_protocol(PYTHON_PROTOCOL_V1)
        python_provider = PythonProvider(
            "api-python-provider",
            allow_local=True,
            resource_manager=app_state.resource_manager,
            hub=app_state.docker_hub  # Python can use Docker hub if available
        )
        await python_provider.initialize()
        registry.register_provider("api-python-provider", "python/v1", python_provider)
        logger.info("Python provider registered")
    except Exception as e:
        logger.warning(f"Python provider registration failed: {e}")
    
    # Ollama provider with hub
    try:
        registry.register_protocol(LLM_PROTOCOL_V1)
        ollama_provider = OllamaProvider(
            "api-ollama-provider",
            auto_discover=False,  # Hub handles discovery
            resource_manager=app_state.resource_manager,
            hub=app_state.ollama_hub
        )
        await ollama_provider.initialize()
        registry.register_provider("api-ollama-provider", "llm/v1", ollama_provider)
        logger.info("Ollama provider registered with hub")
    except Exception as e:
        logger.warning(f"Ollama provider registration failed: {e}")
    
    # MCP provider - always use MCPHub
    try:
        registry.register_protocol(MCP_PROTOCOL_V1)
        mcp_config = {}  # Could load from config file if needed
        mcp_hub = MCPHub(
            auto_discover=False,
            config_data=mcp_config
        )
        mcp_provider = MCPHubProvider(
            provider_id="api-mcp-provider",
            hub=mcp_hub,
            config_data=mcp_config
        )
        await mcp_provider.initialize()
        registry.register_provider("api-mcp-provider", "mcp/v1", mcp_provider)
        logger.info("MCP provider registered")
    except Exception as e:
        logger.warning(f"MCP provider registration failed: {e}")
    


async def cleanup_system():
    """Clean up system resources including hubs and resource manager"""
    # Use unified shutdown
    await unified_shutdown(
        execution_engine=app_state.execution_engine,
        resource_manager=app_state.resource_manager,
        persistence_backend=app_state.persistence_backend,
        registry=app_state.registry,
        verbose=True  # Log info messages
    )


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
        # Submit task to engine
        await app_state.execution_engine.submit_task(task)
        
        # Execute the task directly (without start/stop cycle)
        result = await app_state.execution_engine._execute_task(task)
        
        # Update task status
        if task.id in app_state.active_tasks:
            response = app_state.active_tasks[task.id]
            
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


@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a running task"""
    if not app_state.execution_engine:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    if task_id not in app_state.active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Try to cancel the task
    try:
        # Mark task as cancelled in active tasks
        task_response = app_state.active_tasks.get(task_id)
        if task_response and task_response.status in ["pending", "running"]:
            task_response.status = "cancelled"
            task_response.completed_at = datetime.now()
            
            # Try to cancel in execution engine if it has the method
            if hasattr(app_state.execution_engine, 'cancel_task'):
                await app_state.execution_engine.cancel_task(task_id)
            
            return {"message": f"Task {task_id} cancelled", "status": "cancelled"}
        else:
            return {"message": f"Task {task_id} already completed", "status": task_response.status}
    except Exception as e:
        logger.error(f"Failed to cancel task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(e)}")



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
        # First find matching files
        files = app_state.batch_processor.scan_directory(request.directory, request.pattern)
        
        # If no files found, return empty result
        if not files:
            return {
                "batch_id": f"batch-{uuid.uuid4().hex[:8]}",
                "total_files": 0,
                "successful": 0,
                "failed": 0,
                "processing_time": 0.0,
                "results": {}
            }
        
        # Process the batch
        result = await app_state.batch_processor.process_batch(
            execution_engine=app_state.execution_engine,
            directory=request.directory,
            pattern=request.pattern,
            method=request.method,
            prompt=request.prompt,
            model=request.model
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
        "protocols": app_state.registry.protocol_registry.list_protocols()
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