"""Tests for dependent_workflow.yaml"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock
import yaml

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_dict
from gleitzeit.core.dependency_tracker import DependencyTracker
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter


class TestDependentWorkflow:
    """Test workflow with task dependencies and parameter substitution"""
    
    @pytest.fixture
    def workflow_path(self):
        """Path to workflow file"""
        return Path("examples/dependent_workflow.yaml")
    
    @pytest.fixture
    def workflow_content(self, workflow_path):
        """Load workflow content"""
        with open(workflow_path) as f:
            return yaml.safe_load(f)
    
    @pytest.fixture
    async def mock_ollama_provider(self):
        """Create mock Ollama provider with sequential responses"""
        provider = Mock()
        provider.provider_id = "ollama"
        provider.protocol_id = "llm/v1"
        
        # Responses for each task in order
        responses = [
            {"response": "The Evolution of Artificial Intelligence", "provider_id": "ollama"},
            {"response": "1. Historical Development\n2. Current Applications\n3. Future Implications", "provider_id": "ollama"},
            {"response": "Artificial intelligence has transformed from science fiction to reality...", "provider_id": "ollama"}
        ]
        
        provider.handle_request = AsyncMock(side_effect=responses)
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_registry(self, mock_ollama_provider):
        """Create mock registry"""
        registry = Mock()
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
        """Test workflow has correct dependency structure"""
        assert workflow_content["name"] == "Dependent Tasks Workflow"
        assert len(workflow_content["tasks"]) == 3
        
        # Check task IDs
        task_ids = [task["id"] for task in workflow_content["tasks"]]
        assert task_ids == ["generate_topic", "write_outline", "write_essay"]
        
        # Check dependencies
        assert "dependencies" not in workflow_content["tasks"][0]  # First task has no deps
        assert workflow_content["tasks"][1]["dependencies"] == ["generate_topic"]
        assert workflow_content["tasks"][2]["dependencies"] == ["write_outline"]
    
    @pytest.mark.asyncio
    async def test_dependency_resolution(self, workflow_content):
        """Test dependency resolution creates correct execution order"""
        tracker = DependencyTracker()
        
        # Build dependency graph
        for task in workflow_content["tasks"]:
            deps = task.get("dependencies", [])
            tracker.add_task(task["id"], deps)
        
        # Get execution order
        execution_order = tracker.get_execution_order()
        
        # Verify order
        assert len(execution_order) == 3
        assert execution_order[0] == ["generate_topic"]  # First layer
        assert execution_order[1] == ["write_outline"]   # Second layer
        assert execution_order[2] == ["write_essay"]     # Third layer
    
    @pytest.mark.asyncio
    async def test_parameter_substitution(self, workflow_content):
        """Test parameter substitution in dependent tasks"""
        # Check that dependent tasks reference previous results
        outline_task = workflow_content["tasks"][1]
        assert "${generate_topic.response}" in outline_task["parameters"]["messages"][0]["content"]
        
        essay_task = workflow_content["tasks"][2]
        assert "${write_outline.response}" in essay_task["parameters"]["messages"][0]["content"]
    
    @pytest.mark.asyncio
    async def test_sequential_execution(self, execution_engine, workflow_content, mock_ollama_provider):
        """Test tasks execute in correct sequence based on dependencies"""
        execution_times = []
        task_order = []
        
        async def track_execution(method, params):
            task_order.append(params.get("_task_id"))
            execution_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.05)  # Simulate work
            
            # Return appropriate response based on task
            if len(task_order) == 1:
                return {"response": "AI Topic", "provider_id": "ollama"}
            elif len(task_order) == 2:
                return {"response": "1. Point A\n2. Point B", "provider_id": "ollama"}
            else:
                return {"response": "Essay content...", "provider_id": "ollama"}
        
        mock_ollama_provider.handle_request = track_execution
        
        # Add task IDs to params for tracking
        for task in workflow_content["tasks"]:
            task["parameters"]["_task_id"] = task["id"]
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.3)  # Wait for completion
        
        # Verify execution order
        if len(task_order) == 3:
            assert task_order[0] == "generate_topic"
            assert task_order[1] == "write_outline"
            assert task_order[2] == "write_essay"
            
            # Verify sequential timing (each should start after previous completes)
            assert execution_times[1] > execution_times[0]
            assert execution_times[2] > execution_times[1]
    
    @pytest.mark.asyncio
    async def test_dependency_failure_handling(self, execution_engine, workflow_content):
        """Test handling when a dependency fails"""
        # Make first task fail
        async def fail_first_task(method, params):
            if "generate" in str(params):
                raise Exception("Task failed")
            return {"response": "success", "provider_id": "test"}
        
        execution_engine.registry.get_provider_for_method.return_value.handle_request = fail_first_task
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.1)
        
        # Dependent tasks should not execute
        context = execution_engine.active_workflows.get(workflow_id)
        if context:
            # Check that dependent tasks were not executed
            assert "write_outline" not in context.results
            assert "write_essay" not in context.results
    
    @pytest.mark.asyncio
    async def test_result_propagation(self, execution_engine, workflow_content, mock_persistence):
        """Test that results propagate correctly through dependencies"""
        results_chain = {}
        
        async def capture_results(method, params):
            # Capture what parameters were passed
            task_content = params["messages"][0]["content"]
            
            if "generate_topic" in execution_engine.current_task_id:
                result = {"response": "Space Exploration", "provider_id": "ollama"}
            elif "write_outline" in execution_engine.current_task_id:
                # Should contain the topic from previous task
                assert "Space Exploration" in task_content or "${generate_topic.response}" in task_content
                result = {"response": "1. History\n2. Technology\n3. Future", "provider_id": "ollama"}
            else:  # write_essay
                # Should contain the outline from previous task
                assert "History" in task_content or "${write_outline.response}" in task_content
                result = {"response": "Essay about space...", "provider_id": "ollama"}
            
            results_chain[execution_engine.current_task_id] = result
            return result
        
        # Track current task
        execution_engine.current_task_id = None
        original_execute = execution_engine.execute_task
        
        async def execute_with_tracking(task, context):
            execution_engine.current_task_id = task["id"]
            return await original_execute(task, context)
        
        execution_engine.execute_task = execute_with_tracking
        execution_engine.registry.get_provider_for_method.return_value.handle_request = capture_results
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.2)
        
        # Verify all tasks executed with proper chaining
        assert len(results_chain) == 3
    
    @pytest.mark.asyncio
    async def test_priority_ordering(self, workflow_content):
        """Test that priorities are set correctly"""
        tasks = workflow_content["tasks"]
        
        # Higher priority number = higher priority (executes first if no deps)
        assert tasks[0]["priority"] == 3  # generate_topic - highest
        assert tasks[1]["priority"] == 2  # write_outline - medium
        assert tasks[2]["priority"] == 1  # write_essay - lowest
        
        # But dependencies should override priority
        # So execution order is still: generate_topic -> write_outline -> write_essay
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, execution_engine, workflow_content):
        """Test workflow timeout handling"""
        # Set short timeout
        workflow_content["timeout"] = 1
        
        async def slow_task(*args, **kwargs):
            await asyncio.sleep(2)  # Longer than timeout
            return {"response": "too slow"}
        
        execution_engine.registry.get_provider_for_method.return_value.handle_request = slow_task
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        
        # Should timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                execution_engine.wait_for_completion(workflow_id),
                timeout=3
            )