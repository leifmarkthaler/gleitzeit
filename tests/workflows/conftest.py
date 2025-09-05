"""Shared fixtures and configuration for workflow tests"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock
import yaml

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.docker_hub import DockerHub


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Create standard directories
        (workspace / "workflows").mkdir()
        (workspace / "data").mkdir()
        (workspace / "results").mkdir()
        
        yield workspace


@pytest.fixture
async def mock_persistence():
    """Create mock persistence adapter"""
    persistence = Mock(spec=UnifiedPersistenceAdapter)
    persistence.save_workflow = AsyncMock()
    persistence.save_task = AsyncMock()
    persistence.save_result = AsyncMock()
    persistence.get_workflow = AsyncMock()
    persistence.get_task = AsyncMock()
    persistence.get_result = AsyncMock()
    persistence.update_task_status = AsyncMock()
    persistence.list_workflows = AsyncMock(return_value=[])
    persistence.list_tasks = AsyncMock(return_value=[])
    return persistence


@pytest.fixture
async def mock_ollama_hub():
    """Create mock Ollama hub"""
    hub = Mock(spec=OllamaHub)
    hub.hub_id = "ollama-test"
    hub.get_available_instance = AsyncMock(return_value=Mock(
        id="ollama-instance",
        endpoint="http://localhost:11434",
        status="HEALTHY"
    ))
    hub.start_instance = AsyncMock()
    hub.stop_instance = AsyncMock()
    hub.check_health = AsyncMock(return_value=True)
    hub.get_metrics = AsyncMock(return_value={"total": 1, "healthy": 1})
    return hub


@pytest.fixture
async def mock_docker_hub():
    """Create mock Docker hub"""
    hub = Mock(spec=DockerHub)
    hub.hub_id = "docker-test"
    hub.get_available_instance = AsyncMock(return_value=Mock(
        id="docker-instance",
        endpoint="container-123",
        status="HEALTHY"
    ))
    hub.start_instance = AsyncMock()
    hub.stop_instance = AsyncMock()
    hub.execute_in_container = AsyncMock(return_value={
        "output": "Executed",
        "exit_code": 0
    })
    return hub


@pytest.fixture
async def mock_registry(mock_ollama_hub, mock_docker_hub):
    """Create mock registry with all providers"""
    registry = Mock(spec=ProtocolProviderRegistry)
    
    # Create mock providers
    ollama_provider = Mock(spec=OllamaProvider)
    ollama_provider.provider_id = "ollama"
    ollama_provider.protocol_id = "llm/v1"
    ollama_provider.hub = mock_ollama_hub
    ollama_provider.handle_request = AsyncMock(return_value={
        "response": "LLM response",
        "provider_id": "ollama"
    })
    
    python_provider = Mock(spec=PythonProvider)
    python_provider.provider_id = "python"
    python_provider.protocol_id = "python/v1"
    python_provider.hub = mock_docker_hub
    python_provider.handle_request = AsyncMock(return_value={
        "result": "Python result",
        "output": "Output",
        "provider_id": "python"
    })
    
    mcp_provider = Mock(spec=MCPHubProvider)
    mcp_provider.provider_id = "mcp"
    mcp_provider.protocol_id = "mcp/v1"
    mcp_provider.handle_request = AsyncMock(return_value={
        "result": "MCP result",
        "provider_id": "mcp"
    })
    
    # Setup registry behavior
    async def get_provider(protocol, method):
        if protocol == "llm/v1":
            return ollama_provider
        elif protocol == "python/v1":
            return python_provider
        elif protocol == "mcp/v1":
            return mcp_provider
        return None
    
    registry.get_provider_for_method = AsyncMock(side_effect=get_provider)
    registry.list_providers = Mock(return_value=[
        ollama_provider,
        python_provider,
        mcp_provider
    ])
    
    return registry


@pytest.fixture
async def execution_engine(mock_registry, mock_persistence):
    """Create execution engine with mocked dependencies"""
    queue_manager = QueueManager()
    dependency_resolver = DependencyResolver()
    
    engine = ExecutionEngine(
        registry=mock_registry,
        queue_manager=queue_manager,
        dependency_resolver=dependency_resolver,
        persistence=mock_persistence,
        max_concurrent_tasks=5
    )
    return engine


@pytest.fixture
def workflow_validator():
    """Create workflow validator"""
    from gleitzeit.core.workflow_loader import load_workflow_from_dict
    return load_workflow_from_dict


def load_workflow_file(workflow_path: Path) -> dict:
    """Helper to load workflow YAML file"""
    with open(workflow_path) as f:
        return yaml.safe_load(f)


def create_test_workflow(name: str, tasks: list) -> dict:
    """Helper to create test workflow"""
    return {
        "name": name,
        "version": "1.0",
        "tasks": tasks
    }


def create_test_task(
    task_id: str,
    protocol: str = "llm/v1",
    method: str = "chat",
    dependencies: list = None,
    parameters: dict = None
) -> dict:
    """Helper to create test task"""
    task = {
        "id": task_id,
        "protocol": protocol,
        "method": method,
        "parameters": parameters or {}
    }
    if dependencies:
        task["dependencies"] = dependencies
    return task


class MockWorkflowExecutor:
    """Mock workflow executor for testing"""
    
    def __init__(self, registry, persistence):
        self.registry = registry
        self.persistence = persistence
        self.executed_tasks = []
        self.results = {}
    
    async def execute_workflow(self, workflow: dict) -> dict:
        """Execute workflow and return results"""
        workflow_id = f"wf-test-{len(self.executed_tasks)}"
        
        # Save workflow
        await self.persistence.save_workflow(workflow)
        
        # Execute tasks
        for task in workflow.get("tasks", []):
            # Check dependencies
            deps = task.get("dependencies", [])
            for dep in deps:
                if dep not in self.results:
                    raise ValueError(f"Dependency {dep} not satisfied")
            
            # Get provider
            protocol = task.get("protocol", "llm/v1")
            method = task.get("method", "chat")
            provider = await self.registry.get_provider_for_method(protocol, method)
            
            if not provider:
                raise ValueError(f"No provider for {protocol}/{method}")
            
            # Execute task
            result = await provider.handle_request(method, task.get("parameters", {}))
            
            # Store result
            task_id = task["id"]
            self.results[task_id] = result
            self.executed_tasks.append(task_id)
            
            # Save task result
            await self.persistence.save_result(task_id, result)
        
        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "results": self.results
        }


# Markers for different test categories
pytest.mark.unit = pytest.mark.unit
pytest.mark.integration = pytest.mark.integration
pytest.mark.slow = pytest.mark.slow
pytest.mark.asyncio = pytest.mark.asyncio