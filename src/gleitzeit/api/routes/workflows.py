"""
Workflow submission and management endpoints
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Response
from pydantic import BaseModel, Field

from ...core.sharding import default_sharding
from ..dependencies import get_client_pool
from ..auth.dependencies import get_current_user_auto
from ..auth.models import User

logger = logging.getLogger(__name__)
router = APIRouter()


class WorkflowSubmitRequest(BaseModel):
    """Workflow submission request"""
    workflow: Dict[str, Any] = Field(..., description="Workflow definition")
    workflow_id: Optional[str] = Field(None, description="Optional workflow ID")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional metadata")


class WorkflowSubmitResponse(BaseModel):
    """Workflow submission response"""
    workflow_id: str
    status: str
    message: str
    submitted_at: str


@router.get("/list")
async def list_workflows(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """List workflows with full details"""

    async with client_pool.acquire_connection(user.id) as conn:
        workflows = []

        # Use per-shard indexes instead of scanning
        for shard in range(16):
            index_key = f"{{shard:{shard}}}:index:workflows"
            workflow_ids = await conn.redis.smembers(index_key.encode())

            if not workflow_ids:
                continue

            # Use pipeline for efficient batch fetching
            pipe = conn.redis.pipeline()
            for wf_id_bytes in workflow_ids:
                workflow_id = wf_id_bytes.decode()

                # Get consolidated workflow state
                state_key = default_sharding.get_workflow_key("state", workflow_id)
                pipe.hgetall(state_key.encode())

                # Get workflow definition (if needed for details)
                data_key = default_sharding.get_workflow_key("data", workflow_id)
                pipe.hget(data_key.encode(), b"workflow")

            # Execute pipeline and process results in groups of 2
            results = await pipe.execute()
            workflow_ids_list = list(workflow_ids)

            for i in range(0, len(results), 2):
                state_data = results[i]
                workflow_data = results[i + 1]

                if not state_data:
                    continue

                workflow_id = workflow_ids_list[i // 2].decode()

                # Decode consolidated state data
                decoded_state = {k.decode(): v.decode() for k, v in state_data.items()}

                # Get status from consolidated state
                status_value = decoded_state.get("status", "unknown")

                workflow_info = {
                    "workflow_id": workflow_id,
                    "name": decoded_state.get("name", "Unnamed"),
                    "status": status_value,
                    "created_at": decoded_state.get("submitted_at", ""),
                    "description": decoded_state.get("description", ""),
                    "version": decoded_state.get("version", ""),
                    "progress": {}
                }

                # Add task count from workflow definition if available
                if workflow_data:
                    try:
                        data = json.loads(workflow_data)
                        workflow_info["task_count"] = len(data.get("tasks", []))
                    except json.JSONDecodeError:
                        pass
                else:
                    # Use total_tasks from state if definition not available
                    workflow_info["task_count"] = int(decoded_state.get("total_tasks", 0))

                # Use task counts from consolidated state
                completed_count = int(decoded_state.get("completed_tasks", 0))
                failed_count = int(decoded_state.get("failed_tasks", 0))
                skipped_count = int(decoded_state.get("skipped_tasks", 0))
                blocked_count = int(decoded_state.get("blocked_tasks", 0))
                running_count = int(decoded_state.get("running_tasks", 0))
                total_count = int(decoded_state.get("total_tasks", 0))

                workflow_info["progress"] = {
                    "total": total_count,
                    "completed": completed_count,
                    "failed": failed_count,
                    "running": running_count
                }

                # Apply status filter if specified
                if not status or workflow_info["status"] == status:
                    workflows.append(workflow_info)

    # Sort by creation time (most recent first)
    workflows.sort(key=lambda w: w.get("created_at", ""), reverse=True)

    total = len(workflows)
    paginated = workflows[offset: offset + limit]

    return {
        "workflows": paginated,
        "total": total,
        "limit": limit,
        "offset": offset
    }


from pydantic import BaseModel, Field

class WorkflowsRequest(BaseModel):
    """Request model for getting multiple workflows"""
    workflow_ids: List[str] = Field(..., description="List of workflow IDs to retrieve")

@router.post("/")
async def get_workflows(
    request: WorkflowsRequest,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get data for multiple workflows by their IDs"""

    async with client_pool.acquire_connection(user.id) as conn:
        workflows = []
        for workflow_id in request.workflow_ids[:100]:  # Limit to 100 workflows at once
            # Get consolidated workflow state
            state_key = default_sharding.get_workflow_key("state", workflow_id)
            state_data = await conn.redis.hgetall(state_key.encode())

            if not state_data:
                continue  # Skip missing workflows

            # Get workflow data
            data_key = default_sharding.get_workflow_key("data", workflow_id)
            workflow_data = await conn.redis.hget(data_key.encode(), b"workflow")

            workflow_info = {
                "workflow_id": workflow_id,
                "status": {k.decode(): v.decode() for k, v in state_data.items()}
            }

            if workflow_data:
                data = json.loads(workflow_data)
                workflow_info["name"] = data.get("name", "Unnamed")
                workflow_info["description"] = data.get("description", "")
                workflow_info["task_count"] = len(data.get("tasks", []))
                workflow_info["version"] = data.get("version", "")

            workflows.append(workflow_info)

        return {
            "workflows": workflows,
            "requested": len(request.workflow_ids),
            "found": len(workflows)
        }


