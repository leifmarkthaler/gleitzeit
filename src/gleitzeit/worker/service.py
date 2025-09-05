"""
Standalone Worker Service using existing ClientPool

This service runs a pool of GleitzeitClient instances as workers,
completely decoupled from the API layer for horizontal scaling.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task
from gleitzeit.api.dependencies import ClientPool
from .config import WorkerConfig

logger = logging.getLogger(__name__)


class WorkflowRequest(BaseModel):
    """Request model for workflow execution"""
    workflow: Dict[str, Any]
    options: Optional[Dict[str, Any]] = None


class TaskRequest(BaseModel):
    """Request model for task execution"""
    task: Dict[str, Any]
    options: Optional[Dict[str, Any]] = None


class WorkerService:
    """
    Standalone worker service that runs ClientPool for distributed execution.
    
    This extracts the worker functionality from the API layer, allowing
    workers to run independently and scale horizontally.
    """
    
    def __init__(self, config: Optional[WorkerConfig] = None):
        """
        Initialize worker service.
        
        Args:
            config: Worker configuration (defaults to env vars)
        """
        self.config = config or WorkerConfig.from_env()
        
        # Create client pool with configured size
        self.pool = ClientPool(
            max_size=self.config.pool_size,
            mode=ClientMode[self.config.client_mode.upper()]
        )
        
        # Track service metrics
        self.start_time = datetime.utcnow()
        self.workflows_processed = 0
        self.tasks_processed = 0
        self.active_executions = 0
        self._lock = asyncio.Lock()
        
        # Create FastAPI app
        self.app = self._create_app()
        
        logger.info(f"Initialized WorkerService with pool_size={self.config.pool_size}")
    
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """Manage service lifecycle"""
        # Startup
        logger.info(f"Starting WorkerService on {self.config.host}:{self.config.port}")
        await self.pool.initialize()
        logger.info(f"Worker pool initialized with {self.config.pool_size} clients")
        
        # If resource service is configured, inject into clients
        if self.config.enable_resource_client and self.config.resource_service_url:
            logger.info(f"Configuring resource client: {self.config.resource_service_url}")
            # TODO: Inject StatelessResourceClient when implemented
        
        yield
        
        # Shutdown
        logger.info("Shutting down WorkerService...")
        await self.pool.shutdown()
        logger.info("Worker pool shutdown complete")
    
    def _create_app(self) -> FastAPI:
        """Create FastAPI application"""
        app = FastAPI(
            title=f"{self.config.service_name}",
            description="Gleitzeit Worker Service for distributed workflow execution",
            version="1.0.0",
            lifespan=self.lifespan
        )
        
        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Register routes
        self._register_routes(app)
        
        return app
    
    def _register_routes(self, app: FastAPI):
        """Register API routes"""
        
        @app.get("/")
        async def root():
            """Service info endpoint"""
            return {
                "service": self.config.service_name,
                "type": "worker",
                "pool_size": self.config.pool_size,
                "active_clients": len(self.pool._in_use),
                "available_clients": len(self.pool._pool),
                "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds()
            }
        
        @app.get("/health")
        async def health():
            """Health check endpoint"""
            pool_healthy = len(self.pool._pool) + len(self.pool._in_use) > 0
            
            if not pool_healthy:
                raise HTTPException(status_code=503, detail="Worker pool unhealthy")
            
            return {
                "status": "healthy",
                "pool_size": self.config.pool_size,
                "active_clients": len(self.pool._in_use),
                "available_clients": len(self.pool._pool)
            }
        
        @app.get("/metrics")
        async def metrics():
            """Service metrics endpoint"""
            if not self.config.enable_metrics:
                raise HTTPException(status_code=404, detail="Metrics disabled")
            
            return {
                "service": self.config.service_name,
                "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
                "workflows_processed": self.workflows_processed,
                "tasks_processed": self.tasks_processed,
                "active_executions": self.active_executions,
                "pool": {
                    "size": self.config.pool_size,
                    "active": len(self.pool._in_use),
                    "available": len(self.pool._pool),
                    "utilization": len(self.pool._in_use) / self.config.pool_size * 100
                }
            }
        
        @app.post("/execute/workflow")
        async def execute_workflow(request: WorkflowRequest):
            """
            Execute a workflow using pooled client.
            
            This is the main worker endpoint - receives workflows from
            the API layer or task coordinator and executes them.
            """
            workflow = None
            client = None
            
            try:
                # Parse workflow
                workflow = Workflow(**request.workflow)
                
                # Update metrics
                async with self._lock:
                    self.active_executions += 1
                
                # Acquire client from pool
                client = await self.pool.acquire()
                
                # Submit workflow (non-blocking, event-driven)
                logger.info(f"Submitting workflow {workflow.id} with client from pool")
                submission = await client.submit_workflow(workflow)
                
                # Update metrics
                async with self._lock:
                    self.workflows_processed += 1
                    self.active_executions -= 1
                
                # Return clean submission response (stateless - doesn't wait for completion)
                return {
                    "workflow_id": workflow.id,
                    "status": "submitted",
                    "task_count": len(workflow.tasks),
                    "message": "Workflow submitted for async execution",
                    "details": submission
                }
                
            except Exception as e:
                logger.error(f"Failed to execute workflow: {e}")
                
                # Update metrics
                async with self._lock:
                    self.active_executions = max(0, self.active_executions - 1)
                
                raise HTTPException(
                    status_code=500,
                    detail=f"Workflow execution failed: {str(e)}"
                )
                
            finally:
                # Always release client back to pool
                if client:
                    await self.pool.release(client)
        
        @app.get("/workflow/{workflow_id}/status")
        async def get_workflow_status(workflow_id: str):
            """
            Get workflow status (for polling-based tracking).
            
            In a fully event-driven system, clients should use WebSocket/events.
            This endpoint provides a fallback polling mechanism.
            """
            client = None
            try:
                # Acquire client from pool
                client = await self.pool.acquire()
                
                # Get workflow status
                workflow = await client.get_workflow(workflow_id)
                
                if not workflow:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Workflow {workflow_id} not found"
                    )
                
                # Get progress if available
                progress = None
                if hasattr(client, 'get_workflow_progress'):
                    progress = await client.get_workflow_progress(workflow_id)
                
                return {
                    "workflow_id": workflow_id,
                    "status": workflow.get('status', 'unknown'),
                    "progress": progress,
                    "results": workflow.get('results', {})
                }
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to get workflow status: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get workflow status: {str(e)}"
                )
            finally:
                if client:
                    await self.pool.release(client)
        
        @app.post("/execute/task")
        async def execute_task(request: TaskRequest):
            """
            Execute a single task using pooled client.
            
            For fine-grained task execution when not using full workflows.
            """
            task = None
            client = None
            
            try:
                # Parse task
                task = Task(**request.task)
                
                # Update metrics
                async with self._lock:
                    self.active_executions += 1
                
                # Acquire client from pool
                client = await self.pool.acquire()
                
                # Execute task
                logger.info(f"Executing task {task.id} with client from pool")
                result = await client.execute_task(task)
                
                # Update metrics
                async with self._lock:
                    self.tasks_processed += 1
                    self.active_executions -= 1
                
                return {
                    "success": True,
                    "task_id": task.id,
                    "result": result
                }
                
            except Exception as e:
                logger.error(f"Failed to execute task: {e}")
                
                # Update metrics
                async with self._lock:
                    self.active_executions = max(0, self.active_executions - 1)
                
                raise HTTPException(
                    status_code=500,
                    detail=f"Task execution failed: {str(e)}"
                )
                
            finally:
                # Always release client back to pool
                if client:
                    await self.pool.release(client)
        
        @app.get("/pool/status")
        async def pool_status():
            """Get detailed pool status"""
            return {
                "max_size": self.config.pool_size,
                "current_size": len(self.pool._pool) + len(self.pool._in_use),
                "available": len(self.pool._pool),
                "in_use": len(self.pool._in_use),
                "initialized": self.pool._initialized,
                "utilization_percent": (len(self.pool._in_use) / self.config.pool_size * 100) 
                    if self.config.pool_size > 0 else 0
            }
        
        @app.post("/pool/resize")
        async def resize_pool(new_size: int):
            """Dynamically resize the worker pool"""
            if new_size < 1 or new_size > 1000:
                raise HTTPException(
                    status_code=400,
                    detail="Pool size must be between 1 and 1000"
                )
            
            old_size = self.pool.max_size
            self.pool.max_size = new_size
            
            # If increasing size and currently at capacity, pre-create some clients
            if new_size > old_size and len(self.pool._pool) == 0:
                additional = min(new_size - old_size, 5)  # Create up to 5 new clients
                for _ in range(additional):
                    try:
                        client = await self.pool._create_client()
                        self.pool._pool.append(client)
                    except Exception as e:
                        logger.error(f"Failed to create additional client: {e}")
            
            return {
                "old_size": old_size,
                "new_size": new_size,
                "current_clients": len(self.pool._pool) + len(self.pool._in_use)
            }
    
    async def run(self):
        """Run the worker service"""
        config = uvicorn.Config(
            app=self.app,
            host=self.config.host,
            port=self.config.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()


async def main():
    """Main entry point for worker service"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run service
    service = WorkerService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())