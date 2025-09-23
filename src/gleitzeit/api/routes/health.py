"""
Health check endpoints
"""

from fastapi import APIRouter, Depends
import redis.asyncio as aioredis

router = APIRouter()


@router.get("/")
async def health_check(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Basic health check"""

    # Check Redis connection
    try:
        await redis.ping()
        redis_status = "healthy"
    except:
        redis_status = "unhealthy"

    return {
        "status": "healthy" if redis_status == "healthy" else "degraded",
        "components": {
            "api": "healthy",
            "redis": redis_status
        }
    }


@router.get("/ready")
async def readiness_check(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Readiness check for k8s"""

    try:
        await redis.ping()
        return {"ready": True}
    except:
        return {"ready": False}, 503


@router.get("/live")
async def liveness_check():
    """Liveness check for k8s"""
    return {"alive": True}


# Fix circular import
from ..main import app