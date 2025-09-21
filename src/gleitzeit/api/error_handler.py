"""
Error handling utilities for Gleitzeit API.

Maps Gleitzeit errors to appropriate HTTP status codes.
"""

from typing import Dict, Any, Optional
from fastapi import HTTPException
from gleitzeit.core.errors import (
    SystemError,
    GleitzeitError,
    ErrorCode,
    AuthenticationError,
    AuthorizationError
)
import logging

logger = logging.getLogger(__name__)


# Map ErrorCode to HTTP status codes
ERROR_CODE_TO_STATUS = {
    # Authentication & Authorization
    ErrorCode.AUTHENTICATION_FAILED: 401,
    ErrorCode.AUTHORIZATION_FAILED: 403,
    ErrorCode.ACCOUNT_LOCKED: 423,  # Locked
    ErrorCode.EMAIL_NOT_VERIFIED: 403,
    ErrorCode.FORBIDDEN: 403,
    
    # Client errors
    ErrorCode.INVALID_PARAMS: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.ALREADY_EXISTS: 409,  # Conflict
    ErrorCode.METHOD_NOT_FOUND: 405,
    ErrorCode.METHOD_NOT_SUPPORTED: 405,
    
    # Rate limiting
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,  # Too Many Requests
    
    # Server errors
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SYSTEM_NOT_INITIALIZED: 503,  # Service Unavailable
    ErrorCode.SYSTEM_SHUTDOWN: 503,
    ErrorCode.CONFIGURATION_ERROR: 500,
    ErrorCode.RESOURCE_EXHAUSTED: 503,
    
    # Provider errors
    ErrorCode.PROVIDER_NOT_FOUND: 404,
    ErrorCode.PROVIDER_NOT_AVAILABLE: 503,
    ErrorCode.PROVIDER_TIMEOUT: 504,  # Gateway Timeout
    ErrorCode.PROVIDER_OVERLOADED: 503,
    
    # Task/Workflow errors
    ErrorCode.TASK_VALIDATION_FAILED: 400,
    ErrorCode.TASK_EXECUTION_FAILED: 500,
    ErrorCode.TASK_TIMEOUT: 504,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.WORKFLOW_VALIDATION_FAILED: 400,
    ErrorCode.WORKFLOW_NOT_FOUND: 404,
    
    # Persistence errors
    ErrorCode.PERSISTENCE_CONNECTION_FAILED: 503,
    ErrorCode.PERSISTENCE_WRITE_FAILED: 500,
    ErrorCode.PERSISTENCE_READ_FAILED: 500,
    
    # Network errors
    ErrorCode.CONNECTION_TIMEOUT: 504,
    ErrorCode.CONNECTION_REFUSED: 503,
}


def gleitzeit_error_to_http(error: Exception) -> HTTPException:
    """
    Convert a Gleitzeit error to an appropriate HTTPException.
    
    Args:
        error: The exception to convert
        
    Returns:
        HTTPException with appropriate status code and detail
    """
    # Handle Gleitzeit errors with proper code mapping
    if isinstance(error, GleitzeitError):
        status_code = ERROR_CODE_TO_STATUS.get(error.code, 500)
        
        # Build detail message with error code
        detail = {
            "message": error.message,
            "error_code": error.code.name,
            "error_value": error.code.value
        }
        
        # Add extra data if available
        if error.data:
            detail["data"] = error.data
            
        # Log the error for debugging
        if status_code >= 500:
            logger.error(f"Server error: {error}")
        elif status_code >= 400:
            logger.warning(f"Client error: {error}")
            
        return HTTPException(
            status_code=status_code,
            detail=detail
        )
    
    # Handle non-Gleitzeit exceptions
    logger.error(f"Unexpected error: {error}", exc_info=True)
    return HTTPException(
        status_code=500,
        detail={
            "message": "Internal server error",
            "error_type": type(error).__name__
        }
    )


def handle_auth_error(error: SystemError) -> HTTPException:
    """
    Special handling for authentication errors.
    
    Args:
        error: SystemError from auth operations
        
    Returns:
        HTTPException with appropriate auth status
    """
    # Map specific auth error codes
    if error.code == ErrorCode.AUTHENTICATION_FAILED:
        return HTTPException(
            status_code=401,
            detail={
                "message": error.message,
                "error": "authentication_failed"
            },
            headers={"WWW-Authenticate": "Bearer"}
        )
    elif error.code == ErrorCode.AUTHORIZATION_FAILED:
        return HTTPException(
            status_code=403,
            detail={
                "message": error.message,
                "error": "authorization_failed"
            }
        )
    elif error.code == ErrorCode.ACCOUNT_LOCKED:
        return HTTPException(
            status_code=423,
            detail={
                "message": error.message,
                "error": "account_locked",
                "retry_after": error.data.get("retry_after")
            }
        )
    elif error.code == ErrorCode.EMAIL_NOT_VERIFIED:
        return HTTPException(
            status_code=403,
            detail={
                "message": error.message,
                "error": "email_not_verified"
            }
        )
    else:
        # Fallback to general error handler
        return gleitzeit_error_to_http(error)


def create_error_response(
    status_code: int,
    message: str,
    error_code: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None
) -> HTTPException:
    """
    Create a standardized error response.
    
    Args:
        status_code: HTTP status code
        message: Error message
        error_code: Optional error code string
        data: Optional additional data
        
    Returns:
        HTTPException with standardized format
    """
    detail = {"message": message}
    
    if error_code:
        detail["error_code"] = error_code
        
    if data:
        detail["data"] = data
        
    return HTTPException(
        status_code=status_code,
        detail=detail
    )