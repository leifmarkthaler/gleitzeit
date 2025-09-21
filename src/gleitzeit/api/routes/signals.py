"""
Signal API endpoints for Gleitzeit workflows.

Provides REST API for sending signals to running workflows and
managing signal subscriptions.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import logging

from gleitzeit.core.models import WorkflowStatus
from ..dependencies import get_system_manager, get_pooled_client
from ..auth_dependencies import get_current_user_auto

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalRequest(BaseModel):
    """Request model for sending a signal."""
    signal_name: str
    payload: Optional[Dict[str, Any]] = {}
    
class SignalResponse(BaseModel):
    """Response model for signal operations."""
    status: str
    workflow_id: str
    signal: Optional[str] = None
    message: Optional[str] = None


@router.post("/workflows/{workflow_id}/send")
async def send_signal(
    workflow_id: str,
    request: SignalRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager=Depends(get_system_manager)
):
    """
    Send a signal to a running workflow.
    
    Args:
        workflow_id: Target workflow ID
        request: Signal request with name and payload
        current_user: Current authenticated user
        system_manager: System manager with persistence
        
    Returns:
        SignalResponse with send status
    """
    try:
        # Get workflow status
        workflow_data = await system_manager.persistence.get_workflow(workflow_id)
        if not workflow_data:
            raise HTTPException(404, f"Workflow {workflow_id} not found")
        
        # Handle both dict and Workflow object
        if hasattr(workflow_data, 'status'):
            status = workflow_data.status.value if hasattr(workflow_data.status, 'value') else workflow_data.status
        else:
            status = workflow_data.get("status")
            
        if status not in [WorkflowStatus.RUNNING.value, WorkflowStatus.WAITING.value, WorkflowStatus.PAUSED.value, "sleeping"]:
            raise HTTPException(
                400, 
                f"Workflow is in {status} state and cannot receive signals"
            )
        
        # Publish signal to workflow's signal stream
        signal_data = {
            "signal": request.signal_name,
            "payload": json.dumps(request.payload or {}),
            "sender": current_user.get("id", "unknown"),
            "sender_name": current_user.get("username", "anonymous"),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Use Redis directly from persistence
        if hasattr(system_manager.persistence, 'redis'):
            await system_manager.persistence.redis.xadd(
                f"workflow:signals:{workflow_id}",
                signal_data
            )
        else:
            raise HTTPException(500, "Signal functionality requires Redis persistence")
        
        logger.info(f"Signal '{request.signal_name}' sent to workflow {workflow_id} by {current_user.get('username')}")
        
        return SignalResponse(
            status="sent",
            workflow_id=workflow_id,
            signal=request.signal_name,
            message=f"Signal sent successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send signal to workflow {workflow_id}: {e}")
        raise HTTPException(500, f"Failed to send signal: {str(e)}")


@router.get("/workflows/{workflow_id}/waiting")
async def list_waiting_signals(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager=Depends(get_system_manager)
):
    """
    List signals that a workflow is waiting for.
    
    Args:
        workflow_id: Workflow ID
        current_user: Current authenticated user
        system_manager: System manager with persistence
        
    Returns:
        List of waiting signals and tasks
    """
    try:
        # Get workflow to verify it exists
        workflow_data = await system_manager.persistence.get_workflow(workflow_id)
        if not workflow_data:
            raise HTTPException(404, f"Workflow {workflow_id} not found")
        
        waiting_signals = []
        
        if hasattr(system_manager.persistence, 'redis'):
            # SECURE: Find all workflow-scoped signal waiters for this specific workflow
            async for key in system_manager.persistence.redis.scan_iter(f"signal:{workflow_id}:*:waiters"):
                # Extract signal name from workflow-scoped key: signal:workflow_id:signal_name:waiters
                key_parts = key.split(":")
                if len(key_parts) >= 4 and key_parts[-1] == "waiters":
                    signal_name = key_parts[2]  # signal_name is the third part
                    waiters = await system_manager.persistence.redis.smembers(key)
                    
                    for waiter in waiters:
                        if waiter.startswith(f"{workflow_id}:"):
                            task_id = waiter.split(":", 1)[1]
                            
                            # Get waiter metadata if available
                            waiter_info = {
                                "signal": signal_name,
                                "task_id": task_id,
                                "workflow_id": workflow_id
                            }
                            
                            # Look for additional metadata
                            async for meta_key in system_manager.persistence.redis.scan_iter(f"signal:waiter:*"):
                                meta_data = await system_manager.persistence.redis.hgetall(meta_key)
                                if (meta_data.get("workflow_id") == workflow_id and 
                                    meta_data.get("task_id") == task_id):
                                    waiter_info["mode"] = meta_data.get("mode", "single")
                                    waiter_info["timeout"] = meta_data.get("timeout")
                                    waiter_info["created_at"] = meta_data.get("created_at")
                                    if meta_data.get("signals"):
                                        waiter_info["signals"] = json.loads(meta_data.get("signals"))
                                    break
                            
                            waiting_signals.append(waiter_info)
        
        return {
            "workflow_id": workflow_id,
            "waiting_count": len(waiting_signals),
            "waiting_signals": waiting_signals
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list waiting signals for workflow {workflow_id}: {e}")
        raise HTTPException(500, f"Failed to list waiting signals: {str(e)}")


@router.get("/workflows/{workflow_id}/handlers")
async def list_signal_handlers(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager=Depends(get_system_manager)
):
    """
    List registered signal handlers for a workflow.
    
    Args:
        workflow_id: Workflow ID
        current_user: Current authenticated user
        system_manager: System manager with persistence
        
    Returns:
        Dict of signal handlers
    """
    try:
        # Get workflow to verify it exists
        workflow_data = await system_manager.persistence.get_workflow(workflow_id)
        if not workflow_data:
            raise HTTPException(404, f"Workflow {workflow_id} not found")
        
        handlers = {}
        
        if hasattr(system_manager.persistence, 'redis'):
            # Get all registered handlers for this workflow
            raw_handlers = await system_manager.persistence.redis.hgetall(
                f"workflow:{workflow_id}:signal:handlers"
            )
            
            # Parse handler configurations
            for signal_name, handler_config in raw_handlers.items():
                try:
                    handlers[signal_name] = json.loads(handler_config) if isinstance(handler_config, str) else handler_config
                except:
                    handlers[signal_name] = handler_config
        
        return {
            "workflow_id": workflow_id,
            "handlers": handlers
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list signal handlers for workflow {workflow_id}: {e}")
        raise HTTPException(500, f"Failed to list signal handlers: {str(e)}")


# REMOVED: Global broadcast endpoint removed for security
# Global signal broadcasting allows cross-workflow interference and is a security vulnerability.


@router.post("/workflows/{workflow_id}/send/{signal_name}")
async def send_signal_wake(
    workflow_id: str,
    signal_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager=Depends(get_system_manager)
):
    """
    Send a signal to wake waiting tasks within a specific workflow.
    
    SECURE: Now requires workflow_id to prevent cross-workflow signal interference.
    
    Args:
        workflow_id: Target workflow ID
        signal_name: Name of the signal to send
        current_user: Current authenticated user
        system_manager: System manager with persistence
        
    Returns:
        Number of tasks woken
    """
    try:
        if not hasattr(system_manager.persistence, 'redis'):
            raise HTTPException(500, "Signal functionality requires Redis persistence")
        
        # Verify workflow exists
        workflow_data = await system_manager.persistence.get_workflow(workflow_id)
        if not workflow_data:
            raise HTTPException(404, f"Workflow {workflow_id} not found")
        
        # Send signal to workflow's signal stream (for SignalWorker to process)
        signal_data = {
            "signal": signal_name,
            "payload": "{}",  # No payload for this simple endpoint
            "sender": current_user.get("id", "unknown"),
            "sender_name": current_user.get("username", "anonymous"),
            "timestamp": datetime.utcnow().isoformat()
        }

        await system_manager.persistence.redis.xadd(
            f"workflow:signals:{workflow_id}",
            signal_data
        )

        # Count waiting tasks (for response)
        waiting_key = f"signal:waiters:{workflow_id}:{signal_name}"
        woken = await system_manager.persistence.redis.scard(waiting_key)
        
        return {
            "workflow_id": workflow_id,
            "signal": signal_name,
            "tasks_woken": woken,
            "success": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/waiters")
async def list_all_signal_waiters(
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager=Depends(get_system_manager)
):
    """
    List all signals with waiting tasks across all workflows.
    
    Args:
        current_user: Current authenticated user
        system_manager: System manager with persistence
        
    Returns:
        Signals and their waiters
    """
    try:
        if not hasattr(system_manager.persistence, 'redis'):
            raise HTTPException(500, "Signal functionality requires Redis persistence")
        
        # SECURE: Scan for workflow-scoped signal keys only
        cursor = 0
        signals = {}
        
        while True:
            cursor, keys = await system_manager.persistence.redis.scan(
                cursor,
                match="signal:*:*:waiters",  # workflow-scoped pattern
                count=100
            )
            
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()
                
                # Extract workflow_id and signal name from workflow-scoped key
                key_parts = key.split(":")
                if len(key_parts) >= 4 and key_parts[-1] == "waiters":
                    workflow_id = key_parts[1]
                    signal_name = key_parts[2]
                    scoped_signal = f"{workflow_id}:{signal_name}"
                    
                    # Get waiters
                    waiters = await system_manager.persistence.redis.smembers(key)
                    waiters_list = [
                        w.decode() if isinstance(w, bytes) else w
                        for w in waiters
                    ]
                    
                    if waiters_list:
                        signals[scoped_signal] = waiters_list
            
            if cursor == 0:
                break
        
        return {
            "signals": signals,
            "count": len(signals)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_signal_stats(
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager=Depends(get_system_manager)
):
    """
    Get signal system statistics.
    
    Args:
        current_user: Current authenticated user
        system_manager: System manager
        system_manager: System manager with persistence
        
    Returns:
        Signal system statistics
    """
    try:
        stats = {
            "signal_monitor": {
                "available": False,
                "running": False
            },
            "signal_waiters": {},
            "signal_streams": 0
        }
        
        # Check if signal manager is running (integrated with SystemManager)
        if system_manager and hasattr(system_manager, 'signal_manager'):
            manager = system_manager.signal_manager
            if manager:
                manager_stats = await manager.get_stats()
                stats.update(manager_stats)
                stats["signal_monitor"]["available"] = True
                stats["signal_monitor"]["running"] = manager._running
        
        # Get signal statistics from Redis
        if hasattr(system_manager.persistence, 'redis'):
            # Count waiters per signal
            async for key in system_manager.persistence.redis.scan_iter("signal:*:waiters"):
                if ":waiters" in key:
                    signal_name = key.split(":")[1]
                    count = await system_manager.persistence.redis.scard(key)
                    stats["signal_waiters"][signal_name] = count
            
            # Count signal streams
            stream_count = 0
            async for _ in system_manager.persistence.redis.scan_iter("workflow:signals:*"):
                stream_count += 1
            stats["signal_streams"] = stream_count
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get signal stats: {e}")
        raise HTTPException(500, f"Failed to get signal stats: {str(e)}")