"""
Comprehensive test suite for OllamaProvider.

Tests the legacy Ollama provider that integrates with resource management
and provides LLM capabilities through the Ollama API.
"""

import pytest
import asyncio
import json
import aiohttp
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from typing import Any, Dict

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError, ProviderError


# =========================================================================
# Mock Resource Manager and Hub
# =========================================================================

class MockResourceManager:
    """Mock resource manager for testing"""
    
    def __init__(self, mock_resource=None):
        self.mock_resource = mock_resource
        
    async def allocate_resource(self, resource_type=None, requirements=None):
        """Mock resource allocation with correct signature"""
        if self.mock_resource:
            return self.mock_resource
        return None


class MockResource:
    """Mock allocated resource"""
    
    def __init__(self, endpoint="http://localhost:11434"):
        self.id = "mock_resource_001"
        self.endpoint = endpoint
        self.capabilities = {"llama3.2", "llava:latest"}
        self.status = "available"


class MockOllamaHub:
    """Mock Ollama hub for testing"""
    
    def __init__(self, instances=None):
        self.instances = instances or []
        
    async def get_healthy_instances(self):
        return self.instances
        
    async def allocate_instance(self, model=None):
        if self.instances:
            return self.instances[0]
        return None


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
async def ollama_provider():
    """Create a basic Ollama provider for testing"""
    provider = OllamaProvider(
        provider_id="test_ollama",
        protocol_id="llm/v1",
        default_model="llama3.2"
    )
    await provider.initialize()
    yield provider
    await provider.shutdown()


@pytest.fixture
async def ollama_provider_with_resource_manager():
    """Create Ollama provider with mock resource manager"""
    mock_resource = MockResource("http://ollama-test:11434")
    resource_manager = MockResourceManager(mock_resource)
    
    provider = OllamaProvider(
        provider_id="test_ollama_rm",
        protocol_id="llm/v1",
        resource_manager=resource_manager
    )
    await provider.initialize()
    yield provider
    await provider.shutdown()


@pytest.fixture
async def ollama_provider_no_resources():
    """Create Ollama provider with no available resources"""
    resource_manager = MockResourceManager(mock_resource=None)
    
    provider = OllamaProvider(
        provider_id="test_ollama_no_res",
        protocol_id="llm/v1", 
        resource_manager=resource_manager
    )
    await provider.initialize()
    yield provider
    await provider.shutdown()


@pytest.fixture
def mock_ollama_responses():
    """Common Ollama API response fixtures"""
    return {
        "generate_success": {
            "response": "This is a generated response from the model.",
            "done": True,
            "context": [123, 456, 789]
        },
        "chat_success": {
            "message": {
                "role": "assistant",
                "content": "This is a chat response from the model."
            },
            "done": True
        },
        "vision_success": {
            "message": {
                "role": "assistant", 
                "content": "I can see a cat sitting on a windowsill in this image."
            },
            "done": True
        },
        "embeddings_success": {
            "embedding": [0.1, 0.2, 0.3, -0.4, 0.5]
        },
        "models_success": {
            "models": [
                {"name": "llama3.2:latest"},
                {"name": "llava:latest"},
                {"name": "codellama:13b"}
            ]
        },
        "error_response": {
            "error": "Model not found"
        }
    }


# =========================================================================
# Basic Provider Tests
# =========================================================================

