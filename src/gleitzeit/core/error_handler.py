"""
Centralized Error Handler for Gleitzeit

Provides unified error handling, formatting, and user-friendly messages.
"""

import logging
import traceback
from typing import Optional, Any, Dict, Callable, Union
from functools import wraps
from contextlib import contextmanager

from gleitzeit.core.errors import (
    GleitzeitError, ErrorCode, ErrorDetail,
    TaskError, ProviderError, WorkflowError,
    SystemError, ConfigurationError
)

logger = logging.getLogger(__name__)


class ErrorHandler:
    """Centralized error handling with user-friendly messages"""
    
    # User-friendly error messages
    USER_MESSAGES = {
        ErrorCode.PROVIDER_NOT_AVAILABLE: "The service is temporarily unavailable. Please try again.",
        ErrorCode.PROVIDER_TIMEOUT: "The operation took too long. Please try again.",
        ErrorCode.TASK_TIMEOUT: "The task exceeded the time limit.",
        ErrorCode.TASK_DEPENDENCY_FAILED: "A required previous task failed.",
        ErrorCode.WORKFLOW_CIRCULAR_DEPENDENCY: "The workflow has circular dependencies.",
        ErrorCode.CONFIGURATION_ERROR: "There's a problem with the configuration.",
        ErrorCode.RATE_LIMIT_EXCEEDED: "Too many requests. Please slow down.",
        ErrorCode.RESOURCE_EXHAUSTED: "System resources are exhausted.",
        ErrorCode.CONNECTION_TIMEOUT: "Connection timeout. Check your network.",
        ErrorCode.AUTHENTICATION_FAILED: "Authentication failed. Check your credentials.",
        ErrorCode.PERSISTENCE_CONNECTION_FAILED: "Database connection failed.",
        ErrorCode.INVALID_PARAMS: "Invalid parameters provided.",
        ErrorCode.METHOD_NOT_FOUND: "The requested method doesn't exist.",
        ErrorCode.INTERNAL_ERROR: "An internal error occurred.",
    }
    
    # Suppress these warnings in production
    SUPPRESSED_WARNINGS = {
        "unknown task",
        "not found in results",
        "Field .* not found",
        "depends on unknown task",
    }
    
    def __init__(self, debug: bool = False, suppress_warnings: bool = True):
        """
        Initialize error handler
        
        Args:
            debug: Show detailed error information
            suppress_warnings: Suppress known harmless warnings
        """
        self.debug = debug
        self.suppress_warnings = suppress_warnings
        self._warning_cache = set()  # Avoid repeating same warnings
    
    def format_error(self, error: Exception) -> str:
        """
        Format error for user display
        
        Args:
            error: The exception to format
            
        Returns:
            User-friendly error message
        """
        if isinstance(error, GleitzeitError):
            # Use user-friendly message if available
            user_msg = self.USER_MESSAGES.get(error.code)
            if user_msg and not self.debug:
                return user_msg
            
            # Format with details in debug mode
            if self.debug:
                return f"{error}\nDetails: {error.data}"
            return str(error.message)
        
        # Generic exceptions
        if self.debug:
            return f"{type(error).__name__}: {error}"
        
        # Hide implementation details in production
        return "An error occurred. Use --debug for details."
    
    def handle_error(
        self,
        error: Exception,
        context: Optional[str] = None,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None
    ) -> GleitzeitError:
        """
        Convert any exception to a GleitzeitError with context
        
        Args:
            error: The exception to handle
            context: Optional context about where error occurred
            task_id: Optional task ID
            workflow_id: Optional workflow ID
            
        Returns:
            GleitzeitError with proper context
        """
        # Already a GleitzeitError
        if isinstance(error, GleitzeitError):
            # Add context if not present
            if task_id and "task_id" not in error.data:
                error.data["task_id"] = task_id
            if workflow_id and "workflow_id" not in error.data:
                error.data["workflow_id"] = workflow_id
            if context and "context" not in error.data:
                error.data["context"] = context
            return error
        
        # Convert standard exceptions
        data = {}
        if task_id:
            data["task_id"] = task_id
        if workflow_id:
            data["workflow_id"] = workflow_id
        if context:
            data["context"] = context
        
        # Map common exceptions
        if isinstance(error, TimeoutError):
            return TaskError(
                "Operation timed out",
                ErrorCode.TASK_TIMEOUT,
                task_id=task_id,
                data=data,
                cause=error
            )
        elif isinstance(error, ConnectionError):
            return ProviderError(
                "Connection failed",
                ErrorCode.CONNECTION_REFUSED,
                data=data,
                cause=error
            )
        elif isinstance(error, ValueError):
            return TaskError(
                f"Invalid value: {error}",
                ErrorCode.INVALID_PARAMS,
                task_id=task_id,
                data=data,
                cause=error
            )
        elif isinstance(error, FileNotFoundError):
            return SystemError(
                f"File not found: {error}",
                ErrorCode.CONFIGURATION_ERROR,
                data=data,
                cause=error
            )
        elif isinstance(error, PermissionError):
            return SystemError(
                f"Permission denied: {error}",
                ErrorCode.AUTHORIZATION_FAILED,
                data=data,
                cause=error
            )
        
        # Generic error
        return GleitzeitError(
            str(error),
            ErrorCode.INTERNAL_ERROR,
            data=data,
            cause=error
        )
    
    def should_suppress_warning(self, message: str) -> bool:
        """Check if a warning should be suppressed"""
        if not self.suppress_warnings:
            return False
        
        import re
        for pattern in self.SUPPRESSED_WARNINGS:
            if re.search(pattern, message, re.IGNORECASE):
                return True
        return False
    
    def log_warning(self, message: str, **kwargs):
        """Log warning if not suppressed"""
        if self.should_suppress_warning(message):
            # Cache to avoid processing same warning multiple times
            warning_key = message[:50]  # Use first 50 chars as key
            if warning_key not in self._warning_cache:
                self._warning_cache.add(warning_key)
                logger.debug(f"Suppressed warning: {message}")
        else:
            logger.warning(message, **kwargs)
    
    def log_error(
        self,
        error: Exception,
        context: Optional[str] = None,
        **kwargs
    ):
        """Log error with appropriate detail level"""
        gleitzeit_error = self.handle_error(error, context=context, **kwargs)
        
        if self.debug:
            # Full traceback in debug mode
            logger.error(
                f"{context or 'Error'}: {gleitzeit_error}",
                exc_info=True
            )
        else:
            # Just the message in production
            logger.error(f"{context or 'Error'}: {self.format_error(gleitzeit_error)}")
    
    @contextmanager
    def error_context(
        self,
        operation: str,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        reraise: bool = True
    ):
        """
        Context manager for error handling
        
        Usage:
            with error_handler.error_context("Loading workflow", workflow_id=wf_id):
                # code that might raise
        """
        try:
            yield
        except Exception as e:
            self.log_error(
                e,
                context=operation,
                task_id=task_id,
                workflow_id=workflow_id
            )
            if reraise:
                raise self.handle_error(
                    e,
                    context=operation,
                    task_id=task_id,
                    workflow_id=workflow_id
                )


