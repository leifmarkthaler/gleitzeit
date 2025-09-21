"""
API routes for timer functionality.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any

from gleitzeit.api.dependencies import get_pooled_client
try:
    from gleitzeit.timers import StatelessTimerManager
except ImportError:
    StatelessTimerManager = None

router = APIRouter(prefix="/timers", tags=["timers"])



@router.get("/stats")
async def get_timer_stats(client=Depends(get_pooled_client)):
    """
    Get timer system statistics.
    
    Args:
        persistence: Persistence layer
        
    Returns:
        Timer statistics
    """
    try:
        # Get persistence from client
        persistence = client._adapter.execution_engine.persistence
        # TODO: Implement TimerMonitorService for timer stats
        return {
            "timers": {
                "pending": 0,
                "executed": 0,
                "cancelled": 0
            },
            "note": "Timer monitoring not yet implemented"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending")
async def list_pending_timers(
    limit: int = 100,
    client=Depends(get_pooled_client)
):
    """
    List pending timers.
    
    Args:
        limit: Maximum number of timers to return
        persistence: Persistence layer
        
    Returns:
        List of pending timers
    """
    try:
        # Get persistence from client
        persistence = client._adapter.execution_engine.persistence
        # Get pending timers from Redis
        timers = await persistence.redis.zrange(
            "timers:pending",
            0,
            limit - 1,
            withscores=True
        )
        
        result = []
        for timer_id, wake_at in timers:
            if isinstance(timer_id, bytes):
                timer_id = timer_id.decode()
            
            # Get timer metadata
            timer_data = await persistence.redis.hgetall(f"timer:{timer_id}")
            
            if timer_data:
                # Decode bytes
                timer_info = {
                    k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in timer_data.items()
                }
                
                timer_info["timer_id"] = timer_id
                timer_info["wake_at"] = wake_at
                result.append(timer_info)
        
        return {
            "timers": result,
            "count": len(result),
            "total": await persistence.redis.zcard("timers:pending")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/timer/{timer_id}")
async def cancel_timer(
    timer_id: str,
    client=Depends(get_pooled_client)
):
    """
    Cancel a pending timer.
    
    Args:
        timer_id: Timer ID to cancel
        persistence: Persistence layer
        
    Returns:
        Cancellation result
    """
    try:
        # Get persistence from client
        persistence = client._adapter.execution_engine.persistence
        # Remove from pending timers
        removed = await persistence.redis.zrem("timers:pending", timer_id)
        
        if removed:
            # Get timer data for cleanup
            timer_data = await persistence.redis.hgetall(f"timer:{timer_id}")
            
            if timer_data:
                # Clean up signal waiters if needed
                timer_type = timer_data.get(b"type", b"").decode()
                if timer_type == "wait_or_signal":
                    signal = timer_data.get(b"signal", b"").decode()
                    workflow_id = timer_data.get(b"workflow_id", b"").decode()
                    task_id = timer_data.get(b"task_id", b"").decode()
                    
                    if signal and workflow_id and task_id:
                        await persistence.redis.srem(
                            f"signal:{signal}:waiters",
                            f"{workflow_id}:{task_id}"
                        )
            
            # Delete timer metadata
            await persistence.redis.delete(f"timer:{timer_id}")
            
            return {
                "cancelled": True,
                "timer_id": timer_id
            }
        else:
            return {
                "cancelled": False,
                "reason": "Timer not found or already expired"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


