"""
End-to-end tests for example workflows using event-driven execution engine

These tests run the ExecutionEngine in EVENT_DRIVEN mode as it would run in production,
where submit_workflow() alone should trigger execution through the event system.

These are TRUE end-to-end tests - no mocking, uses real services.
"""

import pytest
import asyncio
import yaml
from pathlib import Path
from typing import Dict, Any, List

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
    "llm_workflow.yaml",
    "python_only_workflow.yaml",
    "mixed_workflow.yaml",
    "dependent_workflow.yaml",
    "parallel_workflow.yaml",
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
class TestExampleWorkflowsEventDriven:
    """Test example workflows with event-driven execution engine - NO MOCKS"""
    
    @pytest.fixture
    def examples_dir(self):
        """Path to examples directory"""
        return Path(__file__).parent.parent.parent / "examples"
    
    @pytest.fixture
    async def event_driven_engine(self):
        """Create execution engine in event-driven mode with REAL providers"""
        # Real persistence
        persistence = UnifiedInMemoryAdapter()
        await persistence.initialize()
        
        # Real registry
        registry = ProtocolProviderRegistry()
        
        # Register protocols first
        registry.register_protocol(LLM_PROTOCOL_V1)
        registry.register_protocol(PYTHON_PROTOCOL_V1)
        registry.register_protocol(MCP_PROTOCOL_V1)
        registry.register_protocol(TEMPLATE_PROTOCOL_V1)
        
        # Real OllamaProvider - no mocking!
        ollama_available = await check_ollama_available()
        ollama_provider = None
        if ollama_available:
            ollama_provider = OllamaProvider(provider_id="ollama")
            await ollama_provider.initialize()
            registry.register_provider("ollama", "llm/v1", ollama_provider)
        else:
            pytest.skip("Ollama not available - skipping e2e test")
        
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
        
        # Start the engine in event-driven mode
        # This is the key difference - we start the engine first
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
    
    @pytest.mark.parametrize("workflow_file", SIMPLE_WORKFLOWS)
    async def test_workflow_execution_event_driven(self, examples_dir, workflow_file, event_driven_engine):
        """Test workflow execution with event-driven engine (production mode)"""
        workflow_path = examples_dir / workflow_file
        
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found: {workflow_file}")
        
        # Load workflow
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Submit workflow - this should trigger execution automatically
        await event_driven_engine.submit_workflow(workflow)
        
        # Wait for workflow to complete (with timeout)
        max_wait = 30  # seconds - real LLM calls take time
        wait_interval = 0.5
        elapsed = 0
        
        while elapsed < max_wait:
            # Check if all tasks are complete
            all_complete = True
            for task in workflow.tasks:
                task_status = event_driven_engine.dependency_tracker.get_task_status(task.id)
                if task_status not in ['completed', 'failed']:
                    all_complete = False
                    break
            
            if all_complete:
                break
                
            await asyncio.sleep(wait_interval)
            elapsed += wait_interval
        
        # Verify results
        for task in workflow.tasks:
            task_status = event_driven_engine.dependency_tracker.get_task_status(task.id)
            assert task_status in ['completed', 'failed'], f"Task {task.id} status: {task_status} after {elapsed}s"
            
            # For completed tasks, check we have results
            if task_status == 'completed':
                result = await event_driven_engine.persistence.get_task_result(task.id)
                assert result is not None, f"No result for completed task {task.id}"
    
    async def test_submit_only_triggers_execution(self, examples_dir, event_driven_engine):
        """Test that submit_workflow alone triggers execution in event-driven mode"""
        workflow_path = examples_dir / "simple_llm_workflow.yaml"
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Track task executions
        executed_tasks = []
        original_execute = event_driven_engine._execute_task
        
        async def track_execution(task):
            executed_tasks.append(task.id)
            return await original_execute(task)
        
        event_driven_engine._execute_task = track_execution
        
        # Submit workflow WITHOUT calling _execute_workflow
        await event_driven_engine.submit_workflow(workflow)
        
        # Wait for execution to start
        await asyncio.sleep(2.0)
        
        # Verify tasks were executed automatically
        assert len(executed_tasks) > 0, "No tasks were executed after submit_workflow"
        
        # Wait for completion
        max_wait = 20
        elapsed = 0
        while elapsed < max_wait:
            if len(executed_tasks) >= len(workflow.tasks):
                break
            await asyncio.sleep(0.5)
            elapsed += 0.5
        
        # Verify all tasks were executed
        assert len(executed_tasks) >= 2, f"Expected at least 2 tasks, got {len(executed_tasks)}"
    
    async def test_dependent_workflow_order_event_driven(self, examples_dir, event_driven_engine):
        """Test that dependent workflow respects task dependencies in event-driven mode"""
        workflow_path = examples_dir / "dependent_workflow.yaml"
        
        if not workflow_path.exists():
            pytest.skip("Dependent workflow not found")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Track task execution order
        execution_order = []
        
        original_execute = event_driven_engine._execute_task
        async def track_execution(task):
            execution_order.append(task.id)
            return await original_execute(task)
        
        event_driven_engine._execute_task = track_execution
        
        # Submit workflow - should trigger execution automatically
        await event_driven_engine.submit_workflow(workflow)
        
        # Wait for workflow to complete
        await asyncio.sleep(10.0)  # Real execution takes time
        
        # Verify dependencies were respected
        for task in workflow.tasks:
            if task.dependencies:
                task_index = execution_order.index(task.id) if task.id in execution_order else -1
                for dep_id in task.dependencies:
                    dep_index = execution_order.index(dep_id) if dep_id in execution_order else -1
                    if task_index >= 0 and dep_index >= 0:
                        assert dep_index < task_index, f"Task {task.id} executed before dependency {dep_id}"
    
    async def test_workflow_completion_event(self, examples_dir, event_driven_engine):
        """Test that workflow completion events are emitted correctly"""
        workflow_path = examples_dir / "simple_llm_workflow.yaml"
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        workflow = load_workflow_from_dict(workflow_content)
        
        # Track workflow events
        workflow_events = []
        
        async def track_workflow_event(event_type, data):
            if 'workflow' in event_type:
                workflow_events.append((event_type, data))
        
        # Register event handler
        event_driven_engine.add_event_handler('workflow:completed', track_workflow_event)
        event_driven_engine.add_event_handler('workflow:failed', track_workflow_event)
        
        # Submit workflow
        await event_driven_engine.submit_workflow(workflow)
        
        # Wait for completion (real LLM calls take time)
        await asyncio.sleep(15.0)
        
        # Check for completion event
        completed_events = [e for e in workflow_events if e[0] == 'workflow:completed']
        assert len(completed_events) > 0, "No workflow:completed event emitted"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])