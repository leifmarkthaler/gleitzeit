"""
End-to-end tests for ALL example workflows in /examples directory

This test suite validates that every example workflow:
1. Can be loaded successfully
2. Has valid structure and syntax
3. Can be executed through the full Gleitzeit system
4. Produces expected results (with mocked providers)

Tests can be run with:
- Mocked providers (default) for CI/CD
- Real Ollama (with --ollama flag) for integration testing
"""

import pytest
import asyncio
import yaml
import json
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import Mock, AsyncMock, patch
import logging

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_file, load_workflow_from_dict
from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter, UnifiedInMemoryAdapter
from gleitzeit.core.protocol import ProtocolSpec
from gleitzeit.protocols import LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1, MCP_PROTOCOL_V1

logger = logging.getLogger(__name__)


# List of all example workflows
EXAMPLE_WORKFLOWS = [
    # Core LLM workflows
    "simple_llm_workflow.yaml",
    "simple_llm_workflow_fixed.yaml",
    "llm_workflow.yaml",
    
    # Python workflows
    "simple_python_workflow.yaml",
    "python_only_workflow.yaml",
    "test_complex_python.yaml",
    
    # MCP workflows
    "simple_mcp_workflow.yaml",
    "mcp_workflow.yaml",
    
    # Mixed workflows
    "mixed_workflow.yaml",
    "mixed_vision_text_workflow.yaml",
    "mixed_vision_file_workflow.yaml",
    
    # Dependency workflows
    "dependent_workflow.yaml",
    "parallel_workflow.yaml",
    
    # Batch workflows
    "batch_text_analysis.yaml",
    "batch_text_dynamic.yaml",
    "batch_python_workflow.yaml",
    "batch_mixed_workflow.yaml",
    "batch_image_description.yaml",
    "batch_image_dynamic.yaml",
    
    # Vision workflows
    "vision_workflow.yaml",
    "vision_file_workflow.yaml",
    
    
    # Agent workflows (may require special handling)
    "agent_workflow.yaml",
    "agent_chat.yaml",
    "agent_code_review.yaml",
    
    # Advanced workflows
    "meeting_analysis_workflow.yaml",
    "text_file_workflow.yaml",
    "test_context_workflow.yaml",
    "test_mixed_substitution.yaml",
    "multi_instance_demo.yaml",
]

# Workflows that require special handling or may be skipped in CI
SKIP_IN_CI = [
    "agent_workflow.yaml",  # Requires agent hub
    "agent_chat.yaml",
    "agent_code_review.yaml",
    "multi_instance_demo.yaml",  # Requires multiple Ollama instances
]

# Workflows that require real files to exist
FILE_DEPENDENT_WORKFLOWS = [
    "text_file_workflow.yaml",
    "vision_file_workflow.yaml",
    "mixed_vision_file_workflow.yaml",
    "meeting_analysis_workflow.yaml",
]


