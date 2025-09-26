"""Task management endpoints"""

import json
import logging
from typing import Dict, Optional, Tuple, List

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis

from ...core.sharding import default_sharding
from ..dependencies import get_redis, get_client_pool
from ..auth.dependencies import get_current_user_auto
from ..auth.models import User

router = APIRouter()
logger = logging.getLogger(__name__)


async def _find_task_state(redis: aioredis.Redis, task_id: str) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """Locate and decode the Redis hash that stores task state."""

    # First try to find the workflow ID for this task using the index
    workflow_id_bytes = await redis.hget(b"{shard:0}:index:task_workflow", task_id.encode())

    if workflow_id_bytes:
        # Found the workflow, now get its shard
        workflow_id = workflow_id_bytes.decode()
        shard_bytes = await redis.hget(b"{shard:0}:index:workflow_shards", workflow_id.encode())

        if shard_bytes:
            # Direct lookup using the shard - no scanning!
            shard = shard_bytes.decode()
            key = f"{{shard:{shard}}}:task:status:{task_id}"
            state_data = await redis.hgetall(key.encode())

            if state_data:
                decoded = {k.decode(): v.decode() for k, v in state_data.items()}

                # Parse JSON encoded fields when possible
                for field in ("result", "error"):
                    if field in decoded:
                        try:
                            decoded[field] = json.loads(decoded[field])
                        except json.JSONDecodeError:
                            pass

                return key, decoded

    # Fallback to scanning if indexes don't exist (for backward compatibility)
    pattern = f"*task:status:{task_id}"

    async for key in redis.scan_iter(match=pattern, count=100):
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
        task_ids: List[str] = []

        if workflow_id:
            # Direct lookup for workflow-specific tasks
            # First get the shard for this workflow
            shard_bytes = await conn.redis.hget(b"{shard:0}:index:workflow_shards", workflow_id.encode())

            if shard_bytes:
                shard = shard_bytes.decode()
                # Get dependency graph for this workflow
                graph_key = f"{{shard:{shard}}}:workflow:dependency:graph:{workflow_id}"
                graph_data = await conn.redis.hgetall(graph_key.encode())

                if graph_data:
                    for task_id_bytes in graph_data.keys():
                        task_id = task_id_bytes.decode()

                        # If we need to filter by status, check it
                        if status:
                            # Direct lookup using shard
                            task_key = f"{{shard:{shard}}}:task:status:{task_id}"
                            task_status = await conn.redis.hget(task_key.encode(), b"status")
                            if task_status and task_status.decode() == status:
                                task_ids.append(task_id)
                        else:
                            task_ids.append(task_id)
            else:
                # Fallback to scan if index doesn't exist
                graph_key_pattern = f"*:workflow:dependency:graph:{workflow_id}"
                async for key in conn.redis.scan_iter(match=graph_key_pattern.encode(), count=10):
                    graph_data = await conn.redis.hgetall(key)
                    for task_id_bytes in graph_data.keys():
                        task_id = task_id_bytes.decode()
                        if status:
                            task_pattern = f"*:task:status:{task_id}".encode()
                            async for task_key in conn.redis.scan_iter(match=task_pattern, count=10):
                                task_data = await conn.redis.hgetall(task_key)
                                if task_data.get(b"status", b"").decode() == status:
                                    task_ids.append(task_id)
                                break
                        else:
                            task_ids.append(task_id)
                    break
        else:
            # List all tasks across all workflows using indexes
            # Get all tasks from the task->workflow index
            all_task_mappings = await conn.redis.hgetall(b"{shard:0}:index:task_workflow")

            if all_task_mappings:
                # If filtering by status, we need to check each task
                if status:
                    # Group tasks by workflow for efficient batch lookup
                    workflow_tasks = {}
                    for task_id_bytes, wf_id_bytes in all_task_mappings.items():
                        wf_id = wf_id_bytes.decode()
                        if wf_id not in workflow_tasks:
                            workflow_tasks[wf_id] = []
                        workflow_tasks[wf_id].append(task_id_bytes.decode())

                    # Check status for each workflow's tasks
                    for wf_id, wf_task_ids in workflow_tasks.items():
                        # Get shard for this workflow
                        shard_bytes = await conn.redis.hget(b"{shard:0}:index:workflow_shards", wf_id.encode())
                        if shard_bytes:
                            shard = shard_bytes.decode()
                            # Batch check task statuses
                            pipe = conn.redis.pipeline()
                            for tid in wf_task_ids:
                                task_key = f"{{shard:{shard}}}:task:status:{tid}"
                                pipe.hget(task_key.encode(), b"status")

                            statuses = await pipe.execute()
                            for tid, task_status in zip(wf_task_ids, statuses):
                                if task_status and task_status.decode() == status:
                                    task_ids.append(tid)
                else:
                    # No status filter, return all task IDs
                    task_ids = [tid.decode() for tid in all_task_mappings.keys()]
            else:
                # Fallback to scanning if indexes don't exist
                pattern = b"*:task:status:*"
                seen_keys = set()
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


