"""
Test OllamaProvider3 with the original OllamaProvider test suite

This proves that the ultra-simplified version maintains full compatibility.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import aiohttp
from aiohttp import ClientTimeout

# Import the ULTRA-SIMPLIFIED provider
from src.gleitzeit.providers.ollama_provider3 import OllamaProvider3
from src.gleitzeit.core.errors import (
    InvalidParameterError, TaskExecutionError, 
    ProviderError, ErrorCode
)


# Mock classes from original tests
class MockResource:
    def __init__(self, endpoint="http://ollama-test:11434", capabilities=None):
        self.id = "mock_resource_001"
        self.endpoint = endpoint
        self.capabilities = capabilities or set()

class MockResourceManager:
    async def allocate_resource(self, resource_type, requirements):
        if requirements and requirements.get("capabilities") == {"llama3.2"}:
            return MockResource(capabilities={"llama3.2"})
        return None

class MockOllamaHub:
    def __init__(self):
        self.hub_id = "ollama_hub_001"
    
    async def get_available_instance(self, capabilities=None, tags=None, strategy=None):
        if capabilities and "llama3.2" in capabilities:
            return MockResource(capabilities=capabilities)
        return MockResource()


class TestOllamaProvider3Compatibility:
    """Test that OllamaProvider3 passes all original OllamaProvider tests"""
    
    @pytest.fixture
    async def provider(self):
        """Create OllamaProvider3 instance"""
        provider = OllamaProvider3(provider_id="ollama3", protocol_id="llm/v1")
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    @pytest.fixture
    async def provider_with_resource_manager(self):
        """Provider with resource manager"""
        provider = OllamaProvider3(
            provider_id="ollama3",
            protocol_id="llm/v1",
            resource_manager=MockResourceManager()
        )
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    @pytest.fixture
    async def provider_with_hub(self):
        """Provider with direct hub connection"""
        provider = OllamaProvider3(
            provider_id="ollama3",
            protocol_id="llm/v1",
            hub=MockOllamaHub()
        )
        await provider.initialize()
        yield provider
        await provider.shutdown()


class TestCoreArchitecture:
    """Test core provider architecture - from original test suite"""
    
    @pytest.mark.asyncio
    async def test_provider_initialization(self):
        """Test basic provider initialization"""
        provider = OllamaProvider3(
            provider_id="test_ollama",
            protocol_id="llm/v1",
            name="Test Ollama Provider",
            description="Test provider for Ollama"
        )
        
        assert provider.provider_id == "test_ollama"
        assert provider.protocol_id == "llm/v1"
        assert provider.name == "Test Ollama Provider"
        assert provider.base_url == "http://localhost:11434"
        assert provider.default_model == "llama3.2"
    
    @pytest.mark.asyncio
    async def test_supported_methods(self):
        """Test that all LLM methods are supported"""
        provider = OllamaProvider3()
        methods = provider.get_supported_methods()
        
        expected = [
            "llm/generate", "llm/complete", "llm/chat",
            "llm/vision", "llm/embeddings", "llm/list_models"
        ]
        
        for method in expected:
            assert method in methods
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check functionality"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'get') as mock_get:
            mock_get.return_value = {"models": []}
            
            result = await provider.health_check()
            assert result is True
            mock_get.assert_called_once_with("/api/tags")
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check handles failures gracefully"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'get') as mock_get:
            mock_get.side_effect = Exception("Connection error")
            
            result = await provider.health_check()
            assert result is False
        
        await provider.shutdown()


class TestLLMProtocolMethods:
    """Test all LLM protocol method implementations"""
    
    @pytest.mark.asyncio
    async def test_generate_method(self):
        """Test text generation"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {
                "response": "Generated text response",
                "done": True
            }
            
            result = await provider.execute("llm/generate", {
                "prompt": "Test prompt",
                "model": "llama3.2",
                "temperature": 0.8
            })
            
            assert result["success"] is True
            assert result["response"] == "Generated text response"
            assert result["done"] is True
            
            # Verify API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/generate" in call_args[0][0]
            
            # Check passed parameters
            data = call_args[1] if len(call_args) > 1 else call_args[0][1]
            assert data["prompt"] == "Test prompt"
            assert data["model"] == "llama3.2"
            assert data["temperature"] == 0.8
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_complete_method_alias(self):
        """Test that complete is an alias for generate"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"response": "Completed text", "done": True}
            
            result = await provider.execute("llm/complete", {"prompt": "Complete this"})
            
            assert result["success"] is True
            assert result["response"] == "Completed text"
            
            # Should call the same generate endpoint
            assert "/api/generate" in mock_post.call_args[0][0]
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_chat_method(self):
        """Test chat completion"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"}
        ]
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {
                "message": {
                    "role": "assistant",
                    "content": "Hello! How can I help you?"
                },
                "done": True
            }
            
            result = await provider.execute("llm/chat", {
                "messages": messages,
                "model": "llama3.2"
            })
            
            assert result["success"] is True
            assert result["response"] == "Hello! How can I help you?"
            assert result["message"]["role"] == "assistant"
            
            # Verify API call
            mock_post.assert_called_once()
            assert "/api/chat" in mock_post.call_args[0][0]
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_vision_method(self):
        """Test vision analysis"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {
                "message": {
                    "content": "I see a cat in the image"
                },
                "done": True
            }
            
            result = await provider.execute("llm/vision", {
                "images": ["base64_image_data"],
                "prompt": "What do you see?"
            })
            
            assert result["success"] is True
            assert "cat" in result["response"]
            
            # Verify correct endpoint and model
            mock_post.assert_called_once()
            call_data = mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1]
            assert call_data["model"] == "llava:latest"  # Vision model
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_embeddings_method(self):
        """Test embeddings generation"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {
                "embedding": [0.1, 0.2, 0.3, 0.4, 0.5]
            }
            
            result = await provider.execute("llm/embeddings", {
                "text": "Test text for embedding"
            })
            
            assert result["success"] is True
            assert result["embedding"] == [0.1, 0.2, 0.3, 0.4, 0.5]
            
            # Verify API call
            mock_post.assert_called_once()
            assert "/api/embeddings" in mock_post.call_args[0][0]
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_list_models_method(self):
        """Test model listing"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'get') as mock_get:
            mock_get.return_value = {
                "models": [
                    {"name": "llama3.2"},
                    {"name": "mistral"},
                    {"name": "llava:latest"}
                ]
            }
            
            result = await provider.execute("llm/list_models", {})
            
            assert result["success"] is True
            assert "llama3.2" in result["models"]
            assert "mistral" in result["models"]
            assert len(result["models"]) == 3
            
            mock_get.assert_called_once_with("/api/tags")
        
        await provider.shutdown()


class TestParameterValidation:
    """Test parameter validation - critical for compatibility"""
    
    @pytest.mark.asyncio
    async def test_generate_requires_prompt(self):
        """Test that generate requires prompt parameter"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with pytest.raises(InvalidParameterError) as exc:
            await provider.execute("llm/generate", {"model": "llama3.2"})
        
        assert "prompt" in str(exc.value).lower() or "required" in str(exc.value).lower()
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_chat_requires_messages(self):
        """Test that chat requires messages parameter"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with pytest.raises(InvalidParameterError) as exc:
            await provider.execute("llm/chat", {"model": "llama3.2"})
        
        assert "messages" in str(exc.value).lower() or "required" in str(exc.value).lower()
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_vision_requires_images(self):
        """Test that vision requires images parameter"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with pytest.raises(InvalidParameterError) as exc:
            await provider.execute("llm/vision", {"prompt": "What do you see?"})
        
        assert "images" in str(exc.value).lower() or "required" in str(exc.value).lower()
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_embeddings_requires_text(self):
        """Test that embeddings requires text parameter"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with pytest.raises(InvalidParameterError) as exc:
            await provider.execute("llm/embeddings", {"model": "nomic-embed-text"})
        
        assert "text" in str(exc.value).lower() or "required" in str(exc.value).lower()
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_invalid_method(self):
        """Test handling of invalid methods"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with pytest.raises(InvalidParameterError) as exc:
            await provider.execute("llm/invalid_method", {"data": "test"})
        
        assert "unknown method" in str(exc.value).lower() or "invalid" in str(exc.value).lower()
        
        await provider.shutdown()


