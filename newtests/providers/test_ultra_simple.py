"""
Tests for Ultra-Simplified Provider System

Validates that minimal providers maintain full functionality.
"""

import pytest
from unittest.mock import patch, AsyncMock
import aiohttp

from src.gleitzeit.providers.ultra_simple import (
    UltraSimpleProvider, UltraHTTPProvider, method,
    create_llm_provider, create_rest_provider, lambda_provider
)
from src.gleitzeit.providers.ollama_provider3 import OllamaProvider3
from src.gleitzeit.core.errors import InvalidParameterError


class TestUltraSimpleProvider:
    """Test the ultra-simple provider base class"""
    
    @pytest.mark.asyncio
    async def test_minimal_provider(self):
        """Test creating a minimal provider with decorators"""
        
        class MinimalProvider(UltraSimpleProvider):
            @method("greet")
            async def say_hello(self, name: str):
                return f"Hello, {name}!"
            
            @method("add", "sum")  # Multiple method names
            async def add_numbers(self, a: int, b: int):
                return {"result": a + b}
        
        provider = MinimalProvider()
        
        # Test method routing
        result = await provider.execute("greet", {"name": "World"})
        assert result == "Hello, World!"
        
        # Test multiple method names
        result1 = await provider.execute("add", {"a": 2, "b": 3})
        result2 = await provider.execute("sum", {"a": 2, "b": 3})
        assert result1 == result2 == {"result": 5}
        
        # Test supported methods
        methods = provider.get_supported_methods()
        assert "greet" in methods
        assert "add" in methods
        assert "sum" in methods
    
    @pytest.mark.asyncio
    async def test_parameter_extraction(self):
        """Test smart parameter extraction from method signature"""
        
        class SmartProvider(UltraSimpleProvider):
            @method("process")
            async def process_data(self, 
                                  required: str,
                                  optional: int = 10,
                                  another: str = "default"):
                return {
                    "required": required,
                    "optional": optional,
                    "another": another
                }
        
        provider = SmartProvider()
        
        # Test with all parameters
        result = await provider.execute("process", {
            "required": "test",
            "optional": 20,
            "another": "custom"
        })
        assert result == {"required": "test", "optional": 20, "another": "custom"}
        
        # Test with only required parameter (defaults applied)
        result = await provider.execute("process", {"required": "test"})
        assert result == {"required": "test", "optional": 10, "another": "default"}
        
        # Test missing required parameter
        with pytest.raises(InvalidParameterError) as exc:
            await provider.execute("process", {})
        assert "required" in str(exc.value)
    
    @pytest.mark.asyncio
    async def test_enterprise_features_inherited(self):
        """Test that enterprise features are automatically included"""
        
        class TestProvider(UltraSimpleProvider):
            @method("test")
            async def test_method(self):
                return {"success": True}
        
        provider = TestProvider()
        
        # Check enterprise features from ProtocolProvider
        assert hasattr(provider, "max_retries")
        assert hasattr(provider, "logger")
        assert hasattr(provider, "get_enhanced_metrics")
        assert hasattr(provider, "handle_request")  # With retry logic
        
        # Test retry logic through handle_request
        with patch.object(provider, 'execute') as mock_execute:
            mock_execute.side_effect = [
                TimeoutError("Network error"),
                {"success": True}
            ]
            
            result = await provider.handle_request("test", {})
            assert result == {"success": True}
            assert mock_execute.call_count == 2  # Retried once


class TestOllamaProvider3:
    """Test the ultra-simplified Ollama provider"""
    
    @pytest.fixture
    async def provider(self):
        provider = OllamaProvider3()
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_generate_method(self, provider):
        """Test text generation with minimal code"""
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"response": "Generated text", "done": True}
            
            result = await provider.execute("llm/generate", {"prompt": "Hello"})
            
            assert result["success"] is True
            assert result["response"] == "Generated text"
            mock_post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_chat_method(self, provider):
        """Test chat completion"""
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {
                "message": {"role": "assistant", "content": "Hi there!"},
                "done": True
            }
            
            result = await provider.execute("llm/chat", {
                "messages": [{"role": "user", "content": "Hello"}]
            })
            
            assert result["success"] is True
            assert result["response"] == "Hi there!"
    
    @pytest.mark.asyncio
    async def test_default_parameters(self, provider):
        """Test that defaults are properly applied"""
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"response": "Test", "done": True}
            
            # Call without model parameter - should use default
            await provider.execute("llm/generate", {"prompt": "Test"})
            
            # Check that default model was used
            call_args = mock_post.call_args[0]
            call_data = mock_post.call_args[1]["data"] if "data" in mock_post.call_args[1] else call_args[1]
            assert call_data["model"] == "llama3.2"
    
    @pytest.mark.asyncio
    async def test_supported_methods(self, provider):
        """Test that all LLM methods are registered"""
        methods = provider.get_supported_methods()
        
        expected = [
            "llm/generate", "llm/complete", "llm/chat",
            "llm/vision", "llm/embeddings", "llm/list_models"
        ]
        
        for method in expected:
            assert method in methods


