"""
Comprehensive test suite for provider decorators.

Tests the ultra-simple decorator system that allows creating providers
from plain functions or classes with minimal boilerplate.
"""

import pytest
import asyncio
import inspect
from unittest.mock import AsyncMock, Mock, patch
from typing import Any, Dict

from gleitzeit.providers.decorators import (
    provider, method_handler, provider_class, simple_http_provider
)
from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.core.errors import ProviderError


# =========================================================================
# Test Function-Based Providers (@provider decorator)
# =========================================================================

class TestProviderDecorator:
    """Test the @provider decorator for function-based providers"""
    
    def test_basic_function_provider(self):
        """Test creating a provider from a simple function"""
        
        @provider("math/v1", methods=["add", "multiply"])
        async def math_provider(method: str, **params):
            a = params.get("a", 0)
            b = params.get("b", 0)
            
            if method == "add":
                return {"result": a + b}
            elif method == "multiply":
                return {"result": a * b}
            else:
                raise ValueError(f"Unknown method: {method}")
        
        # Verify the decorator returns a SimpleProvider instance
        assert isinstance(math_provider, SimpleProvider)
        assert math_provider.provider_id == "math_provider"
        assert math_provider.protocol_id == "math/v1"
        assert math_provider.name == "Math_provider Provider"
    
    def test_provider_with_custom_id(self):
        """Test provider with custom provider_id"""
        
        @provider("calc/v1", provider_id="calculator", name="Calculator Service")
        async def calculator_func(method: str, **params):
            return {"method": method, "params": params}
        
        assert calculator_func.provider_id == "calculator"
        assert calculator_func.protocol_id == "calc/v1"
        assert calculator_func.name == "Calculator Service"
    
    def test_provider_id_auto_cleanup(self):
        """Test automatic cleanup of '_provider' suffix from function name"""
        
        @provider("test/v1")
        async def weather_provider(method: str, **params):
            return {"weather": "sunny"}
        
        # Should remove '_provider' suffix
        assert weather_provider.provider_id == "weather"
    
    def test_provider_with_description(self):
        """Test provider with custom description"""
        
        @provider("test/v1", description="A test provider for unit testing")
        async def test_provider_func(method: str, **params):
            """This is a test function"""
            return {"test": True}
        
        assert test_provider_func.description == "A test provider for unit testing"
        assert test_provider_func.__doc__ == "This is a test function"
    
    def test_provider_with_version(self):
        """Test provider with custom version"""
        
        @provider("test/v1", version="2.0.0")
        async def versioned_provider(method: str, **params):
            return {"version": "2.0.0"}
        
        assert versioned_provider.version == "2.0.0"
    
    @pytest.mark.asyncio
    async def test_provider_execution(self):
        """Test execution of decorated provider"""
        
        @provider("math/v1")
        async def math_provider(method: str, **params):
            if method == "square":
                value = params.get("value", 0)
                return {"result": value ** 2}
            else:
                raise ValueError(f"Unknown method: {method}")
        
        await math_provider.initialize()
        
        # Test successful execution
        result = await math_provider.handle_request("square", {"value": 5})
        assert result == {"result": 25}
        
        # Test error handling
        with pytest.raises(ValueError, match="Unknown method"):
            await math_provider.handle_request("unknown", {})
        
        await math_provider.shutdown()
    
    def test_non_async_function_error(self):
        """Test that non-async functions raise an error"""
        
        with pytest.raises(ValueError, match="must be async"):
            @provider("test/v1")
            def sync_provider(method: str, **params):  # Not async
                return {"sync": True}
    
    @pytest.mark.asyncio
    async def test_provider_supported_methods(self):
        """Test that supported methods are tracked correctly"""
        
        @provider("test/v1", methods=["method1", "method2", "method3"])
        async def multi_method_provider(method: str, **params):
            return {"method": method}
        
        supported_methods = multi_method_provider.get_supported_methods()
        assert set(supported_methods) == {"method1", "method2", "method3"}
    
    @pytest.mark.asyncio
    async def test_provider_with_additional_kwargs(self):
        """Test provider with additional SimpleProvider kwargs"""
        
        @provider("test/v1", max_retries=5, retry_delay=2.0)
        async def retry_provider(method: str, **params):
            return {"retries": "configured"}
        
        assert retry_provider.max_retries == 5
        assert retry_provider.retry_delay == 2.0


# =========================================================================
# Test Method Handler System
# =========================================================================

