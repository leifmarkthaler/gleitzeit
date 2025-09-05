"""
Modularized API using client dependency injection.

This demonstrates the stateless API architecture using
dependency injection instead of singleton patterns.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os
import secrets

from .routes import (
    workflow_router,
    task_router,
    admin_router, 
    system_router,
    auth_router,
    logs_router,
    errors_router,
    events_router
)
from .dependencies import (
    initialize_client_pool,
    shutdown_client_pool,
    get_client_pool
)
from .middleware import (
    AuthenticationMiddleware,
    ErrorHandlingMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
    RequestCleanupMiddleware
)

logger = logging.getLogger(__name__)


async def get_persistence_for_middleware():
    """
    Get persistence backend for middleware use.
    
    Uses the first available client from the pool to get persistence.
    """
    try:
        pool = await get_client_pool()
        # Temporarily acquire a client to get persistence reference
        client = await pool.acquire()
        try:
            if hasattr(client, '_adapter') and hasattr(client._adapter, 'execution_engine'):
                engine = client._adapter.execution_engine
                if hasattr(engine, 'persistence'):
                    return engine.persistence
        finally:
            await pool.release(client)
    except Exception as e:
        logger.warning(f"Could not get persistence for middleware: {e}")
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting Gleitzeit API...")
    
    # Generate or load service token for NATIVE mode authentication
    service_token = os.getenv("GLEITZEIT_SERVICE_TOKEN")
    if not service_token:
        service_token = secrets.token_hex(32)
        logger.info("Generated new service token for NATIVE mode")
    else:
        logger.info("Using configured service token for NATIVE mode")
    
    # Set the service token on the GleitzeitClient class
    from gleitzeit.client import GleitzeitClient
    GleitzeitClient.set_service_token(service_token)
    
    # Store token in app state for dependencies to use
    app.state.service_token = service_token
    
    await initialize_client_pool()
    logger.info("API startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Gleitzeit API...")
    await shutdown_client_pool()
    logger.info("API shutdown complete")


def create_modular_app() -> FastAPI:
    """
    Create FastAPI application with dependency injection.
    
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Gleitzeit API",
        description="Stateless Workflow Orchestration API",
        version="0.0.6",
        lifespan=lifespan
    )
    
    # Add middleware (order matters - applied in reverse)
    
    # CORS middleware (outermost)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Note: Rate limiting middleware will be added after startup
    # when persistence is available
    
    # Request/response logging
    app.add_middleware(LoggingMiddleware)
    
    # Request cleanup (ensures per-request resources are cleaned up)
    app.add_middleware(RequestCleanupMiddleware)
    
    # Error handling
    app.add_middleware(ErrorHandlingMiddleware)
    
    # Authentication (innermost - runs first)
    app.add_middleware(AuthenticationMiddleware, auth_mode="basic")
    
    # Include modular route modules
    app.include_router(auth_router)
    app.include_router(workflow_router)
    app.include_router(task_router)
    app.include_router(admin_router)
    app.include_router(system_router)
    app.include_router(logs_router)
    app.include_router(errors_router)
    app.include_router(events_router)
    
    @app.on_event("startup")
    async def add_rate_limiting():
        """Add rate limiting middleware after persistence is available."""
        persistence = await get_persistence_for_middleware()
        if persistence:
            app.add_middleware(RateLimitMiddleware, requests_per_minute=60, persistence=persistence)
            logger.info("Rate limiting middleware added with persistence backend")
        else:
            logger.warning("Rate limiting middleware skipped - no persistence available")
    
    @app.get("/")
    async def root():
        """API root endpoint."""
        return {
            "message": "Gleitzeit API (Stateless)",
            "version": "0.0.6",
            "architecture": "dependency-injection"
        }
    
    @app.get("/health")
    async def health():
        """Basic health check."""
        # In stateless architecture, SharedClientPool manages clients via SystemManager
        # Pool state is stored in unified backend (Redis/SQL), not in memory
        pool = await get_client_pool()
        
        return {
            "status": "healthy",
            "service": "gleitzeit-api",
            "architecture": "stateless",
            "pool_info": {
                "type": "SharedClientPool",
                "max_size": pool.max_size,
                "instance_id": pool.instance_id,
                "backend": "SystemManager"
            }
        }
    
    return app


# Create the application instance
app = create_modular_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)