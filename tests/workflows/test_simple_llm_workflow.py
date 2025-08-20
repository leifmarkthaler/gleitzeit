"""Tests for simple_llm_workflow.yaml"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import yaml

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_dict
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter


class TestSimpleLLMWorkflow:
    """Test simple LLM workflow execution"""
    
    @pytest.fixture
    def workflow_path(self):
        """Path to workflow file"""
        return Path("examples/simple_llm_workflow.yaml")
    
    @pytest.fixture
    def workflow_content(self, workflow_path):
        """Load workflow content"""
        with open(workflow_path) as f:
            return yaml.safe_load(f)
    
    @pytest.fixture
    async def mock_ollama_provider(self):
        """Create mock Ollama provider"""
        provider = Mock()
        provider.provider_id = "ollama"
        provider.protocol_id = "llm/v1"
        provider.handle_request = AsyncMock(side_effect=[
            {"response": "Welcome to our workflow system! We're thrilled to have you aboard.", "provider_id": "ollama"},
            {"response": "A workflow orchestration system automates and manages complex tasks by coordinating multiple services. It's useful for ensuring reliable execution and handling dependencies between tasks.", "provider_id": "ollama"}
        ])
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_registry(self, mock_ollama_provider):
        """Create mock registry with provider"""
        registry = Mock(spec=ProtocolProviderRegistry)
        registry.get_provider_for_method = AsyncMock(return_value=mock_ollama_provider)
        return registry
    
    @pytest.fixture
    async def mock_persistence(self):
        """Create mock persistence"""
        persistence = Mock(spec=UnifiedPersistenceAdapter)
        persistence.save_workflow = AsyncMock()
        persistence.save_task = AsyncMock()
        persistence.save_result = AsyncMock()
        persistence.get_workflow = AsyncMock()
        persistence.update_task_status = AsyncMock()
        return persistence
    
    
    @pytest.mark.asyncio
    async def test_workflow_structure(self, workflow_content):
        """Test workflow has correct structure"""
        assert workflow_content["name"] == "Simple LLM Workflow"
        assert len(workflow_content["tasks"]) == 2
        assert workflow_content["tasks"][0]["id"] == "greeting_task"
        assert workflow_content["tasks"][1]["id"] == "explanation_task"
        assert workflow_content["timeout"] == 60
    
    @pytest.mark.asyncio
    async def test_task_priorities(self, workflow_content):
        """Test tasks have correct priorities"""
        tasks = workflow_content["tasks"]
        assert tasks[0]["priority"] == 2
        assert tasks[1]["priority"] == 1
    
    @pytest.mark.asyncio
    async def test_workflow_execution(self, execution_engine, workflow_content, mock_ollama_provider):
        """Test workflow executes successfully"""
        # Load and submit workflow
        workflow = load_workflow_from_dict(workflow_content)
        await execution_engine.submit_workflow(workflow)
        workflow_id = workflow.id
        assert workflow_id.startswith("workflow-")
        
        # Simulate execution
        await asyncio.sleep(0.1)  # Allow async tasks to process
        
        # Verify provider was called for both tasks
        assert mock_ollama_provider.handle_request.call_count == 2
        
        # Check first task call
        first_call = mock_ollama_provider.handle_request.call_args_list[0]
        assert first_call[0][0] == "chat"  # method
        assert first_call[0][1]["model"] == "llama3.2"
        assert "greeting" in first_call[0][1]["messages"][0]["content"].lower()
        
        # Check second task call
        second_call = mock_ollama_provider.handle_request.call_args_list[1]
        assert second_call[0][0] == "chat"
        assert "workflow orchestration" in second_call[0][1]["messages"][0]["content"].lower()
    
    @pytest.mark.asyncio
    async def test_parallel_execution(self, execution_engine, workflow_content):
        """Test that independent tasks can execute in parallel"""
        # Both tasks have no dependencies, so should execute in parallel
        start_times = []
        
        async def track_execution_time(*args, **kwargs):
            start_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.1)  # Simulate work
            return {"response": "test", "provider_id": "test"}
        
        execution_engine.registry.get_provider_for_method.return_value.handle_request = track_execution_time
        
        workflow = load_workflow_from_dict(workflow_content)
        await execution_engine.submit_workflow(workflow)
        workflow_id = workflow.id
        await asyncio.sleep(0.3)  # Wait for execution
        
        # If parallel, start times should be very close
        if len(start_times) == 2:
            time_diff = abs(start_times[1] - start_times[0])
            assert time_diff < 0.05  # Should start within 50ms of each other
    
    @pytest.mark.asyncio
    async def test_workflow_timeout(self, execution_engine, workflow_content):
        """Test workflow respects timeout setting"""
        # Make provider slow
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(70)  # Longer than 60s timeout
            return {"response": "too late"}
        
        execution_engine.registry.get_provider_for_method.return_value.handle_request = slow_response
        execution_engine.task_timeout = 1  # Override for faster test
        
        workflow = load_workflow_from_dict(workflow_content)
        await execution_engine.submit_workflow(workflow)
        workflow_id = workflow.id
        
        # Should timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                execution_engine.wait_for_completion(workflow_id),
                timeout=2
            )
    
    @pytest.mark.asyncio
    async def test_workflow_validation(self, workflow_content):
        """Test workflow validation"""
        # Should validate successfully
        workflow = load_workflow_from_dict(workflow_content)
        assert workflow is not None
        assert workflow.name == "Simple LLM Workflow"
        
        # Test invalid workflow
        invalid_workflow = workflow_content.copy()
        del invalid_workflow["tasks"]
        
        with pytest.raises(Exception):  # Will raise some exception for invalid workflow
            load_workflow_from_dict(invalid_workflow)
    
    @pytest.mark.asyncio
    async def test_result_storage(self, execution_engine, workflow_content, mock_persistence):
        """Test results are properly stored"""
        workflow = load_workflow_from_dict(workflow_content)
        await execution_engine.submit_workflow(workflow)
        workflow_id = workflow.id
        await asyncio.sleep(0.1)
        
        # Verify results were saved
        assert mock_persistence.save_result.called
        
        # Check result format
        result_calls = mock_persistence.save_result.call_args_list
        for call in result_calls:
            task_id, result = call[0]
            assert task_id in ["greeting_task", "explanation_task"]
            assert "response" in result
            assert "provider_id" in result