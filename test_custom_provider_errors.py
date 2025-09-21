#!/usr/bin/env python3
"""
Test if error discovery finds custom errors defined in a provider
"""

from gleitzeit.core.error_discovery import get_provider_errors
from gleitzeit.core.errors import ProviderError, ErrorCode
from gleitzeit.providers.simple import SimpleProvider


# Define custom errors for this provider
class DataValidationError(ProviderError):
    """Custom error for data validation failures"""
    def __init__(self, field: str, reason: str, **kwargs):
        super().__init__(
            f"Data validation failed for {field}: {reason}",
            code=ErrorCode.TASK_VALIDATION_FAILED,
            data={"field": field, "reason": reason},
            **kwargs
        )


class RateLimitError(ProviderError):
    """Custom error when rate limit is exceeded"""
    def __init__(self, limit: int, window: str, **kwargs):
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window}",
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            data={"limit": limit, "window": window},
            **kwargs
        )


class APIKeyError(ProviderError):
    """Custom error for API key issues"""
    def __init__(self, message: str = "Invalid or missing API key", **kwargs):
        super().__init__(
            message,
            code=ErrorCode.AUTHENTICATION_FAILED,
            **kwargs
        )


class CustomProvider(SimpleProvider):
    """Provider with custom errors"""

    def __init__(self):
        super().__init__(
            provider_id="custom-provider",
            protocol_id="custom/v1"
        )
        self.api_key = None
        self.request_count = 0
        self.rate_limit = 10

    async def execute(self, method: str, params: dict):
        """Execute method with custom error handling"""

        # Check API key
        if not self.api_key:
            raise APIKeyError("API key not configured")

        # Check rate limit
        self.request_count += 1
        if self.request_count > self.rate_limit:
            raise RateLimitError(self.rate_limit, "minute")

        # Validate data
        if method == "process_data":
            if "data" not in params:
                raise DataValidationError("data", "field is required")
            if not isinstance(params["data"], dict):
                raise DataValidationError("data", "must be a dictionary")

        return {"status": "success", "method": method}


def main():
    print("=" * 60)
    print("TESTING CUSTOM PROVIDER ERROR DISCOVERY")
    print("=" * 60)

    # Create provider instance
    provider = CustomProvider()

    # Discover errors
    errors = get_provider_errors(provider)

    print(f"\nDiscovered {len(errors)} error types:\n")

    # Separate custom from base errors
    custom_errors = []
    base_errors = []

    for error in errors:
        if error.module == "__main__":  # Custom errors are in this module
            custom_errors.append(error)
        else:
            base_errors.append(error)

    print(f"Custom Errors ({len(custom_errors)}):")
    print("-" * 40)
    for error in custom_errors:
        print(f"  ✓ {error.name}")
        if error.description:
            print(f"    {error.description.strip()}")
        if error.error_code:
            print(f"    Code: {error.error_code.name} ({error.error_code.value})")
        print()

    print(f"\nBase/Inherited Errors ({len(base_errors)}):")
    print("-" * 40)
    for error in base_errors:
        print(f"  • {error.name}")

    # Check if our custom errors were found
    custom_error_names = [e.name for e in custom_errors]

    print("\n" + "=" * 60)
    print("VERIFICATION:")
    print("-" * 40)

    expected_custom = ["DataValidationError", "RateLimitError", "APIKeyError"]
    found_custom = [name for name in expected_custom if name in custom_error_names]
    missing_custom = [name for name in expected_custom if name not in custom_error_names]

    if found_custom:
        print(f"✅ Found custom errors: {', '.join(found_custom)}")

    if missing_custom:
        print(f"❌ Missing custom errors: {', '.join(missing_custom)}")

    if len(found_custom) == len(expected_custom):
        print("\n✅ SUCCESS: All custom errors were discovered!")
    else:
        print(f"\n⚠️  PARTIAL: Found {len(found_custom)}/{len(expected_custom)} custom errors")

    print("=" * 60)


if __name__ == "__main__":
    main()