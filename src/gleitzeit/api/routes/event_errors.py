"""
API endpoints for event error management and debugging.

Provides REST endpoints to query persisted event handler errors
for debugging and monitoring purposes.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, HTTPException, Path, Request
from pydantic import BaseModel, Field

from gleitzeit.core.event_error_persistence import get_event_error_persistence
from gleitzeit.api.error_responses import raise_api_error
from gleitzeit.core.errors import ErrorCode
from gleitzeit.auth.decorators import optional_permission, filter_by_ownership

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
@optional_permission("events:read")
@filter_by_ownership()
async def list_event_errors(
    request: Request,
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
    from ..main import app_state
    
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.get_event_errors(
            level=None,
            source=handler_name,
            task_id=None,
            limit=limit,
            offset=0
        )
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        # Convert to response models
        error_responses = []
        for error in result.get("errors", []):
            error_responses.append(EventErrorResponse(
                id=error.get('id', ''),
                handler_name=error.get('source', ''),
                event_type=event_type or 'UNKNOWN',
                event_id=error.get('task_id'),
                error_type=error.get('exception', 'Unknown'),
                error_message=error.get('message', ''),
                error_traceback=error.get('stack_trace'),
                timestamp=datetime.fromisoformat(error['timestamp'].replace('Z', '+00:00')) if isinstance(error['timestamp'], str) else error['timestamp'],
                metadata={}
            ))
        
        return error_responses
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve event errors: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve event errors: {str(e)}")


@router.get("/stats", 
    response_model=EventErrorStats,
    summary="Get error statistics",
    description="Retrieve aggregated statistics about event handler errors for monitoring and identifying problematic handlers.",
    response_description="Aggregated error statistics"
)
@optional_permission("events:read")
async def get_error_statistics(request: Request):
    """
    Get statistics about event handler errors.
    
    Returns aggregated statistics for monitoring and debugging.
    """
    from ..main import app_state
    
    if not app_state.client:
        return EventErrorStats(
            total_errors=0,
            handlers_with_errors=[],
            event_types_with_errors=[],
            oldest_error=None,
            newest_error=None
        )
    
    try:
        result = await app_state.client.get_event_error_stats()
        
        if "error" in result:
            return EventErrorStats(
                total_errors=0,
                handlers_with_errors=[],
                event_types_with_errors=[],
                oldest_error=None,
                newest_error=None
            )
        
        return EventErrorStats(
            total_errors=result.get("total_errors", 0),
            handlers_with_errors=result.get("by_level", {}).items(),
            event_types_with_errors=[],  # Not implemented yet
            oldest_error=None,  # Not implemented yet
            newest_error=None   # Not implemented yet
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
@optional_permission("events:read")
async def get_event_error(
    request: Request,
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
@optional_permission(["events:write", "system:admin"], any_permission=True)
async def cleanup_old_errors(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Delete errors older than this many days")
):
    """
    Clean up old event errors.
    
    Removes errors older than the specified number of days.
    Default retention is 30 days.
    """
    from ..main import app_state
    
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.cleanup_event_errors(days=days)
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cleanup old errors: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup old errors: {str(e)}")


@router.get("/debug/event-bus-stats")
@optional_permission(["events:read", "system:debug"], any_permission=True)
async def get_event_bus_stats(request: Request):
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