class TestFactoryFunctions:
    """Test the factory functions for creating providers"""
    
    @pytest.mark.asyncio
    async def test_create_llm_provider(self):
        """Test one-line LLM provider creation"""
        llm = create_llm_provider("http://localhost:11434", "llama3.2")
        
        await llm.initialize()
        
        with patch.object(llm, 'post') as mock_post:
            mock_post.return_value = {"response": "Test response"}
            
            result = await llm.execute("generate", {"prompt": "Hello"})
            assert "response" in result
        
        await llm.shutdown()
    
    @pytest.mark.asyncio
    async def test_create_rest_provider(self):
        """Test REST provider from endpoint configuration"""
        api = create_rest_provider(
            "https://api.example.com",
            {
                "get_user": "GET /users/{id}",
                "create_user": "POST /users",
                "update_user": "PUT /users/{id}"
            }
        )
        
        await api.initialize()
        
        with patch.object(api, 'get') as mock_get:
            mock_get.return_value = {"id": 123, "name": "John"}
            
            result = await api.execute("get_user", {"id": 123})
            assert result["id"] == 123
            
            # Check that path parameter was extracted
            mock_get.assert_called_with("/users/123", params=None)
        
        await api.shutdown()
    
    @pytest.mark.asyncio
    async def test_lambda_provider(self):
        """Test lambda-style provider creation"""
        
        # Synchronous lambda
        provider = lambda_provider(
            lambda method, **params: {
                "echo": {"text": params.get("text", "echo")},
                "add": {"result": params.get("a", 0) + params.get("b", 0)}
            }.get(method, {"error": "Unknown"})
        )
        
        result = await provider.execute("echo", {"text": "Hello"})
        assert result == {"text": "Hello"}
        
        result = await provider.execute("add", {"a": 5, "b": 3})
        assert result == {"result": 8}
        
        # Async lambda
        async def async_handler(method, **params):
            if method == "async_test":
                return {"async": True, "data": params.get("data")}
            return {"error": "Unknown method"}
        
        async_provider = lambda_provider(async_handler, "async")
        result = await async_provider.execute("async_test", {"data": "test"})
        assert result == {"async": True, "data": "test"}


class TestCodeReduction:
    """Validate the code reduction claims"""
    
    def test_line_count_comparison(self):
        """Compare line counts between implementations"""
        import inspect
        
        # Get OllamaProvider3 source
        from src.gleitzeit.providers.ollama_provider3 import OllamaProvider3
        source = inspect.getsource(OllamaProvider3)
        
        # Count only the actual implementation lines (not comments or docstrings)
        lines = [l for l in source.split('\n') 
                if l.strip() and not l.strip().startswith('#') and not l.strip().startswith('"""')]
        
        # Remove docstring lines
        in_docstring = False
        impl_lines = []
        for line in lines:
            if '"""' in line:
                in_docstring = not in_docstring
                continue
            if not in_docstring:
                impl_lines.append(line)
        
        # Should be around 30-35 lines of actual implementation
        assert len(impl_lines) < 40, f"OllamaProvider3 has {len(impl_lines)} implementation lines"
        
        # Compare feature completeness
        provider = OllamaProvider3()
        methods = provider.get_supported_methods()
        
        # Should support all LLM methods
        expected_methods = [
            "llm/generate", "llm/complete", "llm/chat",
            "llm/vision", "llm/embeddings", "llm/list_models"
        ]
        
        for method in expected_methods:
            assert method in methods, f"Missing method: {method}"


class TestMinimalExamples:
    """Test the minimal example providers"""
    
    @pytest.mark.asyncio
    async def test_five_line_provider(self):
        """Test that a 5-line provider actually works"""
        
        # This is a complete, working provider in 5 lines!
        class TinyProvider(UltraSimpleProvider):
            @method("run")
            async def run(self, cmd: str):
                return {"output": f"Executed: {cmd}"}
        
        provider = TinyProvider()
        result = await provider.execute("run", {"cmd": "test"})
        assert result == {"output": "Executed: test"}
        
        # Still has all enterprise features!
        assert hasattr(provider, "handle_request")  # Retry logic
        assert hasattr(provider, "get_enhanced_metrics")  # Metrics
        assert hasattr(provider, "logger")  # Logging
    
    @pytest.mark.asyncio
    async def test_parameter_validation_automatic(self):
        """Test automatic parameter validation"""
        
        class ValidatedProvider(UltraSimpleProvider):
            @method("process")
            async def process(self, required: str, optional: int = 10):
                return {"req": required, "opt": optional}
        
        provider = ValidatedProvider()
        
        # Valid call
        result = await provider.execute("process", {"required": "test"})
        assert result == {"req": "test", "opt": 10}
        
        # Missing required parameter - automatically caught
        with pytest.raises(InvalidParameterError) as exc:
            await provider.execute("process", {"optional": 20})
        assert "required" in str(exc.value)