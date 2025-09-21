"""
Logs monitoring endpoints - proxies to Gleitzeit API
"""

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict, Any
from datetime import datetime
import aiohttp
import logging
import os

router = APIRouter()
logger = logging.getLogger(__name__)

# Get Gleitzeit API URL from app state dynamically
def get_api_url(request: Request) -> str:
    """Get API URL from app state"""
    return getattr(request.app.state, 'api_url', 'http://localhost:8000')

# In-memory log cache for UI (optional - could be removed if only real-time needed)
_ui_logs = []

@router.get("")
async def get_logs(
    request: Request,
    level: Optional[str] = Query(None, description="Log level filter (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
    source: Optional[str] = Query(None, description="Source/component filter"),
    start_time: Optional[str] = Query(None, description="Start time for log range (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time for log range (ISO format)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
) -> List[Dict[str, Any]]:
    """
    Get logs with optional filtering - proxies to main API
    
    Args:
        level: Log level filter
        source: Source/component filter
        start_time: Start time for range (ISO format)
        end_time: End time for range (ISO format)
        limit: Maximum number of logs
        offset: Pagination offset
    
    Returns:
        List of log entries
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Build query parameters
            params = {
                "limit": limit,
                "offset": offset
            }
            
            if level:
                params["level"] = level
            if source:
                params["source"] = source
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time
            
            # Proxy request to main API
            api_url = get_api_url(request)
            async with session.get(
                f"{api_url}/logs/",
                params=params,
                timeout=30
            ) as response:
                if response.status == 200:
                    logs = await response.json()
                    
                    # Cache logs for UI (optional)
                    _ui_logs.clear()
                    _ui_logs.extend(logs if isinstance(logs, list) else [])
                    
                    return logs
                else:
                    error_text = await response.text()
                    logger.error(f"API request failed: {response.status} - {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Failed to fetch logs: {error_text}"
                    )
                    
        except aiohttp.ClientTimeout:
            logger.error("Timeout connecting to Gleitzeit API")
            raise HTTPException(status_code=504, detail="Timeout connecting to API")
        except aiohttp.ClientError as e:
            logger.error(f"Error connecting to Gleitzeit API: {e}")
            raise HTTPException(status_code=503, detail="Unable to connect to API")
        except Exception as e:
            logger.error(f"Unexpected error fetching logs: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/levels")
async def get_log_levels() -> List[str]:
    """
    Get available log levels - proxies to main API
    
    Returns:
        List of log level strings
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{get_api_url(request)}/logs/levels",
                timeout=10
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"API request failed: {response.status} - {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Failed to fetch log levels: {error_text}"
                    )
                    
        except aiohttp.ClientError as e:
            logger.error(f"Error connecting to Gleitzeit API: {e}")
            # Return default log levels as fallback
            return ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        except Exception as e:
            logger.error(f"Unexpected error fetching log levels: {e}")
            return ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


@router.get("/sources")
async def get_log_sources() -> List[str]:
    """
    Get available log sources - proxies to main API
    
    Returns:
        List of log source strings
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{get_api_url(request)}/logs/sources",
                timeout=10
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"API request failed: {response.status} - {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Failed to fetch log sources: {error_text}"
                    )
                    
        except aiohttp.ClientError as e:
            logger.error(f"Error connecting to Gleitzeit API: {e}")
            # Return empty list as fallback
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching log sources: {e}")
            return []


@router.get("/task/{task_id}")
async def get_task_logs(
    task_id: str,
    level: Optional[str] = Query(None, description="Log level filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
) -> List[Dict[str, Any]]:
    """
    Get logs for a specific task - proxies to main API
    
    Args:
        task_id: Task ID to get logs for
        level: Log level filter
        limit: Maximum number of logs
        offset: Pagination offset
    
    Returns:
        List of log entries for the task
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Build query parameters
            params = {
                "limit": limit,
                "offset": offset
            }
            
            if level:
                params["level"] = level
            
            # Proxy request to main API
            async with session.get(
                f"{get_api_url(request)}/logs/task/{task_id}",
                params=params,
                timeout=30
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"API request failed: {response.status} - {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Failed to fetch task logs: {error_text}"
                    )
                    
        except aiohttp.ClientError as e:
            logger.error(f"Error connecting to Gleitzeit API: {e}")
            raise HTTPException(status_code=503, detail="Unable to connect to API")
        except Exception as e:
            logger.error(f"Unexpected error fetching task logs: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/workflow/{workflow_id}")
async def get_workflow_logs(
    workflow_id: str,
    level: Optional[str] = Query(None, description="Log level filter"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
) -> List[Dict[str, Any]]:
    """
    Get logs for a specific workflow - proxies to main API
    
    Args:
        workflow_id: Workflow ID to get logs for
        level: Log level filter
        limit: Maximum number of logs
        offset: Pagination offset
    
    Returns:
        List of log entries for the workflow
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Build query parameters
            params = {
                "limit": limit,
                "offset": offset
            }
            
            if level:
                params["level"] = level
            
            # Proxy request to main API
            async with session.get(
                f"{get_api_url(request)}/logs/workflow/{workflow_id}",
                params=params,
                timeout=30
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"API request failed: {response.status} - {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Failed to fetch workflow logs: {error_text}"
                    )
                    
        except aiohttp.ClientError as e:
            logger.error(f"Error connecting to Gleitzeit API: {e}")
            raise HTTPException(status_code=503, detail="Unable to connect to API")
        except Exception as e:
            logger.error(f"Unexpected error fetching workflow logs: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_log_stats() -> Dict[str, Any]:
    """
    Get log statistics
    
    Returns:
        Dictionary with log statistics
    """
    # Return local cache stats plus attempt to get API stats
    stats = {
        "cached_logs": len(_ui_logs),
        "cache_levels": {},
        "cache_sources": set(),
        "last_updated": datetime.now().isoformat()
    }
    
    # Analyze cached logs
    for log_entry in _ui_logs:
        level = log_entry.get("level", "UNKNOWN")
        source = log_entry.get("source", "unknown")
        
        stats["cache_levels"][level] = stats["cache_levels"].get(level, 0) + 1
        stats["cache_sources"].add(source)
    
    stats["cache_sources"] = list(stats["cache_sources"])
    
    # Try to get additional stats from API
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{get_api_url(request)}/logs/stats",
                timeout=5
            ) as response:
                if response.status == 200:
                    api_stats = await response.json()
                    stats["api_stats"] = api_stats
    except Exception as e:
        logger.debug(f"Could not fetch API log stats: {e}")
        stats["api_stats"] = None
    
    return stats


# WebSocket integration helpers
async def notify_log_update(log_entry: Dict[str, Any]):
    """
    Send log update notification via WebSocket
    
    Args:
        log_entry: Log entry to broadcast
    """
    from .websocket import manager
    
    update = {
        "type": "log_update",
        "data": log_entry
    }
    await manager.broadcast(update, "logs")


async def notify_log_stream_start(stream_id: str, context: Dict[str, Any]):
    """
    Send log stream start notification
    
    Args:
        stream_id: Stream identifier
        context: Context information (task_id, workflow_id, etc.)
    """
    from .websocket import manager
    
    update = {
        "type": "log_stream_start",
        "data": {
            "stream_id": stream_id,
            "context": context,
            "timestamp": datetime.now().isoformat()
        }
    }
    await manager.broadcast(update, "logs")


async def notify_log_stream_end(stream_id: str):
    """
    Send log stream end notification
    
    Args:
        stream_id: Stream identifier
    """
    from .websocket import manager
    
    update = {
        "type": "log_stream_end",
        "data": {
            "stream_id": stream_id,
            "timestamp": datetime.now().isoformat()
        }
    }
    await manager.broadcast(update, "logs")