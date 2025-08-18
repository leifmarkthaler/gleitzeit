"""
Tests for convenience endpoints (Python execution, chat, batch)
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from gleitzeit.core import TaskResult



class TestChatEndpoint:
    """Test LLM chat endpoint"""
    
    @pytest.mark.asyncio
    async def test_chat_basic(self, async_client, mock_execution_engine):
        """Test basic chat interaction"""
        # Mock chat response
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = {"response": "Hello! I'm an AI assistant. How can I help you today?"}
        result.error = None
        
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"chat_test1234": result}
            
            response = await async_client.post("/chat", json={
                "message": "Hello, how are you?",
                "model": "llama3.2:latest",
                "temperature": 0.7
            })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "success"
        assert "Hello" in data["response"]
        assert data["model"] == "llama3.2:latest"
        assert data["session_id"] is None
    
    @pytest.mark.asyncio
    async def test_chat_with_session(self, async_client, mock_execution_engine):
        """Test chat with session ID"""
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = {"response": "Continuing our conversation..."}
        result.error = None
        
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"chat_test1234": result}
            
            response = await async_client.post("/chat", json={
                "message": "Remember what we talked about?",
                "model": "llama3.2:latest",
                "temperature": 0.5,
                "session_id": "user_session_123"
            })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == "user_session_123"
    
    @pytest.mark.asyncio
    async def test_chat_different_models(self, async_client, mock_execution_engine):
        """Test chat with different models"""
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = {"response": "Response from different model"}
        
        models = ["llama3.2:latest", "mistral:latest", "codellama:latest"]
        
        for model in models:
            with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
                mock_uuid.return_value.hex = "test1234" * 4
                mock_execution_engine.task_results = {"chat_test1234": result}
                
                response = await async_client.post("/chat", json={
                    "message": "Test message",
                    "model": model,
                    "temperature": 0.7
                })
            
            assert response.status_code == 200
            assert response.json()["model"] == model
    
    @pytest.mark.asyncio
    async def test_chat_failure(self, async_client, mock_execution_engine):
        """Test chat when LLM fails"""
        result = MagicMock(spec=TaskResult)
        result.status = "failed"
        result.result = None
        result.error = "Model not available"
        
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"chat_test1234": result}
            
            response = await async_client.post("/chat", json={
                "message": "Hello",
                "model": "nonexistent:latest"
            })
        
        assert response.status_code == 500
        assert "Model not available" in response.json()["detail"]


class TestBatchProcessing:
    """Test batch processing endpoint"""
    
    @pytest.mark.asyncio
    async def test_batch_process_files(self, async_client, mock_batch_processor, mock_batch_result):
        """Test batch processing files"""
        mock_batch_processor.process_batch.return_value = mock_batch_result
        
        response = await async_client.post("/batch", json={
            "directory": "/tmp/test",
            "pattern": "*.txt",
            "prompt": "Summarize this file",
            "model": "llama3.2:latest",
            "max_concurrent": 5
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["batch_id"] == "batch_12345"
        assert data["total_files"] == 10
        assert data["successful"] == 9
        assert data["failed"] == 1
        assert data["processing_time"] == 45.67
        assert "file1.txt" in data["results"]
    
    @pytest.mark.asyncio
    async def test_batch_with_custom_pattern(self, async_client, mock_batch_processor, mock_batch_result):
        """Test batch processing with custom file pattern"""
        mock_batch_processor.process_batch.return_value = mock_batch_result
        
        response = await async_client.post("/batch", json={
            "directory": "/docs",
            "pattern": "*.md",
            "prompt": "Extract key points",
            "model": "llama3.2:latest"
        })
        
        assert response.status_code == 200
        
        # Verify batch processor was called with correct params
        mock_batch_processor.process_batch.assert_called_once()
        call_args = mock_batch_processor.process_batch.call_args[1]
        assert call_args["directory"] == "/docs"
        assert call_args["pattern"] == "*.md"
    
    @pytest.mark.asyncio
    async def test_batch_different_methods(self, async_client, mock_batch_processor, mock_batch_result):
        """Test batch processing with different methods"""
        mock_batch_processor.process_batch.return_value = mock_batch_result
        
        methods = ["llm/chat", "llm/vision"]
        
        for method in methods:
            response = await async_client.post("/batch", json={
                "directory": "/images",
                "pattern": "*.png",
                "method": method,
                "prompt": "Describe this image",
                "model": "llava:latest"
            })
            
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_batch_processing_error(self, async_client, mock_batch_processor):
        """Test batch processing error handling"""
        mock_batch_processor.process_batch.side_effect = Exception("Directory not found")
        
        response = await async_client.post("/batch", json={
            "directory": "/nonexistent",
            "pattern": "*",
            "prompt": "Process this"
        })
        
        assert response.status_code == 500
        assert "Directory not found" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_batch_without_processor(self, async_client):
        """Test batch processing when processor not initialized"""
        from gleitzeit.api.main import app_state
        
        original_processor = app_state.batch_processor
        app_state.batch_processor = None
        
        response = await async_client.post("/batch", json={
            "directory": "/tmp",
            "pattern": "*",
            "prompt": "Process"
        })
        
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        app_state.batch_processor = original_processor
    
    @pytest.mark.asyncio
    async def test_batch_concurrency_limits(self, async_client, mock_batch_processor, mock_batch_result):
        """Test batch processing with different concurrency limits"""
        mock_batch_processor.process_batch.return_value = mock_batch_result
        
        for max_concurrent in [1, 5, 10, 20]:
            response = await async_client.post("/batch", json={
                "directory": "/tmp",
                "pattern": "*",
                "prompt": "Process",
                "max_concurrent": max_concurrent
            })
            
            assert response.status_code == 200


class TestConvenienceEndpointValidation:
    """Test validation for convenience endpoints"""
    
    
    @pytest.mark.asyncio
    async def test_chat_empty_message(self, async_client):
        """Test chat with empty message"""
        response = await async_client.post("/chat", json={
            "message": "",
            "model": "llama3.2:latest"
        })
        
        # Should accept empty message
        assert response.status_code in [200, 500]
    
    @pytest.mark.asyncio
    async def test_batch_invalid_directory(self, async_client, mock_batch_processor):
        """Test batch processing with invalid directory"""
        mock_batch_processor.process_batch.side_effect = Exception("Invalid directory")
        
        response = await async_client.post("/batch", json={
            "directory": "",
            "pattern": "*",
            "prompt": "Process"
        })
        
        assert response.status_code in [422, 500]
    
    @pytest.mark.asyncio
    async def test_chat_invalid_temperature(self, async_client):
        """Test chat with invalid temperature value"""
        response = await async_client.post("/chat", json={
            "message": "Hello",
            "model": "llama3.2:latest",
            "temperature": 2.5  # Too high
        })
        
        # Should accept (provider will validate)
        assert response.status_code in [200, 500]