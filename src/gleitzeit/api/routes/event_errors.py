"""
API endpoints for event error management and debugging.

Provides REST endpoints to query persisted event handler errors
for debugging and monitoring purposes.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, HTTPException, Path
from pydantic import BaseModel, Field

from gleitzeit.core.event_error_persistence import get_event_error_persistence
from gleitzeit.api.error_responses import raise_api_error
from gleitzeit.core.errors import ErrorCode

import logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/event-errors",
    tags=["event-errors"],
    responses={
        404: {"description": "Event error not found"},
        503: {"description": "Event error persistence not available"}
    }
)


class EventErrorResponse(BaseModel):
    """Response model for event errors"""
    id: str = Field(..., description="Unique error ID")
    handler_name: str = Field(..., description="Name of handler that failed")
    event_type: str = Field(..., description="Type of event being handled")
    event_id: Optional[str] = Field(None, description="Event ID if available")
    error_type: str = Field(..., description="Exception class name")
    error_message: str = Field(..., description="Error message")
    error_traceback: Optional[str] = Field(None, description="Full traceback")
    timestamp: datetime = Field(..., description="When error occurred")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    
    class Config:
        schema_extra = {
            "example": {
                "id": "abc-123-def",
                "handler_name": "TaskCompletedHandler",
                "event_type": "TASK_COMPLETED",
                "event_id": "evt-456",
                "error_type": "ValueError",
                "error_message": "Invalid task state",
                "timestamp": "2024-01-15T10:30:00",
                "metadata": {"task_id": "task-789"}
            }
        }


class EventErrorStats(BaseModel):
    """Statistics about event errors"""
    total_errors: int = Field(..., description="Total number of errors")
    handlers_with_errors: List[tuple] = Field(..., description="Handlers and error counts")
    event_types_with_errors: List[tuple] = Field(..., description="Event types and error counts")
    oldest_error: Optional[datetime] = Field(None, description="Oldest error timestamp")
    newest_error: Optional[datetime] = Field(None, description="Newest error timestamp")
    
    class Config:
        schema_extra = {
            "example": {
                "total_errors": 25,
                "handlers_with_errors": [
                    ["TaskCompletedHandler", 15],
                    ["WorkflowHandler", 10]
                ],
                "event_types_with_errors": [
                    ["TASK_COMPLETED", 20],
                    ["WORKFLOW_FAILED", 5]
                ],
                "oldest_error": "2024-01-01T00:00:00",
                "newest_error": "2024-01-15T10:30:00"
            }
        }


@router.get("", 
    response_model=List[EventErrorResponse],
    summary="List recent event errors",
    description="Retrieve persisted event handler errors for debugging and monitoring. Errors are returned in reverse chronological order.",
    response_description="List of event errors with full details"
)
async def list_event_errors(
    limit: int = Query(100, le=1000, description="Maximum errors to return"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    handler_name: Optional[str] = Query(None, description="Filter by handler name"),
    since: Optional[datetime] = Query(None, description="Errors since this timestamp")
):
    """
    List recent event handler errors.
    
    Returns persisted errors for debugging and monitoring.
    Errors are returned in reverse chronological order (newest first).
    """
    error_persistence = get_event_error_persistence()
    if not error_persistence:
        raise_api_error(
            ErrorCode.SYSTEM_NOT_INITIALIZED,
            "Event error persistence not available",
            data={"suggestion": "Event error persistence may be disabled or not initialized"}
        )
    
    try:
        # Get recent errors
        errors = await error_persistence.get_recent_errors(
            limit=limit,
            event_type=event_type
        )
        
        # Apply additional filters
        if handler_name:
            errors = [e for e in errors if e.handler_name == handler_name]
        
        if since:
            errors = [e for e in errors if e.timestamp >= since]
        
        # Convert to response models
        return [
            EventErrorResponse(
                id=error.id,
                handler_name=error.handler_name,
                event_type=error.event_type,
                event_id=error.event_id,
                error_type=error.error_type,
                error_message=error.error_message,
                error_traceback=error.error_traceback,
                timestamp=error.timestamp,
                metadata=error.metadata
            )
            for error in errors[:limit]
        ]
        
    except Exception as e:
        logger.error(f"Failed to retrieve event errors: {e}")
        from gleitzeit.core.errors import SystemError
        raise SystemError(
            message="Failed to retrieve event errors",
            code=ErrorCode.INTERNAL_ERROR,
            cause=e
        )


@router.get("/stats", 
    response_model=EventErrorStats,
    summary="Get error statistics",
    description="Retrieve aggregated statistics about event handler errors for monitoring and identifying problematic handlers.",
    response_description="Aggregated error statistics"
)
async def get_error_statistics():
    """
    Get statistics about event handler errors.
    
    Returns aggregated statistics for monitoring and debugging.
    """
    from gleitzeit.events.base import EventBus
    
    # Try to get stats from the event bus if available
    # This would need to be made accessible, for now we'll use persistence
    error_persistence = get_event_error_persistence()
    
    if not error_persistence:
        # Return empty stats if persistence not available
        return EventErrorStats(
            total_errors=0,
            handlers_with_errors=[],
            event_types_with_errors=[],
            oldest_error=None,
            newest_error=None
        )
    
    try:
        # Get recent errors to calculate stats
        errors = await error_persistence.get_recent_errors(limit=1000)
        
        if not errors:
            return EventErrorStats(
                total_errors=0,
                handlers_with_errors=[],
                event_types_with_errors=[],
                oldest_error=None,
                newest_error=None
            )
        
        # Calculate statistics
        handler_counts = {}
        event_type_counts = {}
        oldest = None
        newest = None
        
        for error in errors:
            # Count by handler
            handler_counts[error.handler_name] = handler_counts.get(error.handler_name, 0) + 1
            
            # Count by event type
            event_type_counts[error.event_type] = event_type_counts.get(error.event_type, 0) + 1
            
            # Track oldest/newest
            if oldest is None or error.timestamp < oldest:
                oldest = error.timestamp
            if newest is None or error.timestamp > newest:
                newest = error.timestamp
        
        # Sort by count
        handlers_sorted = sorted(
            [(h, c) for h, c in handler_counts.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        event_types_sorted = sorted(
            [(e, c) for e, c in event_type_counts.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        return EventErrorStats(
            total_errors=len(errors),
            handlers_with_errors=handlers_sorted,
            event_types_with_errors=event_types_sorted,
            oldest_error=oldest,
            newest_error=newest
        )
        
    except Exception as e:
        logger.error(f"Failed to calculate error statistics: {e}")
        from gleitzeit.core.errors import SystemError
        raise SystemError(
            message="Failed to calculate error statistics",
            code=ErrorCode.INTERNAL_ERROR,
            cause=e
        )


@router.get("/{error_id}", response_model=EventErrorResponse)
async def get_event_error(
    error_id: str = Path(..., description="Event error ID")
):
    """
    Get a specific event error by ID.
    
    Returns the full error details including traceback.
    """
    error_persistence = get_event_error_persistence()
    if not error_persistence:
        raise_api_error(
            ErrorCode.SYSTEM_NOT_INITIALIZED,
            "Event error persistence not available",
            data={"suggestion": "Event error persistence may be disabled or not initialized"}
        )
    
    try:
        error = await error_persistence.get_error(error_id)
        
        if not error:
            raise_api_error(
                ErrorCode.RESOURCE_NOT_FOUND,
                f"Event error not found: {error_id}",
                data={"error_id": error_id}
            )
        
        return EventErrorResponse(
            id=error.id,
            handler_name=error.handler_name,
            event_type=error.event_type,
            event_id=error.event_id,
            error_type=error.error_type,
            error_message=error.error_message,
            error_traceback=error.error_traceback,
            timestamp=error.timestamp,
            metadata=error.metadata
        )
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Failed to retrieve event error: {e}")
        from gleitzeit.core.errors import SystemError
        raise SystemError(
            message=f"Failed to retrieve event error: {error_id}",
            code=ErrorCode.INTERNAL_ERROR,
            cause=e
        )


@router.delete("/cleanup")
async def cleanup_old_errors(
    days: int = Query(30, ge=1, le=365, description="Delete errors older than this many days")
):
    """
    Clean up old event errors.
    
    Removes errors older than the specified number of days.
    Default retention is 30 days.
    """
    error_persistence = get_event_error_persistence()
    if not error_persistence:
        raise_api_error(
            ErrorCode.SYSTEM_NOT_INITIALIZED,
            "Event error persistence not available",
            data={"suggestion": "Event error persistence may be disabled or not initialized"}
        )
    
    try:
        # Temporarily set retention days
        original_retention = error_persistence.retention_days
        error_persistence.retention_days = days
        
        # Cleanup
        removed = await error_persistence.cleanup_old_errors()
        
        # Restore original retention
        error_persistence.retention_days = original_retention
        
        return {
            "success": True,
            "removed": removed,
            "message": f"Removed {removed} errors older than {days} days"
        }
        
    except Exception as e:
        logger.error(f"Failed to cleanup old errors: {e}")
        from gleitzeit.core.errors import SystemError
        raise SystemError(
            message="Failed to cleanup old errors",
            code=ErrorCode.INTERNAL_ERROR,
            cause=e
        )


@router.get("/debug/event-bus-stats")
async def get_event_bus_stats():
    """
    Get current event bus error statistics.
    
    Returns in-memory error stats from the active event bus.
    This is separate from persisted errors and shows current session only.
    """
    # This would need access to the global event bus
    # For now, return a placeholder indicating it needs to be implemented
    return {
        "message": "Event bus stats endpoint requires global event bus access",
        "suggestion": "Use /event-errors/stats for persisted error statistics",
        "available": False
    }