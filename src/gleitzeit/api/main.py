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
import signal
import asyncio

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
from .routes.users import router as users_router
from .routes.sessions import router as sessions_router
from .routes.timers import router as timers_router
from .routes.scheduler import router as scheduler_router
from .routes.signals import router as signals_router
from .routes.streams import router as streams_router
from .routes.error_discovery import router as error_discovery_router
from .routes.triggers import router as triggers_router
from .dependencies import (
    initialize_client_pool,
    shutdown_client_pool,
    get_client_pool,
    get_system_manager
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


# Global shutdown event
shutdown_event = asyncio.Event()


def handle_sigterm(signum, frame):
    """Handle SIGTERM signal for graceful shutdown."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting Gleitzeit API...")
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    
    # Native mode will use SystemManager's AuthManager directly
    # No separate service token needed - auth is centralized
    logger.info("API startup: Native mode will use SystemManager's AuthManager")
    
    await initialize_client_pool()
    logger.info("API startup complete")
    
    # Create background task to monitor shutdown
    shutdown_task = asyncio.create_task(monitor_shutdown())
    
    yield
    
    # Shutdown
    logger.info("Shutting down Gleitzeit API...")
    
    # Cancel shutdown monitor
    shutdown_task.cancel()
    try:
        await shutdown_task
    except asyncio.CancelledError:
        pass
    
    # Graceful shutdown with timeout
    shutdown_timeout = int(os.getenv('GLEITZEIT_SHUTDOWN_TIMEOUT', '30'))
    try:
        logger.info(f"Waiting up to {shutdown_timeout}s for tasks to complete...")
        await asyncio.wait_for(
            graceful_shutdown(),
            timeout=shutdown_timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"Shutdown timeout after {shutdown_timeout}s, forcing shutdown")
    
    await shutdown_client_pool()
    logger.info("API shutdown complete")


async def monitor_shutdown():
    """Monitor for shutdown signal and trigger graceful shutdown."""
    await shutdown_event.wait()
    logger.info("Shutdown signal received, stopping server...")
    # This will trigger the lifespan shutdown
    os._exit(0)


async def graceful_shutdown():
    """Perform graceful shutdown tasks."""
    logger.info("Starting graceful shutdown...")
    
    # Get system manager and stop services
    try:
        system_manager = await get_system_manager()
        if system_manager:
            logger.info("Stopping system manager services...")
            await system_manager.stop()
    except Exception as e:
        logger.error(f"Error stopping system manager: {e}")
    
    # Wait for active requests to complete
    await asyncio.sleep(1)
    
    logger.info("Graceful shutdown completed")


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
    
    # Authentication middleware will be added after startup
    # when SystemManager is available
    
    # Include modular route modules
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(sessions_router)
    app.include_router(workflow_router)
    app.include_router(task_router)
    app.include_router(admin_router)
    app.include_router(system_router)
    app.include_router(logs_router)
    app.include_router(errors_router)
    app.include_router(error_discovery_router)
    app.include_router(events_router)
    app.include_router(timers_router)
    app.include_router(scheduler_router)
    app.include_router(signals_router)
    app.include_router(streams_router)
    app.include_router(triggers_router)
    
    @app.on_event("startup")
    async def add_dynamic_middleware():
        """Add middleware that requires SystemManager/persistence after startup."""
        # Get SystemManager for auth middleware
        system_manager = await get_system_manager()
        
        # Add authentication middleware with SystemManager
        auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
        app.add_middleware(
            AuthenticationMiddleware, 
            auth_mode=auth_mode,
            system_manager=system_manager
        )
        logger.info(f"Authentication middleware added with SystemManager (mode: {auth_mode})")
        
        # Add rate limiting middleware
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