"""
Stream Management API Routes.

Provides API endpoints for monitoring and managing the stream-based
event processing system.
"""

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..dependencies import get_system_manager
from ...system.modular_stream_system_manager import ModularStreamSystemManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/streams", tags=["streams"])


class StreamHealthResponse(BaseModel):
    """Response model for stream health."""
    status: str
    total_streams: int
    healthy_streams: int
    warning_streams: int
    critical_streams: int
    total_pending_messages: int
    redis_memory_usage: Optional[float]
    issues: List[str]


class StreamStatsResponse(BaseModel):
    """Response model for stream statistics."""
    stream_processing: bool
    configuration: Dict[str, Any]
    timer_manager: Optional[Dict[str, Any]]
    signal_manager: Optional[Dict[str, Any]]
    event_scheduler: Optional[Dict[str, Any]]
    consumer_group_manager: Optional[Dict[str, Any]]
    monitor: Optional[Dict[str, Any]]
    metrics_summary: Optional[Dict[str, Any]]


class StreamInfoResponse(BaseModel):
    """Response model for individual stream information."""
    stream_name: str
    length: int
    groups: List[str]
    pending: Dict[str, Any]


@router.get("/health", response_model=StreamHealthResponse)
async def get_stream_health(
    system_manager=Depends(get_system_manager)
):
    """
    Get overall stream system health.

    Returns comprehensive health information about all Redis streams
    including status, pending messages, and any issues.
    """
    try:
        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        if not isinstance(system_manager, StreamSystemManager):
            raise HTTPException(status_code=503, detail="Stream processing not enabled")

        # Get system health with stream information
        health = await system_manager.get_system_health()
        stream_health = health.get("stream_processing", {})

        if "error" in stream_health:
            raise HTTPException(status_code=503, detail=f"Stream health error: {stream_health['error']}")

        return StreamHealthResponse(
            status=stream_health.get("status", "unknown"),
            total_streams=stream_health.get("total_streams", 0),
            healthy_streams=stream_health.get("healthy_streams", 0),
            warning_streams=stream_health.get("warning_streams", 0),
            critical_streams=stream_health.get("critical_streams", 0),
            total_pending_messages=stream_health.get("total_pending_messages", 0),
            redis_memory_usage=stream_health.get("redis_memory_usage"),
            issues=stream_health.get("issues", [])
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stream health: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stream health: {e}")


@router.get("/statistics", response_model=StreamStatsResponse)
async def get_stream_statistics(
    hours: int = Query(1, ge=1, le=24, description="Hours of metrics to include"),
    system_manager=Depends(get_system_manager)
):
    """
    Get detailed stream processing statistics.

    Returns comprehensive statistics about all stream components
    including performance metrics and configuration.
    """
    try:
        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        if not isinstance(system_manager, StreamSystemManager):
            raise HTTPException(status_code=503, detail="Stream processing not enabled")

        # Get stream statistics
        stats = await system_manager.get_stream_statistics()

        if "error" in stats:
            raise HTTPException(status_code=503, detail=f"Stream stats error: {stats['error']}")

        return StreamStatsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stream statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stream statistics: {e}")


@router.get("/info")
async def get_streams_info(
    system_manager=Depends(get_system_manager)
):
    """
    Get information about all Redis streams.

    Returns detailed information about each stream including
    length, consumer groups, and pending messages.
    """
    try:
        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        if not isinstance(system_manager, StreamSystemManager):
            raise HTTPException(status_code=503, detail="Stream processing not enabled")

        streams_info = {}

        # Get timer streams info
        if system_manager.timer_manager and hasattr(system_manager.timer_manager, 'get_stream_info'):
            timer_info = await system_manager.timer_manager.get_stream_info()
            streams_info["timer_streams"] = timer_info

        # Get signal streams info
        if system_manager.signal_manager and hasattr(system_manager.signal_manager, 'get_stream_info'):
            signal_info = await system_manager.signal_manager.get_stream_info()
            streams_info["signal_streams"] = signal_info

        # Get event scheduler streams info
        if system_manager.event_scheduler and hasattr(system_manager.event_scheduler, 'get_stream_info'):
            scheduler_info = await system_manager.event_scheduler.get_stream_info()
            streams_info["scheduler_streams"] = scheduler_info

        return streams_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting streams info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get streams info: {e}")


@router.get("/config")
async def get_stream_config(
    system_manager=Depends(get_system_manager)
):
    """
    Get current stream configuration.

    Returns the current stream processing configuration including
    sharding, consumer groups, and performance settings.
    """
    try:
        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        if not isinstance(system_manager, StreamSystemManager):
            raise HTTPException(status_code=503, detail="Stream processing not enabled")

        config = system_manager.get_stream_config()
        return config

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stream config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stream config: {e}")


@router.get("/metrics/summary")
async def get_metrics_summary(
    hours: int = Query(1, ge=1, le=24, description="Hours of metrics to summarize"),
    system_manager=Depends(get_system_manager)
):
    """
    Get metrics summary for the specified time period.

    Returns aggregated metrics for streams, consumer groups,
    and system performance over the requested time period.
    """
    try:
        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        if not isinstance(system_manager, StreamSystemManager):
            raise HTTPException(status_code=503, detail="Stream processing not enabled")

        if not system_manager.stream_monitor:
            raise HTTPException(status_code=503, detail="Stream monitoring not available")

        summary = system_manager.stream_monitor.get_metrics_summary(hours=hours)
        return summary

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metrics summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get metrics summary: {e}")


@router.post("/consumer-groups/cleanup")
async def cleanup_consumer_groups(
    system_manager=Depends(get_system_manager)
):
    """
    Trigger cleanup of idle consumers across all streams.

    Manually triggers the consumer group cleanup process to remove
    idle consumers and reclaim pending messages.
    """
    try:
        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        if not isinstance(system_manager, StreamSystemManager):
            raise HTTPException(status_code=503, detail="Stream processing not enabled")

        if not system_manager.consumer_group_manager:
            raise HTTPException(status_code=503, detail="Consumer group manager not available")

        # Get list of streams to clean up
        streams_to_clean = []

        # Add timer streams
        if system_manager.timer_manager and hasattr(system_manager.timer_manager, 'get_stream_info'):
            timer_info = await system_manager.timer_manager.get_stream_info()
            streams_to_clean.extend(timer_info.keys())

        # Add signal streams
        if system_manager.signal_manager and hasattr(system_manager.signal_manager, 'get_stream_info'):
            signal_info = await system_manager.signal_manager.get_stream_info()
            streams_to_clean.extend(signal_info.keys())

        # Perform cleanup
        cleanup_results = {}
        for stream_name in streams_to_clean:
            try:
                cleaned = await system_manager.consumer_group_manager.cleanup_idle_consumers(stream_name)
                reclaimed = await system_manager.consumer_group_manager.reclaim_pending_messages(stream_name)
                cleanup_results[stream_name] = {
                    "consumers_cleaned": cleaned,
                    "messages_reclaimed": reclaimed
                }
            except Exception as e:
                cleanup_results[stream_name] = {"error": str(e)}

        return {
            "message": "Consumer group cleanup completed",
            "results": cleanup_results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during consumer group cleanup: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup consumer groups: {e}")


@router.get("/consumer-groups/{stream_name}")
async def get_consumer_group_info(
    stream_name: str,
    system_manager=Depends(get_system_manager)
):
    """
    Get detailed information about consumer groups for a specific stream.

    Returns information about all consumer groups for the specified stream
    including consumer health, pending messages, and performance metrics.
    """
    try:
        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        if not isinstance(system_manager, StreamSystemManager):
            raise HTTPException(status_code=503, detail="Stream processing not enabled")

        if not system_manager.consumer_group_manager:
            raise HTTPException(status_code=503, detail="Consumer group manager not available")

        # Get stream info
        stream_info = await system_manager.consumer_group_manager.get_stream_info(stream_name)
        if not stream_info:
            raise HTTPException(status_code=404, detail=f"Stream {stream_name} not found")

        # Get consumer group details
        group_details = {}
        for group_name in stream_info.groups:
            try:
                consumers = await system_manager.consumer_group_manager.get_consumer_info(stream_name, group_name)
                pending = await system_manager.consumer_group_manager.get_pending_summary(stream_name, group_name)

                group_details[group_name] = {
                    "consumers": [
                        {
                            "name": consumer.name,
                            "pending_count": consumer.pending_count,
                            "idle_time": consumer.idle_time,
                            "last_seen": consumer.last_seen.isoformat() if consumer.last_seen else None
                        }
                        for consumer in consumers
                    ],
                    "pending_summary": pending
                }
            except Exception as e:
                group_details[group_name] = {"error": str(e)}

        return {
            "stream_name": stream_name,
            "stream_info": {
                "length": stream_info.length,
                "groups": stream_info.groups,
                "first_entry_id": stream_info.first_entry_id,
                "last_entry_id": stream_info.last_entry_id
            },
            "consumer_groups": group_details
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting consumer group info for {stream_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get consumer group info: {e}")