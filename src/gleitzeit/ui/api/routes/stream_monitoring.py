"""
Stream Monitoring UI API Routes.

Provides API endpoints for the web UI to monitor and display
stream processing information.
"""

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class StreamDashboardData(BaseModel):
    """Dashboard data for stream monitoring UI."""
    system_health: Dict[str, Any]
    stream_statistics: Dict[str, Any]
    recent_metrics: Dict[str, Any]
    component_status: Dict[str, Any]


async def get_system_manager():
    """Get system manager - fallback for UI when not integrated."""
    try:
        from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager as StreamSystemManager
        from gleitzeit.persistence.factory import PersistenceFactory

        persistence = await PersistenceFactory.create()
        manager = await StreamSystemManager.get_or_create(
            persistence=persistence,
            create_if_missing=False,  # Don't create from UI
            start_system=False
        )
        return manager
    except Exception as e:
        logger.warning(f"Could not get system manager: {e}")
        return None


@router.get("/stream-dashboard", response_model=StreamDashboardData)
async def get_stream_dashboard():
    """
    Get comprehensive dashboard data for stream monitoring UI.

    Returns all the data needed to render the stream monitoring
    dashboard including health, statistics, and metrics.
    """
    try:
        system_manager = await get_system_manager()

        if not system_manager:
            # Return mock data for standalone mode
            return StreamDashboardData(
                system_health={
                    "stream_processing": {
                        "enabled": False,
                        "status": "unavailable",
                        "message": "Stream processing not available"
                    }
                },
                stream_statistics={
                    "stream_processing": False,
                    "message": "System manager not available"
                },
                recent_metrics={
                    "period_hours": 1,
                    "message": "No metrics available"
                },
                component_status={
                    "timer_manager": {"status": "unavailable"},
                    "signal_manager": {"status": "unavailable"},
                    "event_scheduler": {"status": "unavailable"},
                    "stream_monitor": {"status": "unavailable"}
                }
            )

        # Get real stream data
        health = await system_manager.get_system_health()
        stats = await system_manager.get_stream_statistics()

        # Get recent metrics if monitor is available
        recent_metrics = {}
        if hasattr(system_manager, 'stream_monitor') and system_manager.stream_monitor:
            recent_metrics = system_manager.stream_monitor.get_metrics_summary(hours=1)

        # Get component status
        component_status = {}
        if hasattr(system_manager, 'timer_manager') and system_manager.timer_manager:
            timer_stats = system_manager.timer_manager.get_statistics()
            component_status["timer_manager"] = {
                "status": "running" if timer_stats.get("running", False) else "stopped",
                "stream_based": timer_stats.get("stream_based", False),
                "statistics": timer_stats
            }

        if hasattr(system_manager, 'signal_manager') and system_manager.signal_manager:
            signal_stats = system_manager.signal_manager.get_statistics()
            component_status["signal_manager"] = {
                "status": "running" if signal_stats.get("running", False) else "stopped",
                "stream_based": signal_stats.get("stream_based", False),
                "statistics": signal_stats
            }

        if hasattr(system_manager, 'event_scheduler') and system_manager.event_scheduler:
            scheduler_stats = system_manager.event_scheduler.get_statistics()
            component_status["event_scheduler"] = {
                "status": "running" if scheduler_stats.get("running", False) else "stopped",
                "stream_based": scheduler_stats.get("stream_based", False),
                "statistics": scheduler_stats
            }

        if hasattr(system_manager, 'stream_monitor') and system_manager.stream_monitor:
            monitor_status = system_manager.stream_monitor.get_status()
            component_status["stream_monitor"] = {
                "status": "running" if monitor_status.get("running", False) else "stopped",
                "statistics": monitor_status
            }

        return StreamDashboardData(
            system_health=health,
            stream_statistics=stats,
            recent_metrics=recent_metrics,
            component_status=component_status
        )

    except Exception as e:
        logger.error(f"Error getting stream dashboard data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard data: {e}")


@router.get("/stream-health")
async def get_stream_health_summary():
    """
    Get a summary of stream health for UI status indicators.

    Returns simplified health information suitable for displaying
    in UI status badges and indicators.
    """
    try:
        system_manager = await get_system_manager()

        if not system_manager:
            return {
                "overall_status": "unavailable",
                "stream_processing_enabled": False,
                "message": "System manager not available"
            }

        health = await system_manager.get_system_health()
        stream_health = health.get("stream_processing", {})

        return {
            "overall_status": stream_health.get("status", "unknown"),
            "stream_processing_enabled": stream_health.get("enabled", False),
            "total_streams": stream_health.get("total_streams", 0),
            "healthy_streams": stream_health.get("healthy_streams", 0),
            "warning_streams": stream_health.get("warning_streams", 0),
            "critical_streams": stream_health.get("critical_streams", 0),
            "total_pending_messages": stream_health.get("total_pending_messages", 0),
            "redis_memory_usage": stream_health.get("redis_memory_usage"),
            "issues": stream_health.get("issues", [])
        }

    except Exception as e:
        logger.error(f"Error getting stream health summary: {e}")
        return {
            "overall_status": "error",
            "stream_processing_enabled": False,
            "error": str(e)
        }


