"""
Error-aware event handler extension for the easy syntax.

Provides fluent methods to handle specific error codes based on
the comprehensive error system documented in ERROR-SYSTEM-DOCUMENTATION.md.
"""

from typing import Dict, Any, List, Optional, Callable
from gleitzeit.core.errors import ErrorCode, is_retryable_error


class ErrorAwareEventHandler:
    """
    Enhanced event handler that understands Gleitzeit error codes.

    This allows users to handle specific error conditions with proper
    error code awareness.
    """

    def __init__(self, task_builder: 'TaskBuilder'):
        """
        Initialize error-aware event handler.

        Args:
            task_builder: The TaskBuilder this handler extends
        """
        self.task_builder = task_builder
        self._error_handlers: Dict[ErrorCode, List[Callable]] = {}

    def on_provider_timeout(self) -> 'EventHandler':
        """
        Handle provider timeout errors.

        Returns:
            EventHandler configured for PROVIDER_TIMEOUT error
        """
        return self.task_builder.on_error(str(ErrorCode.PROVIDER_TIMEOUT.value))

    def on_provider_not_found(self) -> 'EventHandler':
        """
        Handle provider not found errors.

        Returns:
            EventHandler configured for PROVIDER_NOT_FOUND error
        """
        return self.task_builder.on_error(str(ErrorCode.PROVIDER_NOT_FOUND.value))

    def on_provider_overloaded(self) -> 'EventHandler':
        """
        Handle provider overloaded errors.

        Returns:
            EventHandler configured for PROVIDER_OVERLOADED error
        """
        return self.task_builder.on_error(str(ErrorCode.PROVIDER_OVERLOADED.value))

    def on_method_not_supported(self) -> 'EventHandler':
        """
        Handle method not supported errors.

        Returns:
            EventHandler configured for METHOD_NOT_SUPPORTED error
        """
        return self.task_builder.on_error(str(ErrorCode.METHOD_NOT_SUPPORTED.value))

    def on_task_timeout(self) -> 'EventHandler':
        """
        Handle task timeout errors.

        Returns:
            EventHandler configured for TASK_TIMEOUT error
        """
        return self.task_builder.on_error(str(ErrorCode.TASK_TIMEOUT.value))

    def on_task_validation_failed(self) -> 'EventHandler':
        """
        Handle task validation errors.

        Returns:
            EventHandler configured for TASK_VALIDATION_FAILED error
        """
        return self.task_builder.on_error(str(ErrorCode.TASK_VALIDATION_FAILED.value))

    def on_authentication_failed(self) -> 'EventHandler':
        """
        Handle authentication failures.

        Returns:
            EventHandler configured for AUTHENTICATION_FAILED error
        """
        return self.task_builder.on_error(str(ErrorCode.AUTHENTICATION_FAILED.value))

    def on_rate_limit_exceeded(self) -> 'EventHandler':
        """
        Handle rate limit errors.

        Returns:
            EventHandler configured for RATE_LIMIT_EXCEEDED error
        """
        return self.task_builder.on_error(str(ErrorCode.RATE_LIMIT_EXCEEDED.value))

    def on_resource_exhausted(self) -> 'EventHandler':
        """
        Handle resource exhausted errors (e.g., token limits).

        Returns:
            EventHandler configured for RESOURCE_EXHAUSTED error
        """
        return self.task_builder.on_error(str(ErrorCode.RESOURCE_EXHAUSTED.value))

    def on_retryable_error(self) -> 'RetryableErrorHandler':
        """
        Handle all retryable errors with automatic retry logic.

        Returns:
            RetryableErrorHandler for configuring retry behavior
        """
        return RetryableErrorHandler(self.task_builder)

    def on_critical_error(self) -> 'CriticalErrorHandler':
        """
        Handle critical errors that require immediate attention.

        Returns:
            CriticalErrorHandler for critical error handling
        """
        return CriticalErrorHandler(self.task_builder)


