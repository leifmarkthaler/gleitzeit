"""
Error Discovery Module for Gleitzeit V4

Provides functionality to discover and retrieve custom errors
from protocols and providers at runtime.
"""

import inspect
from typing import Dict, List, Type, Optional, Any, Set
from dataclasses import dataclass
import importlib
import pkgutil

from gleitzeit.core.errors import (
    GleitzeitError, ProviderError, ProtocolError,
    ErrorCode, TaskError, WorkflowError
)
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec
from gleitzeit.providers.base import ProtocolProvider


@dataclass
class ErrorInfo:
    """Information about a discovered error class"""
    name: str
    error_class: Type[Exception]
    base_class: Type[Exception]
    module: str
    error_code: Optional[ErrorCode] = None
    description: Optional[str] = None
    is_retryable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "name": self.name,
            "class": self.error_class.__name__,
            "base_class": self.base_class.__name__,
            "module": self.module,
            "error_code": self.error_code.value if self.error_code else None,
            "error_code_name": self.error_code.name if self.error_code else None,
            "description": self.description or self.error_class.__doc__,
            "is_retryable": self.is_retryable
        }


class ErrorDiscovery:
    """Discovers and catalogs errors from protocols and providers"""

    @staticmethod
    def get_error_code(error_class: Type[Exception]) -> Optional[ErrorCode]:
        """
        Extract the default error code from an error class.

        Args:
            error_class: The error class to inspect

        Returns:
            ErrorCode if found, None otherwise
        """
        # Check if it's a GleitzeitError subclass with __init__
        if issubclass(error_class, GleitzeitError):
            try:
                # Inspect the __init__ signature for default error code
                sig = inspect.signature(error_class.__init__)
                for param_name, param in sig.parameters.items():
                    if param_name == 'code' and param.default != inspect.Parameter.empty:
                        if isinstance(param.default, ErrorCode):
                            return param.default
            except Exception:
                pass
        return None

    @staticmethod
    def is_retryable_error_class(error_class: Type[Exception]) -> bool:
        """
        Check if an error class represents retryable errors.

        Args:
            error_class: The error class to check

        Returns:
            True if errors of this type are retryable
        """
        from gleitzeit.core.errors import is_retryable_error

        # Create a dummy instance to check retryability
        try:
            if issubclass(error_class, GleitzeitError):
                # Try to create instance with minimal args
                if error_class.__name__ in ['ProviderTimeoutError', 'TaskTimeoutError',
                                           'ConnectionTimeoutError', 'ResourceExhaustedError']:
                    return True
        except Exception:
            pass

        return False

    @classmethod
    def discover_module_errors(cls, module) -> List[ErrorInfo]:
        """
        Discover all error classes in a module.

        Args:
            module: The module to inspect

        Returns:
            List of ErrorInfo objects for discovered errors
        """
        errors = []

        for name, obj in inspect.getmembers(module):
            # Check if it's a class and an Exception subclass
            if (inspect.isclass(obj) and
                issubclass(obj, Exception) and
                obj != Exception and
                obj.__module__ == module.__name__):

                # Find the immediate base class
                base_class = obj.__bases__[0] if obj.__bases__ else Exception

                error_info = ErrorInfo(
                    name=name,
                    error_class=obj,
                    base_class=base_class,
                    module=module.__name__,
                    error_code=cls.get_error_code(obj),
                    description=obj.__doc__,
                    is_retryable=cls.is_retryable_error_class(obj)
                )
                errors.append(error_info)

        return errors

    @classmethod
    def get_provider_errors(cls, provider: ProtocolProvider) -> List[ErrorInfo]:
        """
        Get all custom errors that a provider might raise.

        Args:
            provider: The provider instance to inspect

        Returns:
            List of ErrorInfo objects for provider errors
        """
        errors = []
        seen_classes = set()

        # Get the provider's module
        provider_module = inspect.getmodule(provider.__class__)
        if provider_module:
            module_errors = cls.discover_module_errors(provider_module)
            for error_info in module_errors:
                if error_info.error_class not in seen_classes:
                    errors.append(error_info)
                    seen_classes.add(error_info.error_class)

        # Inspect provider methods for raised errors
        for method_name in dir(provider):
            if not method_name.startswith('_'):
                try:
                    method = getattr(provider, method_name)
                    if callable(method):
                        source = inspect.getsource(method)

                        # Look for raise statements
                        import ast
                        tree = ast.parse(source)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Raise):
                                # Try to identify the exception class
                                if isinstance(node.exc, ast.Call):
                                    if isinstance(node.exc.func, ast.Name):
                                        error_name = node.exc.func.id
                                        # Try to resolve the error class
                                        try:
                                            error_class = getattr(provider_module, error_name, None)
                                            if error_class and inspect.isclass(error_class) and issubclass(error_class, Exception):
                                                if error_class not in seen_classes:
                                                    base_class = error_class.__bases__[0] if error_class.__bases__ else Exception
                                                    error_info = ErrorInfo(
                                                        name=error_name,
                                                        error_class=error_class,
                                                        base_class=base_class,
                                                        module=provider_module.__name__ if provider_module else "unknown",
                                                        error_code=cls.get_error_code(error_class),
                                                        description=error_class.__doc__,
                                                        is_retryable=cls.is_retryable_error_class(error_class)
                                                    )
                                                    errors.append(error_info)
                                                    seen_classes.add(error_class)
                                        except Exception:
                                            pass
                except Exception:
                    continue

        # Always include base provider errors
        base_errors = [
            ErrorInfo(
                name="ProviderError",
                error_class=ProviderError,
                base_class=GleitzeitError,
                module="gleitzeit.core.errors",
                error_code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                description="Base provider error",
                is_retryable=False
            ),
            ErrorInfo(
                name="ProviderTimeoutError",
                error_class=type("ProviderTimeoutError", (ProviderError,), {}),
                base_class=ProviderError,
                module="gleitzeit.core.errors",
                error_code=ErrorCode.PROVIDER_TIMEOUT,
                description="Provider operation timed out",
                is_retryable=True
            ),
            ErrorInfo(
                name="MethodNotSupportedError",
                error_class=type("MethodNotSupportedError", (ProviderError,), {}),
                base_class=ProviderError,
                module="gleitzeit.core.errors",
                error_code=ErrorCode.METHOD_NOT_SUPPORTED,
                description="Method not supported by provider",
                is_retryable=False
            )
        ]

        for error_info in base_errors:
            if error_info.name not in [e.name for e in errors]:
                errors.append(error_info)

        return errors

    @classmethod
    def get_protocol_errors(cls, protocol: ProtocolSpec) -> List[ErrorInfo]:
        """
        Get all errors that might be raised by a protocol.

        Args:
            protocol: The protocol specification to inspect

        Returns:
            List of ErrorInfo objects for protocol errors
        """
        errors = []

        # Base protocol errors
        base_errors = [
            ErrorInfo(
                name="ProtocolError",
                error_class=ProtocolError,
                base_class=GleitzeitError,
                module="gleitzeit.core.errors",
                error_code=ErrorCode.PROTOCOL_NOT_FOUND,
                description="Base protocol error",
                is_retryable=False
            ),
            ErrorInfo(
                name="InvalidParameterError",
                error_class=type("InvalidParameterError", (TaskError,), {}),
                base_class=TaskError,
                module="gleitzeit.core.errors",
                error_code=ErrorCode.INVALID_PARAMS,
                description="Invalid parameter provided",
                is_retryable=False
            )
        ]

        errors.extend(base_errors)

        # Check method specifications for documented errors
        for method_name, method_spec in protocol.methods.items():
            if method_spec.description:
                # Look for error documentation in method description
                # This is a simple heuristic - could be enhanced
                if "error" in method_spec.description.lower() or "fail" in method_spec.description.lower():
                    # Add a note about potential method-specific errors
                    pass

        return errors

    @classmethod
    def get_all_provider_errors(cls, provider_class: Optional[Type[ProtocolProvider]] = None) -> Dict[str, List[ErrorInfo]]:
        """
        Get all errors from all registered providers or a specific provider class.

        Args:
            provider_class: Optional specific provider class to inspect

        Returns:
            Dictionary mapping provider names to their error lists
        """
        all_errors = {}

        if provider_class:
            # Get errors for specific provider class
            try:
                # Create a minimal instance for inspection
                provider = provider_class(
                    provider_id="temp",
                    protocol_id="temp",
                    validate_on_init=False
                )
                errors = cls.get_provider_errors(provider)
                all_errors[provider_class.__name__] = errors
            except Exception as e:
                # If we can't instantiate, try to get module errors
                module = inspect.getmodule(provider_class)
                if module:
                    errors = cls.discover_module_errors(module)
                    all_errors[provider_class.__name__] = errors
        else:
            # Discover all provider modules
            import gleitzeit.providers
            provider_modules = []

            for importer, modname, ispkg in pkgutil.iter_modules(gleitzeit.providers.__path__):
                if not ispkg:
                    try:
                        module = importlib.import_module(f"gleitzeit.providers.{modname}")
                        provider_modules.append(module)
                    except Exception:
                        continue

            # Get errors from each module
            for module in provider_modules:
                module_errors = cls.discover_module_errors(module)
                if module_errors:
                    all_errors[module.__name__] = module_errors

        return all_errors

    @classmethod
    def get_error_hierarchy(cls) -> Dict[str, Any]:
        """
        Get the complete error hierarchy from the error system.

        Returns:
            Dictionary representing the error hierarchy
        """
        from gleitzeit.core import errors

        hierarchy = {}

        def build_hierarchy(base_class: Type[Exception], visited: Set[Type] = None) -> Dict[str, Any]:
            if visited is None:
                visited = set()

            if base_class in visited:
                return {}

            visited.add(base_class)

            result = {
                "class": base_class.__name__,
                "module": base_class.__module__,
                "description": base_class.__doc__,
                "subclasses": {}
            }

            # Get error code if available
            error_code = cls.get_error_code(base_class)
            if error_code:
                result["error_code"] = error_code.value
                result["error_code_name"] = error_code.name

            # Find all subclasses in the errors module
            for name, obj in inspect.getmembers(errors):
                if (inspect.isclass(obj) and
                    issubclass(obj, base_class) and
                    obj != base_class and
                    obj.__module__ == errors.__name__):

                    result["subclasses"][name] = build_hierarchy(obj, visited)

            return result

        # Start from GleitzeitError base
        hierarchy = build_hierarchy(GleitzeitError)

        return hierarchy

    @classmethod
    def format_error_report(cls, errors: List[ErrorInfo], title: str = "Error Report") -> str:
        """
        Format a list of errors into a readable report.

        Args:
            errors: List of ErrorInfo objects
            title: Report title

        Returns:
            Formatted string report
        """
        lines = [f"# {title}", ""]

        # Group errors by base class
        by_base = {}
        for error in errors:
            base_name = error.base_class.__name__
            if base_name not in by_base:
                by_base[base_name] = []
            by_base[base_name].append(error)

        for base_name, base_errors in by_base.items():
            lines.append(f"## {base_name} Subclasses")
            lines.append("")

            for error in base_errors:
                lines.append(f"### {error.name}")
                if error.description:
                    lines.append(f"*{error.description.strip()}*")
                lines.append(f"- Module: `{error.module}`")
                if error.error_code:
                    lines.append(f"- Error Code: `{error.error_code.name}` ({error.error_code.value})")
                lines.append(f"- Retryable: {error.is_retryable}")
                lines.append("")

        return "\n".join(lines)


# Convenience functions
def get_provider_errors(provider: ProtocolProvider) -> List[ErrorInfo]:
    """Get all errors for a provider instance"""
    return ErrorDiscovery.get_provider_errors(provider)


def get_protocol_errors(protocol: ProtocolSpec) -> List[ErrorInfo]:
    """Get all errors for a protocol specification"""
    return ErrorDiscovery.get_protocol_errors(protocol)


def get_error_hierarchy() -> Dict[str, Any]:
    """Get the complete error hierarchy"""
    return ErrorDiscovery.get_error_hierarchy()


def discover_all_errors() -> Dict[str, List[ErrorInfo]]:
    """Discover all errors in the system"""
    return ErrorDiscovery.get_all_provider_errors()