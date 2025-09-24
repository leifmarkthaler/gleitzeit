"""
Shared dependencies for FastAPI routes
"""

from typing import TYPE_CHECKING

import redis.asyncio as aioredis

if TYPE_CHECKING:
    from .pools.client_pool import ClientPool


async def get_redis() -> aioredis.Redis:
    """Get Redis connection from app state"""
    from .main import app
    return app.state.redis


async def get_client_pool() -> "ClientPool":
    """Get client pool from app state"""
    from .main import app
    return app.state.client_pool


async def get_sharding():
    """Get sharding configuration"""
    from .main import app
    return app.state.sharding