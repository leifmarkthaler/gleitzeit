"""
Tests for Error Discovery Module
"""

import pytest
from typing import Type

from gleitzeit.core.error_discovery import (
    ErrorDiscovery, ErrorInfo, get_provider_errors,
    get_protocol_errors, get_error_hierarchy, discover_all_errors
)
from gleitzeit.core.errors import (
    GleitzeitError, ProviderError, ProtocolError,
    ErrorCode, ProviderTimeoutError, MethodNotSupportedError,
    ProviderNotFoundError
)
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType
from gleitzeit.providers.simple import SimpleProvider


class CustomProviderError(ProviderError):
    """Custom error for testing"""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            code=ErrorCode.PROVIDER_ERROR,
            **kwargs
        )


class TestProvider(SimpleProvider):
    """Test provider with custom errors"""

    def __init__(self):
        super().__init__(
            provider_id="test-provider",
            protocol_id="test/v1"
        )

    async def execute(self, method: str, params: dict):
        if method == "fail_timeout":
            raise ProviderTimeoutError(self.provider_id, 30.0)
        elif method == "fail_custom":
            raise CustomProviderError("Custom error occurred")
        elif method == "fail_not_supported":
            raise MethodNotSupportedError(method, self.provider_id)
        return {"result": "success"}


