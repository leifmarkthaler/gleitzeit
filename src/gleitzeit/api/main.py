"""
Gleitzeit 0.0.7 API Server

FastAPI-based REST API that submits work to Redis streams for worker processing.
Based on 0.0.6 architecture but adapted for worker-based execution model.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from ..core.sharding import default_sharding
from .pools.client_pool import ClientPool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    logger.info("Starting Gleitzeit API server")

    # Initialize Redis connection
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
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
    version="0.0.7",
    description="Workflow orchestration API - submits to Redis streams for worker processing",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

# Initialize authentication
@app.on_event("startup")
async def startup_event():
    """Initialize authentication on startup"""
    init_auth(app.state.redis)

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
        "version": "0.0.7",
        "status": "operational",
        "description": "Submit workflows to Redis streams for worker processing"
    }