class TestMethodHandler:
    """Test the @method_handler decorator"""
    
    def test_method_handler_decoration(self):
        """Test that method_handler properly marks methods"""
        
        class TestClass:
            @method_handler("test_method")
            async def handle_test(self, **params):
                return {"handled": True}
        
        # Check that the method is properly marked
        handler = TestClass.handle_test
        assert hasattr(handler, '_is_method_handler')
        assert handler._is_method_handler is True
        assert handler._method_name == "test_method"
    
    def test_multiple_method_handlers(self):
        """Test class with multiple method handlers"""
        
        class MultiMethodClass:
            @method_handler("add")
            async def handle_add(self, **params):
                return {"result": params["a"] + params["b"]}
            
            @method_handler("multiply")
            async def handle_multiply(self, **params):
                return {"result": params["a"] * params["b"]}
            
            # Regular method (should be ignored)
            async def regular_method(self):
                return "not a handler"
        
        # Check all handlers are marked
        assert MultiMethodClass.handle_add._method_name == "add"
        assert MultiMethodClass.handle_multiply._method_name == "multiply"
        assert not hasattr(MultiMethodClass.regular_method, '_is_method_handler')


# =========================================================================
# Test Class-Based Providers (@provider_class decorator)
# =========================================================================

class TestProviderClass:
    """Test the @provider_class decorator"""
    
    def test_basic_provider_class(self):
        """Test creating a provider class with method handlers"""
        
        @provider_class("calc/v1")
        class CalculatorProvider:
            def __init__(self, precision=2):
                self.precision = precision
            
            @method_handler("add")
            async def add_numbers(self, **params):
                result = params["a"] + params["b"]
                return {"result": round(result, self.precision)}
            
            @method_handler("subtract")
            async def subtract_numbers(self, **params):
                result = params["a"] - params["b"]
                return {"result": round(result, self.precision)}
        
        # Create instance
        calc = CalculatorProvider(precision=3)
        
        # Verify it's a SimpleProvider
        assert isinstance(calc, SimpleProvider)
        assert calc.provider_id == "calculatorprovider"  # Lowercase class name
        assert calc.protocol_id == "calc/v1"
    
    @pytest.mark.asyncio
    async def test_provider_class_execution(self):
        """Test execution of provider class methods"""
        
        @provider_class("math/v1", provider_id="advanced_math")
        class MathProvider:
            def __init__(self, default_precision=2):
                self.default_precision = default_precision
            
            @method_handler("power")
            async def calculate_power(self, **params):
                base = params.get("base", 1)
                exponent = params.get("exponent", 1)
                result = base ** exponent
                return {"result": round(result, self.default_precision)}
            
            @method_handler("factorial")
            async def calculate_factorial(self, **params):
                n = params.get("n", 0)
                result = 1
                for i in range(1, int(n) + 1):
                    result *= i
                return {"result": result}
        
        # Create and initialize provider
        math_provider = MathProvider(default_precision=3)
        await math_provider.initialize()
        
        # Test power calculation
        result = await math_provider.calculate_power(base=2, exponent=8)
        assert result == {"result": 256}
        
        # Test factorial calculation
        result = await math_provider.calculate_factorial(n=5)
        assert result == {"result": 120}
        
        # Test direct method calls (bypassing handle_request)
        direct_result = await math_provider.power(base=3, exponent=3)
        assert direct_result == {"result": 27}
        
        await math_provider.shutdown()
    
    def test_provider_class_no_handlers_error(self):
        """Test that classes without method handlers raise an error"""
        
        with pytest.raises(ValueError, match="has no @method_handler decorated methods"):
            @provider_class("test/v1")
            class EmptyProvider:
                def __init__(self):
                    pass
                
                async def regular_method(self):
                    return "not a handler"
    
    @pytest.mark.asyncio
    async def test_provider_class_with_state(self):
        """Test provider class that maintains internal state"""
        
        @provider_class("counter/v1")
        class CounterProvider:
            def __init__(self, initial_value=0):
                self.count = initial_value
            
            @method_handler("increment")
            async def increment_counter(self, **params):
                amount = params.get("amount", 1)
                self.count += amount
                return {"count": self.count}
            
            @method_handler("get_count")
            async def get_current_count(self, **params):
                return {"count": self.count}
            
            @method_handler("reset")
            async def reset_counter(self, **params):
                self.count = 0
                return {"count": self.count}
        
        # Create provider with initial state
        counter = CounterProvider(initial_value=10)
        await counter.initialize()
        
        # Test state manipulation
        result = await counter.increment_counter(amount=5)
        assert result == {"count": 15}
        
        result = await counter.get_current_count()
        assert result == {"count": 15}
        
        result = await counter.reset_counter()
        assert result == {"count": 0}
        
        await counter.shutdown()
    
    def test_provider_class_with_custom_parameters(self):
        """Test provider class with custom provider parameters"""
        
        @provider_class(
            "custom/v1", 
            provider_id="custom_provider",
            name="Custom Provider",
            description="A customized provider",
            version="3.0.0",
            max_retries=7
        )
        class CustomProvider:
            @method_handler("test")
            async def test_method(self, **params):
                return {"custom": True}
        
        provider = CustomProvider()
        
        assert provider.provider_id == "custom_provider"
        assert provider.name == "Custom Provider"
        assert provider.description == "A customized provider"
        assert provider.version == "3.0.0"
        assert provider.max_retries == 7
    
    @pytest.mark.asyncio
    async def test_provider_class_parameter_separation(self):
        """Test that provider and user parameters are properly separated"""
        
        @provider_class("test/v1", max_retries=3)  # Provider parameter
        class TestProvider:
            def __init__(self, user_param="default"):  # User parameter
                self.user_param = user_param
            
            @method_handler("get_param")
            async def get_user_param(self, **params):
                return {"user_param": self.user_param}
        
        # Create with user parameter
        provider = TestProvider(user_param="custom_value")
        await provider.initialize()
        
        # Verify provider parameter was set
        assert provider.max_retries == 3
        
        # Verify user parameter was set
        result = await provider.get_user_param()
        assert result == {"user_param": "custom_value"}
        
        await provider.shutdown()


