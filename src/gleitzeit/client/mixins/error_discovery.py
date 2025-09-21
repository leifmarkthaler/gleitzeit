"""
Error discovery mixin for Gleitzeit client.
"""

from typing import Any, Dict, List, Optional

from gleitzeit.core.errors import SystemError
from gleitzeit.core.error_discovery import (
    ErrorDiscovery,
    ErrorInfo,
    get_provider_errors,
    get_protocol_errors,
    get_error_hierarchy
)
from gleitzeit.core.protocol import ProtocolSpec


class ErrorDiscoveryMixin:
    """Mixin providing error discovery operations."""

    async def get_provider_errors(self, provider_id: str) -> List[Dict[str, Any]]:
        """
        Get all errors that a provider might raise.

        Args:
            provider_id: The provider ID to query

        Returns:
            List of error information dictionaries
        """
        if not self._adapter:
            raise SystemError("Client not initialized")

        # Try to get actual provider instance (native mode)
        if hasattr(self._adapter, 'system_manager') and self._adapter.system_manager:
            from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
            system_manager = self._adapter.system_manager
            # ModularStreamSystemManager inherits provider methods
            if hasattr(system_manager, 'get_provider'):
                provider = system_manager.get_provider(provider_id)
                if provider:
                    # Discover errors from actual provider
                    errors = get_provider_errors(provider)
                    return [error.to_dict() for error in errors]

        # Fallback: Try API endpoint if available
        if hasattr(self._adapter, 'request'):
            try:
                response = await self._adapter.request(
                    "GET",
                    f"/errors/provider/{provider_id}"
                )
                if response:
                    return response
            except Exception:
                pass

        # Last resort: return base provider errors
        from gleitzeit.providers.base import ProtocolProvider
        base_errors = ErrorDiscovery.discover_module_errors(
            __import__('gleitzeit.core.errors')
        )
        provider_errors = [e for e in base_errors if 'Provider' in e.name]
        return [error.to_dict() for error in provider_errors]

    async def get_protocol_errors(self, protocol_id: str) -> List[Dict[str, Any]]:
        """
        Get all errors associated with a protocol.

        Args:
            protocol_id: The protocol ID (e.g., "python/v1")

        Returns:
            List of error information dictionaries
        """
        if not self._adapter:
            raise SystemError("Client not initialized")

        # Get protocol from registry
        from gleitzeit.core.protocol import get_protocol
        protocol = get_protocol(protocol_id)
        if not protocol:
            raise SystemError(f"Protocol not found: {protocol_id}")

        # Discover errors
        errors = get_protocol_errors(protocol)

        # Convert to dict format
        return [error.to_dict() for error in errors]

    async def get_error_hierarchy(self) -> Dict[str, Any]:
        """
        Get the complete error hierarchy from the system.

        Returns:
            Dictionary representing the error hierarchy
        """
        if not self._adapter:
            raise SystemError("Client not initialized")

        return get_error_hierarchy()

    async def get_all_provider_errors(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get errors from all registered providers.

        Returns:
            Dictionary mapping provider IDs to their error lists
        """
        if not self._adapter:
            raise SystemError("Client not initialized")

        result = {}

        # Get all providers
        providers = await self._adapter.get_providers()

        for provider_info in providers:
            provider_id = provider_info.get("provider_id")
            if provider_id:
                try:
                    errors = await self.get_provider_errors(provider_id)
                    result[provider_id] = errors
                except Exception as e:
                    # Log but don't fail for individual provider errors
                    self.logger.warning(f"Failed to get errors for provider {provider_id}: {e}")
                    result[provider_id] = []

        return result

    async def get_error_report(self, provider_id: Optional[str] = None) -> str:
        """
        Generate a formatted error report.

        Args:
            provider_id: Optional provider ID to generate report for.
                        If None, generates report for all providers.

        Returns:
            Markdown-formatted error report
        """
        if not self._adapter:
            raise SystemError("Client not initialized")

        if provider_id:
            # Report for specific provider
            errors_dict = await self.get_provider_errors(provider_id)
            errors = [
                ErrorInfo(
                    name=e["name"],
                    error_class=type(e["class"], (Exception,), {}),
                    base_class=type(e["base_class"], (Exception,), {}),
                    module=e["module"],
                    description=e.get("description"),
                    is_retryable=e.get("is_retryable", False)
                )
                for e in errors_dict
            ]

            return ErrorDiscovery.format_error_report(
                errors,
                title=f"Error Report for {provider_id}"
            )
        else:
            # Report for all providers
            all_errors = await self.get_all_provider_errors()

            report = "# System-Wide Error Report\n\n"
            for provider_id, errors_dict in all_errors.items():
                if errors_dict:
                    report += f"## Provider: {provider_id}\n\n"
                    errors = [
                        ErrorInfo(
                            name=e["name"],
                            error_class=type(e["class"], (Exception,), {}),
                            base_class=type(e["base_class"], (Exception,), {}),
                            module=e["module"],
                            description=e.get("description"),
                            is_retryable=e.get("is_retryable", False)
                        )
                        for e in errors_dict
                    ]
                    report += ErrorDiscovery.format_error_report(errors, "").replace("# \n\n", "")
                    report += "\n"

            return report

    async def check_error_retryability(self, error_code: int) -> bool:
        """
        Check if an error code represents a retryable error.

        Args:
            error_code: The error code to check

        Returns:
            True if the error is retryable
        """
        from gleitzeit.core.errors import ErrorCode, is_retryable_error, GleitzeitError

        # Find the error code enum
        for code in ErrorCode:
            if code.value == error_code:
                # Create a dummy error with this code to check retryability
                dummy_error = GleitzeitError("test", code=code)
                return is_retryable_error(dummy_error)

        return False