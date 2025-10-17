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


@router.get("/cluster")
async def cluster_health_check(
    redis: aioredis.Redis = Depends(get_redis)
):
    """Stateless cluster health check - discovers all service instances across deployment modes"""

    # Import time utilities at function level
    import time
    from datetime import datetime, timedelta

    # Check Redis connection
    try:
        await redis.ping()
        redis_connected = True
    except:
        return {
            "status": "unhealthy",
            "error": "Redis connection failed",
            "redis_connected": False,
            "services": {}
        }

    # Discover all registered services
    services = {}
    service_count = 0
    healthy_services = 0

    try:
        async for key in redis.scan_iter(match=b"service:registry:*"):
            service_type = key.decode().split(":")[-1]
            service_data = await redis.hgetall(key)

            if service_data:
                service_count += 1

                # Decode service information
                service_info = {}
                for field, value in service_data.items():
                    service_info[field.decode()] = value.decode()

                # Determine service health based on last heartbeat/registration

                try:
                    started_at = datetime.fromisoformat(service_info.get('started_at', ''))
                    time_since_start = datetime.now() - started_at

                    # Consider service healthy if registered recently (within 5 minutes)
                    is_healthy = time_since_start < timedelta(minutes=5)
                    if is_healthy:
                        healthy_services += 1

                    service_info['health_status'] = 'healthy' if is_healthy else 'stale'
                    service_info['uptime_seconds'] = int(time_since_start.total_seconds())
                except:
                    service_info['health_status'] = 'unknown'
                    service_info['uptime_seconds'] = 0

                services[service_type] = service_info

    except Exception as e:
        return {
            "status": "degraded",
            "error": f"Service discovery failed: {str(e)}",
            "redis_connected": True,
            "services": {}
        }

    # Count workers by type
    worker_types = {}
    api_services = []
    ui_services = []

    for service_type, service_info in services.items():
        if service_type.startswith('worker-'):
            worker_type = service_info.get('worker_type', 'unknown')
            if worker_type not in worker_types:
                worker_types[worker_type] = 0
            worker_types[worker_type] += 1
        elif service_type == 'api':
            api_services.append({
                'host': service_info.get('host', 'unknown'),
                'port': service_info.get('port', 'unknown'),
                'mode': service_info.get('mode', 'unknown'),
                'health_status': service_info.get('health_status', 'unknown')
            })
        elif service_type == 'ui':
            ui_services.append({
                'host': service_info.get('host', 'unknown'),
                'port': service_info.get('port', 'unknown'),
                'mode': service_info.get('mode', 'unknown'),
                'health_status': service_info.get('health_status', 'unknown')
            })

    # Overall cluster status
    if service_count == 0:
        cluster_status = "no_services"
    elif healthy_services == service_count:
        cluster_status = "healthy"
    elif healthy_services > 0:
        cluster_status = "degraded"
    else:
        cluster_status = "unhealthy"

    return {
        "status": cluster_status,
        "redis_connected": True,
        "cluster_info": {
            "total_services": service_count,
            "healthy_services": healthy_services,
            "api_instances": len(api_services),
            "ui_instances": len(ui_services),
            "worker_types": worker_types
        },
        "services": {
            "api": api_services,
            "ui": ui_services,
            "workers": {k: v for k, v in services.items() if k.startswith('worker-')}
        },
        "deployment_modes": list(set(s.get('mode', 'unknown') for s in services.values())),
        "timestamp": datetime.now().isoformat()
    }


@router.get("/coordination")
async def coordination_health_check(
    redis: aioredis.Redis = Depends(get_redis)
):
    """Get coordination mechanism health status (leader election, service registry, streams, sharding)"""
    import json
    import time

    # Retrieve health metrics from Redis (stored by HealthMonitorWorker)
    health_keys = await redis.keys("health:coordination:*")

    if not health_keys:
        return {
            "status": "unknown",
            "message": "Health monitor not running or no data available yet",
            "checks": {},
            "timestamp": time.time()
        }

    all_healthy = True
    checks = {}

    for key in health_keys:
        # Decode key if bytes
        key_str = key.decode() if isinstance(key, bytes) else key

        check_name = key_str.split(":")[-1]
        check_data = await redis.get(key_str)

        if check_data:
            # Decode if bytes
            if isinstance(check_data, bytes):
                check_data = check_data.decode()

            try:
                data = json.loads(check_data)
                checks[check_name] = data

                if not data.get('healthy', True):
                    all_healthy = False
            except json.JSONDecodeError:
                checks[check_name] = {
                    "healthy": False,
                    "issues": ["Failed to parse health check data"],
                    "timestamp": time.time()
                }
                all_healthy = False

    return {
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks,
        "timestamp": time.time()
    }