# =========================================================================
# Error Handling in Decorated Providers
# =========================================================================

class TestDecoratorErrorHandling:
    """Test error handling in decorated providers"""
    
    @pytest.mark.asyncio
    async def test_function_provider_error_propagation(self):
        """Test that errors in function providers are properly propagated"""
        
        @provider("error/v1")
        async def error_provider(method: str, **params):
            error_type = params.get("error_type")
            
            if error_type == "value_error":
                raise ValueError("Invalid value provided")
            elif error_type == "connection_error":
                raise ConnectionError("Network issue")
            elif error_type == "provider_error":
                raise ProviderError("Provider-specific error")
            else:
                return {"success": True}
        
        await error_provider.initialize()
        
        # Test successful execution
        result = await error_provider.handle_request("test", {})
        assert result == {"success": True}
        
        # Test ValueError propagation
        with pytest.raises(ValueError, match="Invalid value"):
            await error_provider.handle_request("test", {"error_type": "value_error"})
        
        # Test ConnectionError propagation (should be retried)
        with pytest.raises(ConnectionError, match="Network issue"):
            await error_provider.handle_request("test", {"error_type": "connection_error"})
        
        # Test ProviderError propagation
        with pytest.raises(ProviderError, match="Provider-specific error"):
            await error_provider.handle_request("test", {"error_type": "provider_error"})
        
        await error_provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_class_provider_error_propagation(self):
        """Test that errors in class providers are properly propagated"""
        
        @provider_class("error_class/v1")
        class ErrorProvider:
            @method_handler("safe_method")
            async def safe_operation(self, **params):
                return {"safe": True}
            
            @method_handler("error_method")
            async def error_operation(self, **params):
                raise RuntimeError("Something went wrong")
        
        provider = ErrorProvider()
        await provider.initialize()
        
        # Test successful method
        result = await provider.safe_operation()
        assert result == {"safe": True}
        
        # Test error method
        with pytest.raises(RuntimeError, match="Something went wrong"):
            await provider.error_operation()
        
        await provider.shutdown()


# =========================================================================
# Integration and Advanced Features
# =========================================================================