@router.get("/component-metrics/{component}")
async def get_component_metrics(
    component: str,
    hours: int = Query(1, ge=1, le=24)
):
    """
    Get detailed metrics for a specific component.

    Supports: timer_manager, signal_manager, event_scheduler, stream_monitor
    """
    try:
        system_manager = await get_system_manager()

        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        # Get component-specific metrics
        if component == "timer_manager" and hasattr(system_manager, 'timer_manager'):
            if system_manager.timer_manager:
                stats = system_manager.timer_manager.get_statistics()
                if hasattr(system_manager.timer_manager, 'get_stream_info'):
                    stream_info = await system_manager.timer_manager.get_stream_info()
                    stats["stream_info"] = stream_info
                return stats

        elif component == "signal_manager" and hasattr(system_manager, 'signal_manager'):
            if system_manager.signal_manager:
                stats = system_manager.signal_manager.get_statistics()
                if hasattr(system_manager.signal_manager, 'get_stream_info'):
                    stream_info = await system_manager.signal_manager.get_stream_info()
                    stats["stream_info"] = stream_info
                return stats

        elif component == "event_scheduler" and hasattr(system_manager, 'event_scheduler'):
            if system_manager.event_scheduler:
                stats = system_manager.event_scheduler.get_statistics()
                if hasattr(system_manager.event_scheduler, 'get_stream_info'):
                    stream_info = await system_manager.event_scheduler.get_stream_info()
                    stats["stream_info"] = stream_info
                return stats

        elif component == "stream_monitor" and hasattr(system_manager, 'stream_monitor'):
            if system_manager.stream_monitor:
                status = system_manager.stream_monitor.get_status()
                metrics = system_manager.stream_monitor.get_metrics_summary(hours=hours)
                return {
                    "status": status,
                    "metrics_summary": metrics
                }

        else:
            raise HTTPException(status_code=404, detail=f"Component {component} not found or not available")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metrics for component {component}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get component metrics: {e}")


@router.get("/stream-topology")
async def get_stream_topology():
    """
    Get stream topology information for visualization.

    Returns information about streams, consumer groups, and their
    relationships for displaying in the UI topology view.
    """
    try:
        system_manager = await get_system_manager()

        if not system_manager:
            return {
                "streams": [],
                "consumer_groups": [],
                "message": "System manager not available"
            }

        topology = {
            "streams": [],
            "consumer_groups": [],
            "sharding_info": {}
        }

        # Get sharding configuration
        if hasattr(system_manager, 'get_stream_config'):
            config = system_manager.get_stream_config()
            topology["sharding_info"] = {
                "total_shards": config.get("total_shards", 0),
                "consumer_group": config.get("consumer_group", ""),
                "monitoring_interval": config.get("monitoring_interval", 0)
            }

        # Get stream information from components
        stream_components = [
            ("timer_manager", "Timer Streams"),
            ("signal_manager", "Signal Streams"),
            ("event_scheduler", "Event Streams")
        ]

        for component_name, display_name in stream_components:
            if hasattr(system_manager, component_name):
                component = getattr(system_manager, component_name)
                if component and hasattr(component, 'get_stream_info'):
                    try:
                        stream_info = await component.get_stream_info()
                        for stream_name, info in stream_info.items():
                            topology["streams"].append({
                                "name": stream_name,
                                "component": display_name,
                                "length": info.get("length", 0),
                                "groups": info.get("groups", []),
                                "pending": info.get("pending", {})
                            })
                    except Exception as e:
                        logger.warning(f"Could not get stream info from {component_name}: {e}")

        # Get consumer group information
        if hasattr(system_manager, 'consumer_group_manager') and system_manager.consumer_group_manager:
            try:
                stats = system_manager.consumer_group_manager.get_statistics()
                topology["consumer_groups"].append({
                    "name": stats.get("consumer_group", ""),
                    "statistics": stats
                })
            except Exception as e:
                logger.warning(f"Could not get consumer group info: {e}")

        return topology

    except Exception as e:
        logger.error(f"Error getting stream topology: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stream topology: {e}")


@router.post("/trigger-cleanup")
async def trigger_stream_cleanup():
    """
    Trigger manual cleanup of stream components.

    Manually triggers cleanup processes for consumer groups,
    idle consumers, and pending messages.
    """
    try:
        system_manager = await get_system_manager()

        if not system_manager:
            raise HTTPException(status_code=503, detail="System manager not available")

        cleanup_results = {
            "triggered_at": "datetime.utcnow().isoformat()",
            "results": {}
        }

        # Trigger consumer group cleanup if available
        if hasattr(system_manager, 'consumer_group_manager') and system_manager.consumer_group_manager:
            # Get list of streams to clean
            streams_to_clean = []

            # Collect streams from different components
            for component_name in ["timer_manager", "signal_manager", "event_scheduler"]:
                if hasattr(system_manager, component_name):
                    component = getattr(system_manager, component_name)
                    if component and hasattr(component, 'get_stream_info'):
                        try:
                            stream_info = await component.get_stream_info()
                            streams_to_clean.extend(stream_info.keys())
                        except Exception as e:
                            logger.warning(f"Could not get streams from {component_name}: {e}")

            # Perform cleanup on each stream
            for stream_name in set(streams_to_clean):  # Remove duplicates
                try:
                    cleaned = await system_manager.consumer_group_manager.cleanup_idle_consumers(stream_name)
                    reclaimed = await system_manager.consumer_group_manager.reclaim_pending_messages(stream_name)
                    cleanup_results["results"][stream_name] = {
                        "consumers_cleaned": cleaned,
                        "messages_reclaimed": reclaimed
                    }
                except Exception as e:
                    cleanup_results["results"][stream_name] = {
                        "error": str(e)
                    }

        return cleanup_results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering stream cleanup: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger cleanup: {e}")