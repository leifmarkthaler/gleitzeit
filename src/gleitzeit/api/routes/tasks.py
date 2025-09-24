"""Task management endpoints"""

import json
from typing import Dict, Optional, Tuple, List

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis

from ...core.sharding import default_sharding
from ..dependencies import get_redis, get_client_pool
from ..auth.dependencies import get_current_user_auto
from ..auth.models import User

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


@router.get("/list")
async def list_task_ids(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    workflow_id: Optional[str] = None,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """List task identifiers with optional filtering"""

    async with client_pool.acquire_connection(user.id) as conn:
        # If filtering by workflow_id, use the dependency graph for efficiency
        if workflow_id:
            # Get tasks from the dependency graph
            graph_key_pattern = f"*:workflow:dependency:graph:{workflow_id}"
            task_ids = []

            # Find the dependency graph key
            async for key in conn.redis.scan_iter(match=graph_key_pattern.encode(), count=10):
                # Get all task IDs from the graph (they are the hash fields)
                graph_data = await conn.redis.hgetall(key)

                for task_id_bytes in graph_data.keys():
                    task_id = task_id_bytes.decode()

                    # If we also need to filter by status, check it
                    if status:
                        # Find the task status key
                        task_pattern = f"*:task:status:{task_id}".encode()
                        task_found = False
                        async for task_key in conn.redis.scan_iter(match=task_pattern, count=10):
                            task_data = await conn.redis.hgetall(task_key)
                            if task_data.get(b"status", b"").decode() == status:
                                task_ids.append(task_id)
                            task_found = True
                            break
                        # If task not found in Redis, skip it
                    else:
                        task_ids.append(task_id)
                break  # Should only be one graph key
        else:
            # Original scan approach for other filters
            pattern = b"*:task:status:*"
            task_ids: List[str] = []
            seen_keys = set()  # Track seen keys to avoid duplicates

            # Use scan_iter which handles the cursor internally
            async for key in conn.redis.scan_iter(match=pattern, count=200):
                if key in seen_keys:
                    continue  # Skip already processed keys
                seen_keys.add(key)

                task_id = key.decode().split(':')[-1]

                # Apply filters
                if status or workflow_id:
                    task_data = await conn.redis.hgetall(key)
                    if task_data:
                        if status and task_data.get(b"status", b"").decode() != status:
                            continue
                        if workflow_id and task_data.get(b"workflow_id", b"").decode() != workflow_id:
                            continue

                task_ids.append(task_id)

    total = len(task_ids)
    paginated = task_ids[offset: offset + limit]

    return {
        "task_ids": paginated,
        "total": total,
        "limit": limit,
        "offset": offset
    }


from pydantic import BaseModel, Field

class TasksRequest(BaseModel):
    """Request model for getting multiple tasks"""
    task_ids: List[str] = Field(..., description="List of task IDs to retrieve")

@router.post("/")
async def get_tasks(
    request: TasksRequest,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get data for multiple tasks by their IDs"""

    async with client_pool.acquire_connection(user.id) as conn:
        tasks = []
        for task_id in request.task_ids[:100]:  # Limit to 100 tasks at once
            # Find the task state key
            state_key, state = await _find_task_state(conn.redis, task_id)

            if not state_key or not state:
                continue  # Skip missing tasks

            task_info = {
                "task_id": task_id,
                **state
            }
            tasks.append(task_info)

        return {
            "tasks": tasks,
            "requested": len(request.task_ids),
            "found": len(tasks)
        }


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get task status and details"""

    async with client_pool.acquire_connection(user.id) as conn:
        state_key, state = await _find_task_state(conn.redis, task_id)
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
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get task execution logs"""

    async with client_pool.acquire_connection(user.id) as conn:
        # Logs are optional; they may be stored under {shard}:task:logs:{task_id}
        pattern = f"*task:logs:{task_id}".encode()
        cursor = b"0"
        logs = []

        while True:
            cursor, keys = await conn.redis.scan(cursor, match=pattern, count=100)
            if keys:
                logs = await conn.redis.lrange(keys[0], 0, -1)
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
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Submit task for retry"""

    async with client_pool.acquire_connection(user.id) as conn:
        task_state_key, state = await _find_task_state(conn.redis, task_id)

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

        workflow_data = await conn.redis.hget(
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
        await conn.redis.xadd(
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
        await conn.redis.hset(
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
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Cancel a task"""
    from datetime import datetime

    async with client_pool.acquire_connection(user.id) as conn:
        task_state_key, state = await _find_task_state(conn.redis, task_id)

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
        await conn.redis.hset(
            task_state_key.encode(),
            mapping={
                b"status": b"cancelled",
                b"cancelled_at": datetime.utcnow().isoformat().encode(),
                b"cancelled_reason": b"user_requested"
            }
        )

        # Add to workflow's cancelled tasks set
        await conn.redis.sadd(
            default_sharding.get_workflow_key("tasks:cancelled", workflow_id).encode(),
            task_id.encode()
        )

        # Emit cancellation event to stream (similar to blocked)
        stream_key = default_sharding.get_stream_key("task:cancelled", workflow_id)
        await conn.redis.xadd(
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
