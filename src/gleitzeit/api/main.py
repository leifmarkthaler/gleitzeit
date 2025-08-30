"""
Example of modularized API using client delegation.

This demonstrates how the main API can be refactored to use
the new modular route architecture.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .routes import (
    workflow_router,
    task_router,
    admin_router, 
    system_router,
    auth_router,
    logs_router,
    errors_router,
    initialize_shared_client,
    shutdown_shared_client
)
from .middleware import (
    AuthenticationMiddleware,
    ErrorHandlingMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting Gleitzeit API...")
    await initialize_shared_client()
    logger.info("API startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Gleitzeit API...")
    await shutdown_shared_client()
    logger.info("API shutdown complete")


def create_modular_app() -> FastAPI:
    """
    Create FastAPI application with modular routes.
    
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Gleitzeit API",
        description="Modular Workflow Orchestration API",
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
    
    # Rate limiting
    app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
    
    # Request/response logging
    app.add_middleware(LoggingMiddleware)
    
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
    
    @app.get("/")
    async def root():
        """API root endpoint."""
        return {
            "message": "Gleitzeit API (Modular)",
            "version": "0.0.6",
            "architecture": "client-delegated-routes"
        }
    
    @app.get("/health")
    async def health():
        """Basic health check."""
        return {"status": "healthy", "service": "gleitzeit-api"}
    
    return app


# Create the application instance
app = create_modular_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)