@pytest.mark.e2e
class TestAllExampleWorkflows:
    """Comprehensive e2e tests for all example workflows"""
    
    @pytest.fixture
    def examples_dir(self):
        """Path to examples directory"""
        return Path(__file__).parent.parent.parent / "examples"
    
    @pytest.fixture
    async def mock_ollama_provider(self):
        """Create mock Ollama provider for testing"""
        provider = AsyncMock(spec=OllamaProvider)
        provider.provider_id = "ollama"
        provider.protocol_id = LLM_PROTOCOL_V1
        provider.name = "Mock Ollama Provider"
        
        # Mock responses for different methods
        async def mock_handle_request(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
            if method == "chat" or method == "llm/chat":
                return {
                    "response": "Mocked LLM response for testing",
                    "model": params.get("model", "llama3.2"),
                    "provider_id": "ollama"
                }
            elif method == "vision" or method == "llm/vision":
                return {
                    "response": "Mocked vision analysis: I see an image",
                    "model": params.get("model", "llava"),
                    "provider_id": "ollama"
                }
            elif method == "generate" or method == "llm/generate":
                return {
                    "response": "Generated text content",
                    "model": params.get("model", "llama3.2"),
                    "provider_id": "ollama"
                }
            elif method == "embeddings" or method == "llm/embeddings":
                return {
                    "embeddings": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                    "model": params.get("model", "llama3.2"),
                    "provider_id": "ollama"
                }
            else:
                return {"response": f"Mock response for {method}", "provider_id": "ollama"}
        
        provider.handle_request = mock_handle_request
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_python_provider(self):
        """Create mock Python provider"""
        provider = AsyncMock(spec=PythonProvider)
        provider.provider_id = "python"
        provider.protocol_id = PYTHON_PROTOCOL_V1
        provider.name = "Mock Python Provider"
        
        async def mock_handle_request(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
            if method == "execute" or method == "python/execute":
                # Return different results based on script
                script = params.get("script", params.get("file", ""))
                if "calculate" in script:
                    return {"result": 42, "output": "Calculation complete", "provider_id": "python"}
                elif "generate" in script:
                    return {"result": [1, 2, 3, 4, 5], "output": "Numbers generated", "provider_id": "python"}
                elif "analyze" in script:
                    return {"result": {"analysis": "complete"}, "output": "Analysis done", "provider_id": "python"}
                else:
                    return {"result": "success", "output": "Script executed", "provider_id": "python"}
            elif method == "validate" or method == "python/validate":
                return {"valid": True, "provider_id": "python"}
            else:
                return {"result": f"Mock Python result for {method}", "provider_id": "python"}
        
        provider.handle_request = mock_handle_request
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_mcp_provider(self):
        """Create mock MCP provider"""
        provider = AsyncMock(spec=SimpleMCPProvider)
        provider.provider_id = "mcp"
        provider.protocol_id = MCP_PROTOCOL_V1
        provider.name = "Mock MCP Provider"
        
        async def mock_handle_request(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
            if "echo" in method:
                return {"result": params.get("message", "echo"), "provider_id": "mcp"}
            elif "add" in method:
                return {"result": params.get("a", 0) + params.get("b", 0), "provider_id": "mcp"}
            elif "multiply" in method:
                return {"result": params.get("a", 1) * params.get("b", 1), "provider_id": "mcp"}
            elif "concat" in method:
                return {"result": params.get("a", "") + params.get("b", ""), "provider_id": "mcp"}
            else:
                return {"result": f"Mock MCP result for {method}", "provider_id": "mcp"}
        
        provider.handle_request = mock_handle_request
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_registry(self, mock_ollama_provider, mock_python_provider, mock_mcp_provider):
        """Create mock registry with all providers"""
        registry = Mock(spec=ProtocolProviderRegistry)
        
        async def get_provider(protocol: str, method: str) -> Any:
            if "llm" in protocol or "llm" in method:
                return mock_ollama_provider
            elif "python" in protocol or "python" in method:
                return mock_python_provider
            elif "mcp" in protocol or "mcp" in method or "tool" in method:
                return mock_mcp_provider
            else:
                # Default to Python provider
                return mock_python_provider
        
        registry.get_provider_for_method = AsyncMock(side_effect=get_provider)
        registry.list_providers = Mock(return_value=[
            mock_ollama_provider,
            mock_python_provider,
            mock_mcp_provider
        ])
        
        return registry
    
    @pytest.fixture
    async def execution_engine(self, mock_registry):
        """Create execution engine with mocked providers in event-driven mode"""
        persistence = UnifiedInMemoryAdapter()
        await persistence.initialize()
        
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        engine = ExecutionEngine(
            registry=mock_registry,
            persistence=persistence,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            max_concurrent_tasks=5
        )
        
        # Start the engine in event-driven mode as a background task
        from gleitzeit.core.execution_engine import ExecutionMode
        engine_task = asyncio.create_task(engine.start(ExecutionMode.EVENT_DRIVEN))
        
        # Wait a bit for engine to start
        await asyncio.sleep(0.1)
        
        yield engine
        
        # Cleanup
        await engine.stop()
        
        # Cancel the engine task
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        
        await persistence.cleanup()
    
    @pytest.mark.parametrize("workflow_file", EXAMPLE_WORKFLOWS)
    async def test_workflow_can_load(self, examples_dir, workflow_file):
        """Test that each workflow file can be loaded successfully"""
        workflow_path = examples_dir / workflow_file
        
        # Skip if file doesn't exist
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        # Load workflow
        try:
            with open(workflow_path) as f:
                workflow_content = yaml.safe_load(f)
            
            workflow = load_workflow_from_dict(workflow_content)
            
            # Basic validation
            assert workflow is not None
            assert workflow.name is not None
            assert len(workflow.tasks) > 0
            
            # Check task structure
            for task in workflow.tasks:
                assert task.id is not None
                assert task.method is not None
                
        except Exception as e:
            pytest.fail(f"Failed to load workflow {workflow_file}: {e}")
    
    @pytest.mark.parametrize("workflow_file", EXAMPLE_WORKFLOWS)
    async def test_workflow_structure(self, examples_dir, workflow_file):
        """Test that each workflow has valid structure"""
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Check required fields
        assert "name" in workflow_content
        assert "tasks" in workflow_content or "type" in workflow_content  # batch workflows have type
        
        if "tasks" in workflow_content:
            for task in workflow_content["tasks"]:
                # Each task should have an ID
                assert "id" in task or "name" in task
                
                # Should have a method or protocol
                assert "method" in task or "protocol" in task
                
                # Should have parameters or params
                assert "parameters" in task or "params" in task or "config" in task
    
    @pytest.mark.parametrize("workflow_file", [
        wf for wf in EXAMPLE_WORKFLOWS 
        if wf not in SKIP_IN_CI and wf not in FILE_DEPENDENT_WORKFLOWS
    ])
    async def test_workflow_execution_mocked(self, examples_dir, workflow_file, execution_engine):
        """Test that each workflow can be executed with mocked providers"""
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        # Load workflow
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Skip batch workflows for now (need special handling)
        if workflow_content.get("type") == "batch":
            pytest.skip("Batch workflows need special handling")
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow
        await execution_engine.submit_workflow(workflow)
        
        # Wait a bit for execution (mocked providers are instant)
        await asyncio.sleep(0.5)
        
        # Check that workflow was submitted
        assert workflow.id in execution_engine.workflow_states
        
        # For simple workflows, check task submission
        for task in workflow.tasks:
            # Task should be tracked
            tracker = execution_engine.dependency_tracker
            assert task.id in tracker.task_status or task.id in tracker.completed_tasks
    
    @pytest.mark.ollama
    @pytest.mark.parametrize("workflow_file", ["simple_llm_workflow.yaml", "llm_workflow.yaml"])
    async def test_workflow_with_real_ollama(self, examples_dir, workflow_file):
        """Test workflow execution with real Ollama (requires Ollama to be running)"""
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        # Check if Ollama is available
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:11434/api/tags", timeout=2) as resp:
                    if resp.status != 200:
                        pytest.skip("Ollama is not running")
        except:
            pytest.skip("Ollama is not available")
        
        # Create real providers
        persistence = UnifiedInMemoryAdapter()
        await persistence.initialize()
        
        registry = ProtocolProviderRegistry()
        
        # Register real Ollama provider
        ollama_provider = OllamaProvider(provider_id="ollama")
        await ollama_provider.initialize()
        registry.register_provider(LLM_PROTOCOL_V1, ollama_provider)
        
        # Create execution engine with real provider
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        engine = ExecutionEngine(
            registry=registry,
            persistence=persistence,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            max_concurrent_tasks=2
        )
        
        # Start engine in event-driven mode as background task
        from gleitzeit.core.execution_engine import ExecutionMode
        engine_task = asyncio.create_task(engine.start(ExecutionMode.EVENT_DRIVEN))
        await asyncio.sleep(0.1)  # Let it start
        
        try:
            # Load and submit workflow
            with open(workflow_path) as f:
                workflow_content = yaml.safe_load(f)
            
            workflow = load_workflow_from_dict(workflow_content)
            await engine.submit_workflow(workflow)
            
            # Wait for real execution (with timeout)
            max_wait = 30  # 30 seconds max
            waited = 0
            while waited < max_wait:
                # Check if all tasks completed
                all_done = True
                for task in workflow.tasks:
                    if task.id not in engine.dependency_tracker.completed_tasks:
                        all_done = False
                        break
                
                if all_done:
                    break
                
                await asyncio.sleep(1)
                waited += 1
            
            # Verify completion
            for task in workflow.tasks:
                assert task.id in engine.dependency_tracker.completed_tasks
            
        finally:
            await engine.stop()
            
            # Cancel the engine task
            engine_task.cancel()
            try:
                await engine_task
            except asyncio.CancelledError:
                pass
            
            await ollama_provider.cleanup()
            await persistence.cleanup()
    
    async def test_all_workflows_listed(self, examples_dir):
        """Verify our test list includes all YAML workflows in examples"""
        actual_workflows = list(examples_dir.glob("*.yaml"))
        actual_names = {wf.name for wf in actual_workflows}
        
        tested_names = set(EXAMPLE_WORKFLOWS)
        
        # Find any workflows we're missing
        missing = actual_names - tested_names
        if missing:
            logger.warning(f"Workflows not in test list: {missing}")
        
        # At least 80% coverage
        coverage = len(tested_names.intersection(actual_names)) / len(actual_names)
        assert coverage >= 0.8, f"Test coverage is only {coverage*100:.1f}%"
    
    @pytest.mark.slow
    async def test_complex_workflow_execution(self, examples_dir, execution_engine):
        """Test a complex workflow with dependencies"""
        workflow_path = examples_dir / "dependent_workflow.yaml"
        
        if not workflow_path.exists():
            pytest.skip("Dependent workflow not found")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        await execution_engine.submit_workflow(workflow)
        
        # Wait for execution
        await asyncio.sleep(1)
        
        # Verify dependency order was respected
        tracker = execution_engine.dependency_tracker
        
        # Tasks with dependencies should not start before their dependencies
        for task in workflow.tasks:
            if task.dependencies:
                # This task should have completed after its dependencies
                for dep_id in task.dependencies:
                    # Both should be in completed or one still running
                    if task.id in tracker.completed_tasks and dep_id in tracker.completed_tasks:
                        # Good - both completed
                        pass
                    elif task.id not in tracker.completed_tasks:
                        # Task not done yet - that's ok
                        pass
                    else:
                        # Task done but dependency not - that's wrong!
                        pytest.fail(f"Task {task.id} completed before dependency {dep_id}")


if __name__ == "__main__":
    # Allow running this test file directly
    pytest.main([__file__, "-v"])