@router.get("/{task_id}/events")
async def get_task_events(
    task_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get task execution events for timeline view"""

    async with client_pool.acquire_connection(user.id) as conn:
        # First, get the workflow_id for this task
        state_key, state = await _find_task_state(conn.redis, task_id)
        if not state_key or not state:
            return {"task_id": task_id, "events": []}

        workflow_id = state.get("workflow_id")
        if not workflow_id:
            # If no workflow_id, create synthetic events from task state
            events = []

            # Add creation event if we have created_at
            if state.get("created_at"):
                events.append({
                    "event_type": "task_created",
                    "timestamp": state.get("created_at"),
                    "data": {"task_id": task_id, "status": "created"}
                })

            # Add execution start event
            if state.get("executed_at"):
                events.append({
                    "event_type": "task_started",
                    "timestamp": state.get("executed_at"),
                    "data": {"task_id": task_id, "status": "running"}
                })

            # Add completion or failure event
            if state.get("completed_at"):
                event_type = "task_completed" if state.get("status") == "completed" else f"task_{state.get('status', 'finished')}"
                event_data = {"task_id": task_id, "status": state.get("status", "unknown")}

                if state.get("result"):
                    event_data["result"] = state.get("result")
                if state.get("error"):
                    event_data["error"] = state.get("error")

                events.append({
                    "event_type": event_type,
                    "timestamp": state.get("completed_at"),
                    "data": event_data
                })

            return {"task_id": task_id, "events": events}

        # Look for events in the event stream
        events = []

        # Try to construct event stream key directly using sharding
        from ...core.sharding import default_sharding
        try:
            # Try the sharded key first (most likely pattern)
            shard_id = default_sharding.get_shard_id(workflow_id)
            direct_stream_key = f"{shard_id}:workflow:events:{workflow_id}"

            # Check if this key exists
            exists = await conn.redis.exists(direct_stream_key.encode())
            if exists:
                event_stream_key = direct_stream_key.encode()
            else:
                event_stream_key = None
        except Exception as e:
            logger.warning(f"Direct key lookup failed: {e}")
            event_stream_key = None

        # If direct lookup failed, fall back to scanning with timeout
        if not event_stream_key:
            stream_key_pattern = f"*:workflow:events:{workflow_id}".encode()
            try:
                # Use asyncio.wait_for to add timeout
                import asyncio
                async def scan_for_stream():
                    async for key in conn.redis.scan_iter(match=stream_key_pattern, count=50):
                        return key
                    return None

                event_stream_key = await asyncio.wait_for(scan_for_stream(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout scanning for event stream for workflow {workflow_id}")
                event_stream_key = None
            except Exception as e:
                logger.error(f"Error scanning for event stream: {e}")
                event_stream_key = None

        if event_stream_key:
            try:
                # Read events from the stream with timeout
                import asyncio
                stream_events = await asyncio.wait_for(
                    conn.redis.xrange(event_stream_key, min=b"-", max=b"+"),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout reading events from stream {event_stream_key}")
                stream_events = []
            except Exception as e:
                logger.error(f"Error reading events from stream: {e}")
                stream_events = []

            for event_id, event_data in stream_events:
                # Decode event data
                decoded_event = {}
                for key, value in event_data.items():
                    key_str = key.decode() if isinstance(key, bytes) else key
                    value_str = value.decode() if isinstance(value, bytes) else value

                    # Parse JSON fields
                    if key_str == "data":
                        try:
                            decoded_event[key_str] = json.loads(value_str)
                        except json.JSONDecodeError:
                            decoded_event[key_str] = value_str
                    else:
                        decoded_event[key_str] = value_str

                # Only include events for this task
                if decoded_event.get("task_id") == task_id:
                    events.append({
                        "event_id": event_id.decode() if isinstance(event_id, bytes) else event_id,
                        "event_type": decoded_event.get("event_type", "unknown"),
                        "timestamp": decoded_event.get("timestamp", ""),
                        "data": decoded_event.get("data", {}),
                        "level": decoded_event.get("level", "info")
                    })

        # If no events found in stream, create synthetic events from task state
        if not events:
            # Add basic state-based events
            if state.get("created_at"):
                events.append({
                    "event_type": "task_created",
                    "timestamp": state.get("created_at"),
                    "data": {"task_id": task_id, "status": "created"}
                })

            if state.get("executed_at"):
                events.append({
                    "event_type": "task_started",
                    "timestamp": state.get("executed_at"),
                    "data": {"task_id": task_id, "status": "running", "worker": state.get("worker_id")}
                })

            if state.get("completed_at"):
                event_type = "task_completed" if state.get("status") == "completed" else f"task_{state.get('status', 'finished')}"
                event_data = {"task_id": task_id, "status": state.get("status", "unknown")}

                if state.get("result"):
                    event_data["result"] = state.get("result")
                if state.get("error"):
                    event_data["error"] = state.get("error")

                events.append({
                    "event_type": event_type,
                    "timestamp": state.get("completed_at"),
                    "data": event_data
                })

        return {
            "task_id": task_id,
            "workflow_id": workflow_id,
            "event_count": len(events),
            "events": events
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