class TestDecoratorIntegration:
    """Test integration of decorated providers with the broader system"""
    
    @pytest.mark.asyncio
    async def test_metrics_collection_in_decorated_providers(self):
        """Test that metrics are properly collected for decorated providers"""
        
        @provider("metrics_test/v1")
        async def metrics_provider(method: str, **params):
            if method == "fast_op":
                return {"fast": True}
            elif method == "slow_op":
                await asyncio.sleep(0.1)
                return {"slow": True}
            else:
                raise ValueError("Unknown method")
        
        await metrics_provider.initialize()
        
        # Execute some operations
        await metrics_provider.handle_request("fast_op", {})
        await metrics_provider.handle_request("slow_op", {})
        
        # Try an error operation
        try:
            await metrics_provider.handle_request("unknown", {})
        except ValueError:
            pass
        
        # Check metrics
        assert metrics_provider.request_count >= 3
        assert metrics_provider.error_count >= 1
        assert len(metrics_provider.latencies) >= 2
        
        # Check enhanced metrics
        metrics = metrics_provider.get_enhanced_metrics()
        assert "fast_op" in metrics["method_breakdown"]
        assert "slow_op" in metrics["method_breakdown"]
        
        await metrics_provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_decorated_provider_with_retry(self):
        """Test retry logic in decorated providers"""
        
        attempt_count = 0
        
        @provider("retry_test/v1", max_retries=3, retry_delay=0.01)
        async def retry_provider(method: str, **params):
            nonlocal attempt_count
            attempt_count += 1
            
            if method == "flaky_op" and attempt_count < 3:
                raise ConnectionError("Temporary failure")
            
            return {"success": True, "attempts": attempt_count}
        
        await retry_provider.initialize()
        
        # Reset counter
        attempt_count = 0
        
        # Should succeed on the 3rd attempt
        result = await retry_provider.handle_request("flaky_op", {})
        assert result["success"] is True
        assert result["attempts"] == 3
        
        await retry_provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_concurrent_decorated_providers(self):
        """Test multiple decorated providers running concurrently"""
        
        @provider("concurrent1/v1")
        async def provider1(method: str, **params):
            await asyncio.sleep(0.1)
            return {"provider": "1", "method": method}
        
        @provider("concurrent2/v1")
        async def provider2(method: str, **params):
            await asyncio.sleep(0.1)
            return {"provider": "2", "method": method}
        
        await provider1.initialize()
        await provider2.initialize()
        
        # Execute operations concurrently
        start_time = asyncio.get_event_loop().time()
        
        results = await asyncio.gather(
            provider1.handle_request("test", {}),
            provider2.handle_request("test", {}),
            provider1.handle_request("test2", {}),
            provider2.handle_request("test2", {})
        )
        
        end_time = asyncio.get_event_loop().time()
        
        # Should complete much faster than sequential execution
        assert end_time - start_time < 0.5  # Much less than 0.4s (4 * 0.1s)
        
        # Verify results
        assert len(results) == 4
        assert results[0]["provider"] == "1"
        assert results[1]["provider"] == "2"
        
        await provider1.shutdown()
        await provider2.shutdown()


# =========================================================================
# Edge Cases and Unusual Scenarios
# =========================================================================

class TestDecoratorEdgeCases:
    """Test edge cases and unusual scenarios with decorators"""
    
    def test_provider_with_empty_methods_list(self):
        """Test provider with empty methods list"""
        
        @provider("test/v1", methods=[])
        async def empty_methods_provider(method: str, **params):
            return {"method": method}
        
        supported_methods = empty_methods_provider.get_supported_methods()
        assert supported_methods == []
    
    @pytest.mark.asyncio
    async def test_provider_with_none_return(self):
        """Test provider that returns None"""
        
        @provider("none/v1")
        async def none_provider(method: str, **params):
            if method == "return_none":
                return None
            else:
                return {"not_none": True}
        
        await none_provider.initialize()
        
        result = await none_provider.handle_request("return_none", {})
        assert result is None
        
        result = await none_provider.handle_request("other", {})
        assert result == {"not_none": True}
        
        await none_provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_class_provider_with_async_init(self):
        """Test class provider with async initialization needs"""
        
        @provider_class("async_init/v1")
        class AsyncInitProvider:
            def __init__(self):
                self.initialized = False
                self.connection = None
            
            async def initialize(self):
                # Simulate async initialization
                await asyncio.sleep(0.01)
                self.initialized = True
                self.connection = "connected"
            
            @method_handler("status")
            async def get_status(self, **params):
                return {
                    "initialized": self.initialized,
                    "connection": self.connection
                }
        
        provider = AsyncInitProvider()
        
        # Before initialization
        result = await provider.get_status()
        assert result["initialized"] is False
        assert result["connection"] is None
        
        # After initialization
        await provider.initialize()
        result = await provider.get_status()
        assert result["initialized"] is True
        assert result["connection"] == "connected"
        
        await provider.shutdown()
    
    def test_provider_metadata_preservation(self):
        """Test that function metadata is preserved in decorated providers"""
        
        @provider("metadata/v1")
        async def documented_provider(method: str, **params):
            """This is a well-documented provider.
            
            It does important things with methods and parameters.
            """
            return {"documented": True}
        
        # Check metadata preservation
        assert documented_provider.__name__ == "documented_provider"
        assert "well-documented provider" in documented_provider.__doc__
        assert hasattr(documented_provider, '__module__')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])