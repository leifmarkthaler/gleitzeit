"""
System monitoring and management endpoints
"""

import json
from typing import Dict, Any

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
        orch_keys = await redis.keys(b"orchestrator:*")
        for key in orch_keys:
            if key.endswith(b":metrics"):
                metrics = await redis.hget(key, b"latest")
                if metrics:
                    status["orchestrator"]["metrics"] = json.loads(metrics.decode())

        # Check worker statuses
        worker_keys = await redis.keys(b"{shard:*}:worker:*")
        for key in worker_keys:
            key_str = key.decode()
            if "metrics" in key_str:
                worker_id = key_str.split(":")[-1]
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
        workflow_keys = await redis.keys(b"{shard:*}:workflow:*:state")
        for key in workflow_keys:
            status = await redis.hget(key, b"status")
            if status:
                metrics["workflows"]["total"] += 1
                status_str = status.decode()
                if status_str == "running":
                    metrics["workflows"]["running"] += 1
                elif status_str == "completed":
                    metrics["workflows"]["completed"] += 1
                elif status_str == "failed":
                    metrics["workflows"]["failed"] += 1

        # Count tasks by status
        task_keys = await redis.keys(b"{shard:*}:task:*:state")
        for key in task_keys:
            status = await redis.hget(key, b"status")
            if status:
                metrics["tasks"]["total"] += 1
                status_str = status.decode()
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
        # Find all worker registration keys
        worker_keys = await redis.keys(b"{shard:*}:worker:*")

        for key in worker_keys:
            key_str = key.decode()
            # Skip metrics keys
            if "metrics" in key_str:
                continue

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


# Fix circular import
from ..main import app