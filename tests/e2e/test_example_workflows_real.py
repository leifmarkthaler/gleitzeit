"""
Real end-to-end tests for example workflows using actual Gleitzeit system

These tests run workflows through the complete Gleitzeit stack:
- Real ExecutionEngine in EVENT_DRIVEN mode
- Real ProtocolProviderRegistry  
- Real persistence (in-memory)
- Real providers with REAL services (no mocking)

Uses the proper event-driven execution where submit_workflow() alone triggers execution.
Tests will skip if required services (e.g., Ollama) are not available.
"""

import pytest
import asyncio
import yaml
from pathlib import Path
from typing import Dict, Any

from gleitzeit.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit.core.workflow_loader import load_workflow_from_dict
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.providers.template_provider import TemplateProvider
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.protocols import (
    LLM_PROTOCOL_V1, 
    PYTHON_PROTOCOL_V1, 
    MCP_PROTOCOL_V1, 
    TEMPLATE_PROTOCOL_V1
)


# Simple workflows to test first
SIMPLE_WORKFLOWS = [
    "simple_llm_workflow.yaml",
    "simple_python_workflow.yaml", 
    "simple_mcp_workflow.yaml",
    "python_only_workflow.yaml",
    "mixed_workflow.yaml",
    "dependent_workflow.yaml",
    "parallel_workflow.yaml",
]

