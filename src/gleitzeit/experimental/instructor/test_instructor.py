"""
Tests for Instructor Provider integration
"""

import pytest
import asyncio
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from gleitzeit.experimental.instructor import InstructorProvider
from gleitzeit.experimental.instructor.models import SchemaDefinition, StructuredOutput
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError


class TestInstructorProvider:
    """Test suite for InstructorProvider"""
    
    @pytest.fixture
    async def provider(self):
        """Create a test provider instance"""
        provider = InstructorProvider(
            default_provider="openai",
            default_model="gpt-3.5-turbo",
            max_retries=2
        )
        # Mock instructor import
        provider.instructor = Mock()
        return provider
    
    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test provider initialization"""
        provider = InstructorProvider()
        assert provider.provider_id == "instructor"
        assert provider.protocol_id == "llm/structured"
        assert provider.default_provider == "openai"
        assert provider.max_retries == 3
    
    @pytest.mark.asyncio
    async def test_supported_methods(self, provider):
        """Test supported methods"""
        methods = provider.get_supported_methods()
        assert "llm/structured" in methods
        assert "llm/extract" in methods
        assert "llm/classify" in methods
        assert provider.can_handle("llm/structured")
        assert not provider.can_handle("llm/unsupported")
    
    @pytest.mark.asyncio
    async def test_health_check(self, provider):
        """Test health check"""
        # Mock the instructor import check
        with patch('builtins.__import__', side_effect=ImportError):
            assert await provider.health_check() == False
        
        # Mock successful import
        with patch('builtins.__import__'):
            assert await provider.health_check() == True
    
    @pytest.mark.asyncio
    async def test_schema_definition_to_pydantic(self):
        """Test schema conversion to Pydantic model"""
        schema = SchemaDefinition(
            name="TestModel",
            properties={
                "name": {"type": "string", "description": "Name field"},
                "age": {"type": "integer"},
                "active": {"type": "boolean"}
            },
            required=["name", "age"]
        )
        
        model = schema.to_pydantic_model()
        assert model.__name__ == "TestModel"
        
        # Test model instantiation
        instance = model(name="John", age=30, active=True)
        assert instance.name == "John"
        assert instance.age == 30
        assert instance.active == True
    
    @pytest.mark.asyncio
    async def test_structured_generate_success(self, provider):
        """Test successful structured generation"""
        # Mock client and response
        mock_response = Mock()
        mock_response.model_dump = Mock(return_value={
            "name": "John Doe",
            "age": 30,
            "email": "john@example.com"
        })
        
        mock_client = Mock()
        mock_client.chat.completions.create = Mock(return_value=mock_response)
        
        provider._get_client = AsyncMock(return_value=mock_client)
        
        params = {
            "schema": {
                "name": "User",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "email": {"type": "string"}
                }
            },
            "messages": [
                {"role": "user", "content": "John Doe, 30 years old, john@example.com"}
            ]
        }
        
        result = await provider._structured_generate(params)
        
        assert result["success"] == True
        assert result["data"]["name"] == "John Doe"
        assert result["data"]["age"] == 30
        assert result["provider"] == "openai"
    
    @pytest.mark.asyncio
    async def test_structured_generate_missing_schema(self, provider):
        """Test structured generation with missing schema"""
        params = {
            "messages": [{"role": "user", "content": "test"}]
        }
        
        with pytest.raises(InvalidParameterError, match="Schema is required"):
            await provider._structured_generate(params)
    
    @pytest.mark.asyncio
    async def test_structured_generate_missing_messages(self, provider):
        """Test structured generation with missing messages"""
        params = {
            "schema": {"name": "Test", "properties": {}}
        }
        
        with pytest.raises(InvalidParameterError, match="Messages are required"):
            await provider._structured_generate(params)
    
    @pytest.mark.asyncio
    async def test_extract_data(self, provider):
        """Test data extraction"""
        # Mock structured_generate
        provider._structured_generate = AsyncMock(return_value={
            "success": True,
            "data": {"product": "iPhone", "price": 999}
        })
        
        params = {
            "text": "The iPhone costs $999",
            "schema": {
                "name": "Product",
                "properties": {
                    "product": {"type": "string"},
                    "price": {"type": "number"}
                }
            }
        }
        
        result = await provider._extract_data(params)
        
        assert result["success"] == True
        assert result["data"]["product"] == "iPhone"
        
        # Verify structured_generate was called with correct messages
        call_args = provider._structured_generate.call_args[0][0]
        assert len(call_args["messages"]) == 2
        assert call_args["messages"][1]["content"] == "The iPhone costs $999"
    
    @pytest.mark.asyncio
    async def test_classify_text(self, provider):
        """Test text classification"""
        # Mock structured_generate
        provider._structured_generate = AsyncMock(return_value={
            "success": True,
            "data": {
                "category": "positive",
                "confidence": 0.95,
                "reasoning": "Positive sentiment detected"
            }
        })
        
        params = {
            "text": "This product is amazing!",
            "categories": ["positive", "negative", "neutral"]
        }
        
        result = await provider._classify_text(params)
        
        assert result["success"] == True
        assert result["data"]["category"] == "positive"
        
        # Verify the schema includes the categories
        call_args = provider._structured_generate.call_args[0][0]
        assert "positive" in call_args["messages"][0]["content"]
    
    @pytest.mark.asyncio
    async def test_classify_missing_text(self, provider):
        """Test classification with missing text"""
        params = {
            "categories": ["positive", "negative"]
        }
        
        with pytest.raises(InvalidParameterError, match="Text is required"):
            await provider._classify_text(params)
    
    @pytest.mark.asyncio
    async def test_execute_unsupported_method(self, provider):
        """Test execution of unsupported method"""
        with pytest.raises(InvalidParameterError, match="Unsupported method"):
            await provider.execute("llm/unsupported", {})
    
    @pytest.mark.asyncio
    async def test_create_client_openai(self, provider):
        """Test OpenAI client creation"""
        mock_instructor = Mock()
        mock_instructor.from_openai = Mock(return_value=Mock())
        
        with patch.dict('sys.modules', {'instructor': mock_instructor, 'openai': Mock()}):
            client = await provider._create_client("openai")
            assert client is not None
            mock_instructor.from_openai.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_client_anthropic(self, provider):
        """Test Anthropic client creation"""
        mock_instructor = Mock()
        mock_instructor.from_anthropic = Mock(return_value=Mock())
        
        with patch.dict('sys.modules', {'instructor': mock_instructor, 'anthropic': Mock()}):
            client = await provider._create_client("anthropic")
            assert client is not None
            mock_instructor.from_anthropic.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_client_unsupported(self, provider):
        """Test unsupported client creation"""
        with pytest.raises(InvalidParameterError, match="Unsupported provider"):
            await provider._create_client("unsupported_provider")
    
    @pytest.mark.asyncio
    async def test_convert_to_anthropic_format(self, provider):
        """Test message format conversion for Anthropic"""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        
        converted = provider._convert_to_anthropic_format(messages)
        
        # System message should be removed
        assert len(converted) == 2
        assert converted[0]["role"] == "user"
        assert converted[0]["content"] == "Hello"
        assert converted[1]["role"] == "assistant"
        assert converted[1]["content"] == "Hi there"
    
    @pytest.mark.asyncio 
    async def test_handle_request_delegation(self, provider):
        """Test that handle_request delegates to execute"""
        provider.execute = AsyncMock(return_value={"result": "test"})
        
        result = await provider.handle_request("llm/structured", {"test": "params"})
        
        assert result == {"result": "test"}
        provider.execute.assert_called_once_with("llm/structured", {"test": "params"})


class TestSchemaDefinition:
    """Test SchemaDefinition model"""
    
    def test_from_dict(self):
        """Test creating schema from dictionary"""
        data = {
            "name": "TestSchema",
            "properties": {
                "field1": {"type": "string"},
                "field2": {"type": "integer"}
            },
            "required": ["field1"],
            "description": "Test schema"
        }
        
        schema = SchemaDefinition.from_dict(data)
        assert schema.name == "TestSchema"
        assert "field1" in schema.properties
        assert schema.required == ["field1"]
        assert schema.description == "Test schema"
    
    def test_python_type_conversion(self):
        """Test JSON schema to Python type conversion"""
        schema = SchemaDefinition(
            name="Test",
            properties={
                "str_field": {"type": "string"},
                "int_field": {"type": "integer"},
                "float_field": {"type": "number"},
                "bool_field": {"type": "boolean"},
                "list_field": {"type": "array", "items": {"type": "string"}},
                "dict_field": {"type": "object"}
            }
        )
        
        model = schema.to_pydantic_model()
        
        # Test that the model can be instantiated with correct types
        instance = model(
            str_field="test",
            int_field=42,
            float_field=3.14,
            bool_field=True,
            list_field=["a", "b"],
            dict_field={"key": "value"}
        )
        
        assert instance.str_field == "test"
        assert instance.int_field == 42
        assert instance.float_field == 3.14
        assert instance.bool_field == True
        assert instance.list_field == ["a", "b"]
        assert instance.dict_field == {"key": "value"}


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])