"""
Real error handler for the easy client that uses actual implemented errors.

This module discovers what errors are actually implemented by providers
and creates handlers based on what's really available, not hypothetical
event handlers that don't exist.
"""

from typing import Dict, List, Optional, Type, Any
from gleitzeit.core.error_discovery import (
    get_provider_errors,
    ErrorInfo,
    ErrorDiscovery
)
from gleitzeit.core.errors import ErrorCode, is_retryable_error
from gleitzeit.client import GleitzeitClient
import asyncio


class RealErrorHandler:
    """
    Error handler that uses actual implemented errors from providers.

    This discovers what errors providers can actually raise and provides
    methods to handle them based on what's really implemented.
    """

    def __init__(self, task_builder: 'TaskBuilder'):
        """
        Initialize with a TaskBuilder.

        Args:
            task_builder: The TaskBuilder this handler extends
        """
        self.task_builder = task_builder
        self._discovered_errors: Optional[List[ErrorInfo]] = None

    async def discover_errors(self, client: GleitzeitClient) -> List[ErrorInfo]:
        """
        Discover what errors are actually implemented for this task's protocol.

        Args:
            client: GleitzeitClient to use for discovery

        Returns:
            List of ErrorInfo objects for errors this provider can raise
        """
        if self._discovered_errors is not None:
            return self._discovered_errors

        # Extract protocol from task
        protocol = self.task_builder.task_data.get("protocol")
        if not protocol:
            return []

        try:
            # Get errors for this protocol's provider
            errors = await client.get_provider_errors(protocol)
            self._discovered_errors = errors
            return errors
        except Exception as e:
            print(f"Could not discover errors for {protocol}: {e}")
            return []

    def handle_retryable_errors(self) -> 'TaskBuilder':
        """
        Configure the task to handle retryable errors using the actual retry system.

        The system already implements retry logic for retryable error codes.
        This method ensures the task is configured to use it.

        Returns:
            TaskBuilder for chaining
        """
        # The retry system is built-in and checks is_retryable_error()
        # We just need to ensure retry metadata is set
        # The actual retry count is controlled by task metadata, not config

        # Set reasonable retry configuration in metadata
        if not self.task_builder.task_data.get("metadata"):
            self.task_builder.task_data["metadata"] = {}

        # These are the actual fields the retry manager checks
        self.task_builder.task_data["metadata"]["max_attempts"] = 3
        self.task_builder.task_data["metadata"]["retry_delay"] = 2.0

        return self.task_builder

    def with_timeout(self, seconds: int) -> 'TaskBuilder':
        """
        Set timeout for the task using the actual timeout system.

        The TaskExecutor uses task_timeout for execution timeouts.

        Args:
            seconds: Timeout in seconds

        Returns:
            TaskBuilder for chaining
        """
        # The actual field used by the system
        self.task_builder.task_data["timeout"] = seconds
        return self.task_builder

    def get_retryable_error_codes(self) -> List[ErrorCode]:
        """
        Get the error codes that are actually retryable in the system.

        Returns:
            List of retryable ErrorCode values
        """
        # These are the actual retryable codes from the error system
        return [
            ErrorCode.PROVIDER_TIMEOUT,
            ErrorCode.PROVIDER_OVERLOADED,
            ErrorCode.CONNECTION_TIMEOUT,
            ErrorCode.NETWORK_UNREACHABLE,
            ErrorCode.RESOURCE_EXHAUSTED,
            ErrorCode.RATE_LIMIT_EXCEEDED,
        ]

    def print_discovered_errors(self, errors: List[ErrorInfo]):
        """
        Print discovered errors for debugging.

        Args:
            errors: List of ErrorInfo objects
        """
        print(f"\nDiscovered {len(errors)} errors for {self.task_builder.task_id}:")
        for error in errors:
            retryable = "✓ Retryable" if error.is_retryable else "✗ Not retryable"
            code = error.error_code.name if error.error_code else "N/A"
            print(f"  - {error.name} ({code}) - {retryable}")


def add_real_error_methods(task_builder_class):
    """
    Add methods to TaskBuilder that use real error handling.

    Args:
        task_builder_class: The TaskBuilder class to extend
    """

    def real_errors(self) -> RealErrorHandler:
        """
        Get real error handler that uses actual implemented errors.

        Returns:
            RealErrorHandler instance
        """
        if not hasattr(self, '_real_error_handler'):
            self._real_error_handler = RealErrorHandler(self)
        return self._real_error_handler

    def with_retry(self, max_attempts: int = 3, delay: float = 2.0) -> 'TaskBuilder':
        """
        Configure retry using the actual retry system.

        Args:
            max_attempts: Maximum retry attempts
            delay: Delay between retries in seconds

        Returns:
            Self for chaining
        """
        if not self.task_data.get("metadata"):
            self.task_data["metadata"] = {}

        self.task_data["metadata"]["max_attempts"] = max_attempts
        self.task_data["metadata"]["retry_delay"] = delay

        return self

    def with_timeout(self, seconds: int) -> 'TaskBuilder':
        """
        Set timeout using the actual timeout system.

        Args:
            seconds: Timeout in seconds

        Returns:
            Self for chaining
        """
        self.task_data["timeout"] = seconds
        return self

    # Add the methods to TaskBuilder
    task_builder_class.real_errors = real_errors
    task_builder_class.with_retry = with_retry
    task_builder_class.with_timeout = with_timeout


async def discover_provider_errors_example():
    """
    Example of discovering what errors are actually available.
    """
    from gleitzeit.client import GleitzeitClient

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Discover errors for different providers
    protocols = ["python/v1", "llm/v1", "timer/v1"]

    for protocol in protocols:
        print(f"\n{'='*50}")
        print(f"Errors for {protocol}:")
        print('='*50)

        try:
            errors = await client.get_provider_errors(protocol)

            # Separate retryable from non-retryable
            retryable = [e for e in errors if e.get('is_retryable', False)]
            non_retryable = [e for e in errors if not e.get('is_retryable', False)]

            print(f"\nRetryable errors ({len(retryable)}):")
            for error in retryable:
                code = error.get('error_code_name', 'N/A')
                print(f"  ✓ {error['name']} - {code}")

            print(f"\nNon-retryable errors ({len(non_retryable)}):")
            for error in non_retryable:
                code = error.get('error_code_name', 'N/A')
                print(f"  ✗ {error['name']} - {code}")

        except Exception as e:
            print(f"  Error discovering: {e}")


if __name__ == "__main__":
    # Run the discovery example
    asyncio.run(discover_provider_errors_example())