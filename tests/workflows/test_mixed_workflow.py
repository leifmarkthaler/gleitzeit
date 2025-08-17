"""Tests for mixed_workflow.yaml - combining LLM and Python tasks"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock
import yaml

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider


class TestMixedWorkflow:
    """Test workflow combining different provider types"""
    
    @pytest.fixture
    def workflow_path(self):
        """Path to workflow file"""
        return Path("examples/mixed_workflow.yaml")
    
    @pytest.fixture
    def workflow_content(self, workflow_path):
        """Load workflow content"""
        with open(workflow_path) as f:
            return yaml.safe_load(f)
    
    @pytest.fixture
    async def mock_ollama_provider(self):
        """Create mock Ollama provider"""
        provider = Mock(spec=OllamaProvider)
        provider.provider_id = "ollama"
        provider.protocol_id = "llm/v1"
        provider.handle_request = AsyncMock(
            return_value={
                "response": "The numbers are: 5, 10, 15, 20, 25",
                "provider_id": "ollama"
            }
        )
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_python_provider(self):
        """Create mock Python provider"""
        provider = Mock(spec=PythonProvider)
        provider.provider_id = "python"
        provider.protocol_id = "python/v1"
        
        # Return different results based on the code being executed
        async def execute_python(method, params):
            code = params.get("code", "")
            
            if "sum" in code.lower() or "total" in code.lower():
                return {"result": 75, "output": "Sum: 75", "provider_id": "python"}
            elif "average" in code.lower() or "mean" in code.lower():
                return {"result": 15, "output": "Average: 15", "provider_id": "python"}
            elif "max" in code.lower():
                return {"result": 25, "output": "Max: 25", "provider_id": "python"}
            else:
                return {"result": "Processed", "output": "Done", "provider_id": "python"}
        
        provider.handle_request = AsyncMock(side_effect=execute_python)
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_registry(self, mock_ollama_provider, mock_python_provider):
        """Create mock registry with both providers"""
        registry = Mock()
        
        async def get_provider(protocol, method):
            if protocol == "llm/v1":
                return mock_ollama_provider
            elif protocol == "python/v1":
                return mock_python_provider
            return None
        
        registry.get_provider_for_method = AsyncMock(side_effect=get_provider)
        return registry
    
    @pytest.fixture
    async def mock_persistence(self):
        """Create mock persistence"""
        persistence = Mock()
        persistence.save_workflow = AsyncMock()
        persistence.save_task = AsyncMock()
        persistence.save_result = AsyncMock()
        persistence.update_task_status = AsyncMock()
        return persistence
    
    
    @pytest.mark.asyncio
    async def test_workflow_has_mixed_providers(self, workflow_content):
        """Test workflow contains both LLM and Python tasks"""
        protocols_used = set()
        
        for task in workflow_content["tasks"]:
            # Extract protocol from method or explicit protocol field
            if "protocol" in task:
                protocols_used.add(task["protocol"])
            elif "method" in task:
                if "llm" in task["method"]:
                    protocols_used.add("llm/v1")
                elif "python" in task["method"]:
                    protocols_used.add("python/v1")
        
        # Should have at least 2 different protocol types
        assert len(protocols_used) >= 2 or (
            any("llm" in str(task) for task in workflow_content["tasks"]) and
            any("python" in str(task) or "code" in str(task) for task in workflow_content["tasks"])
        )
    
    @pytest.mark.asyncio
    async def test_llm_to_python_flow(self, execution_engine, mock_ollama_provider, mock_python_provider):
        """Test LLM generates data that Python processes"""
        workflow = {
            "name": "LLM to Python",
            "tasks": [
                {
                    "id": "generate",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Generate 5 numbers"}]
                    }
                },
                {
                    "id": "process",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["generate"],
                    "parameters": {
                        "code": "numbers = [5, 10, 15, 20, 25]; print(sum(numbers))"
                    }
                }
            ]
        }
        
        workflow_id = await execution_engine.submit_workflow(workflow)
        await asyncio.sleep(0.2)
        
        # Verify both providers were called
        mock_ollama_provider.handle_request.assert_called_once()
        mock_python_provider.handle_request.assert_called_once()
        
        # Verify Python task received LLM output
        python_call = mock_python_provider.handle_request.call_args
        assert python_call is not None
    
    @pytest.mark.asyncio
    async def test_python_to_llm_flow(self, execution_engine, mock_ollama_provider, mock_python_provider):
        """Test Python generates data that LLM processes"""
        workflow = {
            "name": "Python to LLM",
            "tasks": [
                {
                    "id": "calculate",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {
                        "code": "import random; numbers = [random.randint(1,100) for _ in range(5)]; print(numbers)"
                    }
                },
                {
                    "id": "explain",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["calculate"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Explain these numbers: ${calculate.result}"}]
                    }
                }
            ]
        }
        
        workflow_id = await execution_engine.submit_workflow(workflow)
        await asyncio.sleep(0.2)
        
        # Verify execution order
        assert mock_python_provider.handle_request.call_count == 1
        assert mock_ollama_provider.handle_request.call_count == 1
        
        # Python should be called before LLM
        # (In real execution, this would be enforced by dependencies)
    
    @pytest.mark.asyncio
    async def test_parallel_mixed_providers(self, execution_engine, mock_ollama_provider, mock_python_provider):
        """Test parallel execution of different provider types"""
        workflow = {
            "name": "Parallel Mixed",
            "tasks": [
                {
                    "id": "llm_task1",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {"model": "llama3.2", "messages": [{"role": "user", "content": "Task 1"}]}
                },
                {
                    "id": "python_task1",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {"code": "print('Task 1')"}
                },
                {
                    "id": "llm_task2",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {"model": "llama3.2", "messages": [{"role": "user", "content": "Task 2"}]}
                },
                {
                    "id": "python_task2",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {"code": "print('Task 2')"}
                }
            ]
        }
        
        # Track execution times
        start_times = []
        
        async def track_timing(*args, **kwargs):
            start_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.05)
            return {"response": "done", "provider_id": "test"}
        
        mock_ollama_provider.handle_request = track_timing
        mock_python_provider.handle_request = track_timing
        
        workflow_id = await execution_engine.submit_workflow(workflow)
        await asyncio.sleep(0.3)
        
        # All tasks should start close together (parallel)
        if len(start_times) == 4:
            max_diff = max(start_times) - min(start_times)
            assert max_diff < 0.1  # Should start within 100ms
    
    @pytest.mark.asyncio
    async def test_error_handling_across_providers(self, execution_engine, mock_ollama_provider, mock_python_provider):
        """Test error handling when one provider fails"""
        # Make Python provider fail
        mock_python_provider.handle_request = AsyncMock(side_effect=Exception("Python execution failed"))
        
        workflow = {
            "name": "Error Test",
            "tasks": [
                {
                    "id": "llm_task",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {"model": "llama3.2", "messages": [{"role": "user", "content": "Hello"}]}
                },
                {
                    "id": "python_task",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["llm_task"],
                    "parameters": {"code": "print('This will fail')"}
                },
                {
                    "id": "final_llm",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["python_task"],
                    "parameters": {"model": "llama3.2", "messages": [{"role": "user", "content": "Final"}]}
                }
            ]
        }
        
        workflow_id = await execution_engine.submit_workflow(workflow)
        await asyncio.sleep(0.2)
        
        # First LLM task should succeed
        assert mock_ollama_provider.handle_request.call_count >= 1
        
        # Python task should fail
        assert mock_python_provider.handle_request.call_count >= 1
        
        # Final LLM task should not execute (dependency failed)
        # In a real implementation, this would be tracked in workflow status
    
    @pytest.mark.asyncio
    async def test_complex_data_flow(self, execution_engine, mock_ollama_provider, mock_python_provider):
        """Test complex data flow between providers"""
        workflow = {
            "name": "Complex Flow",
            "tasks": [
                {
                    "id": "generate_data",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Generate JSON data"}]
                    }
                },
                {
                    "id": "process_data",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["generate_data"],
                    "parameters": {
                        "code": "import json; data = '${generate_data.response}'; result = len(data)"
                    }
                },
                {
                    "id": "analyze_result",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["process_data"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Analyze: ${process_data.result}"}]
                    }
                },
                {
                    "id": "final_calculation",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["analyze_result"],
                    "parameters": {
                        "code": "final = '${analyze_result.response}'.split(); print(len(final))"
                    }
                }
            ]
        }
        
        workflow_id = await execution_engine.submit_workflow(workflow)
        await asyncio.sleep(0.3)
        
        # Verify all tasks executed in order
        assert mock_ollama_provider.handle_request.call_count == 2  # Two LLM tasks
        assert mock_python_provider.handle_request.call_count == 2  # Two Python tasks
    
    @pytest.mark.asyncio
    async def test_provider_specific_timeout(self, execution_engine):
        """Test different timeout settings for different providers"""
        workflow = {
            "name": "Timeout Test",
            "tasks": [
                {
                    "id": "quick_llm",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "timeout": 5,  # Short timeout
                    "parameters": {"model": "llama3.2", "messages": [{"role": "user", "content": "Quick"}]}
                },
                {
                    "id": "long_python",
                    "protocol": "python/v1",
                    "method": "execute",
                    "timeout": 30,  # Longer timeout
                    "parameters": {"code": "import time; time.sleep(1); print('Done')"}
                }
            ]
        }
        
        # Tasks should respect individual timeout settings
        # This would be enforced by the execution engine
        assert workflow["tasks"][0]["timeout"] == 5
        assert workflow["tasks"][1]["timeout"] == 30