"""
Worker management API endpoints.

Provides REST API for:
- Listing workers
- Stopping individual workers
- Getting worker status
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import subprocess
import psutil
import redis
import redis.asyncio as aioredis
import logging

from ..dependencies import get_redis

logger = logging.getLogger(__name__)

router = APIRouter()


# ============= Models =============

class WorkerInfo(BaseModel):
    """Information about a worker"""
    worker_id: str = Field(..., description="Worker ID")
    worker_type: str = Field(..., description="Worker type (e.g., 'timer', 'task_execution')")
    pid: Optional[str] = Field(None, description="Process ID (for native workers)")
    state: Optional[str] = Field(None, description="Worker state")
    shards: Optional[str] = Field(None, description="Assigned shards")
    started_at: Optional[str] = Field(None, description="Start timestamp")
    mode: Optional[str] = Field(None, description="Deployment mode (docker/native)")


class WorkerListResponse(BaseModel):
    """Response for worker list endpoint"""
    workers: List[WorkerInfo] = Field(..., description="List of registered workers")
    total: int = Field(..., description="Total number of workers")


class WorkerStopRequest(BaseModel):
    """Request to stop a worker"""
    worker_name: str = Field(..., description="Worker name or type to stop")
    force: bool = Field(False, description="Force kill (SIGKILL) instead of graceful shutdown")
    timeout: int = Field(10, description="Timeout in seconds for graceful shutdown", ge=1, le=300)


class WorkerStopResult(BaseModel):
    """Result of stopping a worker"""
    worker_name: str = Field(..., description="Worker identifier that was stopped")
    pid: Optional[int] = Field(None, description="Process ID (for native workers)")
    container_name: Optional[str] = Field(None, description="Container name (for Docker workers)")
    mode: str = Field(..., description="Worker mode (docker/native)")
    success: bool = Field(..., description="Whether stop was successful")
    message: Optional[str] = Field(None, description="Additional message")


class WorkerStopResponse(BaseModel):
    """Response for worker stop endpoint"""
    stopped: List[WorkerStopResult] = Field(..., description="List of stopped workers")
    total_stopped: int = Field(..., description="Total workers stopped")
    docker_stopped: int = Field(0, description="Docker containers stopped")
    native_stopped: int = Field(0, description="Native processes stopped")
    registry_cleaned: int = Field(0, description="Registry entries cleaned")


# ============= Endpoints =============

@router.get("/", response_model=WorkerListResponse)
async def list_workers():
    """
    List all registered workers.

    Returns information about all workers registered in Redis,
    including both Docker and native workers.

    Returns:
        WorkerListResponse with list of workers and total count
    """
    try:
        redis_conn = redis.Redis(host='localhost', port=6379, decode_responses=True)
        workers = []

        # Scan for all worker registry keys
        for key in redis_conn.scan_iter(match="{shard:0}:worker:registry:*"):
            try:
                data = redis_conn.hgetall(key)
                if data:
                    workers.append(WorkerInfo(
                        worker_id=data.get('worker_id', 'unknown'),
                        worker_type=data.get('worker_type', 'unknown'),
                        pid=data.get('pid'),
                        state=data.get('state', 'unknown'),
                        shards=data.get('shards', '[]'),
                        started_at=data.get('started_at'),
                        mode=data.get('mode', 'unknown')
                    ))
            except Exception as e:
                logger.warning(f"Error reading worker data from {key}: {e}")
                continue

        return WorkerListResponse(
            workers=workers,
            total=len(workers)
        )

    except Exception as e:
        logger.error(f"Error listing workers: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list workers: {str(e)}")


@router.post("/stop", response_model=WorkerStopResponse)
async def stop_worker(request: WorkerStopRequest):
    """
    Stop a specific worker by name or type.

    Stops Docker containers and/or native processes matching the worker name.
    Supports graceful shutdown (SIGTERM) or force kill (SIGKILL).
    Automatically cleans up Redis registry for stopped workers.

    Args:
        request: WorkerStopRequest with worker_name, force flag, and timeout

    Returns:
        WorkerStopResponse with details of stopped workers

    Example:
        POST /workers/stop
        {
            "worker_name": "timer",
            "force": false,
            "timeout": 10
        }
    """
    stopped_workers = []
    docker_stopped = 0
    native_stopped = 0
    registry_cleaned = 0

    # Normalize worker name
    worker_name = request.worker_name
    if not worker_name.startswith('worker_'):
        worker_search = f"worker_{worker_name}"
    else:
        worker_search = worker_name

    base_name = worker_name.replace('worker_', '')

    # 1. Stop Docker containers
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            containers = [c for c in result.stdout.strip().split('\n') if c]
            matching_containers = [
                c for c in containers
                if worker_search.lower() in c.lower() or base_name.lower() in c.lower()
            ]

            for container in matching_containers:
                try:
                    if request.force:
                        subprocess.run(["docker", "kill", container],
                                     capture_output=True, timeout=5)
                    else:
                        subprocess.run(["docker", "stop", "-t", str(request.timeout), container],
                                     capture_output=True, timeout=request.timeout + 5)

                    stopped_workers.append(WorkerStopResult(
                        worker_name=container,
                        container_name=container,
                        mode="docker",
                        success=True
                    ))
                    docker_stopped += 1
                except Exception as e:
                    stopped_workers.append(WorkerStopResult(
                        worker_name=container,
                        container_name=container,
                        mode="docker",
                        success=False,
                        message=str(e)
                    ))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Docker not available

    # 2. Stop native processes
    processes_to_stop = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue

            cmdline_str = ' '.join(cmdline)

            if 'python' in cmdline_str and 'gleitzeit.workers.runner' in cmdline_str:
                if (worker_search.lower() in cmdline_str.lower() or
                    base_name.lower() in cmdline_str.lower()):
                    processes_to_stop.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for proc in processes_to_stop:
        try:
            pid = proc.pid
            if request.force:
                proc.kill()
            else:
                proc.terminate()

            stopped_workers.append(WorkerStopResult(
                worker_name=f"PID-{pid}",
                pid=pid,
                mode="native",
                success=True
            ))
            native_stopped += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            stopped_workers.append(WorkerStopResult(
                worker_name=f"PID-{proc.pid}",
                pid=proc.pid,
                mode="native",
                success=False,
                message=str(e)
            ))

    # Wait for graceful shutdown if not forcing
    if not request.force and processes_to_stop:
        gone, alive = psutil.wait_procs(processes_to_stop, timeout=request.timeout)

        # Force kill any remaining processes
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    # 3. Clean up Redis registry
    if native_stopped > 0 or docker_stopped > 0:
        try:
            redis_conn = redis.Redis(host='localhost', port=6379, decode_responses=True)

            for key in redis_conn.scan_iter(match="{shard:0}:worker:registry:*"):
                try:
                    worker_data = redis_conn.hgetall(key)
                    if not worker_data:
                        continue

                    worker_id = worker_data.get('worker_id', '')
                    worker_type = worker_data.get('worker_type', '')
                    pid_str = worker_data.get('pid', '')

                    # Check if this worker matches
                    matches = (worker_search.lower() in worker_id.lower() or
                              worker_search.lower() in worker_type.lower() or
                              base_name.lower() in worker_type.lower())

                    if not matches:
                        continue

                    # Check if process is dead
                    process_dead = True
                    if pid_str:
                        try:
                            pid = int(pid_str)
                            psutil.Process(pid)
                            process_dead = False
                        except (psutil.NoSuchProcess, ValueError, OverflowError):
                            process_dead = True

                    # Clean up if dead
                    if process_dead:
                        redis_conn.delete(key)
                        registry_cleaned += 1

                except Exception:
                    continue

        except Exception as e:
            logger.warning(f"Redis cleanup failed: {e}")

    if len(stopped_workers) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No workers found matching: {worker_name}"
        )

    return WorkerStopResponse(
        stopped=stopped_workers,
        total_stopped=len(stopped_workers),
        docker_stopped=docker_stopped,
        native_stopped=native_stopped,
        registry_cleaned=registry_cleaned
    )


@router.get("/{worker_id}", response_model=WorkerInfo)
async def get_worker(worker_id: str):
    """
    Get detailed information about a specific worker.

    Args:
        worker_id: Worker ID to look up

    Returns:
        WorkerInfo with worker details

    Raises:
        404: Worker not found
    """
    try:
        redis_conn = redis.Redis(host='localhost', port=6379, decode_responses=True)

        # Try to find worker in registry
        for key in redis_conn.scan_iter(match="{shard:0}:worker:registry:*"):
            data = redis_conn.hgetall(key)
            if data and data.get('worker_id') == worker_id:
                return WorkerInfo(
                    worker_id=data.get('worker_id', 'unknown'),
                    worker_type=data.get('worker_type', 'unknown'),
                    pid=data.get('pid'),
                    state=data.get('state', 'unknown'),
                    shards=data.get('shards', '[]'),
                    started_at=data.get('started_at'),
                    mode=data.get('mode', 'unknown')
                )

        raise HTTPException(status_code=404, detail=f"Worker not found: {worker_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting worker {worker_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get worker: {str(e)}")
