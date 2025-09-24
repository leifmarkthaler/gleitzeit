"""
Health check endpoints
"""

from fastapi import APIRouter, Depends
import redis.asyncio as aioredis

from ..dependencies import get_redis

router = APIRouter()


@router.get("/")
async def health_check(
    redis: aioredis.Redis = Depends(get_redis)
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
    redis: aioredis.Redis = Depends(get_redis)
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
    redis: aioredis.Redis = Depends(get_redis)
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

    worker_count = 0
    if redis_connected:
        async for _ in redis.scan_iter(match=b"{shard:*}:worker:registry:*", count=100):
            worker_count += 1

    # Count active workflows
    active_workflows = 0
    if redis_connected:
        async for key in redis.scan_iter(match=b"{shard:*}:workflow:state:*", count=100):
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
