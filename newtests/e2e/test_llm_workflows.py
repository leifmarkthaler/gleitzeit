"""
End-to-end tests for LLM workflows

Tests cover:
- Complete LLM workflow execution
- Vision workflows
- Parallel LLM tasks
- Complex dependencies
- Real-world scenarios
- Error recovery

Related components:
- Full Gleitzeit stack
- Ollama integration
- Workflow YAML loading
"""

import pytest
import asyncio
import yaml
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock, patch

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_dict
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.core.protocol import ProtocolSpec


@pytest.mark.e2e
@pytest.mark.ollama
class TestLLMWorkflows:
    """End-to-end tests for LLM workflows"""
    
    @pytest.fixture
    async def mock_ollama_hub(self):
        """Create mock Ollama hub"""
        hub = AsyncMock(spec=OllamaHub)
        hub.ensure_started = AsyncMock(return_value=True)
        hub.health_check = AsyncMock(return_value=True)
        hub.base_url = "http://localhost:11434"
        
        # Mock session with proper response
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "response": "This is a mock LLM response",
            "model": "llama3.2",
            "done": True
        })
        mock_response.raise_for_status = Mock()
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        hub.session = mock_session
        yield hub
        await hub.cleanup()
    
    @pytest.fixture
    async def execution_engine_with_ollama(self, mock_ollama_hub):
        """Create execution engine with Ollama provider"""
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            max_concurrent_tasks=3
        )
        
        # Register LLM protocol with methods
        from gleitzeit.protocols import LLM_PROTOCOL_V1
        engine.registry.register_protocol(LLM_PROTOCOL_V1)
        
        # Create and register Ollama provider
        provider = OllamaProvider(
            provider_id="ollama_test",
            hub=mock_ollama_hub
        )
        await provider.initialize()
        
        # Make sure the provider health check works
        health = await provider.health_check()
        assert health is True, f"Provider health check failed: {health}"
        
        engine.registry.register_provider("ollama_test", "llm/v1", provider)
        
        yield engine
        await engine.stop()
    
    @pytest.mark.asyncio
    async def test_simple_llm_workflow(self, execution_engine_with_ollama):
        """Test simple LLM workflow execution"""
        workflow_dict = {
            "name": "Simple LLM Test",
            "tasks": [
                {
                    "id": "greeting",
                    "name": "Generate Greeting",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Say hello in a friendly way"}
                        ]
                    }
                }
            ]
        }
        
        workflow = load_workflow_from_dict(workflow_dict)
        
        # Execute workflow
        await execution_engine_with_ollama.submit_workflow(workflow)
        await execution_engine_with_ollama._execute_workflow(workflow)
        
        # Check completion
        task = workflow.tasks[0]
        assert task.status.value == "completed"
        
        # Check result
        result = execution_engine_with_ollama.task_results.get("greeting")
        assert result is not None
        assert "response" in result.result
    
    @pytest.mark.asyncio
    async def test_dependent_llm_workflow(self, execution_engine_with_ollama):
        """Test LLM workflow with task dependencies"""
        workflow_dict = {
            "name": "Dependent LLM Workflow",
            "tasks": [
                {
                    "id": "story_start",
                    "name": "Start Story",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Start a short story about a robot"}
                        ]
                    }
                },
                {
                    "id": "story_continue",
                    "name": "Continue Story",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Continue the story: ${story_start.response}"}
                        ]
                    },
                    "dependencies": ["story_start"]
                },
                {
                    "id": "story_end",
                    "name": "End Story",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "End the story: ${story_continue.response}"}
                        ]
                    },
                    "dependencies": ["story_continue"]
                }
            ]
        }
        
        workflow = load_workflow_from_dict(workflow_dict)
        
        # Execute workflow
        await execution_engine_with_ollama.submit_workflow(workflow)
        await execution_engine_with_ollama._execute_workflow(workflow)
        
        # All tasks should complete in order
        assert workflow.tasks[0].status.value == "completed"
        assert workflow.tasks[1].status.value == "completed"
        assert workflow.tasks[2].status.value == "completed"
        
        # Check execution order
        assert workflow.tasks[0].completed_at < workflow.tasks[1].started_at
        assert workflow.tasks[1].completed_at < workflow.tasks[2].started_at
    
    @pytest.mark.asyncio
    async def test_parallel_llm_workflow(self, execution_engine_with_ollama):
        """Test parallel LLM task execution"""
        workflow_dict = {
            "name": "Parallel LLM Workflow",
            "tasks": [
                {
                    "id": f"analysis_{i}",
                    "name": f"Analysis Task {i}",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": f"Analyze topic {i}"}
                        ]
                    }
                }
                for i in range(3)
            ]
        }
        
        workflow = load_workflow_from_dict(workflow_dict)
        
        # Execute workflow
        await execution_engine_with_ollama.submit_workflow(workflow)
        await execution_engine_with_ollama._execute_workflow(workflow)
        
        # All tasks should complete
        for task in workflow.tasks:
            assert task.status.value == "completed"
        
        # Tasks should have overlapping execution times (parallel)
        # At least some tasks should start before others complete
        start_times = [t.started_at for t in workflow.tasks if t.started_at]
        end_times = [t.completed_at for t in workflow.tasks if t.completed_at]
        
        if len(start_times) > 1 and len(end_times) > 1:
            # Check for overlap
            latest_start = max(start_times)
            earliest_end = min(end_times)
            assert latest_start <= earliest_end  # Some overlap
    
    @pytest.mark.asyncio
    async def test_vision_workflow(self, execution_engine_with_ollama):
        """Test vision analysis workflow"""
        # Mock vision response
        mock_hub = execution_engine_with_ollama.registry.provider_instances["ollama_test"].hub
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "response": "I see an image with various colors and shapes",
            "model": "llava",
            "done": True
        })
        mock_response.raise_for_status = Mock()
        mock_hub.session.post.return_value.__aenter__.return_value = mock_response
        
        workflow_dict = {
            "name": "Vision Analysis",
            "tasks": [
                {
                    "id": "analyze_image",
                    "name": "Analyze Image",
                    "protocol": "llm/v1",
                    "method": "vision",
                    "params": {
                        "model": "llava",
                        "image_path": "/tmp/test_image.png",
                        "messages": [
                            {"role": "user", "content": "Describe this image"}
                        ]
                    }
                }
            ]
        }
        
        workflow = load_workflow_from_dict(workflow_dict)
        
        # Execute workflow
        await execution_engine_with_ollama.submit_workflow(workflow)
        await execution_engine_with_ollama._execute_workflow(workflow)
        
        # Check completion
        assert workflow.tasks[0].status.value == "completed"
        
        # Check vision endpoint was called
        mock_hub.session.post.assert_called()
        call_args = mock_hub.session.post.call_args
        assert "vision" in str(call_args) or "api/generate" in str(call_args)
    
    @pytest.mark.asyncio
    async def test_complex_analysis_workflow(self, execution_engine_with_ollama):
        """Test complex multi-stage analysis workflow"""
        workflow_dict = {
            "name": "Complex Analysis",
            "tasks": [
                {
                    "id": "data_analysis",
                    "name": "Analyze Data",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Analyze this dataset: [1,2,3,4,5]"}
                        ]
                    }
                },
                {
                    "id": "pattern_detection",
                    "name": "Detect Patterns",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Find patterns in: ${data_analysis.response}"}
                        ]
                    },
                    "dependencies": ["data_analysis"]
                },
                {
                    "id": "summary",
                    "name": "Generate Summary",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Summarize findings: ${pattern_detection.response}"}
                        ]
                    },
                    "dependencies": ["pattern_detection"]
                },
                {
                    "id": "recommendations",
                    "name": "Make Recommendations",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Based on ${summary.response}, what do you recommend?"}
                        ]
                    },
                    "dependencies": ["summary"]
                }
            ]
        }
        
        workflow = load_workflow_from_dict(workflow_dict)
        
        # Execute workflow
        await execution_engine_with_ollama.submit_workflow(workflow)
        await execution_engine_with_ollama._execute_workflow(workflow)
        
        # All tasks should complete
        for task in workflow.tasks:
            assert task.status.value == "completed"
        
        # Check sequential execution
        for i in range(len(workflow.tasks) - 1):
            assert workflow.tasks[i].completed_at < workflow.tasks[i+1].started_at
    
    @pytest.mark.asyncio
    async def test_workflow_with_retries(self, execution_engine_with_ollama):
        """Test workflow with retry on failure"""
        # Make provider fail first time
        call_count = 0
        
        async def flaky_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_response = AsyncMock()
            if call_count == 1:
                # First call fails
                mock_response.raise_for_status.side_effect = Exception("Connection error")
            else:
                # Subsequent calls succeed
                mock_response.json = AsyncMock(return_value={
                    "response": "Success after retry",
                    "model": "llama3.2",
                    "done": True
                })
                mock_response.raise_for_status = Mock()
            
            return mock_response
        
        mock_hub = execution_engine_with_ollama.registry.provider_instances["ollama_test"].hub
        mock_hub.session.post.return_value.__aenter__.side_effect = flaky_response
        
        workflow_dict = {
            "name": "Retry Workflow",
            "tasks": [
                {
                    "id": "retry_task",
                    "name": "Task with Retry",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Test retry"}
                        ]
                    },
                    "max_retries": 3
                }
            ]
        }
        
        workflow = load_workflow_from_dict(workflow_dict)
        
        # Execute workflow
        await execution_engine_with_ollama.submit_workflow(workflow)
        await execution_engine_with_ollama._execute_workflow(workflow)
        
        # Task should eventually succeed
        assert workflow.tasks[0].status.value == "completed"
        assert workflow.tasks[0].attempt_count > 1
    
    @pytest.mark.asyncio
    async def test_workflow_timeout_handling(self, execution_engine_with_ollama):
        """Test workflow handles task timeouts"""
        # Make provider slow
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than timeout
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"response": "Too late"})
            return mock_response
        
        mock_hub = execution_engine_with_ollama.registry.provider_instances["ollama_test"].hub
        mock_hub.session.post.return_value.__aenter__.side_effect = slow_response
        
        workflow_dict = {
            "name": "Timeout Workflow",
            "tasks": [
                {
                    "id": "timeout_task",
                    "name": "Task with Timeout",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Test"}]
                    },
                    "timeout": 1  # 1 second timeout
                }
            ]
        }
        
        workflow = load_workflow_from_dict(workflow_dict)
        
        # Execute workflow with timeout
        try:
            await asyncio.wait_for(
                execution_engine_with_ollama.submit_workflow(workflow),
                timeout=2
            )
            await asyncio.wait_for(
                execution_engine_with_ollama._execute_workflow(workflow),
                timeout=2
            )
        except asyncio.TimeoutError:
            pass
        
        # Task should have failed or timed out
        task = workflow.tasks[0]
        assert task.status.value in ["failed", "pending"]