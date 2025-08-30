"""
Provider Factory with Validation and Debugging

Bulletproof provider creation with comprehensive validation,
error reporting, and debugging capabilities.
"""

import inspect
import asyncio
from typing import Dict, Any, Optional, Type, List, Callable, Set
from abc import ABC
import traceback
import logging

from .base import ProtocolProvider
from .simple import SimpleProvider
from .http_provider import HTTPProvider
from .ultra_simple import UltraSimpleProvider, UltraHTTPProvider
from gleitzeit.core.errors import GleitzeitError, ErrorCode


class ProviderFactoryError(GleitzeitError):
    """Base class for provider factory errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INVALID_PARAMS,
        provider_class: Optional[str] = None,
        validation_errors: Optional[List[str]] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if provider_class:
            data["provider_class"] = provider_class
        if validation_errors:
            data["validation_errors"] = validation_errors
        super().__init__(message, code, data=data, **kwargs)


class ProviderValidationError(ProviderFactoryError):
    """Provider failed validation checks"""
    pass


class ProviderInitializationError(ProviderFactoryError):
    """Provider failed to initialize properly"""
    pass


class ProviderMethodError(ProviderFactoryError):
    """Provider method implementation error"""
    pass


class ProviderCompatibilityError(ProviderFactoryError):
    """Provider not compatible with Gleitzeit system"""
    pass


class ProviderValidator:
    """
    Validates provider implementations for correctness and compatibility.
    
    Performs comprehensive checks to ensure providers will work correctly
    in the Gleitzeit system before they're deployed.
    """
    
    def __init__(self, strict_mode: bool = True):
        """
        Args:
            strict_mode: If True, enforce all best practices. If False, only check critical issues.
        """
        self.strict_mode = strict_mode
        self.logger = logging.getLogger(__name__)
    
    def validate_provider_class(self, provider_class: Type[ProtocolProvider]) -> List[str]:
        """
        Validate a provider class before instantiation.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check inheritance
        if not issubclass(provider_class, ProtocolProvider):
            errors.append(f"{provider_class.__name__} must inherit from ProtocolProvider or its subclasses")
        
        # Check required methods based on inheritance
        if issubclass(provider_class, UltraSimpleProvider) or issubclass(provider_class, UltraHTTPProvider):
            # Ultra-simple providers need decorated methods or execute override
            if not self._has_decorated_methods(provider_class) and not self._overrides_execute(provider_class):
                errors.append("Ultra-simple providers must have @method decorated methods or override execute()")
        
        elif issubclass(provider_class, SimpleProvider) or issubclass(provider_class, HTTPProvider):
            # Simple providers must implement execute
            if not self._overrides_execute(provider_class):
                errors.append("SimpleProvider/HTTPProvider must implement execute() method")
        
        else:
            # Direct ProtocolProvider subclasses need these methods
            required_methods = ['execute', 'initialize', 'shutdown', 'health_check']
            for method in required_methods:
                if not self._implements_method(provider_class, method):
                    errors.append(f"ProtocolProvider subclass must implement {method}() method")
        
        # Check method signatures
        signature_errors = self._validate_method_signatures(provider_class)
        errors.extend(signature_errors)
        
        # Check for common mistakes
        if self.strict_mode:
            errors.extend(self._check_common_mistakes(provider_class))
        
        return errors
    
    def validate_provider_instance(self, provider: ProtocolProvider) -> List[str]:
        """
        Validate a provider instance after creation.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check required attributes
        required_attrs = ['provider_id', 'protocol_id']
        for attr in required_attrs:
            if not hasattr(provider, attr) or not getattr(provider, attr):
                errors.append(f"Provider missing required attribute: {attr}")
        
        # Check provider_id format
        if hasattr(provider, 'provider_id'):
            provider_id = provider.provider_id
            if not provider_id or not isinstance(provider_id, str):
                errors.append("provider_id must be a non-empty string")
            elif ' ' in provider_id:
                errors.append("provider_id cannot contain spaces")
            elif not provider_id.replace('_', '').replace('-', '').replace('.', '').isalnum():
                errors.append("provider_id should only contain alphanumeric characters, underscores, hyphens, and dots")
        
        # Check protocol_id format
        if hasattr(provider, 'protocol_id'):
            protocol_id = provider.protocol_id
            if not protocol_id or not isinstance(protocol_id, str):
                errors.append("protocol_id must be a non-empty string")
            elif '/' not in protocol_id and self.strict_mode:
                errors.append("protocol_id should follow format: namespace/version (e.g., 'llm/v1')")
        
        # Check method implementations (only in strict mode, this is optional)
        if self.strict_mode and hasattr(provider, 'get_supported_methods'):
            methods = provider.get_supported_methods()
            if not methods:
                # This is a recommendation, not an error
                pass  # Don't add as error, just a best practice
        
        # Validate enterprise features are available
        enterprise_attrs = ['max_retries', 'logger', 'handle_request']
        for attr in enterprise_attrs:
            if not hasattr(provider, attr):
                errors.append(f"Provider missing enterprise feature: {attr}")
        
        return errors
    
    async def validate_provider_runtime(
        self, 
        provider: ProtocolProvider,
        test_methods: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List[str]:
        """
        Validate provider at runtime by testing actual method execution.
        
        Args:
            provider: Provider instance to test
            test_methods: Dict of method names to test parameters
            
        Returns:
            List of runtime errors
        """
        errors = []
        
        # Test initialization
        try:
            await provider.initialize()
        except Exception as e:
            errors.append(f"Failed to initialize: {e}")
            return errors  # Can't continue without initialization
        
        # Test health check
        try:
            health = await provider.health_check()
            if not isinstance(health, bool):
                errors.append(f"health_check() must return bool, got {type(health)}")
        except Exception as e:
            errors.append(f"health_check() failed: {e}")
        
        # Test supported methods
        if test_methods:
            for method, params in test_methods.items():
                try:
                    result = await provider.execute(method, params)
                    if result is None:
                        errors.append(f"Method {method} returned None")
                    elif not isinstance(result, (dict, list, str, int, float, bool)):
                        errors.append(f"Method {method} returned non-JSON-serializable type: {type(result)}")
                except Exception as e:
                    errors.append(f"Method {method} failed: {e}")
        
        # Test shutdown
        try:
            await provider.shutdown()
        except Exception as e:
            errors.append(f"Failed to shutdown: {e}")
        
        return errors
    
    def _has_decorated_methods(self, provider_class: Type) -> bool:
        """Check if class has @method decorated methods"""
        for name, method in inspect.getmembers(provider_class, inspect.isfunction):
            if hasattr(method, '_method_names'):
                return True
        return False
    
    def _overrides_execute(self, provider_class: Type) -> bool:
        """Check if class overrides execute method"""
        # Check if execute is defined in this class (not inherited)
        if 'execute' in provider_class.__dict__:
            return True
        return False
    
    def _implements_method(self, provider_class: Type, method_name: str) -> bool:
        """Check if class implements a specific method"""
        if not hasattr(provider_class, method_name):
            return False
        
        method = getattr(provider_class, method_name)
        if not callable(method):
            return False
        
        # Check if it's not abstract
        if hasattr(method, '__isabstractmethod__') and method.__isabstractmethod__:
            return False
        
        return True
    
    def _validate_method_signatures(self, provider_class: Type) -> List[str]:
        """Validate method signatures match expected patterns"""
        errors = []
        
        # Check execute signature if present
        if hasattr(provider_class, 'execute'):
            method = getattr(provider_class, 'execute')
            if callable(method):
                sig = inspect.signature(method)
                params = list(sig.parameters.keys())
                
                # Should have self, method, params (or **kwargs for compatibility)
                if len(params) < 3:
                    if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                        errors.append("execute() should accept (self, method, params) or (self, method, **kwargs)")
        
        return errors
    
    def _check_common_mistakes(self, provider_class: Type) -> List[str]:
        """Check for common implementation mistakes"""
        errors = []
        
        # Check for synchronous execute method (should be async)
        if hasattr(provider_class, 'execute'):
            method = getattr(provider_class, 'execute')
            if callable(method) and not inspect.iscoroutinefunction(method):
                errors.append("execute() must be async (use 'async def')")
        
        # Check for missing async on other key methods
        for method_name in ['initialize', 'shutdown', 'health_check', 'handle_request']:
            if hasattr(provider_class, method_name):
                method = getattr(provider_class, method_name)
                if callable(method) and not inspect.iscoroutinefunction(method):
                    errors.append(f"{method_name}() must be async (use 'async def')")
        
        return errors


class ProviderFactory:
    """
    Bulletproof provider factory with validation and debugging.
    
    Ensures providers are correctly implemented and compatible
    before they're used in the Gleitzeit system.
    Now includes automatic protocol generation and registration.
    """
    
    def __init__(
        self,
        strict_validation: bool = True,
        auto_fix: bool = False,
        debug_mode: bool = False,
        auto_generate_protocols: bool = False,
        auto_register_protocols: bool = False,
        protocol_registry: Optional[Any] = None
    ):
        """
        Args:
            strict_validation: Enforce all best practices
            auto_fix: Attempt to fix common issues automatically
            debug_mode: Enable detailed debugging output
            auto_generate_protocols: Auto-generate protocols from provider implementation
            auto_register_protocols: Auto-register generated protocols
            protocol_registry: Registry to register protocols with
        """
        self.strict_validation = strict_validation
        self.auto_fix = auto_fix
        self.debug_mode = debug_mode
        self.auto_generate_protocols = auto_generate_protocols
        self.auto_register_protocols = auto_register_protocols
        self.protocol_registry = protocol_registry
        self.validator = ProviderValidator(strict_mode=strict_validation)
        self.logger = logging.getLogger(__name__)
        
        # Registry of validated providers and generated protocols
        self._validated_providers: Set[str] = set()
        self.generated_protocols: Dict[str, Any] = {}
    
    def create_provider(
        self,
        provider_class: Type[ProtocolProvider],
        *args,
        validate: bool = True,
        test_methods: Optional[Dict[str, Dict[str, Any]]] = None,
        generate_protocol: Optional[bool] = None,
        register_protocol: Optional[bool] = None,
        **kwargs
    ) -> ProtocolProvider:
        """
        Create a provider instance with validation.
        
        Args:
            provider_class: Provider class to instantiate
            *args: Positional arguments for provider
            validate: Whether to perform validation
            test_methods: Methods to test during runtime validation
            **kwargs: Keyword arguments for provider
            
        Returns:
            Validated provider instance
            
        Raises:
            ProviderValidationError: If validation fails
            ProviderInitializationError: If initialization fails
        """
        class_name = provider_class.__name__
        
        if self.debug_mode:
            self.logger.info(f"Creating provider: {class_name}")
        
        # Step 1: Validate class
        if validate:
            class_errors = self.validator.validate_provider_class(provider_class)
            if class_errors:
                if self.auto_fix:
                    provider_class = self._attempt_auto_fix(provider_class, class_errors)
                    # Re-validate after fixes
                    class_errors = self.validator.validate_provider_class(provider_class)
                
                if class_errors:
                    raise ProviderValidationError(
                        f"Provider class {class_name} failed validation",
                        provider_class=class_name,
                        validation_errors=class_errors
                    )
        
        # Step 2: Configure protocol generation
        # Use factory defaults if not specified
        if generate_protocol is None:
            generate_protocol = self.auto_generate_protocols
        if register_protocol is None:
            register_protocol = self.auto_register_protocols
        
        # Add protocol generation settings to kwargs
        if generate_protocol:
            kwargs['auto_generate_protocol'] = True
            kwargs['register_protocol'] = register_protocol
            if register_protocol and self.protocol_registry:
                kwargs['protocol_registry'] = self.protocol_registry
        
        # Step 3: Create instance
        # Disable automatic validation in base class if we're handling it here
        if validate and 'validate_on_init' not in kwargs:
            kwargs['validate_on_init'] = False
        
        try:
            provider = provider_class(*args, **kwargs)
        except Exception as e:
            raise ProviderInitializationError(
                f"Failed to create {class_name} instance: {e}",
                provider_class=class_name,
                cause=e
            )
        
        # Step 3: Validate instance
        if validate:
            instance_errors = self.validator.validate_provider_instance(provider)
            if instance_errors:
                raise ProviderValidationError(
                    f"Provider instance {class_name} failed validation",
                    provider_class=class_name,
                    validation_errors=instance_errors
                )
        
        # Step 4: Runtime validation (if test methods provided)
        if validate and test_methods:
            async def run_validation():
                return await self.validator.validate_provider_runtime(provider, test_methods)
            
            try:
                runtime_errors = asyncio.run(run_validation())
                if runtime_errors:
                    raise ProviderValidationError(
                        f"Provider {class_name} failed runtime validation",
                        provider_class=class_name,
                        validation_errors=runtime_errors
                    )
            except Exception as e:
                if isinstance(e, ProviderValidationError):
                    raise
                raise ProviderInitializationError(
                    f"Runtime validation failed for {class_name}: {e}",
                    provider_class=class_name,
                    cause=e
                )
        
        # Step 5: Store generated protocol if available
        if hasattr(provider, 'get_generated_protocol'):
            protocol = provider.get_generated_protocol()
            if protocol:
                self.generated_protocols[provider.provider_id] = protocol
                if self.debug_mode:
                    self.logger.info(f"Generated protocol: {protocol.protocol_id}")
        
        # Mark as validated
        provider_key = f"{provider.provider_id}:{provider.protocol_id}"
        self._validated_providers.add(provider_key)
        
        if self.debug_mode:
            self.logger.info(f"Successfully created and validated provider: {provider_key}")
        
        return provider
    
    def validate_existing_provider(
        self,
        provider: ProtocolProvider,
        test_methods: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List[str]:
        """
        Validate an existing provider instance.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Class validation
        class_errors = self.validator.validate_provider_class(type(provider))
        errors.extend(class_errors)
        
        # Instance validation
        instance_errors = self.validator.validate_provider_instance(provider)
        errors.extend(instance_errors)
        
        # Runtime validation
        if test_methods:
            async def run_validation():
                return await self.validator.validate_provider_runtime(provider, test_methods)
            
            runtime_errors = asyncio.run(run_validation())
            errors.extend(runtime_errors)
        
        return errors
    
    def create_provider_from_config(
        self,
        config: Dict[str, Any],
        validate: bool = True
    ) -> ProtocolProvider:
        """
        Create a provider from configuration dictionary.
        
        Config format:
        {
            "type": "http" | "simple" | "ultra",
            "provider_id": "my_provider",
            "protocol_id": "my_protocol/v1",
            "base_url": "https://api.example.com",  # for HTTP providers
            "methods": {
                "method_name": {
                    "handler": "function_name" | callable,
                    "params": ["param1", "param2"]
                }
            }
        }
        """
        provider_type = config.get("type", "simple")
        provider_id = config.get("provider_id")
        protocol_id = config.get("protocol_id")
        
        if not provider_id or not protocol_id:
            raise ProviderValidationError(
                "Config must include provider_id and protocol_id",
                validation_errors=["Missing provider_id or protocol_id"]
            )
        
        # Create provider class dynamically
        if provider_type == "ultra":
            base_class = UltraHTTPProvider if "base_url" in config else UltraSimpleProvider
        elif provider_type == "http":
            base_class = HTTPProvider
        else:
            base_class = SimpleProvider
        
        # Build provider class
        class ConfiguredProvider(base_class):
            pass
        
        # Add configuration
        if "base_url" in config:
            ConfiguredProvider.base_url = config["base_url"]
        
        # Add methods
        if "methods" in config:
            for method_name, method_config in config["methods"].items():
                self._add_method_to_class(ConfiguredProvider, method_name, method_config)
        
        # Create instance
        return self.create_provider(
            ConfiguredProvider,
            provider_id=provider_id,
            protocol_id=protocol_id,
            validate=validate,
            **config.get("kwargs", {})
        )
    
    def _add_method_to_class(
        self,
        provider_class: Type,
        method_name: str,
        method_config: Dict[str, Any]
    ):
        """Add a method to a provider class from configuration"""
        handler = method_config.get("handler")
        
        if callable(handler):
            # Direct callable
            setattr(provider_class, method_name, handler)
        elif isinstance(handler, str):
            # Method name to generate
            async def configured_method(self, **params):
                # Simple echo implementation for testing
                return {"method": method_name, "params": params}
            
            setattr(provider_class, method_name, configured_method)
    
    def _attempt_auto_fix(
        self,
        provider_class: Type,
        errors: List[str]
    ) -> Type:
        """
        Attempt to automatically fix common provider issues.
        
        Returns:
            Fixed provider class (or original if can't fix)
        """
        if not self.auto_fix:
            return provider_class
        
        # Check if this is a direct ProtocolProvider subclass (abstract)
        # These can't be auto-fixed as they need proper implementation
        import inspect
        if provider_class.__bases__ == (ProtocolProvider,):
            # Direct subclass of abstract ProtocolProvider
            self.logger.warning(
                f"Cannot auto-fix {provider_class.__name__}: "
                "Direct ProtocolProvider subclasses need full implementation. "
                "Consider using SimpleProvider or UltraSimpleProvider instead."
            )
            return provider_class
        
        # Create a new class with fixes
        class FixedProvider(provider_class):
            pass
        
        fixed_any = False
        
        # Fix sync methods that should be async
        for method_name in ["execute", "initialize", "shutdown", "health_check"]:
            if hasattr(provider_class, method_name):
                method = getattr(provider_class, method_name)
                if callable(method) and not inspect.iscoroutinefunction(method):
                    # Wrap sync method to make it async
                    original_method = method
                    
                    async def async_wrapper(self, *args, **kwargs):
                        return original_method(self, *args, **kwargs)
                    
                    setattr(FixedProvider, method_name, async_wrapper)
                    self.logger.info(f"Wrapped sync {method_name}() to be async in {provider_class.__name__}")
                    fixed_any = True
        
        # Add missing optional methods (only for non-abstract classes)
        if not inspect.isabstract(provider_class):
            # Add get_supported_methods if missing (optional but recommended)
            if not hasattr(provider_class, "get_supported_methods"):
                def get_supported_methods(self):
                    return []
                
                FixedProvider.get_supported_methods = get_supported_methods
                self.logger.info(f"Auto-added get_supported_methods() to {provider_class.__name__}")
                fixed_any = True
        
        return FixedProvider if fixed_any else provider_class


