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
from .pools.client_pool import ClientPool
from .middleware.security import (
    RateLimitMiddleware,
    RequestTrackingMiddleware,
    SecurityHeadersMiddleware,
    AuditLoggingMiddleware,
    IPWhitelistMiddleware
)

logger = logging.getLogger(__name__)


def load_config(config_path: str = "gleitzeit.yaml") -> Dict[str, Any]:
    """Load configuration from gleitzeit.yaml"""
    # Check multiple locations for config file
    possible_paths = [
        Path(config_path),
        Path.cwd() / config_path,
        Path.cwd().parent / config_path,
        Path(__file__).parent.parent.parent / config_path,
    ]

    for path in possible_paths:
        if path.exists():
            logger.info(f"Loading config from {path}")
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}

    logger.warning(f"Config file {config_path} not found, using defaults")
    return {}


# Load configuration at module level
CONFIG = load_config(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    logger.info("Starting Gleitzeit API server")

    # Initialize Redis connection from config
    redis_config = CONFIG.get('redis', {})
    redis_url = os.getenv("REDIS_URL", None)

    if not redis_url:
        # Build Redis URL from config
        if redis_config.get('mode') == 'single':
            single_node = redis_config.get('single_node', {})
            redis_host = single_node.get('host', 'localhost')
            redis_port = single_node.get('port', 6379)
            redis_db = single_node.get('db', 0)
            redis_url = f"redis://{redis_host}:{redis_port}/{redis_db}"
        else:
            redis_url = "redis://localhost:6379"

    app.state.redis = await aioredis.from_url(
        redis_url,
        decode_responses=False
    )

    # Initialize client connection pool
    app.state.client_pool = ClientPool()
    await app.state.client_pool.initialize()

    # Store sharding config
    app.state.sharding = default_sharding

    logger.info("API server initialized successfully")

    yield

    # Cleanup
    logger.info("Shutting down Gleitzeit API server")
    await app.state.client_pool.shutdown()
    await app.state.redis.close()


# Create FastAPI application
app = FastAPI(
    title="Gleitzeit API",
    version="0.0.7-secure",
    description="Secure workflow orchestration API with authentication and rate limiting",
    lifespan=lifespan
)

# Configure CORS from YAML config
cors_config = CONFIG.get('security', {}).get('cors', {})

# Build allowed origins list
allowed_origins = []

# Check if we should auto-compute from serve config
if cors_config.get('use_serve_config', True):
    serve_config = CONFIG.get('serve', {})

    # Add API URL
    api_config = serve_config.get('api', {})
    api_host = api_config.get('host', 'localhost')
    if api_host == '0.0.0.0':
        api_host = 'localhost'
    api_port = api_config.get('port', 8000)
    allowed_origins.extend([
        f"http://{api_host}:{api_port}",
        f"http://localhost:{api_port}",
        f"http://127.0.0.1:{api_port}"
    ])

    # Add UI URL
    ui_config = serve_config.get('ui', {})
    if ui_config.get('enabled', True):
        ui_host = ui_config.get('host', 'localhost')
        if ui_host == '0.0.0.0':
            ui_host = 'localhost'
        ui_port = ui_config.get('port', 8004)
        allowed_origins.extend([
            f"http://{ui_host}:{ui_port}",
            f"http://localhost:{ui_port}",
            f"http://127.0.0.1:{ui_port}"
        ])

# Add additional origins from config
additional_origins = cors_config.get('additional_origins', '')
if additional_origins:
    if isinstance(additional_origins, str):
        allowed_origins.extend(additional_origins.split(','))
    elif isinstance(additional_origins, list):
        allowed_origins.extend(additional_origins)

# Add from environment as fallback
env_origins = os.getenv("CORS_ORIGINS", "")
if env_origins:
    allowed_origins.extend(env_origins.split(','))

# Remove duplicates and empty strings
allowed_origins = list(filter(None, set(allowed_origins)))

# Default if nothing configured
if not allowed_origins:
    allowed_origins = ["http://localhost:8000", "http://localhost:8004"]

logger.info(f"CORS allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=cors_config.get('allow_credentials', True),
    allow_methods=cors_config.get('allow_methods', ["GET", "POST", "PUT", "DELETE", "OPTIONS"]),
    allow_headers=cors_config.get('allow_headers', ["Content-Type", "Authorization", "X-Session-ID", "X-API-Key"]),
    expose_headers=cors_config.get('expose_headers', ["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"]),
)

# Add security middleware (order matters - these run in reverse order)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTrackingMiddleware)


# Dependency injection helpers
async def get_redis() -> aioredis.Redis:
    """Get Redis connection from app state"""
    return app.state.redis


async def get_client_pool() -> ClientPool:
    """Get client pool from app state"""
    return app.state.client_pool


async def get_sharding():
    """Get sharding configuration"""
    return app.state.sharding


# Import and include routers
from .routes import workflows, tasks, system, health, auth
from .auth.dependencies import init_auth

# Initialize authentication and rate limiting
@app.on_event("startup")
async def startup_event():
    """Initialize authentication and middleware on startup"""
    # Initialize auth with config
    auth_config = CONFIG.get('auth', {})

    # Set GLEITZEIT_AUTO_LOGIN from config
    if 'auto_login' in auth_config:
        os.environ['GLEITZEIT_AUTO_LOGIN'] = str(auth_config['auto_login']).lower()

    # Set JWT config from YAML
    jwt_config = auth_config.get('jwt', {})
    if 'secret' in jwt_config:
        os.environ['JWT_SECRET'] = str(jwt_config['secret'])

    init_auth(app.state.redis)

    # Add rate limiting middleware from config
    rate_limit_config = CONFIG.get('security', {}).get('rate_limiting', {})
    if rate_limit_config.get('enabled', True):
        app.add_middleware(
            RateLimitMiddleware,
            redis=app.state.redis,
            default_limit=rate_limit_config.get('default_limit', 100),
            window=rate_limit_config.get('window', 60)
        )

    # Add audit logging middleware from config
    audit_config = CONFIG.get('security', {}).get('audit', {})
    if audit_config.get('enabled', True):
        app.add_middleware(
            AuditLoggingMiddleware,
            redis=app.state.redis
        )

    # Add IP whitelist from config
    ip_whitelist_config = CONFIG.get('security', {}).get('ip_whitelist', {})
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