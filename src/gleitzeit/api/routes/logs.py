"""
API endpoints for log management and querying.

Provides REST endpoints to query, search, and manage system logs
collected by the LogCollector service.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, HTTPException, Depends, Request
from pydantic import BaseModel, Field
import logging

from gleitzeit.core.log_collector import get_log_collector
from gleitzeit.core.logs import LogLevel, LogSource
from gleitzeit.api.error_responses import raise_api_error
from gleitzeit.core.errors import ErrorCode
from gleitzeit.auth.decorators import optional_permission, filter_by_ownership

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/logs",
    tags=["logs"],
    responses={
        503: {"description": "Log collector not available"}
    }
)


class LogEntryResponse(BaseModel):
    """Response model for log entries"""
    id: Optional[str] = Field(None, description="Log entry ID")
    timestamp: datetime = Field(..., description="When log was created")
    level: str = Field(..., description="Log level")
    source: str = Field(..., description="Log source")
    message: str = Field(..., description="Log message")
    task_id: Optional[str] = Field(None, description="Associated task ID")
    workflow_id: Optional[str] = Field(None, description="Associated workflow ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    
    class Config:
        schema_extra = {
            "example": {
                "id": "log-123",
                "timestamp": "2024-01-15T10:30:00Z",
                "level": "INFO",
                "source": "TASK",
                "message": "Task execution started",
                "task_id": "task-456",
                "workflow_id": "wf-789",
                "metadata": {"provider": "ollama"}
            }
        }


class LogQueryResponse(BaseModel):
    """Response for log queries"""
    logs: List[LogEntryResponse] = Field(..., description="Log entries")
    total: int = Field(..., description="Total matching logs")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Results per page")


class LogStats(BaseModel):
    """Log statistics response"""
    total_logs: int = Field(..., description="Total number of logs")
    by_level: Dict[str, int] = Field(..., description="Counts by log level")
    by_source: Dict[str, int] = Field(..., description="Counts by source")
    oldest_log: Optional[datetime] = Field(None, description="Oldest log timestamp")
    newest_log: Optional[datetime] = Field(None, description="Newest log timestamp")
    storage_backend: str = Field(..., description="Storage backend in use")
    retention_days: Optional[int] = Field(None, description="Retention period in days")
    
    class Config:
        schema_extra = {
            "example": {
                "total_logs": 10000,
                "by_level": {
                    "DEBUG": 3000,
                    "INFO": 5000,
                    "WARNING": 1500,
                    "ERROR": 500
                },
                "by_source": {
                    "TASK": 7000,
                    "WORKFLOW": 2000,
                    "SYSTEM": 800,
                    "API": 200
                },
                "oldest_log": "2024-01-01T00:00:00Z",
                "newest_log": "2024-01-15T15:30:00Z",
                "storage_backend": "redis",
                "retention_days": 30
            }
        }


class RetentionSettings(BaseModel):
    """Log retention settings"""
    retention_days: int = Field(..., description="Days to retain logs")
    auto_cleanup: bool = Field(..., description="Enable automatic cleanup")
    cleanup_schedule: Optional[str] = Field(None, description="Cleanup schedule")
    max_logs_per_task: Optional[int] = Field(None, description="Max logs per task")


@router.get("", 
    response_model=LogQueryResponse,
    summary="Query system logs",
    description="Query all system logs with filtering and pagination support."
)
@optional_permission("logs:read")
@filter_by_ownership()
async def query_logs(
    request: Request,
    level: Optional[str] = Query(None, description="Filter by log level"),
    source: Optional[str] = Query(None, description="Filter by source"),
    task_id: Optional[str] = Query(None, description="Filter by task ID"),
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    since: Optional[datetime] = Query(None, description="Logs since timestamp"),
    until: Optional[datetime] = Query(None, description="Logs until timestamp"),
    limit: int = Query(100, le=1000, description="Maximum logs to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Query system logs with filtering and pagination.
    
    Returns logs matching the specified criteria, ordered by timestamp (newest first).
    """
    from ..main import app_state
    
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.query_logs(
            level=level,
            source=source,
            task_id=task_id,
            workflow_id=workflow_id,
            limit=limit,
            offset=offset
        )
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        # Convert to response models
        log_entries = []
        for log in result.get("logs", []):
            log_entries.append(LogEntryResponse(
                id=log.get('id'),
                timestamp=datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00')) if isinstance(log['timestamp'], str) else log['timestamp'],
                level=log['level'],
                source=log['source'],
                message=log['message'],
                task_id=log.get('task_id'),
                workflow_id=log.get('workflow_id'),
                metadata=log.get('metadata')
            ))
        
        return LogQueryResponse(
            logs=log_entries,
            total=result.get("total", 0),
            offset=offset,
            limit=limit
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {str(e)}")


@router.get("/search",
    response_model=LogQueryResponse,
    summary="Search logs",
    description="Search logs by text content across all tasks and workflows."
)
@optional_permission("logs:read")
@filter_by_ownership()
async def search_logs(
    request: Request,
    query: str = Query(..., description="Search query text"),
    task_id: Optional[str] = Query(None, description="Filter by task ID"),
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    level: Optional[str] = Query(None, description="Minimum log level"),
    limit: int = Query(50, le=500, description="Maximum results")
):
    """
    Search logs by text content.
    
    Searches through log messages for the specified query text.
    """
    from ..main import app_state
    
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.search_logs(
            query=query,
            limit=limit,
            offset=0
        )
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        # Convert to response models
        log_entries = []
        for log in result.get("logs", []):
            log_entries.append(LogEntryResponse(
                id=log.get('id'),
                timestamp=datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00')) if isinstance(log['timestamp'], str) else log['timestamp'],
                level=log['level'],
                source=log['source'],
                message=log['message'],
                task_id=log.get('task_id'),
                workflow_id=log.get('workflow_id'),
                metadata=log.get('metadata')
            ))
        
        return LogQueryResponse(
            logs=log_entries,
            total=result.get("total", len(log_entries)),
            offset=0,
            limit=limit
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to search logs: {str(e)}")


@router.get("/stats",
    response_model=LogStats,
    summary="Get log statistics",
    description="Get aggregated statistics about system logs."
)
@optional_permission("logs:read")
async def get_log_statistics(
    request: Request,
    since: Optional[datetime] = Query(None, description="Stats since timestamp"),
    until: Optional[datetime] = Query(None, description="Stats until timestamp")
):
    """
    Get log statistics.
    
    Returns aggregated statistics about log volumes, levels, and sources.
    """
    from ..main import app_state
    
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.get_log_stats()
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        return LogStats(
            total_logs=result.get("total_logs", 0),
            by_level=result.get("by_level", {}),
            by_source={},  # Not implemented yet in GleitzeitClient
            oldest_log=None,  # Not implemented yet in GleitzeitClient
            newest_log=None,  # Not implemented yet in GleitzeitClient
            storage_backend=result.get("storage_backend", "unknown"),
            retention_days=30  # Default retention
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get log statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get log statistics: {str(e)}")


@router.delete("/cleanup",
    summary="Clean up old logs",
    description="Remove logs older than specified retention period."
)
@optional_permission(["logs:write", "system:admin"], any_permission=True)
async def cleanup_logs(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Delete logs older than N days"),
    level: Optional[str] = Query(None, description="Only delete logs of this level or lower")
):
    """
    Clean up old logs.
    
    Removes logs older than the specified number of days.
    Optionally filter by log level to only remove debug/info logs.
    """
    from ..main import app_state
    
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.cleanup_logs(days=days)
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cleanup logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup logs: {str(e)}")


@router.get("/retention",
    response_model=RetentionSettings,
    summary="Get retention settings",
    description="Get current log retention configuration."
)
@optional_permission("logs:read")
async def get_retention_settings(request: Request):
    """
    Get log retention settings.
    
    Returns the current configuration for log retention and cleanup.
    """
    log_collector = get_log_collector()
    if not log_collector:
        raise_api_error(
            ErrorCode.SYSTEM_NOT_INITIALIZED,
            "Log collector not available"
        )
    
    # Return current settings (these would typically come from config)
    return RetentionSettings(
        retention_days=30,  # Default
        auto_cleanup=False,  # Not yet implemented
        cleanup_schedule="daily",
        max_logs_per_task=10000
    )


@router.put("/retention",
    response_model=RetentionSettings,
    summary="Update retention settings",
    description="Update log retention configuration."
)
@optional_permission(["logs:write", "system:admin"], any_permission=True)
async def update_retention_settings(request: Request, settings: RetentionSettings):
    """
    Update log retention settings.
    
    Updates the configuration for log retention and cleanup.
    Note: This endpoint is not yet fully implemented.
    """
    log_collector = get_log_collector()
    if not log_collector:
        raise_api_error(
            ErrorCode.SYSTEM_NOT_INITIALIZED,
            "Log collector not available"
        )
    
    # This would need to persist settings and update collector
    # For now, just return the requested settings
    logger.info(f"Log retention update requested: {settings.dict()}")
    
    return settings


@router.get("/tail/{task_id}",
    response_model=List[LogEntryResponse],
    summary="Tail task logs",
    description="Get the most recent logs for a specific task."
)
@optional_permission("logs:read")
async def tail_task_logs(
    request: Request,
    task_id: str,
    lines: int = Query(50, le=500, description="Number of recent lines")
):
    """
    Tail logs for a specific task.
    
    Returns the most recent log entries for the specified task.
    """
    log_collector = get_log_collector()
    if not log_collector:
        raise_api_error(
            ErrorCode.SYSTEM_NOT_INITIALIZED,
            "Log collector not available"
        )
    
    try:
        if not log_collector.log_redis:
            raise_api_error(
                ErrorCode.FEATURE_NOT_AVAILABLE,
                "Log tailing requires Redis backend"
            )
        
        # Get recent logs for task
        logs = await log_collector.log_redis.get_logs(
            task_id=task_id,
            limit=lines
        )
        
        # Convert to response models
        log_entries = []
        for log in logs:
            log_entries.append(LogEntryResponse(
                id=getattr(log, 'id', None),
                timestamp=log.timestamp,
                level=log.level.name,
                source=log.source.name,
                message=log.message,
                task_id=log.task_id,
                workflow_id=log.workflow_id,
                metadata=log.metadata
            ))
        
        return log_entries
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to tail logs: {e}")
        from gleitzeit.core.errors import SystemError
        raise SystemError(
            message=f"Failed to tail logs for task {task_id}",
            code=ErrorCode.INTERNAL_ERROR,
            cause=e
        )