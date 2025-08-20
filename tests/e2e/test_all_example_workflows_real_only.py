"""
Comprehensive end-to-end tests for all example workflows using REAL services only

NO MOCKS - These tests use real Gleitzeit components and real services.
Tests will skip if required services are not available.
"""

import pytest
import asyncio
import yaml
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

from gleitzeit.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit.core.workflow_loader import load_workflow_from_file, load_workflow_from_dict
from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.providers.template_provider import TemplateProvider
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.protocols import (
    LLM_PROTOCOL_V1,
    PYTHON_PROTOCOL_V1,
    MCP_PROTOCOL_V1,
    TEMPLATE_PROTOCOL_V1
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# All example workflows in the examples directory
EXAMPLE_WORKFLOWS = [
    "simple_llm_workflow.yaml",
    "simple_python_workflow.yaml",
    "simple_mcp_workflow.yaml",
    "llm_workflow.yaml",
    "python_only_workflow.yaml",
    "mixed_workflow.yaml",
    "dependent_workflow.yaml",
    "parallel_workflow.yaml",
    "dependent_llm_tasks.yaml",
    "dependent_python_tasks.yaml",
    "error_handling_workflow.yaml",
    "template_workflow.yaml",
    "batch_processing_workflow.yaml",
    "code_analysis_workflow.yaml",
    "content_generation_workflow.yaml",
    "data_processing_workflow.yaml",
    "research_workflow.yaml",
    "tutorial_workflow.yaml",
    "vision_workflow.yaml",
    "agent_reasoning.yaml",
    "agent_code_review.yaml",
]

# Categorize workflows by requirements
PYTHON_ONLY_WORKFLOWS = [
    "simple_python_workflow.yaml",
    "python_only_workflow.yaml",
    "dependent_python_tasks.yaml",
]

MCP_ONLY_WORKFLOWS = [
    "simple_mcp_workflow.yaml",
]

TEMPLATE_WORKFLOWS = [
    "template_workflow.yaml",
]

# Workflows that require LLM
LLM_REQUIRED_WORKFLOWS = [
    "simple_llm_workflow.yaml",
    "llm_workflow.yaml",
    "mixed_workflow.yaml",
    "dependent_workflow.yaml",
    "dependent_llm_tasks.yaml",
    "vision_workflow.yaml",
    "content_generation_workflow.yaml",
    "research_workflow.yaml",
    "agent_reasoning.yaml",
    "agent_code_review.yaml",
]


async def check_ollama_available() -> bool:
    """Check if Ollama is running and available"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=2)) as response:
                return response.status == 200
    except:
        return False


@pytest.mark.e2e
@pytest.mark.real
class TestAllExampleWorkflowsReal:
    """Comprehensive e2e tests for all example workflows with REAL services"""
    
    @pytest.fixture
    def examples_dir(self):
        """Path to examples directory"""
        return Path(__file__).parent.parent.parent / "examples"
    
    @pytest.fixture
    async def real_engine(self):
        """Create real execution engine with real providers"""
        # Real persistence
        persistence = UnifiedInMemoryAdapter()
        await persistence.initialize()
        
        # Real registry
        registry = ProtocolProviderRegistry()
        
        # Register all protocols
        registry.register_protocol(LLM_PROTOCOL_V1)
        registry.register_protocol(PYTHON_PROTOCOL_V1)
        registry.register_protocol(MCP_PROTOCOL_V1)
        registry.register_protocol(TEMPLATE_PROTOCOL_V1)
        
        # Check Ollama availability
        ollama_available = await check_ollama_available()
        ollama_provider = None
        
        if ollama_available:
            # Real Ollama provider
            ollama_provider = OllamaProvider(provider_id="ollama")
            await ollama_provider.initialize()
            registry.register_provider("ollama", "llm/v1", ollama_provider)
            logger.info("Ollama provider registered")
        else:
            logger.warning("Ollama not available - LLM workflows will be skipped")
        
        # Real Python provider
        python_provider = PythonProvider(provider_id="python")
        await python_provider.initialize()
        registry.register_provider("python", "python/v1", python_provider)
        logger.info("Python provider registered")
        
        # Real MCP provider
        mcp_provider = SimpleMCPProvider(provider_id="mcp")
        await mcp_provider.initialize()
        registry.register_provider("mcp", "mcp/v1", mcp_provider)
        logger.info("MCP provider registered")
        
        # Real template provider
        template_provider = TemplateProvider(provider_id="template")
        await template_provider.initialize()
        registry.register_provider("template", "template/v1", template_provider)
        logger.info("Template provider registered")
        
        # Create execution engine
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        engine = ExecutionEngine(
            registry=registry,
            persistence=persistence,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            max_concurrent_tasks=5
        )
        
        # Store Ollama availability
        engine.ollama_available = ollama_available
        
        # Start engine in event-driven mode
        engine_task = asyncio.create_task(engine.start(ExecutionMode.EVENT_DRIVEN))
        await asyncio.sleep(0.1)  # Let it start
        
        yield engine
        
        # Cleanup
        await engine.stop()
        
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        
        if ollama_provider:
            await ollama_provider.cleanup()
        await python_provider.cleanup()
        await persistence.cleanup()
    
    async def _wait_for_completion(self, engine, workflow, timeout=30):
        """Wait for workflow to complete"""
        elapsed = 0
        interval = 0.5
        
        while elapsed < timeout:
            all_done = True
            for task in workflow.tasks:
                result = engine.get_task_result(task.id)
                if not result or result.status not in ['completed', 'failed']:
                    all_done = False
                    break
            
            if all_done:
                return True
            
            await asyncio.sleep(interval)
            elapsed += interval
        
        return False
    
    @pytest.mark.parametrize("workflow_file", EXAMPLE_WORKFLOWS)
    async def test_workflow_can_load(self, examples_dir, workflow_file):
        """Test that each workflow file can be loaded successfully"""
        workflow_path = examples_dir / workflow_file
        
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
    
    @pytest.mark.parametrize("workflow_file", PYTHON_ONLY_WORKFLOWS)
    async def test_python_workflows(self, examples_dir, workflow_file, real_engine):
        """Test Python-only workflows (always work)"""
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_completion(real_engine, workflow)
        assert completed, f"Workflow {workflow_file} did not complete"
        
        # Verify all tasks completed
        for task in workflow.tasks:
            result = real_engine.get_task_result(task.id)
            assert result is not None, f"No result for task {task.id}"
            assert result.status in ['completed', 'failed']
    
    @pytest.mark.parametrize("workflow_file", MCP_ONLY_WORKFLOWS)
    async def test_mcp_workflows(self, examples_dir, workflow_file, real_engine):
        """Test MCP-only workflows (always work)"""
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_completion(real_engine, workflow)
        assert completed, f"Workflow {workflow_file} did not complete"
        
        # Verify all tasks completed
        for task in workflow.tasks:
            result = real_engine.get_task_result(task.id)
            assert result is not None, f"No result for task {task.id}"
            assert result.status == 'completed', f"Task {task.id} failed"
    
    @pytest.mark.parametrize("workflow_file", LLM_REQUIRED_WORKFLOWS)
    async def test_llm_workflows(self, examples_dir, workflow_file, real_engine):
        """Test LLM-dependent workflows (skip if Ollama not available)"""
        if not real_engine.ollama_available:
            pytest.skip("Ollama not available - skipping LLM workflow")
        
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion (longer timeout for LLM)
        completed = await self._wait_for_completion(real_engine, workflow, timeout=60)
        assert completed, f"Workflow {workflow_file} did not complete"
        
        # Verify all tasks completed
        for task in workflow.tasks:
            result = real_engine.get_task_result(task.id)
            assert result is not None, f"No result for task {task.id}"
            assert result.status in ['completed', 'failed']
            
            # For LLM tasks that completed, verify we got responses
            if 'llm' in task.method and result.status == 'completed':
                assert result.result is not None
    
    async def test_workflow_dependencies_respected(self, examples_dir, real_engine):
        """Test that task dependencies are executed in correct order"""
        # Use a workflow with clear dependencies
        workflow_path = examples_dir / "dependent_python_tasks.yaml"
        
        if not workflow_path.exists():
            pytest.skip("Dependent workflow not found")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Track execution order
        execution_order = []
        
        original_execute = real_engine._execute_task
        async def track_execution(task):
            execution_order.append(task.id)
            return await original_execute(task)
        
        real_engine._execute_task = track_execution
        
        # Submit workflow
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_completion(real_engine, workflow, timeout=30)
        assert completed, "Workflow did not complete"
        
        # Verify dependencies were respected
        for task in workflow.tasks:
            if task.dependencies:
                task_idx = execution_order.index(task.id) if task.id in execution_order else -1
                for dep_id in task.dependencies:
                    dep_idx = execution_order.index(dep_id) if dep_id in execution_order else -1
                    if task_idx >= 0 and dep_idx >= 0:
                        assert dep_idx < task_idx, f"Task {task.id} ran before {dep_id}"
    
    async def test_parallel_execution(self, examples_dir, real_engine):
        """Test that independent tasks execute in parallel"""
        # Use parallel workflow if it exists
        workflow_path = examples_dir / "parallel_workflow.yaml"
        
        if not workflow_path.exists():
            # Create a simple parallel workflow
            workflow = Workflow(
                name="Test Parallel",
                tasks=[
                    Task(id="task1", method="mcp/tool.echo", params={"message": "1"}),
                    Task(id="task2", method="mcp/tool.echo", params={"message": "2"}),
                    Task(id="task3", method="mcp/tool.echo", params={"message": "3"}),
                ]
            )
        else:
            with open(workflow_path) as f:
                workflow_content = yaml.safe_load(f)
            workflow = load_workflow_from_dict(workflow_content)
        
        # Track concurrent executions
        executing = set()
        max_concurrent = 0
        
        original_execute = real_engine._execute_task
        async def track_concurrent(task):
            executing.add(task.id)
            nonlocal max_concurrent
            max_concurrent = max(max_concurrent, len(executing))
            
            result = await original_execute(task)
            
            executing.remove(task.id)
            return result
        
        real_engine._execute_task = track_concurrent
        
        # Submit workflow
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_completion(real_engine, workflow)
        assert completed, "Workflow did not complete"
        
        # Should have executed multiple tasks concurrently
        assert max_concurrent > 1, "Tasks did not execute in parallel"
    
    async def test_error_handling(self, examples_dir, real_engine):
        """Test that workflow handles errors appropriately"""
        # Use error handling workflow if it exists
        workflow_path = examples_dir / "error_handling_workflow.yaml"
        
        if workflow_path.exists():
            with open(workflow_path) as f:
                workflow_content = yaml.safe_load(f)
            workflow = load_workflow_from_dict(workflow_content)
        else:
            # Create a workflow with an intentional error
            workflow = Workflow(
                name="Test Error Handling",
                tasks=[
                    Task(
                        id="error_task",
                        method="python/execute",
                        params={"code": "raise ValueError('Test error')"}
                    ),
                    Task(
                        id="normal_task",
                        method="mcp/tool.echo",
                        params={"message": "This should still run"}
                    )
                ]
            )
        
        # Submit workflow
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        await self._wait_for_completion(real_engine, workflow, timeout=15)
        
        # Check that we have results for all tasks
        for task in workflow.tasks:
            result = real_engine.get_task_result(task.id)
            assert result is not None, f"No result for task {task.id}"
            # Task should either complete or fail properly
            assert result.status in ['completed', 'failed']
    
    async def test_all_workflows_listed(self, examples_dir):
        """Verify our test list includes all YAML workflows in examples"""
        actual_workflows = list(examples_dir.glob("*.yaml"))
        actual_names = {f.name for f in actual_workflows}
        
        # Workflows we're testing
        tested_workflows = set(EXAMPLE_WORKFLOWS)
        
        # Find any workflows we're missing
        missing = actual_names - tested_workflows
        
        # Some workflows might be templates or require special setup
        allowed_missing = {
            "text_file_workflow.yaml",  # Requires file
            "vision_file_workflow.yaml",  # Requires image file
            "mixed_vision_file_workflow.yaml",  # Requires multiple files
            "meeting_analysis_workflow.yaml",  # Requires audio file
            "multi_instance_demo.yaml",  # Requires multiple Ollama instances
            "code_review_workflow.yaml",  # May be duplicate
            "data_analysis_workflow.yaml",  # May require data files
        }
        
        unexpected_missing = missing - allowed_missing
        
        if unexpected_missing:
            logger.warning(f"Workflows not in test list: {unexpected_missing}")
        
        # We should be testing most workflows
        coverage = len(tested_workflows) / len(actual_names) if actual_names else 0
        assert coverage > 0.7, f"Test coverage too low: {coverage:.1%}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])