"""
Extension Manager Exceptions

Custom exception classes for extension management operations.
"""

class ExtensionError(Exception):
    """Base exception for extension-related errors"""
    pass

class ExtensionNotFound(ExtensionError):
    """Raised when an extension cannot be found"""
    def __init__(self, extension_name: str):
        self.extension_name = extension_name
        super().__init__(f"Extension '{extension_name}' not found")

class ExtensionConfigError(ExtensionError):
    """Raised when extension configuration is invalid"""
    def __init__(self, extension_name: str, message: str):
        self.extension_name = extension_name
        super().__init__(f"Extension '{extension_name}' configuration error: {message}")

class ExtensionLoadError(ExtensionError):
    """Raised when extension fails to load"""
    def __init__(self, extension_name: str, reason: str):
        self.extension_name = extension_name
        super().__init__(f"Failed to load extension '{extension_name}': {reason}")

class ExtensionDependencyError(ExtensionError):
    """Raised when extension dependencies are not satisfied"""
    def __init__(self, extension_name: str, missing_deps: list):
        self.extension_name = extension_name
        self.missing_deps = missing_deps
        deps_str = ', '.join(missing_deps)
        super().__init__(f"Extension '{extension_name}' missing dependencies: {deps_str}")

class ExtensionValidationError(ExtensionError):
    """Raised when extension validation fails"""
    def __init__(self, extension_name: str, validation_errors: list):
        self.extension_name = extension_name
        self.validation_errors = validation_errors
        errors_str = '; '.join(validation_errors)
        super().__init__(f"Extension '{extension_name}' validation failed: {errors_str}")

class ExtensionServiceError(ExtensionError):
    """Raised when extension service operations fail"""
    def __init__(self, extension_name: str, service_error: str):
        self.extension_name = extension_name
        super().__init__(f"Extension '{extension_name}' service error: {service_error}")