class TestOllamaProviderBasics:
    """Test basic Ollama provider functionality"""
    
    @pytest.mark.asyncio
    async def test_provider_initialization(self):
        """Test Ollama provider initialization"""
        provider = OllamaProvider(
            provider_id="test_ollama",
            protocol_id="llm/v1",
            default_model="llama3.2"
        )
        
        assert provider.provider_id == "test_ollama"
        assert provider.protocol_id == "llm/v1"
        assert provider.default_model == "llama3.2"
        assert provider.name == "Ollama Provider"
        assert provider.session is None
        
        await provider.initialize()
        assert provider.session is not None
        assert isinstance(provider.session, aiohttp.ClientSession)
        
        await provider.shutdown()
        assert provider.session is None
    
    @pytest.mark.asyncio
    async def test_provider_with_resource_manager(self):
        """Test provider initialization with resource manager"""
        resource_manager = MockResourceManager()
        provider = OllamaProvider(
            provider_id="test_ollama_rm",
            resource_manager=resource_manager
        )
        
        assert provider.resource_manager == resource_manager
        
        await provider.initialize()
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_provider_with_hub(self):
        """Test provider initialization with hub"""
        hub = MockOllamaHub()
        provider = OllamaProvider(
            provider_id="test_ollama_hub",
            hub=hub
        )
        
        assert provider.hub == hub
        
        await provider.initialize()
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_supported_methods(self, ollama_provider):
        """Test that provider reports correct supported methods"""
        supported = ollama_provider.get_supported_methods()
        
        expected_methods = [
            "llm/generate",
            "llm/complete",
            "llm/chat", 
            "llm/vision",
            "llm/embeddings",
            "llm/list_models"
        ]
        
        for method in expected_methods:
            assert method in supported
    
    @pytest.mark.asyncio
    async def test_can_handle_methods(self, ollama_provider):
        """Test method capability checking"""
        assert ollama_provider.can_handle("llm/generate")
        assert ollama_provider.can_handle("llm/chat")
        assert ollama_provider.can_handle("llm/vision")
        assert not ollama_provider.can_handle("unknown/method")
        assert not ollama_provider.can_handle("http/request")
    
    @pytest.mark.asyncio
    async def test_health_check(self, ollama_provider):
        """Test provider health check"""
        with patch.object(ollama_provider.session, 'get') as mock_get:
            # Mock successful health check
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_get.return_value.__aenter__.return_value = mock_response
            
            health = await ollama_provider.health_check()
            assert health is True
            
            mock_get.assert_called_once_with(
                "http://localhost:11434/api/tags",
                timeout=aiohttp.ClientTimeout(total=2)
            )
    
    @pytest.mark.asyncio
    async def test_health_check_failure_graceful(self, ollama_provider):
        """Test health check failure is handled gracefully"""
        with patch.object(ollama_provider.session, 'get') as mock_get:
            # Mock connection error
            mock_get.side_effect = aiohttp.ClientConnectorError(
                connection_key=Mock(), os_error=OSError("Connection refused")
            )
            
            # Provider should still report healthy (hub handles instance availability)
            health = await ollama_provider.health_check()
            assert health is True


# =========================================================================
# Resource Management Tests
# =========================================================================