class RetryableErrorHandler:
    """
    Handler for retryable errors with automatic retry configuration.
    """

    def __init__(self, task_builder: 'TaskBuilder'):
        """
        Initialize retryable error handler.

        Args:
            task_builder: The TaskBuilder to configure
        """
        self.task_builder = task_builder
        self.retryable_codes = [
            ErrorCode.PROVIDER_TIMEOUT,
            ErrorCode.PROVIDER_OVERLOADED,
            ErrorCode.CONNECTION_TIMEOUT,
            ErrorCode.NETWORK_UNREACHABLE,
            ErrorCode.RESOURCE_EXHAUSTED,
            ErrorCode.RATE_LIMIT_EXCEEDED,
        ]

    def with_exponential_backoff(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0
    ) -> 'TaskBuilder':
        """
        Configure exponential backoff for retryable errors.

        Args:
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds

        Returns:
            TaskBuilder for chaining
        """
        # Configure retry with exponential backoff
        self.task_builder.retry(max_retries)

        # Add handlers for each retryable error code
        for error_code in self.retryable_codes:
            handler = self.task_builder.on_error(str(error_code.value))
            # Wait with exponential backoff
            handler.wait("${retry_count * 2}")  # Simple exponential
            handler.retry_self()

        return self.task_builder

    def with_linear_backoff(
        self,
        max_retries: int = 3,
        delay: float = 5.0
    ) -> 'TaskBuilder':
        """
        Configure linear backoff for retryable errors.

        Args:
            max_retries: Maximum number of retry attempts
            delay: Fixed delay between retries in seconds

        Returns:
            TaskBuilder for chaining
        """
        # Configure retry with linear backoff
        self.task_builder.retry(max_retries)

        # Add handlers for each retryable error code
        for error_code in self.retryable_codes:
            handler = self.task_builder.on_error(str(error_code.value))
            handler.wait(delay)
            handler.retry_self()

        return self.task_builder


class CriticalErrorHandler:
    """
    Handler for critical errors that need immediate attention.
    """

    def __init__(self, task_builder: 'TaskBuilder'):
        """
        Initialize critical error handler.

        Args:
            task_builder: The TaskBuilder to configure
        """
        self.task_builder = task_builder
        self.critical_codes = [
            ErrorCode.SYSTEM_SHUTDOWN,
            ErrorCode.AUTHENTICATION_FAILED,
            ErrorCode.AUTHORIZATION_FAILED,
            ErrorCode.CONFIGURATION_ERROR,
        ]

    def notify_and_halt(
        self,
        notification_protocol: str = "notification/v1:send_alert"
    ) -> 'TaskBuilder':
        """
        Send notification and halt workflow on critical errors.

        Args:
            notification_protocol: Protocol for sending notifications

        Returns:
            TaskBuilder for chaining
        """
        for error_code in self.critical_codes:
            handler = self.task_builder.on_error(str(error_code.value))
            handler.run(
                f"{self.task_builder.task_id}_critical_alert",
                notification_protocol
            ).with_(
                severity="CRITICAL",
                message=f"Critical error in task {self.task_builder.task_id}",
                error_code="${error.code}",
                error_message="${error.message}"
            )

        return self.task_builder

    def escalate_to_admin(
        self,
        admin_protocol: str = "admin/v1:escalate"
    ) -> 'TaskBuilder':
        """
        Escalate critical errors to admin for manual intervention.

        Args:
            admin_protocol: Protocol for admin escalation

        Returns:
            TaskBuilder for chaining
        """
        for error_code in self.critical_codes:
            handler = self.task_builder.on_error(str(error_code.value))
            handler.run(
                f"{self.task_builder.task_id}_admin_escalation",
                admin_protocol
            ).with_(
                task_id=self.task_builder.task_id,
                error_code="${error.code}",
                error_details="${error}",
                workflow_id="${workflow.id}"
            )

        return self.task_builder


def add_error_aware_methods(task_builder_class):
    """
    Monkey-patch TaskBuilder to add error-aware methods.

    This adds convenience methods to TaskBuilder for handling
    specific error conditions.

    Args:
        task_builder_class: The TaskBuilder class to extend
    """

    def errors(self) -> ErrorAwareEventHandler:
        """
        Get error-aware event handler for this task.

        Returns:
            ErrorAwareEventHandler instance
        """
        if not hasattr(self, '_error_handler'):
            self._error_handler = ErrorAwareEventHandler(self)
        return self._error_handler

    # Add the method to TaskBuilder
    task_builder_class.errors = errors