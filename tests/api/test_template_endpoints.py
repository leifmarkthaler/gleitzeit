"""
Tests for workflow template endpoints
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch
from gleitzeit.core import TaskResult


class TestTemplateExecution:
    """Test template execution endpoints"""
    
    @pytest.mark.asyncio
    async def test_execute_research_template(self, async_client, mock_execution_engine, mock_template_result):
        """Test executing research template"""
        # Mock template execution
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = mock_template_result
        result.error = None
        
        # Set up the mock to return the result for the correct task ID
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"template_test1234": result}
            
            response = await async_client.post("/templates/research", json={
                "topic": "quantum computing",
                "depth": "deep",
                "max_steps": 5
            })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["template_type"] == "research"
        assert data["topic"] == "test topic"
        assert data["status"] == "completed"
        assert data["steps_planned"] == 5
        assert data["success"] is True
        assert "Research Report" in data["report"]
    
    @pytest.mark.asyncio
    async def test_execute_code_template(self, async_client, mock_execution_engine):
        """Test executing code generation template"""
        # Mock code template result
        code_result = {
            "template_type": "code",
            "workflow_id": "template_code_12345",
            "task": "Create calculator",
            "language": "python",
            "status": "completed",
            "steps_planned": 5,
            "execution_time": 89.5,
            "code": "class Calculator:\n    def add(self, a, b):\n        return a + b",
            "review": "Code looks good with proper structure",
            "documentation": "# Calculator Class\n\nSimple calculator implementation",
            "test_result": {"output": "All tests passed"},
            "success": True
        }
        
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = code_result
        
        # Set up the mock to return the result for the correct task ID
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"template_test1234": result}
            
            response = await async_client.post("/templates/code", json={
                "task": "Create a calculator class",
                "language": "python"
            })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["template_type"] == "code"
        assert data["language"] == "python"
        assert "class Calculator" in data["code"]
        assert data["success"] is True
    
    @pytest.mark.asyncio
    async def test_execute_analyze_template(self, async_client, mock_execution_engine):
        """Test executing analysis template"""
        analysis_result = {
            "template_type": "analysis",
            "workflow_id": "template_analysis_12345",
            "status": "completed",
            "execution_time": 23.4,
            "analysis": "The content shows three main themes...",
            "success": True
        }
        
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = analysis_result
        
        # Set up the mock to return the result for the correct task ID
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"template_test1234": result}
            
            response = await async_client.post("/templates/analyze", json={
                "content": "Long document content here...",
                "question": "What are the main themes?"
            })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["template_type"] == "analysis"
        assert "three main themes" in data["analysis"]
    
    @pytest.mark.asyncio
    async def test_execute_chat_template(self, async_client, mock_execution_engine):
        """Test executing chat template"""
        chat_result = {
            "template_type": "chat",
            "workflow_id": "template_chat_12345",
            "session_id": "session_123",
            "status": "completed",
            "execution_time": 5.6,
            "response": "Hello! How can I help you today?",
            "success": True
        }
        
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = chat_result
        
        # Set up the mock to return the result for the correct task ID
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"template_test1234": result}
            
            response = await async_client.post("/templates/chat", json={
                "message": "Hello!",
                "session_id": "session_123"
            })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["template_type"] == "chat"
        assert data["session_id"] == "session_123"
        assert "Hello" in data["response"]
    
    @pytest.mark.asyncio
    async def test_unknown_template_type(self, async_client):
        """Test executing unknown template type"""
        response = await async_client.post("/templates/unknown", json={
            "param": "value"
        })
        
        assert response.status_code == 400
        assert "Unknown template type" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_template_execution_failure(self, async_client, mock_execution_engine):
        """Test template execution failure"""
        result = MagicMock(spec=TaskResult)
        result.status = "failed"
        result.result = None
        result.error = "Template execution failed"
        
        # Set up the mock to return the result for the correct task ID
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"template_test1234": result}
            
            response = await async_client.post("/templates/research", json={
                "topic": "test topic"
            })
        
        assert response.status_code == 500
        assert "Template execution failed" in response.json()["detail"]


class TestTemplateParameters:
    """Test template parameter handling"""
    
    @pytest.mark.asyncio
    async def test_research_template_parameters(self, async_client, mock_execution_engine):
        """Test research template with various parameters"""
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = {"template_type": "research", "success": True}
        
        # Set up with correct task ID pattern
        
        # Test different depth levels
        for depth in ["shallow", "medium", "deep"]:
            with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
                mock_uuid.return_value.hex = "test1234" * 4
                mock_execution_engine.task_results = {"template_test1234": result}
                
                response = await async_client.post("/templates/research", json={
                    "topic": "AI ethics",
                    "depth": depth,
                    "max_steps": 3
                })
            
            assert response.status_code == 200
        
        # Test max_steps range
        for max_steps in [1, 5, 10]:
            with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
                mock_uuid.return_value.hex = "test1234" * 4
                mock_execution_engine.task_results = {"template_test1234": result}
                
                response = await async_client.post("/templates/research", json={
                    "topic": "AI ethics",
                    "max_steps": max_steps
                })
            
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_code_template_languages(self, async_client, mock_execution_engine):
        """Test code template with different languages"""
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = {"template_type": "code", "success": True}
        
        # Set up with correct task ID pattern
        
        languages = ["python", "javascript", "typescript", "java", "go", "rust"]
        
        for language in languages:
            with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
                mock_uuid.return_value.hex = "test1234" * 4
                mock_execution_engine.task_results = {"template_test1234": result}
                
                response = await async_client.post("/templates/code", json={
                    "task": "Create a function",
                    "language": language
                })
            
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_analyze_template_optional_question(self, async_client, mock_execution_engine):
        """Test analysis template with and without question"""
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = {"template_type": "analysis", "success": True}
        
        # Set up with correct task ID pattern
        
        # With question
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"template_test1234": result}
            
            response = await async_client.post("/templates/analyze", json={
                "content": "Document content",
                "question": "What is the summary?"
            })
        
        assert response.status_code == 200
        
        # Without question (should use default)
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test5678" * 4
            mock_execution_engine.task_results = {"template_test5678": result}
            
            response = await async_client.post("/templates/analyze", json={
                "content": "Document content"
            })
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_template_missing_required_params(self, async_client):
        """Test templates with missing required parameters"""
        # Research without topic
        response = await async_client.post("/templates/research", json={
            "depth": "medium"
        })
        assert response.status_code in [422, 500]  # May fail at validation or execution
        
        # Code without task
        response = await async_client.post("/templates/code", json={
            "language": "python"
        })
        assert response.status_code in [422, 500]
        
        # Analyze without content
        response = await async_client.post("/templates/analyze", json={
            "question": "What is this?"
        })
        assert response.status_code in [422, 500]
        
        # Chat without message
        response = await async_client.post("/templates/chat", json={
            "session_id": "123"
        })
        assert response.status_code in [422, 500]


class TestTemplateWorkflowGeneration:
    """Test that templates generate proper workflows"""
    
    @pytest.mark.asyncio
    async def test_template_submits_task(self, async_client, mock_execution_engine):
        """Test that template execution submits task to engine"""
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = {"template_type": "research", "success": True}
        
        # Set up the mock to return the result for the correct task ID
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            mock_execution_engine.task_results = {"template_test1234": result}
            
            response = await async_client.post("/templates/research", json={
                "topic": "test"
            })
        
        assert response.status_code == 200
        
        # Verify task was submitted
        await asyncio.sleep(0.1)
        mock_execution_engine.submit_task.assert_called()
        mock_execution_engine.start.assert_called()
    
    @pytest.mark.asyncio
    async def test_template_without_engine(self, async_client):
        """Test template execution when engine not initialized"""
        from gleitzeit.api.main import app_state
        
        original_engine = app_state.execution_engine
        app_state.execution_engine = None
        
        response = await async_client.post("/templates/research", json={
            "topic": "test"
        })
        
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        app_state.execution_engine = original_engine