"""
Task management endpoints
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis

from ...core.sharding import default_sharding

router = APIRouter()


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get task status and details"""

    # Get task state
    state_key = default_sharding.get_task_key("state", task_id)
    state_data = await redis.hgetall(state_key.encode())

    if not state_data:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get task result if available
    result_key = default_sharding.get_task_key("result", task_id)
    result_data = await redis.hgetall(result_key.encode())

    # Decode and combine
    task_info = {
        "task_id": task_id,
        "state": {k.decode(): v.decode() for k, v in state_data.items()},
    }

    if result_data:
        task_info["result"] = {
            k.decode(): json.loads(v.decode()) if k in [b"result", b"error"] else v.decode()
            for k, v in result_data.items()
        }

    return task_info


@router.get("/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get task execution logs"""

    # Get logs from Redis list
    logs_key = default_sharding.get_task_key("logs", task_id)
    logs = await redis.lrange(logs_key.encode(), 0, -1)

    if not logs:
        return {"task_id": task_id, "logs": []}

    # Decode logs
    decoded_logs = []
    for log_entry in logs:
        try:
            decoded_logs.append(json.loads(log_entry.decode()))
        except:
            decoded_logs.append({"message": log_entry.decode()})

    return {
        "task_id": task_id,
        "log_count": len(decoded_logs),
        "logs": decoded_logs
    }


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Submit task for retry"""

    # Check task exists
    state_key = default_sharding.get_task_key("state", task_id)
    state_data = await redis.hgetall(state_key.encode())

    if not state_data:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check if task is in retryable state
    status = state_data.get(b"status", b"").decode()
    # Don't allow retry of cancelled or blocked tasks (same behavior)
    if status not in ["failed", "error", "timeout"]:
        if status in ["cancelled", "blocked"]:
            raise HTTPException(
                status_code=400,
                detail=f"Task cannot be retried - it was {status}"
            )
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be retried in status: {status}"
        )

    # Get task data
    data_key = default_sharding.get_task_key("data", task_id)
    task_data = await redis.hget(data_key.encode(), b"task")

    if not task_data:
        raise HTTPException(status_code=404, detail="Task data not found")

    # Submit to retry stream
    stream_key = default_sharding.get_stream_key("task:retry", task_id)
    await redis.xadd(
        stream_key.encode(),
        {
            b"task_id": task_id.encode(),
            b"task": task_data,
            b"retry_reason": b"manual_retry",
            b"previous_status": status.encode()
        }
    )

    # Update task state
    await redis.hset(
        state_key.encode(),
        mapping={
            b"status": b"retrying",
            b"retry_requested": b"true"
        }
    )

    return {
        "task_id": task_id,
        "status": "retrying",
        "message": "Task submitted for retry"
    }


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Cancel a task"""
    from datetime import datetime

    # Check task exists
    state_key = default_sharding.get_task_key("state", task_id)
    state_data = await redis.hgetall(state_key.encode())

    if not state_data:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check if task is in cancellable state
    status = state_data.get(b"status", b"").decode()
    if status in ["completed", "failed", "cancelled", "blocked"]:
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be cancelled in status: {status}"
        )

    # Get workflow_id from state data
    workflow_id = state_data.get(b"workflow_id", b"").decode()
    if not workflow_id:
        # Try to extract from task_id pattern if not in state
        parts = task_id.split("_")
        if len(parts) > 1:
            workflow_id = parts[0]

    # Update task state to cancelled
    await redis.hset(
        state_key.encode(),
        mapping={
            b"status": b"cancelled",
            b"cancelled_at": datetime.utcnow().isoformat().encode(),
            b"cancelled_reason": b"user_requested"
        }
    )

    # Add to workflow's cancelled tasks set
    if workflow_id:
        await redis.sadd(
            default_sharding.get_workflow_key("tasks:cancelled", workflow_id).encode(),
            task_id.encode()
        )

        # Emit cancellation event to stream (similar to blocked)
        stream_key = default_sharding.get_stream_key("task:cancelled", task_id)
        await redis.xadd(
            stream_key.encode(),
            {
                b"task_id": task_id.encode(),
                b"workflow_id": workflow_id.encode(),
                b"reason": b"user_requested",
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

    return {
        "task_id": task_id,
        "status": "cancelled",
        "message": "Task cancellation requested"
    }


# Fix circular import
from ..main import app