def error_handler_decorator(
    handler: ErrorHandler,
    operation: Optional[str] = None,
    reraise: bool = True
):
    """
    Decorator for automatic error handling
    
    Usage:
        @error_handler_decorator(handler, "Processing task")
        def process_task(task_id):
            # code
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            op = operation or f"{func.__name__}"
            try:
                return func(*args, **kwargs)
            except Exception as e:
                handler.log_error(e, context=op)
                if reraise:
                    raise handler.handle_error(e, context=op)
                return None
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            op = operation or f"{func.__name__}"
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                handler.log_error(e, context=op)
                if reraise:
                    raise handler.handle_error(e, context=op)
                return None
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    
    return decorator


# Global error handler instance
_global_handler: Optional[ErrorHandler] = None


def get_error_handler(debug: bool = False) -> ErrorHandler:
    """Get or create global error handler"""
    global _global_handler
    if _global_handler is None:
        _global_handler = ErrorHandler(debug=debug)
    return _global_handler


def set_error_handler(handler: ErrorHandler):
    """Set global error handler"""
    global _global_handler
    _global_handler = handler


# Convenience functions
def format_error(error: Exception, debug: bool = False) -> str:
    """Format error for display"""
    handler = get_error_handler(debug)
    return handler.format_error(error)


def handle_error(
    error: Exception,
    context: Optional[str] = None,
    **kwargs
) -> GleitzeitError:
    """Convert exception to GleitzeitError"""
    handler = get_error_handler()
    return handler.handle_error(error, context, **kwargs)


def suppress_warning(message: str) -> bool:
    """Check if warning should be suppressed"""
    handler = get_error_handler()
    return handler.should_suppress_warning(message)


# Common error factories
def task_not_found_error(task_id: str) -> TaskError:
    """Create task not found error"""
    return TaskError(
        f"Task '{task_id}' not found",
        ErrorCode.TASK_NOT_FOUND,
        task_id=task_id
    )


def dependency_not_found_error(task_id: str, dependency: str) -> TaskError:
    """Create dependency not found error"""
    return TaskError(
        f"Task '{task_id}' depends on unknown task '{dependency}'",
        ErrorCode.TASK_DEPENDENCY_FAILED,
        task_id=task_id,
        data={"missing_dependency": dependency}
    )


def provider_not_available_error(provider_id: str, reason: str = "") -> ProviderError:
    """Create provider not available error"""
    msg = f"Provider '{provider_id}' is not available"
    if reason:
        msg += f": {reason}"
    return ProviderError(
        msg,
        ErrorCode.PROVIDER_NOT_AVAILABLE,
        provider_id=provider_id
    )


def workflow_validation_error(workflow_id: str, errors: list) -> WorkflowError:
    """Create workflow validation error"""
    return WorkflowError(
        f"Workflow validation failed: {', '.join(errors)}",
        ErrorCode.WORKFLOW_VALIDATION_FAILED,
        workflow_id=workflow_id,
        data={"validation_errors": errors}
    )