class TestDefaultParameters:
    """Test default parameter handling"""
    
    @pytest.mark.asyncio
    async def test_generate_uses_default_model(self):
        """Test that generate uses default model when not specified"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"response": "test", "done": True}
            
            await provider.execute("llm/generate", {"prompt": "test"})
            
            call_data = mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1]
            assert call_data["model"] == "llama3.2"  # Default model
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_vision_uses_vision_model(self):
        """Test that vision uses appropriate default model"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"message": {"content": "test"}, "done": True}
            
            await provider.execute("llm/vision", {
                "images": ["image_data"],
                # No model specified
            })
            
            call_data = mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1]
            assert call_data["model"] == "llava:latest"  # Vision model default
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_embeddings_uses_embedding_model(self):
        """Test that embeddings uses appropriate default model"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"embedding": [0.1, 0.2]}
            
            await provider.execute("llm/embeddings", {
                "text": "test text"
                # No model specified
            })
            
            call_data = mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1]
            assert call_data["model"] == "nomic-embed-text"  # Embedding model default
        
        await provider.shutdown()


class TestEnterpriseFeatures:
    """Test that enterprise features work with ultra-simplified provider"""
    
    @pytest.mark.asyncio
    async def test_retry_logic_inherited(self):
        """Test that retry logic from ProtocolProvider works"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        # Test through handle_request (where retry logic lives)
        with patch.object(provider, 'execute') as mock_execute:
            # First call fails with retryable error, second succeeds
            mock_execute.side_effect = [
                TimeoutError("Network timeout"),
                {"success": True, "response": "Success after retry"}
            ]
            
            result = await provider.handle_request("llm/generate", {"prompt": "test"})
            
            assert result["success"] is True
            assert mock_execute.call_count == 2  # Retried once
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """Test that metrics are collected automatically"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"response": "test", "done": True}
            
            # Execute some requests
            await provider.execute("llm/generate", {"prompt": "test1"})
            await provider.execute("llm/generate", {"prompt": "test2"})
            
            # Check metrics
            metrics = provider.get_enhanced_metrics()
            assert "request_count" in metrics
            assert "method_breakdown" in metrics
            assert "latency" in metrics or len(provider.latencies) > 0
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_session_management(self):
        """Test HTTP session is properly managed"""
        provider = OllamaProvider3()
        
        # Before initialization, no session
        assert provider.session is None
        
        # After initialization, session exists
        await provider.initialize()
        assert provider.session is not None
        assert isinstance(provider.session, aiohttp.ClientSession)
        
        # After shutdown, session is closed
        await provider.shutdown()
        assert provider.session is None


class TestCompatibilityEdgeCases:
    """Test edge cases to ensure full compatibility"""
    
    @pytest.mark.asyncio
    async def test_extra_parameters_passed_through(self):
        """Test that extra parameters are passed through via **kwargs"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"response": "test", "done": True}
            
            # Pass extra parameters that should be forwarded
            await provider.execute("llm/generate", {
                "prompt": "test",
                "temperature": 0.9,
                "top_p": 0.95,
                "max_tokens": 500,
                "custom_param": "value"
            })
            
            call_data = mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1]
            
            # All parameters should be passed through
            assert call_data["temperature"] == 0.9
            assert call_data["top_p"] == 0.95
            assert call_data["max_tokens"] == 500
            assert call_data["custom_param"] == "value"
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_response_format_compatibility(self):
        """Test that response format matches original provider"""
        provider = OllamaProvider3()
        await provider.initialize()
        
        # Test generate response format
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {"response": "Generated text", "done": True}
            
            result = await provider.execute("llm/generate", {"prompt": "test"})
            
            # Should have success flag and response
            assert "success" in result
            assert "response" in result
            assert "done" in result
            assert result["success"] is True
        
        # Test chat response format
        with patch.object(provider, 'post') as mock_post:
            mock_post.return_value = {
                "message": {"role": "assistant", "content": "Chat response"},
                "done": True
            }
            
            result = await provider.execute("llm/chat", {"messages": []})
            
            # Should have success, response, and message
            assert "success" in result
            assert "response" in result
            assert "message" in result
            assert result["success"] is True
        
        await provider.shutdown()


# Run count test
def test_provider3_is_ultra_simple():
    """Verify that OllamaProvider3 is indeed ultra-simplified"""
    import inspect
    from src.gleitzeit.providers.ollama_provider3 import OllamaProvider3
    
    source = inspect.getsource(OllamaProvider3)
    
    # Count actual implementation lines (excluding comments and docstrings)
    lines = source.split('\n')
    impl_lines = []
    in_docstring = False
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            continue
            
        # Handle docstrings
        if '"""' in line or "'''" in line:
            if in_docstring:
                in_docstring = False
                continue
            else:
                # Check if docstring closes on same line
                if line.count('"""') >= 2 or line.count("'''") >= 2:
                    continue
                in_docstring = True
                continue
        
        if in_docstring:
            continue
            
        impl_lines.append(line)
    
    # Should be around 35-40 lines of actual implementation
    line_count = len(impl_lines)
    print(f"OllamaProvider3 has {line_count} implementation lines")
    
    # Verify it's actually simplified (less than 50 lines)
    assert line_count < 50, f"Provider is not ultra-simplified: {line_count} lines"