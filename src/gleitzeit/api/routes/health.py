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


@router.get("/detailed")
async def detailed_health_check(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Detailed health check with system information"""

    # Check Redis
    try:
        await redis.ping()
        redis_info = await redis.info()
        redis_status = "healthy"
        redis_connected = True
    except:
        redis_info = {}
        redis_status = "unhealthy"
        redis_connected = False

    # Count workers
    worker_pattern = b"worker:*:state"
    cursor = b"0"
    worker_count = 0

    if redis_connected:
        while True:
            cursor, keys = await redis.scan(cursor, match=worker_pattern, count=100)
            worker_count += len(keys)
            if cursor == b"0":
                break

    # Count active workflows
    workflow_pattern = b"*:workflow:state:*"
    cursor = b"0"
    workflow_keys = []
    active_workflows = 0

    if redis_connected:
        while True:
            cursor, keys = await redis.scan(cursor, match=workflow_pattern, count=100)
            workflow_keys.extend(keys)
            if cursor == b"0":
                break

        # Count active workflows
        for key in workflow_keys[:100]:  # Limit for performance
            state_data = await redis.hgetall(key)
            if state_data:
                status = state_data.get(b"status", b"").decode()
                if status in ["running", "pending", "submitted"]:
                    active_workflows += 1

    return {
        "status": "healthy" if redis_status == "healthy" else "degraded",
        "version": "0.0.7",
        "redis_connected": redis_connected,
        "worker_count": worker_count,
        "active_workflows": active_workflows,
        "redis_info": {
            "version": redis_info.get("redis_version", "unknown") if redis_info else "unknown",
            "uptime": redis_info.get("uptime_in_seconds", 0) if redis_info else 0,
            "connected_clients": redis_info.get("connected_clients", 0) if redis_info else 0
        }
    }


# Fix circular import
from ..main import app