class WorkflowValidateRequest(BaseModel):
    """Workflow validation request"""
    workflow: Dict[str, Any] = Field(..., description="Workflow definition to validate")


@router.post("/validate")
async def validate_workflow(
    request: WorkflowValidateRequest,
    user: User = Depends(get_current_user_auto)
):
    """
    Validate a workflow definition without submitting it.
    Uses the actual WorkflowLoaderWorkerV2 transform and validation logic.
    """
    from ...workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
    from ...workers.base import WorkerConfig
    import uuid

    try:
        # Create minimal worker config for validation
        # We don't need Redis connection for transform/validate
        config = WorkerConfig(
            worker_type="workflow_loader",
            worker_id="validation_worker",
            consumer_group="validation",
            redis_url="redis://localhost:6379",  # Not used for validation
            batch_size=1
        )

        # Create worker instance for validation
        worker = WorkflowLoaderWorkerV2(config)

        # Generate temporary workflow ID for validation
        workflow_id = f"validation_{uuid.uuid4().hex[:12]}"

        # Transform raw workflow (this is what the actual worker does)
        transformed_workflow = await worker.transform_workflow(request.workflow, workflow_id)

        # Validate transformed workflow (this is what the actual worker does)
        validation_errors = worker.validate_workflow(transformed_workflow)

        if validation_errors:
            return {
                "valid": False,
                "errors": validation_errors
            }

        # Get workflow summary
        tasks = transformed_workflow.get('tasks', [])
        has_dependencies = any(
            task.get('dependencies')
            for task in tasks
        )

        summary = {
            'name': transformed_workflow.get('name', 'Unnamed'),
            'task_count': len(tasks),
            'has_dependencies': has_dependencies
        }

        return {
            "valid": True,
            "message": "Workflow validation passed",
            "summary": summary
        }

    except Exception as e:
        return {
            "valid": False,
            "errors": [f"Validation error: {str(e)}"]
        }


