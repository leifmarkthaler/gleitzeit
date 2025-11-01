"""
Gleitzeit 0.0.7 API Server

FastAPI-based REST API that submits work to Redis streams for worker processing.
Based on 0.0.6 architecture but adapted for worker-based execution model.
"""

import logging
import os
import yaml
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from ..core.sharding import default_sharding
from ..core.instance import initialize_instance
from .pools.client_pool import ClientPool
from .middleware.security import (
    RateLimitMiddleware,
    RequestTrackingMiddleware,
    SecurityHeadersMiddleware,
    AuditLoggingMiddleware,
    IPWhitelistMiddleware
)

logger = logging.getLogger(__name__)

# Module-level variables injected by APIWorker
# These MUST be set by APIWorker.on_initialize() before uvicorn starts
_worker_redis = None
_worker_config = None
_redis_url = None

def set_worker_dependencies(redis_instance, config: Dict[str, Any], redis_url: str):
    """Called by APIWorker to inject Redis connection, config, and redis_url"""
    global _worker_redis, _worker_config, _redis_url
    _worker_redis = redis_instance
    _worker_config = config
    _redis_url = redis_url
    logger.info(f"Worker dependencies injected: Redis={type(redis_instance)}, redis_url={redis_url}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    logger.info("Starting Gleitzeit API server")

    # Redis, config, and redis_url MUST be injected by APIWorker before server starts
    global _worker_redis, _worker_config, _redis_url
    if _worker_redis is None or _worker_config is None or _redis_url is None:
        error_msg = (
            "Worker dependencies not injected. "
            "The API must be run via APIWorker, not directly. "
            "Use 'gleitzeit serve' to start the API."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Use the injected Redis connection
    app.state.redis = _worker_redis
    logger.info(f"Using Redis connection from worker: {type(app.state.redis)}")

    # Initialize instance from environment variables if set
    instance_name = os.environ.get('GLEITZEIT_INSTANCE_NAME')
    instance_role = os.environ.get('GLEITZEIT_INSTANCE_ROLE', 'standalone')
    if instance_name:
        initialize_instance(instance_name, instance_role)
        logger.info(f"Initialized instance: {instance_name} with role {instance_role}")

    # Initialize client connection pool with redis_url from worker
    app.state.client_pool = ClientPool(
        redis_url=_redis_url,
        max_clients_per_user=10  # Can be configured
    )
    await app.state.client_pool.initialize()

    # Store sharding config
    app.state.sharding = default_sharding

    # Initialize EventBroadcaster for WebSocket support
    from .services.event_broadcaster import EventBroadcaster, set_broadcaster
    broadcaster = EventBroadcaster(_redis_url)
    await broadcaster.start()
    set_broadcaster(broadcaster)
    app.state.broadcaster = broadcaster
    logger.info("Event broadcaster initialized for WebSocket support")

    # Register Docker service if in Docker environment and service registry is enabled
    service_type = os.environ.get('SERVICE_TYPE')
    if service_type:
        # Check if service registry is enabled in config
        registry_config = _worker_config.get('service_registry', {})
        if registry_config.get('enabled', True):  # Default to enabled for backward compatibility
            try:
                from ..core.config_manager import ConfigurationManager
                config_manager = ConfigurationManager(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'), {})
                service_redis_url = config_manager.get_redis_url()

                from ..core.docker_service_registry import register_service
                await register_service(service_type, service_redis_url)
                logger.info(f"Registered {service_type} service in Redis registry")
            except Exception as e:
                logger.warning(f"Failed to register Docker service: {e}")
        else:
            logger.info("Service registry disabled in configuration")

    logger.info("API server initialized successfully")

    yield

    # Cleanup
    logger.info("Shutting down Gleitzeit API server")

    # Unregister Docker service if in Docker environment
    # This is legacy code for Docker-based deployments
    service_type = os.environ.get('SERVICE_TYPE')
    if service_type:
        # TODO: This Docker service registry code should be removed or updated
        # to use the worker's Redis connection directly
        pass

    # Stop event broadcaster
    if hasattr(app.state, 'broadcaster'):
        await app.state.broadcaster.stop()
        logger.info("Event broadcaster stopped")

    await app.state.client_pool.shutdown()
    await app.state.redis.close()


# Create FastAPI application
app = FastAPI(
    title="Gleitzeit API",
    version="0.0.7-secure",
    description="Secure workflow orchestration API with authentication and rate limiting",
    lifespan=lifespan
)

# CORS and security middleware will be configured in startup_event
# after worker injects config from gleitzeit.yaml
# Do NOT add any middleware here - all middleware uses worker config


# Dependency injection helpers are now in dependencies.py


# Import and include routers
from .routes import workflows, tasks, system, health, auth, websocket, metrics, workers
from .auth.dependencies import init_auth
from .discovery import router as discovery_router

# Initialize authentication and rate limiting
@app.on_event("startup")
async def startup_event():
    """Initialize authentication and middleware on startup"""
    # Get config from worker injection
    global _worker_config
    if _worker_config is None:
        logger.warning("Worker config not available in startup event")
        return

    # Initialize auth with config
    auth_config = _worker_config.get('auth', {})

    # Set GLEITZEIT_AUTO_LOGIN from config
    if 'auto_login' in auth_config:
        os.environ['GLEITZEIT_AUTO_LOGIN'] = str(auth_config['auto_login']).lower()

    # Set JWT config from YAML
    jwt_config = auth_config.get('jwt', {})
    if 'secret' in jwt_config:
        os.environ['JWT_SECRET'] = str(jwt_config['secret'])

    init_auth(app.state.redis)

    # Add rate limiting middleware from config
    rate_limit_config = _worker_config.get('security', {}).get('rate_limiting', {})
    if rate_limit_config.get('enabled', True):
        app.add_middleware(
            RateLimitMiddleware,
            redis=app.state.redis,
            default_limit=rate_limit_config.get('default_limit', 100),
            window=rate_limit_config.get('window', 60)
        )

    # Add audit logging middleware from config
    audit_config = _worker_config.get('security', {}).get('audit', {})
    if audit_config.get('enabled', True):
        app.add_middleware(
            AuditLoggingMiddleware,
            redis=app.state.redis
        )

    # Add IP whitelist from config
    ip_whitelist_config = _worker_config.get('security', {}).get('ip_whitelist', {})
    if ip_whitelist_config.get('enabled', False):
        whitelist_str = ip_whitelist_config.get('whitelist', '')
        if whitelist_str:
            admin_whitelist = whitelist_str.split(',') if isinstance(whitelist_str, str) else whitelist_str
            app.add_middleware(
                IPWhitelistMiddleware,
                whitelist=admin_whitelist
            )

    logger.info("Security middleware initialized with config from gleitzeit.yaml")

app.include_router(auth.router, prefix="/auth", tags=["authentication"])
app.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(system.router, prefix="/system", tags=["system"])
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(discovery_router, tags=["discovery"])
app.include_router(metrics.router, tags=["metrics"])
app.include_router(workers.router, prefix="/workers", tags=["workers"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Gleitzeit API",
        "version": "0.0.7-secure",
        "status": "operational",
        "description": "Secure workflow orchestration API",
        "features": [
            "authentication",
            "rate_limiting",
            "request_tracking",
            "ownership_management",
            "audit_logging"
        ]
    }