class TestOllamaResourceManagement:
    """Test Ollama provider resource management integration"""
    
    @pytest.mark.asyncio
    async def test_resource_allocation_success(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test successful resource allocation and request execution"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["generate_success"]
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await provider.execute("llm/generate", {"prompt": "Hello world"})
            
            assert result["success"] is True
            assert "This is a generated response" in result["response"]
            mock_post.assert_called_once_with(
                "http://ollama-test:11434/api/generate",
                json={
                    "model": "llama3.2",
                    "prompt": "Hello world", 
                    "stream": False,
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 100
                }
            )
    
    @pytest.mark.asyncio
    async def test_resource_allocation_failure(self, ollama_provider_no_resources):
        """Test handling of resource allocation failure"""
        provider = ollama_provider_no_resources
        
        with pytest.raises(ProviderError, match="Failed to allocate Ollama resource"):
            await provider.execute("llm/generate", {"prompt": "Hello world"})
    
    @pytest.mark.asyncio
    async def test_model_specific_allocation(self, ollama_provider_with_resource_manager):
        """Test resource allocation with specific model requirements"""
        provider = ollama_provider_with_resource_manager
        
        # Mock the allocate_resource method to verify model capabilities are passed
        with patch.object(provider, 'allocate_resource') as mock_allocate:
            mock_resource = MockResource("http://model-specific:11434")
            mock_allocate.return_value = mock_resource
            
            with patch.object(provider.session, 'post') as mock_post:
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json.return_value = {"response": "test", "done": True}
                mock_post.return_value.__aenter__.return_value = mock_response
                
                await provider.execute("llm/generate", {
                    "prompt": "Hello",
                    "model": "llama3.1"
                })
                
                # Verify model capabilities were passed to resource allocation
                # The base class wraps capabilities in requirements dict
                mock_allocate.assert_called_once()


# =========================================================================
# LLM Method Tests  
# =========================================================================

class TestOllamaLLMMethods:
    """Test individual LLM method implementations"""
    
    @pytest.mark.asyncio
    async def test_generate_method(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test text generation method"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["generate_success"]
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await provider.execute("llm/generate", {
                "prompt": "Write a haiku about coding",
                "model": "llama3.2",
                "temperature": 0.8,
                "max_tokens": 50
            })
            
            assert result["success"] is True
            assert result["model"] == "llama3.2"
            assert result["done"] is True
            assert "generated response" in result["response"]
            
            # Verify API call parameters
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            assert json_data["model"] == "llama3.2"
            assert json_data["prompt"] == "Write a haiku about coding"
            assert json_data["temperature"] == 0.8
            assert json_data["max_tokens"] == 50
            assert json_data["stream"] is False
    
    @pytest.mark.asyncio
    async def test_generate_complete_alias(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test that llm/complete is an alias for llm/generate"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["generate_success"]
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await provider.execute("llm/complete", {"prompt": "Complete this"})
            
            assert result["success"] is True
            # Should call the generate endpoint
            mock_post.assert_called_once()
            assert "/api/generate" in mock_post.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_chat_method(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test chat completion method"""
        provider = ollama_provider_with_resource_manager
        
        messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
            {"role": "user", "content": "What's the weather like?"}
        ]
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["chat_success"]
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await provider.execute("llm/chat", {
                "messages": messages,
                "model": "llama3.2",
                "temperature": 0.5
            })
            
            assert result["success"] is True
            assert result["model"] == "llama3.2"
            assert result["done"] is True
            assert "chat response" in result["response"]
            assert "message" in result
            
            # Verify API call
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            assert json_data["model"] == "llama3.2"
            assert json_data["messages"] == messages
            assert json_data["temperature"] == 0.5
    
    @pytest.mark.asyncio
    async def test_vision_method(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test vision analysis method"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["vision_success"]
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await provider.execute("llm/vision", {
                "images": ["base64encodedimage1", "base64encodedimage2"],
                "prompt": "Describe what you see in these images",
                "model": "llava:latest"
            })
            
            assert result["success"] is True
            assert result["model"] == "llava:latest"
            assert result["done"] is True
            assert "cat sitting on a windowsill" in result["response"]
            
            # Verify API call structure for vision
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            assert json_data["model"] == "llava:latest"
            assert len(json_data["messages"]) == 1
            message = json_data["messages"][0]
            assert message["role"] == "user"
            assert message["content"] == "Describe what you see in these images"
            assert message["images"] == ["base64encodedimage1", "base64encodedimage2"]
    
    @pytest.mark.asyncio
    async def test_embeddings_method(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test embeddings generation method"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["embeddings_success"]
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await provider.execute("llm/embeddings", {
                "text": "This is some text to embed",
                "model": "nomic-embed-text"
            })
            
            assert result["success"] is True
            assert result["model"] == "nomic-embed-text"
            assert "embedding" in result
            assert len(result["embedding"]) == 5
            assert result["embedding"] == [0.1, 0.2, 0.3, -0.4, 0.5]
            
            # Verify API call
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            assert json_data["model"] == "nomic-embed-text"
            assert json_data["prompt"] == "This is some text to embed"
    
    @pytest.mark.asyncio
    async def test_list_models_method(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test model listing method"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["models_success"]
            mock_get.return_value.__aenter__.return_value = mock_response
            
            result = await provider.execute("llm/list_models", {})
            
            assert result["success"] is True
            assert "models" in result
            expected_models = ["llama3.2:latest", "llava:latest", "codellama:13b"]
            assert result["models"] == expected_models
            
            # Verify API call
            mock_get.assert_called_once_with("http://ollama-test:11434/api/tags")


# =========================================================================
# Parameter Validation Tests
# =========================================================================

class TestOllamaParameterValidation:
    """Test parameter validation for different methods"""
    
    @pytest.mark.asyncio
    async def test_generate_missing_prompt(self, ollama_provider_with_resource_manager):
        """Test generate method with missing prompt"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="Prompt is required"):
            await provider.execute("llm/generate", {})
    
    @pytest.mark.asyncio
    async def test_generate_empty_prompt(self, ollama_provider_with_resource_manager):
        """Test generate method with empty prompt"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="Prompt is required"):
            await provider.execute("llm/generate", {"prompt": ""})
    
    @pytest.mark.asyncio
    async def test_chat_missing_messages(self, ollama_provider_with_resource_manager):
        """Test chat method with missing messages"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="Messages are required"):
            await provider.execute("llm/chat", {})
    
    @pytest.mark.asyncio
    async def test_chat_empty_messages(self, ollama_provider_with_resource_manager):
        """Test chat method with empty messages list"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="Messages are required"):
            await provider.execute("llm/chat", {"messages": []})
    
    @pytest.mark.asyncio
    async def test_vision_missing_images(self, ollama_provider_with_resource_manager):
        """Test vision method with missing images"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="At least one image required"):
            await provider.execute("llm/vision", {"prompt": "What do you see?"})
    
    @pytest.mark.asyncio
    async def test_vision_empty_images(self, ollama_provider_with_resource_manager):
        """Test vision method with empty images list"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="At least one image required"):
            await provider.execute("llm/vision", {"images": [], "prompt": "What do you see?"})
    
    @pytest.mark.asyncio
    async def test_embeddings_missing_text(self, ollama_provider_with_resource_manager):
        """Test embeddings method with missing text"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="Text is required"):
            await provider.execute("llm/embeddings", {})
    
    @pytest.mark.asyncio
    async def test_embeddings_empty_text(self, ollama_provider_with_resource_manager):
        """Test embeddings method with empty text"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="Text is required"):
            await provider.execute("llm/embeddings", {"text": ""})
    
    @pytest.mark.asyncio
    async def test_unsupported_method(self, ollama_provider_with_resource_manager):
        """Test execution of unsupported method"""
        provider = ollama_provider_with_resource_manager
        
        with pytest.raises(InvalidParameterError, match="Unsupported method"):
            await provider.execute("unsupported/method", {})


# =========================================================================
# Error Handling Tests
# =========================================================================

class TestOllamaErrorHandling:
    """Test error handling for various failure scenarios"""
    
    @pytest.mark.asyncio
    async def test_ollama_api_error_response(self, ollama_provider_with_resource_manager):
        """Test handling of Ollama API error responses"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 404
            mock_response.text.return_value = "Model not found"
            mock_post.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(TaskExecutionError, match="Generation failed: Model not found"):
                await provider.execute("llm/generate", {"prompt": "Hello"})
    
    @pytest.mark.asyncio
    async def test_connection_error_handling(self, ollama_provider_with_resource_manager):
        """Test handling of connection errors"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_post.side_effect = aiohttp.ClientConnectorError(
                connection_key=Mock(), os_error=OSError("Connection refused")
            )
            
            with pytest.raises(TaskExecutionError, match="Connection error"):
                await provider.execute("llm/generate", {"prompt": "Hello"})
    
    @pytest.mark.asyncio
    async def test_timeout_error_handling(self, ollama_provider_with_resource_manager):
        """Test handling of timeout errors"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            # Wrap TimeoutError in aiohttp.ClientError like real usage would
            mock_post.side_effect = aiohttp.ClientConnectorError(
                connection_key=Mock(), os_error=asyncio.TimeoutError("Request timeout")
            )
            
            with pytest.raises(TaskExecutionError, match="Connection error"):
                await provider.execute("llm/generate", {"prompt": "Hello"})
    
    @pytest.mark.asyncio
    async def test_chat_api_error(self, ollama_provider_with_resource_manager):
        """Test chat method API error handling"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 500
            mock_response.text.return_value = "Internal server error"
            mock_post.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(TaskExecutionError, match="Chat failed: Internal server error"):
                await provider.execute("llm/chat", {
                    "messages": [{"role": "user", "content": "Hello"}]
                })
    
    @pytest.mark.asyncio 
    async def test_vision_api_error(self, ollama_provider_with_resource_manager):
        """Test vision method API error handling"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.text.return_value = "Invalid image format"
            mock_post.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(TaskExecutionError, match="Vision analysis failed: Invalid image format"):
                await provider.execute("llm/vision", {
                    "images": ["invalid_image_data"],
                    "prompt": "What do you see?"
                })
    
    @pytest.mark.asyncio
    async def test_embeddings_api_error(self, ollama_provider_with_resource_manager):
        """Test embeddings method API error handling"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 422
            mock_response.text.return_value = "Text too long"
            mock_post.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(TaskExecutionError, match="Embeddings failed: Text too long"):
                await provider.execute("llm/embeddings", {"text": "Some text"})
    
    @pytest.mark.asyncio
    async def test_list_models_api_error(self, ollama_provider_with_resource_manager):
        """Test list models method API error handling"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 503
            mock_response.text.return_value = "Service unavailable"
            mock_get.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(TaskExecutionError, match="List models failed: Service unavailable"):
                await provider.execute("llm/list_models", {})


# =========================================================================
# Default Parameters Tests
# =========================================================================

class TestOllamaDefaultParameters:
    """Test default parameter handling"""
    
    @pytest.mark.asyncio
    async def test_generate_default_parameters(self, ollama_provider_with_resource_manager):
        """Test generate method with default parameters"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = {"response": "test", "done": True}
            mock_post.return_value.__aenter__.return_value = mock_response
            
            await provider.execute("llm/generate", {"prompt": "Hello"})
            
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            
            # Check default values
            assert json_data["model"] == "llama3.2"  # Provider default
            assert json_data["temperature"] == 0.7
            assert json_data["top_p"] == 0.9
            assert json_data["max_tokens"] == 100
            assert json_data["stream"] is False
    
    @pytest.mark.asyncio
    async def test_chat_default_parameters(self, ollama_provider_with_resource_manager):
        """Test chat method with default parameters"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = {
                "message": {"role": "assistant", "content": "test"}, 
                "done": True
            }
            mock_post.return_value.__aenter__.return_value = mock_response
            
            await provider.execute("llm/chat", {
                "messages": [{"role": "user", "content": "Hello"}]
            })
            
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            
            # Check default values
            assert json_data["model"] == "llama3.2"
            assert json_data["temperature"] == 0.7
            assert json_data["top_p"] == 0.9
            assert json_data["stream"] is False
    
    @pytest.mark.asyncio
    async def test_vision_default_parameters(self, ollama_provider_with_resource_manager):
        """Test vision method with default parameters"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = {
                "message": {"role": "assistant", "content": "test"},
                "done": True
            }
            mock_post.return_value.__aenter__.return_value = mock_response
            
            await provider.execute("llm/vision", {"images": ["base64image"]})
            
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            
            # Check default values
            assert json_data["model"] == "llava:latest"  # Vision-specific default
            assert json_data["messages"][0]["content"] == "What is in this image?"
            assert json_data["stream"] is False
    
    @pytest.mark.asyncio
    async def test_embeddings_default_parameters(self, ollama_provider_with_resource_manager):
        """Test embeddings method with default parameters"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
            mock_post.return_value.__aenter__.return_value = mock_response
            
            await provider.execute("llm/embeddings", {"text": "Test text"})
            
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]
            
            # Check default model for embeddings
            assert json_data["model"] == "nomic-embed-text"


# =========================================================================
# Context Manager Tests
# =========================================================================

class TestOllamaContextManager:
    """Test async context manager functionality"""
    
    @pytest.mark.asyncio
    async def test_context_manager_success(self, mock_ollama_responses):
        """Test successful context manager usage"""
        resource_manager = MockResourceManager(MockResource())
        
        async with OllamaProvider(resource_manager=resource_manager) as provider:
            assert provider.session is not None
            assert isinstance(provider.session, aiohttp.ClientSession)
            
            # Test a request within context
            with patch.object(provider.session, 'post') as mock_post:
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json.return_value = mock_ollama_responses["generate_success"]
                mock_post.return_value.__aenter__.return_value = mock_response
                
                result = await provider.execute("llm/generate", {"prompt": "Test"})
                assert result["success"] is True
        
        # Session should be cleaned up
        assert provider.session is None
    
    @pytest.mark.asyncio
    async def test_context_manager_exception_cleanup(self):
        """Test context manager cleanup on exception"""
        provider = OllamaProvider(resource_manager=MockResourceManager(MockResource()))
        
        try:
            async with provider:
                assert provider.session is not None
                # Simulate an exception
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Session should still be cleaned up
        assert provider.session is None


# =========================================================================
# Integration and Performance Tests
# =========================================================================

class TestOllamaIntegration:
    """Test integration scenarios and performance aspects"""
    
    @pytest.mark.asyncio
    async def test_handle_request_wrapper(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test that handle_request properly wraps execute"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider, 'execute') as mock_execute:
            mock_execute.return_value = mock_ollama_responses["generate_success"]
            
            result = await provider.handle_request("llm/generate", {"prompt": "Test"})
            
            assert result == mock_ollama_responses["generate_success"]
            mock_execute.assert_called_once_with("llm/generate", {"prompt": "Test"})
    
    @pytest.mark.asyncio
    async def test_multiple_requests_same_session(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test multiple requests using the same session"""
        provider = ollama_provider_with_resource_manager
        session = provider.session
        
        with patch.object(provider.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_ollama_responses["generate_success"]
            mock_post.return_value.__aenter__.return_value = mock_response
            
            # Execute multiple requests
            for i in range(3):
                result = await provider.execute("llm/generate", {"prompt": f"Test {i}"})
                assert result["success"] is True
            
            # Verify same session was used
            assert provider.session is session
            assert mock_post.call_count == 3
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self, ollama_provider_with_resource_manager, mock_ollama_responses):
        """Test handling of concurrent requests"""
        provider = ollama_provider_with_resource_manager
        
        with patch.object(provider.session, 'post') as mock_post:
            # Create different responses for concurrent requests
            responses = []
            for i in range(3):
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json.return_value = {
                    "response": f"Response {i}",
                    "done": True
                }
                responses.append(mock_response)
            
            mock_post.return_value.__aenter__.side_effect = responses
            
            # Execute concurrent requests
            tasks = [
                provider.execute("llm/generate", {"prompt": f"Concurrent test {i}"})
                for i in range(3)
            ]
            
            results = await asyncio.gather(*tasks)
            
            assert len(results) == 3
            for i, result in enumerate(results):
                assert result["success"] is True
                assert f"Response {i}" in result["response"]
    
    @pytest.mark.asyncio
    async def test_lazy_initialization(self):
        """Test that provider initializes session lazily"""
        provider = OllamaProvider(resource_manager=MockResourceManager(MockResource()))
        
        # Session should be None initially
        assert provider.session is None
        
        # Mock the initialization to create a session
        async def mock_initialize():
            provider.session = aiohttp.ClientSession()
        
        with patch.object(provider, 'initialize', side_effect=mock_initialize) as mock_init:
            with patch.object(aiohttp.ClientSession, 'post') as mock_post:
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json.return_value = {"response": "test", "done": True}
                mock_post.return_value.__aenter__.return_value = mock_response
                
                await provider.execute("llm/generate", {"prompt": "Test"})
                
                # Initialize should have been called due to lazy initialization
                mock_init.assert_called_once()
        
        await provider.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])