@router.post("/submit", response_model=WorkflowSubmitResponse)
async def submit_workflow(
    request: WorkflowSubmitRequest,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """
    Submit a workflow for execution.

    The workflow is submitted to the workflow:load stream where it will be:
    1. Picked up by WorkflowLoaderWorker for validation
    2. If valid, forwarded to workflow:submitted stream
    3. Processed by DependencyWorker to create tasks
    4. Tasks executed by TaskExecutionWorker
    """
    async with client_pool.acquire_connection(user.id) as conn:
        # Generate workflow ID if not provided
        workflow_id = request.workflow_id or str(uuid.uuid4())

        # Add workflow ID to the workflow if not present
        if "workflow_id" not in request.workflow:
            request.workflow["workflow_id"] = workflow_id

        # Add user information to metadata
        metadata = request.metadata.copy() if request.metadata else {}
        metadata["user_id"] = user.id
        metadata["username"] = user.username

        # Prepare submission data
        submission_data = {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(request.workflow).encode(),
            b"metadata": json.dumps(metadata).encode(),
            b"submitted_at": datetime.utcnow().isoformat().encode(),
            b"source": b"api",
            b"user_id": user.id.encode()
        }

        try:
            # Submit to workflow:load stream (sharded by workflow_id)
            stream_key = default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id)

            # Add to stream
            message_id = await conn.redis.xadd(
                stream_key.encode(),
                submission_data
            )

            # Store initial workflow state
            workflow_key = default_sharding.get_workflow_key("state", workflow_id)
            await conn.redis.hset(
                workflow_key.encode(),
                mapping={
                    b"workflow_id": workflow_id.encode(),
                    b"status": b"submitted",
                    b"submitted_at": datetime.utcnow().isoformat().encode(),
                    b"stream_message_id": message_id,
                    b"user_id": user.id.encode()
                }
            )

            return WorkflowSubmitResponse(
                workflow_id=workflow_id,
                status="submitted",
                message=f"Workflow submitted to stream {stream_key}",
                submitted_at=datetime.utcnow().isoformat()
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to submit workflow: {str(e)}")


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get workflow status and details"""

    async with client_pool.acquire_connection(user.id) as conn:
        # Get consolidated workflow state
        state_key = default_sharding.get_workflow_key("state", workflow_id)
        state_data = await conn.redis.hgetall(state_key.encode())

        if not state_data:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Get workflow data
        data_key = default_sharding.get_workflow_key("data", workflow_id)
        workflow_data = await conn.redis.hgetall(data_key.encode())

        # Decode and combine
        result = {
            "workflow_id": workflow_id,
            "state": {k.decode(): v.decode() for k, v in state_data.items()},
        }

        if workflow_data:
            result["data"] = {
                k.decode(): json.loads(v.decode()) if k == b"workflow" else v.decode()
                for k, v in workflow_data.items()
            }

        return result


@router.get("/{workflow_id}/tasks")
async def get_workflow_tasks(
    workflow_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get all tasks for a workflow"""

    async with client_pool.acquire_connection(user.id) as conn:
        # Use index to get shard directly
        shard_bytes = await conn.redis.hget(b"{shard:0}:index:workflow_shards", workflow_id.encode())

        task_ids = set()

        if shard_bytes:
            # Direct lookup using shard - no scanning!
            shard = shard_bytes.decode()
            graph_key = f"{{shard:{shard}}}:workflow:dependency:graph:{workflow_id}"
            graph_data = await conn.redis.hgetall(graph_key.encode())

            if graph_data:
                task_ids = set(graph_data.keys())
            else:
                # Fallback to workflow:tasks set
                task_list_key = default_sharding.get_workflow_key("tasks", workflow_id)
                task_ids = await conn.redis.smembers(task_list_key.encode())
        else:
            # Fallback to scanning if index doesn't exist
            graph_key_pattern = f"*:workflow:dependency:graph:{workflow_id}".encode()
            graph_found = False
            async for key in conn.redis.scan_iter(match=graph_key_pattern, count=10):
                graph_data = await conn.redis.hgetall(key)
                for task_id_bytes in graph_data.keys():
                    task_ids.add(task_id_bytes)
                graph_found = True
                break

            if not graph_found:
                task_list_key = default_sharding.get_workflow_key("tasks", workflow_id)
                task_ids = await conn.redis.smembers(task_list_key.encode())

        if not task_ids:
            return {"workflow_id": workflow_id, "tasks": []}

        # Get workflow definition to look up task names
        workflow_data_key = default_sharding.get_workflow_key("data", workflow_id)
        workflow_data_raw = await conn.redis.hget(workflow_data_key.encode(), b"workflow")

        task_id_to_name = {}
        if workflow_data_raw:
            try:
                workflow_def = json.loads(workflow_data_raw.decode())
                # Build map of task ID to task name
                for task in workflow_def.get("tasks", []):
                    if "id" in task and "name" in task:
                        task_id_to_name[task["id"]] = task["name"]
            except (json.JSONDecodeError, AttributeError):
                pass

        # Get task details
        tasks = []
        for task_id_bytes in task_ids:
            task_id = task_id_bytes.decode()
            task_key = default_sharding.get_task_key(task_id, workflow_id)
            task_data = await conn.redis.hgetall(task_key.encode())

            if task_data:
                decoded = {k.decode(): v.decode() for k, v in task_data.items()}
                for field in ("result", "error"):
                    if field in decoded:
                        try:
                            decoded[field] = json.loads(decoded[field])
                        except json.JSONDecodeError:
                            pass

                # Add task name from workflow definition if available
                task_obj = {
                    "task_id": task_id,
                    **decoded
                }
                if task_id in task_id_to_name:
                    task_obj["name"] = task_id_to_name[task_id]

                tasks.append(task_obj)

        return {
            "workflow_id": workflow_id,
            "task_count": len(tasks),
            "tasks": tasks
        }


@router.get("/{workflow_id}/tasks/{task_id}/dependencies")
async def get_task_dependencies(
    workflow_id: str,
    task_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get dependencies for a specific task in a workflow"""

    async with client_pool.acquire_connection(user.id) as conn:
        # Get workflow data
        data_key = default_sharding.get_workflow_key("data", workflow_id)
        workflow_data = await conn.redis.hget(data_key.encode(), b"workflow")

        if not workflow_data:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow = json.loads(workflow_data)
        tasks = workflow.get("tasks", [])

        # Find the task and its dependencies
        for task in tasks:
            if task.get("name") == task_id or task.get("id") == task_id:
                return {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "dependencies": task.get("dependencies", [])
                }

        raise HTTPException(status_code=404, detail="Task not found in workflow")


@router.get("/{workflow_id}/tasks/{task_id}/dependents")
async def get_task_dependents(
    workflow_id: str,
    task_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get tasks that depend on a specific task"""

    async with client_pool.acquire_connection(user.id) as conn:
        # Get workflow data
        data_key = default_sharding.get_workflow_key("data", workflow_id)
        workflow_data = await conn.redis.hget(data_key.encode(), b"workflow")

        if not workflow_data:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow = json.loads(workflow_data)
        tasks = workflow.get("tasks", [])

        # Find all tasks that depend on this task
        dependents = []
        for task in tasks:
            task_name = task.get("name", task.get("id", ""))
            dependencies = task.get("dependencies", [])
            if task_id in dependencies:
                dependents.append(task_name)

        return {
            "task_id": task_id,
            "workflow_id": workflow_id,
            "dependents": dependents
        }


@router.post("/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Cancel a running workflow and all its tasks"""

    async with client_pool.acquire_connection(user.id) as conn:
        # Update workflow state
        state_key = default_sharding.get_workflow_key("state", workflow_id)
        exists = await conn.redis.exists(state_key.encode())

        if not exists:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Set workflow cancellation status
        await conn.redis.hset(
            state_key.encode(),
            mapping={
                b"status": b"cancelled",
                b"cancelled_at": datetime.utcnow().isoformat().encode(),
                b"cancelled_reason": b"user_requested"
            }
        )

        # Emit workflow cancellation event to stream
        workflow_stream_key = default_sharding.get_stream_key("workflow:cancelled", workflow_id)
        await conn.redis.xadd(
            workflow_stream_key.encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"reason": b"user_requested",
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        # Get all tasks for this workflow
        tasks_key = default_sharding.get_workflow_key("tasks", workflow_id)
        task_ids = await conn.redis.smembers(tasks_key.encode())

        cancelled_count = 0
        for task_id_bytes in task_ids:
            task_id = task_id_bytes.decode()
            task_state_key = default_sharding.get_task_key(task_id, workflow_id)
            task_state = await conn.redis.hgetall(task_state_key.encode())

            if task_state:
                status = task_state.get(b"status", b"").decode()
                # Only cancel tasks that are not in terminal states
                if status not in ["completed", "failed", "cancelled", "blocked"]:
                    # Update task state to cancelled
                    await conn.redis.hset(
                        task_state_key.encode(),
                        mapping={
                            b"status": b"cancelled",
                            b"cancelled_at": datetime.utcnow().isoformat().encode(),
                            b"cancelled_reason": b"workflow_cancelled"
                        }
                    )

                    # Add to workflow's cancelled tasks set
                    await conn.redis.sadd(
                        default_sharding.get_workflow_key("tasks:cancelled", workflow_id).encode(),
                        task_id.encode()
                    )

                    # Emit task cancellation event
                    task_stream_key = default_sharding.get_stream_key("task:cancelled", workflow_id)
                    await conn.redis.xadd(
                        task_stream_key.encode(),
                        {
                            b"task_id": task_id.encode(),
                            b"workflow_id": workflow_id.encode(),
                            b"reason": b"workflow_cancelled",
                            b"timestamp": datetime.utcnow().isoformat().encode()
                        }
                    )
                    cancelled_count += 1

        return {
            "workflow_id": workflow_id,
            "status": "cancelled",
            "tasks_cancelled": cancelled_count,
            "message": f"Workflow cancelled successfully, {cancelled_count} tasks were cancelled"
        }


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """
    Delete a workflow and all its associated data from Redis.

    This permanently removes:
    - Workflow state
    - Workflow data
    - All task data
    - Workflow from status indices

    Use with caution - this operation cannot be undone.
    """

    async with client_pool.acquire_connection(user.id) as conn:
        # Get workflow state to check if it exists
        state_key = default_sharding.get_workflow_key("state", workflow_id)
        workflow_state = await conn.redis.hgetall(state_key.encode())

        if not workflow_state:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Get shard for cleanup operations
        shard = default_sharding.get_shard(workflow_id)

        # Get workflow status for index cleanup
        status_bytes = workflow_state.get(b'status', b'unknown')
        workflow_status = status_bytes.decode() if isinstance(status_bytes, bytes) else str(status_bytes)

        deleted_keys = []

        # 1. Delete workflow state
        await conn.redis.delete(state_key.encode())
        deleted_keys.append(state_key)

        # 2. Delete workflow data
        data_key = default_sharding.get_workflow_key("data", workflow_id)
        await conn.redis.delete(data_key.encode())
        deleted_keys.append(data_key)

        # 3. Get and delete all tasks
        tasks_key = default_sharding.get_workflow_key("tasks", workflow_id)
        task_ids = await conn.redis.smembers(tasks_key.encode())

        deleted_tasks = 0
        for task_id_bytes in task_ids:
            task_id = task_id_bytes.decode()
            task_state_key = default_sharding.get_task_key(task_id, workflow_id)
            await conn.redis.delete(task_state_key.encode())
            deleted_tasks += 1

        # Delete tasks set
        await conn.redis.delete(tasks_key.encode())

        # 4. Remove from status indices (all possible statuses)
        status_indices = ['running', 'waiting', 'completed', 'failed', 'scheduled', 'cancelled']
        for status in status_indices:
            index_key = f"{{shard:{shard}}}:workflows:by_status:{status}"
            await conn.redis.zrem(index_key.encode(), workflow_id.encode())

        # 5. Remove from shard indices
        # Remove from per-shard workflow index (used by list endpoint)
        shard_index_key = f"{{shard:{shard}}}:index:workflows"
        await conn.redis.srem(shard_index_key.encode(), workflow_id.encode())

        # Remove from workflow shard mapping (used by get_workflow_tasks)
        await conn.redis.hdel(b"{shard:0}:index:workflow_shards", workflow_id.encode())

        # 5. Delete task status sets (running, completed, pending, etc.)
        task_status_sets = [
            f"{{shard:{shard}}}:workflow:tasks:running:{workflow_id}",
            f"{{shard:{shard}}}:workflow:tasks:completed:{workflow_id}",
            f"{{shard:{shard}}}:workflow:tasks:pending:{workflow_id}",
            f"{{shard:{shard}}}:workflow:tasks:failed:{workflow_id}",
            f"{{shard:{shard}}}:workflow:tasks:waiting:{workflow_id}",
            f"{{shard:{shard}}}:workflow:tasks:blocked:{workflow_id}",
            f"{{shard:{shard}}}:workflow:tasks:skipped:{workflow_id}"
        ]

        for set_key in task_status_sets:
            await conn.redis.delete(set_key.encode())

        # 6. Delete any streams related to this workflow
        stream_keys = [
            default_sharding.get_stream_key("workflow:completed", workflow_id),
            default_sharding.get_stream_key("workflow:failed", workflow_id),
            default_sharding.get_stream_key("workflow:cancelled", workflow_id),
        ]

        for stream_key in stream_keys:
            await conn.redis.delete(stream_key.encode())

        return {
            "workflow_id": workflow_id,
            "status": "deleted",
            "deleted_tasks": deleted_tasks,
            "deleted_keys": len(deleted_keys) + deleted_tasks + len(task_status_sets) + len(stream_keys),
            "message": f"Workflow and all associated data deleted successfully"
        }


@router.get("/{workflow_id}/events")
async def get_workflow_events(
    workflow_id: str,
    user: User = Depends(get_current_user_auto),
    client_pool = Depends(get_client_pool)
):
    """Get workflow and task execution events for timeline view (no cache)"""

    async with client_pool.acquire_connection(user.id) as conn:
        # Look for events in the event stream
        events = []

        # Try to construct event stream key directly using sharding
        try:
            # Try the sharded key first (most likely pattern)
            shard = default_sharding.get_shard(workflow_id)
            direct_stream_key = f"{{shard:{shard}}}:workflow:events:{workflow_id}"

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
                logger.warning(f"Timeout while scanning for event stream for workflow {workflow_id}")
                event_stream_key = None
            except Exception as e:
                logger.warning(f"Error scanning for event stream: {e}")
                event_stream_key = None

        # Read events from the stream if found
        if event_stream_key:
            try:
                # Read all events from the stream (limit to last 100)
                stream_data = await conn.redis.xrevrange(
                    event_stream_key,
                    count=100
                )

                for msg_id, data in stream_data:
                    try:
                        # Parse event data
                        event_type = data.get(b"event_type", b"unknown").decode()
                        timestamp = data.get(b"timestamp", b"").decode()

                        # Parse event data JSON if present
                        event_data = {}
                        if b"data" in data:
                            try:
                                event_data = json.loads(data[b"data"].decode())
                            except:
                                pass

                        events.append({
                            "type": event_type,
                            "timestamp": timestamp,
                            "data": event_data,
                            "message_id": msg_id.decode(),
                            "source": "workflow"
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing event: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Error reading events from stream {event_stream_key}: {e}")

        # If no events found in stream, create synthetic events from workflow state
        if not events:
            # Get workflow state
            state_key = default_sharding.get_workflow_key("state", workflow_id)
            state = await conn.redis.hgetall(state_key.encode())

            if state:
                # Add workflow submission event
                if state.get(b"submitted_at"):
                    events.append({
                        "type": "workflow_submitted",
                        "timestamp": state.get(b"submitted_at").decode(),
                        "data": {"workflow_id": workflow_id, "status": "pending"},
                        "source": "workflow"
                    })

                # Add workflow started event - use minimum task executed_at to avoid race condition
                if state.get(b"started_at"):
                    workflow_started_timestamp = state.get(b"started_at").decode()

                    # Try to get minimum task execution time for more accurate started_at
                    try:
                        shard = default_sharding.get_shard(workflow_id)
                        graph_key = f"{{shard:{shard}}}:workflow:dependency:graph:{workflow_id}"
                        graph_data = await conn.redis.hgetall(graph_key.encode())
                        task_ids = [k.decode() for k in graph_data.keys()] if graph_data else []

                        min_task_start = None
                        for task_id in task_ids:
                            task_key = default_sharding.get_task_key(task_id, workflow_id)
                            task_executed_at = await conn.redis.hget(task_key.encode(), b"executed_at")
                            if task_executed_at:
                                task_start_str = task_executed_at.decode()
                                try:
                                    from datetime import datetime
                                    task_start = datetime.fromisoformat(task_start_str)
                                    if min_task_start is None or task_start < min_task_start:
                                        min_task_start = task_start
                                except:
                                    pass

                        # Use minimum task start time if found
                        if min_task_start:
                            workflow_started_timestamp = min_task_start.isoformat()
                    except Exception as e:
                        logger.debug(f"Could not determine workflow start from tasks: {e}")

                    events.append({
                        "type": "workflow_started",
                        "timestamp": workflow_started_timestamp,
                        "data": {"workflow_id": workflow_id, "status": "running"},
                        "source": "workflow"
                    })

                # Add completion/failure event
                if state.get(b"completed_at"):
                    status = state.get(b"status", b"unknown").decode()
                    event_type = f"workflow_{status}"
                    events.append({
                        "type": event_type,
                        "timestamp": state.get(b"completed_at").decode(),
                        "data": {"workflow_id": workflow_id, "status": status},
                        "source": "workflow"
                    })

        # Now get task events for all tasks in this workflow
        # Get task IDs from dependency graph or task set
        shard_bytes = await conn.redis.hget(b"{shard:0}:index:workflow_shards", workflow_id.encode())
        task_ids = set()

        if shard_bytes:
            # Direct lookup using shard
            shard = shard_bytes.decode()
            graph_key = f"{{shard:{shard}}}:workflow:dependency:graph:{workflow_id}"
            graph_data = await conn.redis.hgetall(graph_key.encode())

            if graph_data:
                task_ids = set(k.decode() for k in graph_data.keys())
            else:
                # Fallback to workflow:tasks set
                task_list_key = default_sharding.get_workflow_key("tasks", workflow_id)
                task_ids_bytes = await conn.redis.smembers(task_list_key.encode())
                task_ids = set(t.decode() for t in task_ids_bytes)

        # Get workflow definition to map task IDs to names
        task_id_to_name = {}
        workflow_data_key = default_sharding.get_workflow_key("data", workflow_id)
        workflow_data_raw = await conn.redis.hget(workflow_data_key.encode(), b"workflow")
        if workflow_data_raw:
            try:
                workflow_def = json.loads(workflow_data_raw.decode())
                for task in workflow_def.get("tasks", []):
                    if "id" in task and "name" in task:
                        task_id_to_name[task["id"]] = task["name"]
            except (json.JSONDecodeError, AttributeError):
                pass

        # Fetch events for each task
        for task_id in task_ids:
            try:
                task_name = task_id_to_name.get(task_id, task_id)

                # Get task shard
                task_shard = default_sharding.get_shard(task_id)
                task_event_key = f"{{shard:{task_shard}}}:task:events:{task_id}"

                # Try to read task events from stream
                task_stream_data = await conn.redis.xrevrange(
                    task_event_key.encode(),
                    count=50  # Limit per task
                )

                # If stream has events, use them
                if task_stream_data:
                    for msg_id, data in task_stream_data:
                        try:
                            event_type = data.get(b"event_type", b"unknown").decode()
                            timestamp = data.get(b"timestamp", b"").decode()

                            # Parse event data JSON if present
                            event_data = {}
                            if b"data" in data:
                                try:
                                    event_data = json.loads(data[b"data"].decode())
                                except:
                                    pass

                            # Add task info to event data
                            event_data["task_id"] = task_id
                            event_data["task_name"] = task_name

                            events.append({
                                "type": event_type,
                                "timestamp": timestamp,
                                "data": event_data,
                                "message_id": msg_id.decode(),
                                "source": "task"
                            })
                        except Exception as e:
                            logger.warning(f"Error parsing task event: {e}")
                            continue
                else:
                    # No stream found, create synthetic events from task state
                    task_key = default_sharding.get_task_key(task_id, workflow_id)
                    task_data = await conn.redis.hgetall(task_key.encode())

                    if task_data:
                        # Decode task data
                        task_state = {k.decode(): v.decode() for k, v in task_data.items()}

                        # Parse JSON fields
                        for field in ("result", "error"):
                            if field in task_state:
                                try:
                                    task_state[field] = json.loads(task_state[field])
                                except json.JSONDecodeError:
                                    pass

                        # Add creation event if we have created_at
                        if task_state.get("created_at"):
                            events.append({
                                "type": "task_created",
                                "timestamp": task_state.get("created_at"),
                                "data": {
                                    "task_id": task_id,
                                    "task_name": task_name,
                                    "status": "created"
                                },
                                "source": "task"
                            })

                        # Add execution start event
                        if task_state.get("executed_at"):
                            event_data = {
                                "task_id": task_id,
                                "task_name": task_name,
                                "status": "running"
                            }
                            if task_state.get("worker_id"):
                                event_data["worker"] = task_state.get("worker_id")

                            events.append({
                                "type": "task_started",
                                "timestamp": task_state.get("executed_at"),
                                "data": event_data,
                                "source": "task"
                            })

                        # Add completion or failure event
                        if task_state.get("completed_at"):
                            status = task_state.get("status", "unknown")
                            event_type = "task_completed" if status == "completed" else f"task_{status}"
                            event_data = {
                                "task_id": task_id,
                                "task_name": task_name,
                                "status": status
                            }

                            if task_state.get("result"):
                                event_data["result"] = task_state.get("result")
                            if task_state.get("error"):
                                event_data["error"] = task_state.get("error")

                            events.append({
                                "type": event_type,
                                "timestamp": task_state.get("completed_at"),
                                "data": event_data,
                                "source": "task"
                            })

            except Exception as e:
                logger.debug(f"No events for task {task_id}: {e}")
                continue

        # Post-process: Fix workflow event timestamps to avoid race conditions
        # Workflow started should be earliest task start, workflow completed should be latest task completion
        from datetime import datetime

        task_events = [e for e in events if e.get("source") == "task"]
        workflow_events = {e.get("type"): e for e in events if e.get("source") == "workflow"}

        if task_events:
            # Find earliest task start time
            task_start_times = []
            for e in task_events:
                if "started" in e.get("type", ""):
                    try:
                        task_start_times.append(datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")))
                    except:
                        pass

            # Find latest task completion time
            task_completion_times = []
            for e in task_events:
                if "completed" in e.get("type", "") or "failed" in e.get("type", ""):
                    try:
                        task_completion_times.append(datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")))
                    except:
                        pass

            # Update workflow_started timestamp to earliest task start
            if task_start_times and "workflow_started" in workflow_events:
                min_task_start = min(task_start_times)
                workflow_events["workflow_started"]["timestamp"] = min_task_start.isoformat()

            # Update workflow completion timestamp to latest task completion
            for completion_type in ["workflow_completed", "workflow_failed", "workflow_completed_with_skips"]:
                if task_completion_times and completion_type in workflow_events:
                    max_task_completion = max(task_completion_times)
                    workflow_events[completion_type]["timestamp"] = max_task_completion.isoformat()

        # Sort all events by timestamp (newest first), then by logical order for stability
        # When timestamps are equal, workflow events should come before task events
        # And within same type, follow logical sequence (submitted -> started -> completed)

        event_type_order = {
            "workflow_submitted": 0,
            "workflow_started": 1,
            "task_created": 2,
            "task_started": 3,
            "task_completed": 4,
            "task_failed": 5,
            "workflow_completed": 6,
            "workflow_failed": 6,
            "workflow_completed_with_skips": 6
        }

        def sort_key(event):
            # Parse timestamp
            try:
                ts = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            except:
                ts = datetime.min

            # Source priority: workflow (0) before task (1)
            source_priority = 0 if event.get("source") == "workflow" else 1

            # Event type priority
            type_priority = event_type_order.get(event.get("type"), 99)

            # Sort by: timestamp desc (negative for reverse), source asc, type asc
            return (-ts.timestamp(), source_priority, type_priority)

        events.sort(key=sort_key)

        # Return with no-cache headers to ensure fresh data
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content={"workflow_id": workflow_id, "events": events},
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

