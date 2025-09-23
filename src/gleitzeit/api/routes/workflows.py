"""
Workflow submission and management endpoints
"""

import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import redis.asyncio as aioredis

from ...core.sharding import default_sharding

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


@router.post("/submit", response_model=WorkflowSubmitResponse)
async def submit_workflow(
    request: WorkflowSubmitRequest,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """
    Submit a workflow for execution.

    The workflow is submitted to the workflow:load stream where it will be:
    1. Picked up by WorkflowLoaderWorker for validation
    2. If valid, forwarded to workflow:submitted stream
    3. Processed by DependencyWorker to create tasks
    4. Tasks executed by TaskExecutionWorker
    """
    # Generate workflow ID if not provided
    workflow_id = request.workflow_id or str(uuid.uuid4())

    # Add workflow ID to the workflow if not present
    if "workflow_id" not in request.workflow:
        request.workflow["workflow_id"] = workflow_id

    # Prepare submission data
    submission_data = {
        b"workflow_id": workflow_id.encode(),
        b"workflow": json.dumps(request.workflow).encode(),
        b"metadata": json.dumps(request.metadata).encode(),
        b"submitted_at": datetime.utcnow().isoformat().encode(),
        b"source": b"api"
    }

    try:
        # Submit to workflow:load stream (sharded by workflow_id)
        stream_key = default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id)

        # Add to stream
        message_id = await redis.xadd(
            stream_key.encode(),
            submission_data
        )

        # Store initial workflow state
        workflow_key = default_sharding.get_workflow_key("state", workflow_id)
        await redis.hset(
            workflow_key.encode(),
            mapping={
                b"workflow_id": workflow_id.encode(),
                b"status": b"submitted",
                b"submitted_at": datetime.utcnow().isoformat().encode(),
                b"stream_message_id": message_id
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
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get workflow status and details"""

    # Get workflow state
    state_key = default_sharding.get_workflow_key("state", workflow_id)
    state_data = await redis.hgetall(state_key.encode())

    if not state_data:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get workflow data
    data_key = default_sharding.get_workflow_key("data", workflow_id)
    workflow_data = await redis.hgetall(data_key.encode())

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
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get all tasks for a workflow"""

    # Get task list from workflow
    task_list_key = default_sharding.get_workflow_key("tasks", workflow_id)
    task_ids = await redis.smembers(task_list_key.encode())

    if not task_ids:
        return {"workflow_id": workflow_id, "tasks": []}

    # Get task details
    tasks = []
    for task_id_bytes in task_ids:
        task_id = task_id_bytes.decode()
        task_key = default_sharding.get_task_key("state", task_id)
        task_data = await redis.hgetall(task_key.encode())

        if task_data:
            tasks.append({
                "task_id": task_id,
                **{k.decode(): v.decode() for k, v in task_data.items()}
            })

    return {
        "workflow_id": workflow_id,
        "task_count": len(tasks),
        "tasks": tasks
    }


@router.post("/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Cancel a running workflow and all its tasks"""

    # Update workflow state
    state_key = default_sharding.get_workflow_key("state", workflow_id)
    exists = await redis.exists(state_key.encode())

    if not exists:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Set workflow cancellation status
    await redis.hset(
        state_key.encode(),
        mapping={
            b"status": b"cancelled",
            b"cancelled_at": datetime.utcnow().isoformat().encode(),
            b"cancelled_reason": b"user_requested"
        }
    )

    # Emit workflow cancellation event to stream
    workflow_stream_key = default_sharding.get_stream_key("workflow:cancelled", workflow_id)
    await redis.xadd(
        workflow_stream_key.encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"reason": b"user_requested",
            b"timestamp": datetime.utcnow().isoformat().encode()
        }
    )

    # Get all tasks for this workflow
    tasks_key = default_sharding.get_workflow_key("tasks", workflow_id)
    task_ids = await redis.smembers(tasks_key.encode())

    cancelled_count = 0
    for task_id_bytes in task_ids:
        task_id = task_id_bytes.decode()
        task_state_key = default_sharding.get_task_key("state", task_id)
        task_state = await redis.hgetall(task_state_key.encode())

        if task_state:
            status = task_state.get(b"status", b"").decode()
            # Only cancel tasks that are not in terminal states
            if status not in ["completed", "failed", "cancelled", "blocked"]:
                # Update task state to cancelled
                await redis.hset(
                    task_state_key.encode(),
                    mapping={
                        b"status": b"cancelled",
                        b"cancelled_at": datetime.utcnow().isoformat().encode(),
                        b"cancelled_reason": b"workflow_cancelled"
                    }
                )

                # Add to workflow's cancelled tasks set
                await redis.sadd(
                    default_sharding.get_workflow_key("tasks:cancelled", workflow_id).encode(),
                    task_id.encode()
                )

                # Emit task cancellation event
                task_stream_key = default_sharding.get_stream_key("task:cancelled", task_id)
                await redis.xadd(
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
        "message": f"Workflow cancelled, {cancelled_count} tasks were cancelled"
    }


# Fix circular import by getting app instance
from ..main import app