"""
Workflow submission and management endpoints
"""

import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from ...core.sharding import default_sharding
from ..dependencies import get_client_pool
from ..auth.dependencies import get_current_user_auto
from ..auth.models import User

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

                # Get workflow status
                status_key = default_sharding.get_workflow_key("status", workflow_id)
                pipe.hgetall(status_key.encode())

                # Get workflow data
                data_key = default_sharding.get_workflow_key("data", workflow_id)
                pipe.hget(data_key.encode(), b"workflow")

            # Execute pipeline and process results in pairs
            results = await pipe.execute()
            workflow_ids_list = list(workflow_ids)

            for i in range(0, len(results), 2):
                state_data = results[i]
                workflow_data = results[i + 1]

                if not state_data:
                    continue

                workflow_id = workflow_ids_list[i // 2].decode()

                # Decode state data
                decoded_state = {k.decode(): v.decode() for k, v in state_data.items()}

                workflow_info = {
                    "workflow_id": workflow_id,
                    "name": "Unnamed",
                    "status": decoded_state.get("status", "unknown"),
                    "created_at": decoded_state.get("submitted_at", ""),
                    "progress": {}
                }

                # Add workflow definition details if available
                if workflow_data:
                    try:
                        data = json.loads(workflow_data)
                        workflow_info["name"] = data.get("name", "Unnamed")
                        workflow_info["description"] = data.get("description", "")
                        workflow_info["task_count"] = len(data.get("tasks", []))
                        workflow_info["version"] = data.get("version", "")
                    except json.JSONDecodeError:
                        pass

                # Use cached task counts if available
                completed_count = int(decoded_state.get("completed_count", 0))
                failed_count = int(decoded_state.get("failed_count", 0))
                running_count = int(decoded_state.get("running_count", 0))
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
            # Get workflow status
            state_key = default_sharding.get_workflow_key("status", workflow_id)
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
        # Get workflow status
        state_key = default_sharding.get_workflow_key("status", workflow_id)
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

                tasks.append({
                    "task_id": task_id,
                    **decoded
                })

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