# LLM-dependent workflows (need Ollama)
LLM_WORKFLOWS = [
    "simple_llm_workflow.yaml",
    "llm_workflow.yaml",
    "mixed_workflow.yaml",
    "dependent_workflow.yaml",
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
class TestExampleWorkflowsReal:
    """Test example workflows with real Gleitzeit engine - NO MOCKS"""
    
    @pytest.fixture
    def examples_dir(self):
        """Path to examples directory"""
        return Path(__file__).parent.parent.parent / "examples"
    
    @pytest.fixture
    async def real_engine(self):
        """Create real Gleitzeit execution engine with REAL providers"""
        # Real persistence
        persistence = UnifiedInMemoryAdapter()
        await persistence.initialize()
        
        # Real registry
        registry = ProtocolProviderRegistry()
        
        # Register protocols
        registry.register_protocol(LLM_PROTOCOL_V1)
        registry.register_protocol(PYTHON_PROTOCOL_V1)
        registry.register_protocol(MCP_PROTOCOL_V1)
        registry.register_protocol(TEMPLATE_PROTOCOL_V1)
        
        # Check if Ollama is available
        ollama_available = await check_ollama_available()
        ollama_provider = None
        
        if ollama_available:
            # Real OllamaProvider - no mocking!
            ollama_provider = OllamaProvider(provider_id="ollama")
            await ollama_provider.initialize()
            registry.register_provider("ollama", "llm/v1", ollama_provider)
        
        # Real Python provider
        python_provider = PythonProvider(provider_id="python")
        await python_provider.initialize()
        registry.register_provider("python", "python/v1", python_provider)
        
        # Real MCP provider
        mcp_provider = SimpleMCPProvider(provider_id="mcp")
        await mcp_provider.initialize()
        registry.register_provider("mcp", "mcp/v1", mcp_provider)
        
        # Real template provider
        template_provider = TemplateProvider(provider_id="template")
        await template_provider.initialize()
        registry.register_provider("template", "template/v1", template_provider)
        
        # Real queue manager and dependency resolver
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        # Create real execution engine
        engine = ExecutionEngine(
            registry=registry,
            persistence=persistence,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            max_concurrent_tasks=5
        )
        
        # Store ollama availability for tests to check
        engine.ollama_available = ollama_available
        
        # START the engine in event-driven mode for proper execution
        engine_task = asyncio.create_task(engine.start(ExecutionMode.EVENT_DRIVEN))
        
        # Wait a bit for engine to start
        await asyncio.sleep(0.1)
        
        yield engine
        
        # Stop the engine
        await engine.stop()
        
        # Cancel the engine task
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        
        # Cleanup
        if ollama_provider:
            await ollama_provider.cleanup()
        await python_provider.cleanup()
        # MCP and Template providers don't have cleanup
        await persistence.cleanup()
    
    async def _wait_for_workflow_completion(self, engine, workflow, timeout=30):
        """Helper to wait for workflow completion"""
        elapsed = 0
        interval = 0.5
        
        while elapsed < timeout:
            all_complete = True
            for task in workflow.tasks:
                result = engine.get_task_result(task.id)
                if not result or result.status not in ['completed', 'failed']:
                    all_complete = False
                    break
            
            if all_complete:
                return True
                
            await asyncio.sleep(interval)
            elapsed += interval
        
        return False
    
    @pytest.mark.parametrize("workflow_file", ["simple_python_workflow.yaml", "python_only_workflow.yaml", "simple_mcp_workflow.yaml"])
    async def test_non_llm_workflows(self, examples_dir, workflow_file, real_engine):
        """Test workflows that don't require LLM (always work)"""
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        # Load workflow
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow ONLY - should trigger execution automatically
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_workflow_completion(real_engine, workflow)
        assert completed, f"Workflow {workflow_file} did not complete in time"
        
        # Verify results
        for task in workflow.tasks:
            result = await real_engine.persistence.get_task_result(task.id)
            assert result is not None, f"No result for task {task.id}"
            assert result.status in ['completed', 'failed'], f"Task {task.id} status: {result.status}"
    
    @pytest.mark.parametrize("workflow_file", LLM_WORKFLOWS)
    async def test_llm_workflows(self, examples_dir, workflow_file, real_engine):
        """Test workflows that require LLM (skip if Ollama not available)"""
        if not real_engine.ollama_available:
            pytest.skip("Ollama not available - skipping LLM workflow test")
        
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        # Load workflow
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow ONLY - should trigger execution automatically
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion (longer timeout for real LLM calls)
        completed = await self._wait_for_workflow_completion(real_engine, workflow, timeout=60)
        assert completed, f"Workflow {workflow_file} did not complete in time"
        
        # Verify results
        for task in workflow.tasks:
            result = await real_engine.persistence.get_task_result(task.id)
            assert result is not None, f"No result for task {task.id}"
            assert result.status in ['completed', 'failed'], f"Task {task.id} status: {result.status}"
            
            # For LLM tasks, verify we got actual responses
            if 'llm' in task.method and result.status == 'completed':
                assert result.result is not None, f"LLM task {task.id} has no result"
    
    async def test_python_workflow_execution(self, examples_dir, real_engine):
        """Test Python-only workflow execution"""
        workflow_path = examples_dir / "python_only_workflow.yaml"
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow ONLY
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_workflow_completion(real_engine, workflow)
        assert completed, "Workflow did not complete in time"
        
        # Check all tasks completed
        for task in workflow.tasks:
            result = real_engine.get_task_result(task.id)
            assert result is not None
            assert result.status == 'completed', f"Task {task.id} failed"
    
    async def test_mcp_workflow_execution(self, examples_dir, real_engine):
        """Test MCP workflow execution"""
        workflow_path = examples_dir / "simple_mcp_workflow.yaml"
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow ONLY
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_workflow_completion(real_engine, workflow)
        assert completed, "Workflow did not complete in time"
        
        # Verify MCP tool results
        for task in workflow.tasks:
            result = real_engine.get_task_result(task.id)
            assert result is not None
            assert result.status == 'completed', f"Task {task.id} failed"
            
            # Check specific MCP tool results
            if 'add' in task.method:
                # Should have a numeric result
                assert result.result is not None
    
    async def test_dependent_workflow_order(self, examples_dir, real_engine):
        """Test that dependent workflow respects task dependencies"""
        workflow_path = examples_dir / "dependent_workflow.yaml"
        
        if not workflow_path.exists():
            pytest.skip("Dependent workflow not found")
        
        # Check if this workflow needs LLM
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
            needs_llm = any('llm' in task.get('method', '') for task in workflow_content.get('tasks', []))
        
        if needs_llm and not real_engine.ollama_available:
            pytest.skip("Ollama not available - skipping dependent workflow test")
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Track task execution order
        execution_order = []
        
        original_execute = real_engine._execute_task
        async def track_execution(task):
            execution_order.append(task.id)
            return await original_execute(task)
        
        real_engine._execute_task = track_execution
        
        # Submit workflow ONLY
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_workflow_completion(real_engine, workflow, timeout=45)
        assert completed, "Workflow did not complete in time"
        
        # Verify dependencies were respected
        for task in workflow.tasks:
            if task.dependencies:
                task_index = execution_order.index(task.id) if task.id in execution_order else -1
                for dep_id in task.dependencies:
                    dep_index = execution_order.index(dep_id) if dep_id in execution_order else -1
                    if task_index >= 0 and dep_index >= 0:
                        assert dep_index < task_index, f"Task {task.id} executed before dependency {dep_id}"
    
    async def test_parallel_workflow_execution(self, examples_dir, real_engine):
        """Test that parallel tasks execute concurrently"""
        workflow_path = examples_dir / "parallel_workflow.yaml"
        
        if not workflow_path.exists():
            pytest.skip("Parallel workflow not found")
        
        # Check if this workflow needs LLM
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
            needs_llm = any('llm' in task.get('method', '') for task in workflow_content.get('tasks', []))
        
        if needs_llm and not real_engine.ollama_available:
            pytest.skip("Ollama not available - skipping parallel workflow test")
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Track simultaneous executions
        executing_tasks = set()
        max_concurrent = 0
        
        original_execute = real_engine._execute_task
        async def track_concurrent(task):
            executing_tasks.add(task.id)
            nonlocal max_concurrent
            max_concurrent = max(max_concurrent, len(executing_tasks))
            
            result = await original_execute(task)
            
            executing_tasks.remove(task.id)
            return result
        
        real_engine._execute_task = track_concurrent
        
        # Submit workflow ONLY
        await real_engine.submit_workflow(workflow)
        
        # Wait for completion
        completed = await self._wait_for_workflow_completion(real_engine, workflow, timeout=45)
        assert completed, "Workflow did not complete in time"
        
        # Should have had multiple tasks executing at once
        assert max_concurrent > 1, "Tasks did not execute in parallel"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])