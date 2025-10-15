"""
Structured Logging Mixin for Gleitzeit Components.

Provides consistent, structured logging across all components by integrating
with the centralized LogCollector system.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
import asyncio
import contextvars

from gleitzeit.core.logs import LogLevel, LogSource

# Use StatelessLogService for logging
from gleitzeit.core.stateless_log_service import StatelessLogService

log_context = contextvars.ContextVar('log_context', default={})

# Optional OpenTelemetry integration
try:
    from opentelemetry import trace
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    trace = None

# Standard logger for fallback
logger = logging.getLogger(__name__)


class LoggingMixin:
    """
    Mixin to add structured logging to any class.
    
    Integrates with the centralized LogCollector when available,
    falls back to standard Python logging otherwise.
    
    Usage:
        class MyComponent(LoggingMixin):
            async def do_something(self):
                await self.log_operation("starting_task", task_id="123")
                try:
                    # ... do work ...
                    await self.log_success("task_completed", task_id="123", duration=5.2)
                except Exception as e:
                    await self.log_error("task_failed", e, task_id="123")
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize the mixin"""
        # Only call super().__init__() if there's another class in the MRO
        # to avoid TypeError with object.__init__()
        if len(self.__class__.__mro__) > 2:  # More than (cls, LoggingMixin, object)
            super().__init__(*args, **kwargs)
        self._component_name = self.__class__.__name__
        self._log_source = self._determine_log_source()
    
    def _determine_log_source(self) -> LogSource:
        """Determine the appropriate LogSource based on component type"""
        name_lower = self._component_name.lower()
        
        if "engine" in name_lower:
            return LogSource.ENGINE
        elif "provider" in name_lower:
            return LogSource.PROVIDER
        elif "queue" in name_lower or "task" in name_lower:
            return LogSource.QUEUE  # Changed from TASK to QUEUE
        elif "dependency" in name_lower or "workflow" in name_lower:
            return LogSource.DEPENDENCY
        elif "api" in name_lower or "endpoint" in name_lower:
            return LogSource.API
        elif "hub" in name_lower:
            return LogSource.HUB
        elif "retry" in name_lower:
            return LogSource.RETRY
        elif "scheduler" in name_lower:
            return LogSource.SCHEDULER
        else:
            return LogSource.SYSTEM
    
    async def log_operation(
        self,
        operation: str,
        level: LogLevel = LogLevel.INFO,
        **context
    ) -> None:
        """
        Log an operation with context.

        Args:
            operation: Name of the operation being performed
            level: Log severity level
            **context: Additional context to include in the log
        """
        message = f"{self._component_name}.{operation}"

        # Write to Redis if appropriate level
        await self._log_to_redis(level, message, operation, context)

        # Also write to file logs (existing behavior)
        await self._log(level, message, context)
    
    async def log_success(
        self,
        operation: str,
        **context
    ) -> None:
        """
        Log a successful operation.

        Args:
            operation: Name of the operation that succeeded
            **context: Additional context to include in the log
        """
        message = f"{self._component_name}.{operation} succeeded"

        # Write to Redis
        await self._log_to_redis(LogLevel.INFO, message, operation, context)

        # Also write to file logs
        await self._log(LogLevel.INFO, message, context)
    
    async def log_error(
        self,
        operation: str,
        error: Exception,
        **context
    ) -> None:
        """
        Log an error with full context.

        Now writes to Redis via StatelessLogService.

        Args:
            operation: Name of the operation that failed
            error: The exception that occurred
            **context: Additional context to include in the log
        """
        message = f"{self._component_name}.{operation} failed: {str(error)}"

        # Extract workflow and task IDs
        workflow_id = context.get('workflow_id')
        task_id = context.get('task_id')

        # Error details
        error_type = type(error).__name__

        # Get stack trace
        import traceback
        stack_trace = ''.join(traceback.format_exception(
            type(error), error, error.__traceback__
        ))

        # Build metadata
        error_metadata = {
            "operation": operation,
            "error_message": str(error),
            **context
        }

        # Add error code if it's a GleitzeitError
        if hasattr(error, 'code'):
            error_metadata["error_code"] = error.code.value if hasattr(error.code, 'value') else error.code
            error_metadata["error_code_name"] = error.code.name if hasattr(error.code, 'name') else str(error.code)

        # Add cause if available
        if hasattr(error, 'cause') and error.cause:
            error_metadata["cause"] = str(error.cause)
            error_metadata["cause_type"] = type(error.cause).__name__

        # Get Redis connection
        redis = context.pop('redis', None) or getattr(self, 'redis', None)

        if redis:
            try:
                # Write to Redis via StatelessLogService
                await StatelessLogService.log_error(
                    redis=redis,
                    message=message,
                    workflow_id=workflow_id,
                    task_id=task_id,
                    component=self._component_name,
                    error_type=error_type,
                    stack_trace=stack_trace,
                    metadata=error_metadata
                )
            except Exception as e:
                # Fallback to file logging
                logger.error(f"Failed to write error to Redis: {e}")
                self._fallback_log(LogLevel.ERROR, message, error_metadata)
        else:
            # No Redis, use fallback
            self._fallback_log(LogLevel.ERROR, message, error_metadata)
    
    async def log_warning(
        self,
        operation: str,
        warning_message: str,
        **context
    ) -> None:
        """
        Log a warning.

        Args:
            operation: Name of the operation
            warning_message: Warning message
            **context: Additional context to include in the log
        """
        message = f"{self._component_name}.{operation}: {warning_message}"

        # Write to Redis
        await self._log_to_redis(LogLevel.WARNING, message, operation, context)

        # Also write to file logs
        await self._log(LogLevel.WARNING, message, context)
    
    async def log_debug(
        self,
        operation: str,
        debug_message: str,
        **context
    ) -> None:
        """
        Log debug information.

        Args:
            operation: Name of the operation
            debug_message: Debug message
            **context: Additional context to include in the log
        """
        message = f"{self._component_name}.{operation}: {debug_message}"

        # Write to Redis (with sampling)
        await self._log_to_redis(LogLevel.DEBUG, message, operation, context)

        # Also write to file logs
        await self._log(LogLevel.DEBUG, message, context)
    
    async def _log_to_redis(
        self,
        level: LogLevel,
        message: str,
        operation: str,
        context: Dict[str, Any]
    ) -> None:
        """
        Write log to Redis via StatelessLogService.

        Args:
            level: Log severity level
            message: Log message
            operation: Operation name
            context: Additional context
        """
        # Get Redis connection
        redis = context.get('redis') or getattr(self, 'redis', None)
        if not redis:
            return  # No Redis, skip

        # Extract workflow/task IDs
        workflow_id = context.get('workflow_id')
        task_id = context.get('task_id')

        # Default sample rate for DEBUG (10%)
        sample_rate = context.get('debug_sample_rate', 0.1)

        try:
            if level == LogLevel.ERROR:
                # Errors already handled by log_error method
                pass
            elif level == LogLevel.WARNING:
                await StatelessLogService.log_warning(
                    redis=redis,
                    message=message,
                    workflow_id=workflow_id,
                    task_id=task_id,
                    component=self._component_name,
                    warning_type=operation,
                    metadata=context
                )
            elif level == LogLevel.INFO:
                await StatelessLogService.log_info(
                    redis=redis,
                    message=message,
                    workflow_id=workflow_id,
                    task_id=task_id,
                    component=self._component_name,
                    operation=operation,
                    metadata=context
                )
            elif level == LogLevel.DEBUG:
                await StatelessLogService.log_debug(
                    redis=redis,
                    message=message,
                    workflow_id=workflow_id,
                    task_id=task_id,
                    component=self._component_name,
                    operation=operation,
                    metadata=context,
                    sample_rate=sample_rate
                )
        except Exception as e:
            # Don't fail if Redis logging fails
            logger.warning(f"Failed to write log to Redis: {e}")

    async def _log(
        self,
        level: LogLevel,
        message: str,
        context: Dict[str, Any]
    ) -> None:
        """
        Internal method to log via LogCollector or fallback to standard logging.

        Args:
            level: Log severity level
            message: Log message
            context: Additional context
        """
        # Try to use LogCollector
        log_collector = get_log_collector()
        
        if log_collector:
            # Extract IDs from context if present
            task_id = context.pop('task_id', None)
            workflow_id = context.pop('workflow_id', None)
            provider_id = context.pop('provider_id', None)
            
            # Add component info to metadata
            metadata = {
                "component": self._component_name,
                **context
            }
            
            try:
                await log_collector.log(
                    level=level,
                    message=message,
                    source=self._log_source,
                    task_id=task_id,
                    workflow_id=workflow_id,
                    provider_id=provider_id,
                    metadata=metadata
                )
            except Exception as e:
                # Fallback to standard logging if LogCollector fails
                logger.error(f"Failed to log via LogCollector: {e}")
                self._fallback_log(level, message, context)
        else:
            # No LogCollector available, use standard logging
            self._fallback_log(level, message, context)
    
    def _fallback_log(
        self,
        level: LogLevel,
        message: str,
        context: Dict[str, Any]
    ) -> None:
        """
        Fallback to standard Python logging.
        
        Args:
            level: Log severity level
            message: Log message
            context: Additional context
        """
        # Map LogLevel to Python logging levels
        level_map = {
            LogLevel.DEBUG: logging.DEBUG,
            LogLevel.INFO: logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
            LogLevel.CRITICAL: logging.CRITICAL
        }
        
        py_level = level_map.get(level, logging.INFO)
        
        # Log with extra context
        logger.log(
            py_level,
            message,
            extra={
                "component": self._component_name,
                **context
            }
        )
    
    def set_log_context(self, **context) -> None:
        """
        Set context that will be included in all subsequent logs.
        
        Args:
            **context: Context to set (e.g., task_id, workflow_id)
        """
        current_context = log_context.get()
        updated_context = {**current_context, **context}
        log_context.set(updated_context)
    
    def clear_log_context(self) -> None:
        """Clear the current log context."""
        log_context.set({})
    
    async def traced_operation(self, operation_name: str, **attributes):
        """Simple traced operation - just logs start/end and adds span attributes if OpenTelemetry available"""
        from contextlib import asynccontextmanager
        
        @asynccontextmanager
        async def _traced_op():
            start_time = datetime.utcnow()
            await self.log_operation(f"{operation_name}_start", **attributes)
            
            span = None
            if OPENTELEMETRY_AVAILABLE and trace:
                try:
                    current_span = trace.get_current_span()
                    if current_span and current_span.is_recording():
                        span = current_span
                        # Add attributes to current span
                        for key, value in attributes.items():
                            span.set_attribute(f"op.{key}", value)
                        span.set_attribute("op.component", self._component_name)
                        span.set_attribute("op.operation", operation_name)
                except:
                    pass
            
            try:
                yield span
                duration = (datetime.utcnow() - start_time).total_seconds()
                await self.log_success(f"{operation_name}_complete", duration_seconds=duration, **attributes)
            except Exception as e:
                duration = (datetime.utcnow() - start_time).total_seconds()
                await self.log_error(operation_name, e, duration_seconds=duration, **attributes)
                raise
        
        return _traced_op()


class SyncLoggingMixin(LoggingMixin):
    """
    Synchronous version of LoggingMixin for non-async components.
    
    Uses synchronous fallback logging instead of creating async tasks.
    This ensures true stateless operation without creating event loops.
    """
    
    def _sync_log(self, level: LogLevel, message: str, context: Dict[str, Any]):
        """Direct synchronous logging without async operations."""
        # Always use fallback logging in sync contexts to avoid event loop issues
        self._fallback_log(level, message, context)
    
    def log_operation(self, operation: str, level: LogLevel = LogLevel.INFO, **context) -> None:
        """Synchronous version of log_operation."""
        message = f"{self._component_name}.{operation}"
        self._sync_log(level, message, context)
    
    def log_success(self, operation: str, **context) -> None:
        """Synchronous version of log_success."""
        message = f"{self._component_name}.{operation} succeeded"
        self._sync_log(LogLevel.INFO, message, context)
    
    def log_error(self, operation: str, error: Exception, **context) -> None:
        """Synchronous version of log_error."""
        message = f"{self._component_name}.{operation} failed: {str(error)}"
        
        # Add error details to context
        error_context = {
            **context,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "operation": operation
        }
        
        # Add error code if it's a GleitzeitError
        if hasattr(error, 'code'):
            error_context["error_code"] = error.code.value if hasattr(error.code, 'value') else error.code
            error_context["error_code_name"] = error.code.name if hasattr(error.code, 'name') else str(error.code)
        
        # Add cause if available
        if hasattr(error, 'cause') and error.cause:
            error_context["cause"] = str(error.cause)
            error_context["cause_type"] = type(error.cause).__name__
        
        self._sync_log(LogLevel.ERROR, message, error_context)
    
    def log_warning(self, operation: str, warning_message: str, **context) -> None:
        """Synchronous version of log_warning."""
        message = f"{self._component_name}.{operation}: {warning_message}"
        self._sync_log(LogLevel.WARNING, message, context)
    
    def log_debug(self, operation: str, debug_message: str, **context) -> None:
        """Synchronous version of log_debug."""
        message = f"{self._component_name}.{operation}: {debug_message}"
        self._sync_log(LogLevel.DEBUG, message, context)


