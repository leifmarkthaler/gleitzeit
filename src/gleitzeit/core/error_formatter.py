"""
Error Formatter for Gleitzeit

Provides consistent error formatting and user-friendly messages without suppressing important logs.
"""

import logging
import re
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from gleitzeit.core.errors import (
    GleitzeitError, ErrorCode, ErrorDetail,
    TaskError, ProviderError, WorkflowError
)

logger = logging.getLogger(__name__)


class ErrorFormatter:
    """Formats errors for different audiences (users vs developers)"""
    
    # User-friendly error messages
    USER_FRIENDLY_MESSAGES = {
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
    
    # Patterns that indicate normal operation (not real errors)
    EXPECTED_PATTERNS = [
        r"Task '.*' depends on unknown task",  # Normal during dependency resolution
        r"Field .* not found in task .* result",  # Normal during parameter substitution
        r"Referenced task .* not found in results",  # Normal during early execution
    ]
    
    def __init__(self, debug: bool = False):
        """
        Initialize error formatter
        
        Args:
            debug: Show detailed error information
        """
        self.debug = debug
    
    def format_for_user(self, error: Exception) -> str:
        """
        Format error for end-user display
        
        Args:
            error: The exception to format
            
        Returns:
            User-friendly error message
        """
        if isinstance(error, GleitzeitError):
            # Use user-friendly message if available
            user_msg = self.USER_FRIENDLY_MESSAGES.get(error.code)
            if user_msg and not self.debug:
                return user_msg
            
            # In debug mode, show more details
            if self.debug:
                details = []
                if error.data:
                    for key, value in error.data.items():
                        if key not in ['cause', 'cause_type']:  # Skip internal fields
                            details.append(f"{key}: {value}")
                
                if details:
                    return f"{error.message} ({', '.join(details)})"
            
            return error.message
        
        # Generic exceptions
        if self.debug:
            return f"{type(error).__name__}: {error}"
        
        # Hide implementation details in production
        return "An error occurred. Use --debug for details."
    
    def format_for_log(self, error: Exception, context: Optional[str] = None) -> str:
        """
        Format error for logging (always detailed)
        
        Args:
            error: The exception to format
            context: Optional context about where error occurred
            
        Returns:
            Detailed error message for logs
        """
        if isinstance(error, GleitzeitError):
            parts = []
            if context:
                parts.append(f"[{context}]")
            parts.append(f"{error.code.name}: {error.message}")
            
            if error.data:
                parts.append(f"Data: {error.data}")
            
            if error.cause:
                parts.append(f"Caused by: {error.cause}")
            
            return " | ".join(parts)
        
        # Generic exception
        parts = []
        if context:
            parts.append(f"[{context}]")
        parts.append(f"{type(error).__name__}: {error}")
        return " | ".join(parts)
    
    def is_expected_warning(self, message: str) -> bool:
        """
        Check if a warning message is expected during normal operation
        
        Args:
            message: The warning message
            
        Returns:
            True if this is an expected warning
        """
        for pattern in self.EXPECTED_PATTERNS:
            if re.search(pattern, message):
                return True
        return False
    
    def get_log_level(self, message: str) -> int:
        """
        Determine appropriate log level for a message
        
        Args:
            message: The log message
            
        Returns:
            Logging level (DEBUG, INFO, WARNING, ERROR)
        """
        if self.is_expected_warning(message):
            # Expected warnings go to DEBUG in production, INFO in debug mode
            return logging.DEBUG if not self.debug else logging.INFO
        return logging.WARNING


class CleanLogger:
    """
    Wrapper for logger that adjusts log levels based on context
    """
    
    def __init__(self, logger: logging.Logger, formatter: ErrorFormatter):
        self.logger = logger
        self.formatter = formatter
    
    def log(self, level: int, message: str, *args, **kwargs):
        """Log with automatic level adjustment"""
        # Adjust level for expected warnings
        if level == logging.WARNING:
            level = self.formatter.get_log_level(message)
        
        self.logger.log(level, message, *args, **kwargs)
    
    def debug(self, message: str, *args, **kwargs):
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """Warning that might be downgraded to debug"""
        level = self.formatter.get_log_level(message)
        self.logger.log(level, message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        self.logger.error(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        self.logger.exception(message, *args, **kwargs)


# Global formatter instance
_global_formatter: Optional[ErrorFormatter] = None


def get_error_formatter(debug: bool = False) -> ErrorFormatter:
    """Get or create global error formatter"""
    global _global_formatter
    if _global_formatter is None:
        _global_formatter = ErrorFormatter(debug=debug)
    return _global_formatter


def set_debug_mode(debug: bool):
    """Set global debug mode"""
    global _global_formatter
    _global_formatter = ErrorFormatter(debug=debug)


def format_error_for_user(error: Exception, debug: bool = False) -> str:
    """Format error for user display"""
    formatter = get_error_formatter(debug)
    return formatter.format_for_user(error)


def format_error_for_log(error: Exception, context: Optional[str] = None) -> str:
    """Format error for logging"""
    formatter = get_error_formatter()
    return formatter.format_for_log(error, context)


def get_clean_logger(name: str, debug: bool = False) -> CleanLogger:
    """
    Get a logger that adjusts levels for expected warnings
    
    Args:
        name: Logger name
        debug: Debug mode
        
    Returns:
        CleanLogger instance
    """
    formatter = get_error_formatter(debug)
    logger = logging.getLogger(name)
    return CleanLogger(logger, formatter)


# Error message improvements for common cases
def improve_error_message(error: Exception) -> str:
    """
    Improve error messages for common cases
    
    Args:
        error: The exception
        
    Returns:
        Improved error message
    """
    message = str(error)
    
    # Common improvements
    improvements = {
        r"Task '(.+)' depends on unknown task '(.+)'": 
            "Task '{0}' requires task '{1}' which hasn't been defined or executed yet",
        
        r"Field (.+) not found in task (.+) result":
            "Task '{1}' doesn't have a '{0}' field in its result. Check the task output format.",
        
        r"Referenced task (.+) not found in results":
            "Task '{0}' hasn't completed yet or wasn't found",
        
        r"Provider not found: (.+)":
            "The '{0}' service isn't available. Check if it's installed and running.",
        
        r"Connection to (.+) timed out":
            "Couldn't connect to {0}. Check if the service is running and accessible.",
    }
    
    for pattern, improved in improvements.items():
        match = re.search(pattern, message)
        if match:
            return improved.format(*match.groups())
    
    return message


class ErrorContext:
    """Context manager for clean error handling in operations"""
    
    def __init__(
        self,
        operation: str,
        logger: Optional[logging.Logger] = None,
        debug: bool = False,
        reraise: bool = True
    ):
        self.operation = operation
        self.logger = logger or logging.getLogger(__name__)
        self.debug = debug
        self.reraise = reraise
        self.formatter = ErrorFormatter(debug=debug)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            # Log the full error details
            log_msg = self.formatter.format_for_log(exc_val, self.operation)
            
            if isinstance(exc_val, GleitzeitError):
                # Known error - log at appropriate level
                if exc_val.code in [ErrorCode.TASK_CANCELLED, ErrorCode.WORKFLOW_CANCELLED]:
                    self.logger.info(log_msg)
                else:
                    self.logger.error(log_msg)
            else:
                # Unknown error - always log as error with traceback
                self.logger.error(log_msg, exc_info=True)
            
            # Optionally reraise with improved message
            if self.reraise:
                if not isinstance(exc_val, GleitzeitError):
                    # Wrap in GleitzeitError for consistency
                    raise TaskError(
                        improve_error_message(exc_val),
                        ErrorCode.TASK_EXECUTION_FAILED,
                        data={"operation": self.operation, "original_error": str(exc_val)}
                    ) from exc_val
                # Re-raise GleitzeitError as-is
                raise
            
            return True  # Suppress the exception
        
        return False