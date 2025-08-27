"""
Structured error responses for Gleitzeit API.

Integrates with the central error system to provide consistent,
actionable error messages with proper HTTP status codes.
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gleitzeit.core.errors import (
    ErrorCode, ErrorDetail, GleitzeitError,
    TaskError, WorkflowError, ProviderError,
    PersistenceError, SystemError
)


class APIErrorResponse(BaseModel):
    """Structured API error response model"""
    error: Dict[str, Any] = Field(..., description="Error details")
    request_id: Optional[str] = Field(None, description="Request tracking ID")
    
    class Config:
        schema_extra = {
            "example": {
                "error": {
                    "code": -29001,
                    "message": "Task validation failed",
                    "data": {
                        "task_id": "task-123",
                        "validation_errors": ["Missing required field: method"]
                    }
                },
                "request_id": "req-abc123"
            }
        }


def error_code_to_http_status(code: ErrorCode) -> int:
    """Map error codes to HTTP status codes"""
    
    # 4xx Client Errors
    if code in [
        ErrorCode.INVALID_REQUEST,
        ErrorCode.INVALID_PARAMS,
        ErrorCode.TASK_VALIDATION_FAILED,
        ErrorCode.WORKFLOW_VALIDATION_FAILED,
        ErrorCode.TASK_PARAMETER_ERROR
    ]:
        return 400  # Bad Request
    
    if code == ErrorCode.AUTHENTICATION_FAILED:
        return 401  # Unauthorized
    
    if code == ErrorCode.AUTHORIZATION_FAILED:
        return 403  # Forbidden
    
    if code in [
        ErrorCode.METHOD_NOT_FOUND,
        ErrorCode.TASK_NOT_FOUND,
        ErrorCode.WORKFLOW_NOT_FOUND,
        ErrorCode.PROVIDER_NOT_FOUND,
        ErrorCode.PROTOCOL_NOT_FOUND
    ]:
        return 404  # Not Found
    
    if code == ErrorCode.TASK_TIMEOUT:
        return 408  # Request Timeout
    
    if code == ErrorCode.TASK_CANCELLED:
        return 409  # Conflict
    
    if code == ErrorCode.RATE_LIMIT_EXCEEDED:
        return 429  # Too Many Requests
    
    # 5xx Server Errors
    if code in [
        ErrorCode.PROVIDER_NOT_AVAILABLE,
        ErrorCode.PROVIDER_UNHEALTHY,
        ErrorCode.PROVIDER_TIMEOUT,
        ErrorCode.PROVIDER_OVERLOADED,
        ErrorCode.RESOURCE_EXHAUSTED,
        ErrorCode.QUEUE_FULL,
        ErrorCode.SYSTEM_NOT_INITIALIZED,
        ErrorCode.SYSTEM_SHUTDOWN
    ]:
        return 503  # Service Unavailable
    
    if code in [
        ErrorCode.PERSISTENCE_CONNECTION_FAILED,
        ErrorCode.NETWORK_UNREACHABLE,
        ErrorCode.CONNECTION_REFUSED
    ]:
        return 502  # Bad Gateway
    
    # Default to 500 for any other errors
    return 500  # Internal Server Error


def create_api_error_response(
    error: Exception,
    request_id: Optional[str] = None
) -> JSONResponse:
    """
    Create a structured API error response from an exception.
    
    Args:
        error: The exception that occurred
        request_id: Optional request tracking ID
        
    Returns:
        JSONResponse with appropriate status code and error details
    """
    
    # Handle GleitzeitError and its subclasses
    if isinstance(error, GleitzeitError):
        error_detail = error.to_error_detail()
        status_code = error_code_to_http_status(error.code)
        
        # Add helpful context for common errors
        if error.code == ErrorCode.TASK_VALIDATION_FAILED:
            error_detail.data = error_detail.data or {}
            error_detail.data["suggestion"] = "Check that all required fields are provided and valid"
        
        elif error.code == ErrorCode.PROVIDER_NOT_AVAILABLE:
            error_detail.data = error_detail.data or {}
            error_detail.data["suggestion"] = "The provider may be offline or overloaded. Try again later."
        
        elif error.code == ErrorCode.PERSISTENCE_CONNECTION_FAILED:
            error_detail.data = error_detail.data or {}
            error_detail.data["suggestion"] = "System is using fallback storage. Performance may be degraded."
            
    # Handle standard HTTPException
    elif isinstance(error, HTTPException):
        error_detail = ErrorDetail(
            code=ErrorCode.INTERNAL_ERROR,
            message=error.detail or str(error),
            data={"status_code": error.status_code}
        )
        status_code = error.status_code
        
    # Handle any other exception
    else:
        error_detail = ErrorDetail(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            data={
                "error_type": type(error).__name__,
                "error_message": str(error)
            }
        )
        status_code = 500
    
    # Build response
    response_data = APIErrorResponse(
        error=error_detail.to_dict(),
        request_id=request_id
    )
    
    return JSONResponse(
        status_code=status_code,
        content=response_data.dict()
    )


class APIErrorHandler:
    """Global error handler for the API"""
    
    @staticmethod
    async def handle_gleitzeit_error(request: Request, error: GleitzeitError):
        """Handle GleitzeitError exceptions"""
        request_id = request.headers.get("X-Request-ID")
        return create_api_error_response(error, request_id)
    
    @staticmethod
    async def handle_http_exception(request: Request, error: HTTPException):
        """Handle HTTPException"""
        request_id = request.headers.get("X-Request-ID")
        return create_api_error_response(error, request_id)
    
    @staticmethod
    async def handle_generic_exception(request: Request, error: Exception):
        """Handle any other exceptions"""
        request_id = request.headers.get("X-Request-ID")
        
        # Log the full exception for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unhandled exception: {error}", exc_info=True)
        
        return create_api_error_response(error, request_id)


def raise_api_error(
    code: ErrorCode,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    cause: Optional[Exception] = None
):
    """
    Convenience function to raise a GleitzeitError that will be handled by the API.
    
    Args:
        code: Error code from ErrorCode enum
        message: Human-readable error message
        data: Optional additional context
        cause: Optional underlying exception
        
    Raises:
        GleitzeitError with the specified details
    """
    raise GleitzeitError(
        message=message,
        code=code,
        data=data,
        cause=cause
    )