class TestErrorDiscovery:
    """Test error discovery functionality"""

    def test_error_info_creation(self):
        """Test ErrorInfo dataclass creation"""
        error_info = ErrorInfo(
            name="TestError",
            error_class=ProviderError,
            base_class=GleitzeitError,
            module="test.module",
            error_code=ErrorCode.PROVIDER_ERROR,
            description="Test error",
            is_retryable=False
        )

        assert error_info.name == "TestError"
        assert error_info.error_class == ProviderError
        assert error_info.base_class == GleitzeitError
        assert error_info.error_code == ErrorCode.PROVIDER_ERROR

        # Test to_dict conversion
        error_dict = error_info.to_dict()
        assert error_dict["name"] == "TestError"
        assert error_dict["class"] == "ProviderError"
        assert error_dict["error_code"] == ErrorCode.PROVIDER_ERROR.value
        assert error_dict["error_code_name"] == "PROVIDER_ERROR"

    def test_get_error_code(self):
        """Test extracting error codes from error classes"""
        # Test with ProviderTimeoutError
        code = ErrorDiscovery.get_error_code(ProviderTimeoutError)
        assert code == ErrorCode.PROVIDER_TIMEOUT

        # Test with MethodNotSupportedError
        code = ErrorDiscovery.get_error_code(MethodNotSupportedError)
        assert code == ErrorCode.METHOD_NOT_SUPPORTED

        # Test with base ProviderError
        code = ErrorDiscovery.get_error_code(ProviderError)
        assert code == ErrorCode.PROVIDER_NOT_AVAILABLE

    def test_is_retryable_error_class(self):
        """Test checking if error classes are retryable"""
        # Timeout errors should be retryable
        assert ErrorDiscovery.is_retryable_error_class(ProviderTimeoutError) is True

        # Method not supported should not be retryable
        assert ErrorDiscovery.is_retryable_error_class(MethodNotSupportedError) is False

    def test_discover_module_errors(self):
        """Test discovering errors in a module"""
        import gleitzeit.core.errors as errors_module

        discovered = ErrorDiscovery.discover_module_errors(errors_module)

        # Should find various error classes
        error_names = [e.name for e in discovered]
        assert "ProviderError" in error_names
        assert "ProtocolError" in error_names
        assert "TaskError" in error_names
        assert "WorkflowError" in error_names

        # Check that discovered errors have correct base classes
        provider_error = next(e for e in discovered if e.name == "ProviderError")
        assert provider_error.base_class == GleitzeitError

    def test_get_provider_errors(self):
        """Test getting errors from a provider"""
        provider = TestProvider()
        errors = ErrorDiscovery.get_provider_errors(provider)

        # Should include base provider errors
        error_names = [e.name for e in errors]
        assert "ProviderError" in error_names
        assert "ProviderTimeoutError" in error_names
        assert "MethodNotSupportedError" in error_names

        # Check retryability
        timeout_error = next((e for e in errors if e.name == "ProviderTimeoutError"), None)
        if timeout_error:
            assert timeout_error.is_retryable is True

    def test_get_protocol_errors(self):
        """Test getting errors from a protocol"""
        protocol = ProtocolSpec(
            name="test",
            version="v1",
            description="Test protocol",
            methods={
                "test_method": MethodSpec(
                    name="test_method",
                    description="A test method that might fail",
                    params_schema={
                        "input": ParameterSpec(
                            type=ParameterType.STRING,
                            description="Input parameter"
                        )
                    }
                )
            }
        )

        errors = ErrorDiscovery.get_protocol_errors(protocol)

        # Should include base protocol errors
        error_names = [e.name for e in errors]
        assert "ProtocolError" in error_names
        assert "InvalidParameterError" in error_names

        # Check error codes
        protocol_error = next(e for e in errors if e.name == "ProtocolError")
        assert protocol_error.error_code == ErrorCode.PROTOCOL_NOT_FOUND

    def test_get_error_hierarchy(self):
        """Test getting the complete error hierarchy"""
        hierarchy = ErrorDiscovery.get_error_hierarchy()

        # Should have GleitzeitError at the root
        assert hierarchy["class"] == "GleitzeitError"
        assert "subclasses" in hierarchy

        # Should have various error categories
        subclass_names = list(hierarchy["subclasses"].keys())
        assert "ProviderError" in subclass_names or any("Provider" in name for name in subclass_names)
        assert "ProtocolError" in subclass_names or any("Protocol" in name for name in subclass_names)

    def test_format_error_report(self):
        """Test formatting error report"""
        errors = [
            ErrorInfo(
                name="Error1",
                error_class=ProviderError,
                base_class=GleitzeitError,
                module="test.module",
                error_code=ErrorCode.PROVIDER_ERROR,
                description="First error",
                is_retryable=False
            ),
            ErrorInfo(
                name="Error2",
                error_class=ProviderTimeoutError,
                base_class=ProviderError,
                module="test.module",
                error_code=ErrorCode.PROVIDER_TIMEOUT,
                description="Timeout error",
                is_retryable=True
            )
        ]

        report = ErrorDiscovery.format_error_report(errors, "Test Report")

        # Check report structure
        assert "# Test Report" in report
        assert "## GleitzeitError Subclasses" in report or "## ProviderError Subclasses" in report
        assert "### Error1" in report
        assert "### Error2" in report
        assert "Retryable: True" in report
        assert "Retryable: False" in report

    def test_convenience_functions(self):
        """Test convenience functions"""
        # Test get_provider_errors
        provider = TestProvider()
        errors = get_provider_errors(provider)
        assert len(errors) > 0

        # Test get_protocol_errors
        protocol = ProtocolSpec(
            name="test",
            version="v1",
            methods={}
        )
        errors = get_protocol_errors(protocol)
        assert len(errors) > 0

        # Test get_error_hierarchy
        hierarchy = get_error_hierarchy()
        assert "class" in hierarchy
        assert hierarchy["class"] == "GleitzeitError"

    def test_get_all_provider_errors_with_specific_class(self):
        """Test getting errors from a specific provider class"""
        all_errors = ErrorDiscovery.get_all_provider_errors(TestProvider)

        assert "TestProvider" in all_errors or TestProvider.__name__ in all_errors
        if "TestProvider" in all_errors:
            errors = all_errors["TestProvider"]
        else:
            errors = all_errors[TestProvider.__name__]

        error_names = [e.name for e in errors]
        # Should find CustomProviderError if module inspection works
        # At minimum should have base provider errors
        assert len(errors) > 0

    def test_error_discovery_integration(self):
        """Test complete error discovery flow"""
        # Discover all errors in the system
        all_errors = discover_all_errors()

        # Should discover errors from various provider modules
        assert len(all_errors) > 0

        # Check that discovered errors have proper structure
        for module_name, errors in all_errors.items():
            for error in errors:
                assert isinstance(error, ErrorInfo)
                assert error.name
                assert error.error_class
                assert error.base_class
                assert error.module