"""
System monitoring and management endpoints
"""

import json
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis

from ...core.sharding import default_sharding

router = APIRouter()


@router.get("/status")
async def system_status(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get overall system status"""

    status = {
        "orchestrator": {},
        "workers": {},
        "queues": {},
        "shards": {}
    }

    try:
        # Check orchestrator status
        async for key in redis.scan_iter(match=b"orchestrator:*", count=100):
            if key.endswith(b":metrics"):
                metrics = await redis.hget(key, b"latest")
                if metrics:
                    status["orchestrator"]["metrics"] = json.loads(metrics.decode())

        # Check worker statuses via metrics hashes
        async for key in redis.scan_iter(match=b"{shard:*}:worker:metrics:*", count=100):
            worker_id = key.decode().split(":")[-1]
            worker_data = await redis.hgetall(key)
            if worker_data:
                status["workers"][worker_id] = {
                    k.decode(): v.decode() for k, v in worker_data.items()
                }

        # Check queue depths
        streams = {
            "workflow:load": 0,
            "workflow:submitted": 0,
            "task:ready": 0,
            "task:completed": 0
        }

        for stream_name in streams:
            total_length = 0
            for shard in range(16):  # Assuming 16 shards
                stream_key = f"{{shard:{shard}}}:{stream_name}".encode()
                length = await redis.xlen(stream_key)
                total_length += length

            status["queues"][stream_name] = total_length

        return status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system status: {str(e)}")


@router.get("/metrics")
async def get_metrics(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get system metrics"""

    metrics = {
        "workflows": {
            "total": 0,
            "running": 0,
            "completed": 0,
            "failed": 0
        },
        "tasks": {
            "total": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0
        }
    }

    try:
        # Count workflows by status
        async for key in redis.scan_iter(match=b"{shard:*}:workflow:state:*", count=100):
            wf_status = await redis.hget(key, b"status")
            if wf_status:
                metrics["workflows"]["total"] += 1
                status_str = wf_status.decode()
                if status_str == "running":
                    metrics["workflows"]["running"] += 1
                elif status_str == "completed":
                    metrics["workflows"]["completed"] += 1
                elif status_str == "failed":
                    metrics["workflows"]["failed"] += 1

        # Count tasks by status
        async for key in redis.scan_iter(match=b"{shard:*}:task:status:*", count=200):
            task_status = await redis.hget(key, b"status")
            if task_status:
                metrics["tasks"]["total"] += 1
                status_str = task_status.decode()
                if status_str == "pending":
                    metrics["tasks"]["pending"] += 1
                elif status_str == "running":
                    metrics["tasks"]["running"] += 1
                elif status_str == "completed":
                    metrics["tasks"]["completed"] += 1
                elif status_str == "failed":
                    metrics["tasks"]["failed"] += 1

        return metrics

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@router.get("/workers")
async def list_workers(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """List all registered workers"""

    workers = []

    try:
        async for key in redis.scan_iter(match=b"{shard:*}:worker:registry:*", count=100):
            worker_data = await redis.hgetall(key)
            if worker_data:
                worker_info = {k.decode(): v.decode() for k, v in worker_data.items()}
                workers.append(worker_info)

        return {
            "count": len(workers),
            "workers": workers
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list workers: {str(e)}")


@router.get("/metrics/workflows")
async def get_workflow_metrics(
    time_range: str = "1h",
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get workflow-specific metrics"""

    # Parse time range (simplified)
    hours = 1
    if time_range.endswith('h'):
        hours = int(time_range[:-1])
    elif time_range.endswith('d'):
        hours = int(time_range[:-1]) * 24

    status_counts: Dict[str, int] = {}
    total = 0

    async for key in redis.scan_iter(match=b"{shard:*}:workflow:state:*", count=100):
        state_data = await redis.hgetall(key)
        if not state_data:
            continue
        total += 1
        status_value = state_data.get(b"status", b"unknown").decode()
        status_counts[status_value] = status_counts.get(status_value, 0) + 1

    return {
        "time_range": time_range,
        "total_workflows": total,
        "by_status": status_counts,
        "active": status_counts.get("running", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0)
    }


@router.get("/metrics/tasks")
async def get_task_metrics(
    time_range: str = "1h",
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get task-specific metrics"""

    total = 0
    status_counts: Dict[str, int] = {}
    protocol_counts: Dict[str, int] = {}

    async for key in redis.scan_iter(match=b"{shard:*}:task:status:*", count=200):
        state_data = await redis.hgetall(key)
        if not state_data:
            continue
        total += 1
        status_value = state_data.get(b"status", b"unknown").decode()
        status_counts[status_value] = status_counts.get(status_value, 0) + 1

        protocol_value = state_data.get(b"protocol", b"unknown").decode()
        protocol_counts[protocol_value] = protocol_counts.get(protocol_value, 0) + 1

    return {
        "time_range": time_range,
        "total_tasks": total,
        "by_status": status_counts,
        "by_protocol": protocol_counts,
        "executing": status_counts.get("executing", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0)
    }


@router.get("/redis/info")
async def get_redis_info(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get Redis server information"""

    info = await redis.info()

    return {
        "version": info.get("redis_version", "unknown"),
        "uptime_seconds": info.get("uptime_in_seconds", 0),
        "connected_clients": info.get("connected_clients", 0),
        "used_memory": info.get("used_memory_human", "0B"),
        "total_connections_received": info.get("total_connections_received", 0),
        "total_commands_processed": info.get("total_commands_processed", 0),
        "keyspace": {
            db: stats for db, stats in info.items()
            if db.startswith("db")
        }
    }


@router.get("/queues")
async def get_queue_depths(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get queue depths for all streams"""

    # Define known stream patterns
    stream_patterns = [
        "workflow:*",
        "task:*",
        "handler:*"
    ]

    queues = {}

    for pattern in stream_patterns:
        async for key in redis.scan_iter(match=f"{{shard:*}}:{pattern}".encode(), count=200):
            try:
                length = await redis.xlen(key)
                queues[key.decode()] = length
            except Exception:
                continue

    return {
        "queues": queues,
        "total_queues": len(queues),
        "total_messages": sum(queues.values())
    }


@router.get("/audit/logs")
async def get_audit_logs(
    limit: int = 100,
    offset: int = 0,
    level: Optional[str] = None,
    workflow_id: Optional[str] = None,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get audit logs (placeholder - would need proper logging implementation)"""

    # This is a placeholder - in production you'd query actual audit logs
    return {
        "logs": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "message": "Audit logging not yet implemented"
    }


@router.get("/logs/errors")
async def get_error_logs(
    limit: int = 100,
    offset: int = 0,
    level: str = "ERROR",
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get error logs from Redis"""

    # Check for error entries in Redis (would need proper error tracking)
    error_pattern = b"*:error:*"
    cursor = b"0"
    error_keys = []

    while True:
        cursor, keys = await redis.scan(cursor, match=error_pattern, count=100)
        error_keys.extend(keys)
        if cursor == b"0":
            break

    errors = []
    for key in error_keys[offset:offset+limit]:
        error_data = await redis.hgetall(key)
        if error_data:
            errors.append({k.decode(): v.decode() for k, v in error_data.items()})

    return {
        "errors": errors,
        "total": len(error_keys),
        "limit": limit,
        "offset": offset
    }


@router.get("/resources")
async def get_resource_usage():
    """Get system resource usage"""

    import psutil

    return {
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "count": psutil.cpu_count()
        },
        "memory": {
            "percent": psutil.virtual_memory().percent,
            "available": psutil.virtual_memory().available,
            "total": psutil.virtual_memory().total
        },
        "disk": {
            "percent": psutil.disk_usage('/').percent,
            "free": psutil.disk_usage('/').free,
            "total": psutil.disk_usage('/').total
        }
    }


@router.get("/config")
async def get_configuration():
    """Get system configuration (sanitized)"""

    from ..main import CONFIG

    # Return sanitized config (remove sensitive data)
    safe_config = {
        "redis": {
            "mode": CONFIG.get("redis", {}).get("mode", "single")
        },
        "api": {
            "host": CONFIG.get("api", {}).get("host", "0.0.0.0"),
            "port": CONFIG.get("api", {}).get("port", 8000)
        },
        "auth": {
            "enabled": CONFIG.get("auth", {}).get("enabled", False),
            "auto_login": CONFIG.get("auth", {}).get("auto_login", False)
        },
        "security": {
            "rate_limiting": CONFIG.get("security", {}).get("rate_limiting", {}).get("enabled", False)
        }
    }

    return safe_config


@router.post("/workers/health-check")
async def trigger_health_check_all_workers(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Trigger health check for all workers"""

    results = {}

    async for key in redis.scan_iter(match=b"{shard:*}:worker:registry:*", count=100):
        worker_data = await redis.hgetall(key)
        worker_id = worker_data.get(b"worker_id") or key.decode().split(":")[-1].encode()
        results[worker_id.decode()] = bool(worker_data)

    return {
        "results": results,
        "healthy": sum(1 for v in results.values() if v),
        "unhealthy": sum(1 for v in results.values() if not v),
        "total": len(results)
    }


@router.get("/sessions")
async def get_active_sessions(
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get active user sessions"""

    # Find session keys
    pattern = b"session:*"
    cursor = b"0"
    session_keys = []

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        session_keys.extend(keys)
        if cursor == b"0":
            break

    sessions = []
    for key in session_keys[:100]:  # Limit for performance
        session_data = await redis.hgetall(key)
        if session_data:
            sessions.append({
                "session_id": key.decode().split(':')[-1],
                "user": session_data.get(b"username", b"unknown").decode(),
                "created_at": session_data.get(b"created_at", b"").decode()
            })

    return {
        "sessions": sessions,
        "total": len(session_keys),
        "active": len(sessions)
    }


# Fix circular import
from ..main import app
