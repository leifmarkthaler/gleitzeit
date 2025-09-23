"""Task management endpoints"""

import json
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis

from ...core.sharding import default_sharding

router = APIRouter()


async def _find_task_state(redis: aioredis.Redis, task_id: str) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """Locate and decode the Redis hash that stores task state."""

    pattern = f"*task:status:{task_id}".encode()
    cursor: bytes = b"0"

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            state_data = await redis.hgetall(key)
            if not state_data:
                continue

            decoded = {k.decode(): v.decode() for k, v in state_data.items()}

            # Parse JSON encoded fields when possible
            for field in ("result", "error"):
                if field in decoded:
                    try:
                        decoded[field] = json.loads(decoded[field])
                    except json.JSONDecodeError:
                        pass

            return key.decode(), decoded

        if cursor == b"0":
            break

    return None, None


def _decode_logs(entries):
    decoded = []
    for entry in entries:
        try:
            decoded.append(json.loads(entry.decode()))
        except json.JSONDecodeError:
            decoded.append({"message": entry.decode()})
    return decoded


def _find_task_definition(workflow: Dict[str, Dict], task_id: str) -> Optional[Dict]:
    for task in workflow.get("tasks", []):
        if task.get("id") == task_id or task.get("name") == task_id:
            return task
    return None


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get task status and details"""

    state_key, state = await _find_task_state(redis, task_id)
    if not state_key or not state:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "workflow_id": state.get("workflow_id"),
        "state": state,
    }


@router.get("/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get task execution logs"""

    # Logs are optional; they may be stored under {shard}:task:logs:{task_id}
    pattern = f"*task:logs:{task_id}".encode()
    cursor = b"0"
    logs = []

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        if keys:
            logs = await redis.lrange(keys[0], 0, -1)
            break
        if cursor == b"0":
            break

    if not logs:
        return {"task_id": task_id, "logs": []}

    return {
        "task_id": task_id,
        "log_count": len(logs),
        "logs": _decode_logs(logs)
    }


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Submit task for retry"""

    task_state_key, state = await _find_task_state(redis, task_id)

    if not task_state_key or not state:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check if task is in retryable state
    status = state.get("status", "")
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

    workflow_id = state.get("workflow_id")
    if not workflow_id:
        raise HTTPException(status_code=400, detail="Workflow ID missing for task")

    workflow_data = await redis.hget(
        default_sharding.get_workflow_key("data", workflow_id).encode(),
        b"workflow"
    )

    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow definition not found")

    workflow = json.loads(workflow_data)
    task_definition = _find_task_definition(workflow, task_id)

    if not task_definition:
        raise HTTPException(status_code=404, detail="Task definition not found in workflow")

    # Submit to retry stream
    stream_key = default_sharding.get_stream_key("task:retry", workflow_id)
    await redis.xadd(
        stream_key.encode(),
        {
            b"task_id": task_id.encode(),
            b"workflow_id": workflow_id.encode(),
            b"task": json.dumps(task_definition).encode(),
            b"retry_reason": b"manual_retry",
            b"previous_status": status.encode()
        }
    )

    # Update task state
    await redis.hset(
        task_state_key.encode(),
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

    task_state_key, state = await _find_task_state(redis, task_id)

    if not task_state_key or not state:
        raise HTTPException(status_code=404, detail="Task not found")

    status = state.get("status", "")
    if status in ["completed", "failed", "cancelled", "blocked"]:
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be cancelled in status: {status}"
        )

    workflow_id = state.get("workflow_id")
    if not workflow_id:
        raise HTTPException(status_code=400, detail="Workflow ID missing for task")

    # Update task state to cancelled
    await redis.hset(
        task_state_key.encode(),
        mapping={
            b"status": b"cancelled",
            b"cancelled_at": datetime.utcnow().isoformat().encode(),
            b"cancelled_reason": b"user_requested"
        }
    )

    # Add to workflow's cancelled tasks set
    await redis.sadd(
        default_sharding.get_workflow_key("tasks:cancelled", workflow_id).encode(),
        task_id.encode()
    )

    # Emit cancellation event to stream (similar to blocked)
    stream_key = default_sharding.get_stream_key("task:cancelled", workflow_id)
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