# Convenience functions
def create_validated_provider(
    provider_class: Type[ProtocolProvider],
    *args,
    **kwargs
) -> ProtocolProvider:
    """
    Create a provider with strict validation.
    
    Raises:
        ProviderValidationError: If provider is not valid
    """
    factory = ProviderFactory(strict_validation=True, debug_mode=True)
    return factory.create_provider(provider_class, *args, validate=True, **kwargs)


def validate_provider(provider: ProtocolProvider, strict: bool = False) -> bool:
    """
    Check if a provider is valid.
    
    Args:
        provider: Provider instance to validate
        strict: Enable strict validation mode
    
    Returns:
        True if valid, False otherwise
    """
    factory = ProviderFactory(strict_validation=strict)
    errors = factory.validate_existing_provider(provider)
    return len(errors) == 0


def debug_provider(
    provider: ProtocolProvider,
    test_methods: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Debug a provider and return detailed validation report.
    
    Returns:
        Dictionary with validation results and recommendations
    """
    factory = ProviderFactory(strict_validation=True, debug_mode=True)
    validator = factory.validator
    
    report = {
        "provider_class": provider.__class__.__name__,
        "provider_id": getattr(provider, "provider_id", "MISSING"),
        "protocol_id": getattr(provider, "protocol_id", "MISSING"),
        "validation_results": {},
        "recommendations": [],
        "test_results": {}
    }
    
    # Class validation
    class_errors = validator.validate_provider_class(type(provider))
    report["validation_results"]["class"] = {
        "valid": len(class_errors) == 0,
        "errors": class_errors
    }
    
    # Instance validation
    instance_errors = validator.validate_provider_instance(provider)
    report["validation_results"]["instance"] = {
        "valid": len(instance_errors) == 0,
        "errors": instance_errors
    }
    
    # Runtime validation
    if test_methods:
        async def test():
            return await validator.validate_provider_runtime(provider, test_methods)
        
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, skip runtime tests or run in thread
            runtime_errors = ["Skipped runtime tests (already in async context)"]
        except RuntimeError:
            # No event loop, we can use asyncio.run
            runtime_errors = asyncio.run(test())
        report["validation_results"]["runtime"] = {
            "valid": len(runtime_errors) == 0,
            "errors": runtime_errors
        }
    
    # Generate recommendations
    all_errors = class_errors + instance_errors
    if "must implement execute()" in " ".join(all_errors):
        report["recommendations"].append(
            "Implement the execute() method to handle provider requests"
        )
    
    if "provider_id" in " ".join(all_errors):
        report["recommendations"].append(
            "Ensure provider_id is set and follows naming conventions"
        )
    
    if not getattr(provider, "get_supported_methods", lambda: [])():
        report["recommendations"].append(
            "Override get_supported_methods() to declare what methods this provider handles"
        )
    
    # Check for best practices
    if hasattr(provider, "base_url") and "http" in provider.__class__.__name__.lower():
        report["recommendations"].append(
            "Consider using HTTPProvider or UltraHTTPProvider base class for HTTP-based providers"
        )
    
    return report