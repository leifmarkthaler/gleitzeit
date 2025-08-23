"""
Pytest configuration and fixtures for API tests
"""

import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Import the app and dependencies
from gleitzeit.api.main import app, app_state, setup_system, cleanup_system
from gleitzeit.core import Task, Workflow, Priority, TaskResult
from gleitzeit.core.models import TaskStatus


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def mock_execution_engine():
    """Mock execution engine for testing"""
    engine = AsyncMock()
    engine.submit_workflow = AsyncMock()
    engine._execute_workflow = AsyncMock()
    engine.submit_task = AsyncMock()
    engine.start = AsyncMock()
    engine.task_results = {}
    engine.registry = MagicMock()
    python_provider = MagicMock()
    python_provider.protocol_id = "python/v1"
    python_provider.name = "PythonProvider"
    python_provider.description = "Test Python provider"
    python_provider.is_running = lambda: True
    python_provider.get_supported_methods = lambda: ["python/execute", "python/validate"]
    
    ollama_provider = MagicMock()
    ollama_provider.protocol_id = "llm/v1"
    ollama_provider.name = "OllamaProvider"
    ollama_provider.description = "Test LLM provider"
    ollama_provider.is_running = lambda: True
    ollama_provider.get_supported_methods = lambda: ["llm/chat", "llm/vision"]
    
    engine.registry.provider_instances = {
        "test-python-provider": python_provider,
        "test-ollama-provider": ollama_provider
    }
    engine.registry.list_protocols = lambda: ["python/v1", "llm/v1", "mcp/v1", "template/v1"]
    return engine


@pytest_asyncio.fixture
async def mock_persistence():
    """Mock persistence backend for testing"""
    persistence = AsyncMock()
    persistence.get_task_count_by_status = AsyncMock(return_value={
        "completed": 100,
        "failed": 5,
        "queued": 2
    })
    persistence.shutdown = AsyncMock()
    return persistence


@pytest_asyncio.fixture
async def mock_batch_processor():
    """Mock batch processor for testing"""
    processor = AsyncMock()
    processor.process_batch = AsyncMock()
    return processor


@pytest_asyncio.fixture
async def mock_gleitzeit_client():
    """Mock GleitzeitClient for testing"""
    from gleitzeit.core import Task, Priority
    client = AsyncMock()
    
    # Mock run_workflow method
    client.run_workflow = AsyncMock(return_value={
        "workflow_id": "api_workflow_12345678",
        "status": "success",
        "results": {
            "task1": {"status": "completed", "result": {"output": "Task 1 completed"}},
            "task2": {"status": "completed", "result": {"output": "Task 2 completed"}}
        }
    })
    
    # Mock get_status method
    client.get_status = AsyncMock(return_value={
        "providers": {
            "test-python-provider": {
                "protocol": "python/v1",
                "status": "healthy",
                "methods": ["python/execute"]
            },
            "test-ollama-provider": {
                "protocol": "llm/v1", 
                "status": "healthy",
                "methods": ["llm/chat"]
            }
        },
        "persistence": "MockPersistence",
        "task_statistics": {
            "completed": 100,
            "failed": 5,
            "queued": 2
        }
    })
    
    # Mock get_workflow method
    client.get_workflow = AsyncMock(return_value=MagicMock(
        id="api_workflow_12345678",
        name="Test Workflow",
        created_at=None,
        completed_at=None
    ))
    
    # Mock get_workflow_tasks method
    client.get_workflow_tasks = AsyncMock(return_value=[
        MagicMock(id="task1", status="completed"),
        MagicMock(id="task2", status="completed")
    ])
    
    # Mock list_workflows method
    client.list_workflows = AsyncMock(return_value={
        "workflows": [],
        "total": 0,
        "limit": 50,
        "offset": 0
    })
    
    # Mock list_tasks method
    client.list_tasks = AsyncMock(return_value={
        "tasks": [],
        "total": 0,
        "limit": 100,
        "offset": 0
    })
    
    # Mock delete_task method
    client.delete_task = AsyncMock(return_value=True)
    
    # Mock delete_workflow method
    client.delete_workflow = AsyncMock(return_value=True)
    
    # Mock get_task method - returns a proper Task object
    mock_get_task = MagicMock(spec=Task)
    mock_get_task.id = "client_task_12345678"
    mock_get_task.name = "Test Task"
    mock_get_task.protocol = "python/v1"
    mock_get_task.method = "python/execute"
    mock_get_task.params = {"code": "result = 2 + 2"}
    mock_get_task.status = "submitted"
    mock_get_task.result = None
    mock_get_task.error = None
    mock_get_task.created_at = datetime.now()
    mock_get_task.completed_at = None
    mock_get_task.priority = Priority.NORMAL
    client.get_task = AsyncMock(return_value=mock_get_task)
    
    # Mock submit_task method - this returns a Task object with an ID
    mock_task = MagicMock(spec=Task)
    mock_task.id = "client_task_12345678"  # Client generates the ID
    mock_task.name = "Test Task"
    mock_task.protocol = "python/v1"
    mock_task.method = "python/execute"
    mock_task.params = {"code": "result = 2 + 2"}
    mock_task.status = "submitted"
    mock_task.priority = Priority.NORMAL
    client.submit_task = AsyncMock(return_value=mock_task)
    
    # Mock execute_task method
    client.execute_task = AsyncMock(return_value=MagicMock(
        status="completed",
        result={"output": "Success", "result": 4},
        error=None
    ))
    
    # Mock wait_for_task method - called by background task
    client.wait_for_task = AsyncMock(return_value=MagicMock(
        status="completed",
        result={"output": "Success", "result": 4},
        error=None
    ))
    
    # Mock get_task_statistics method
    client.get_task_statistics = AsyncMock(return_value={
        "completed": 100,
        "failed": 5,
        "queued": 2
    })
    
    # Mock get_task_result method
    client.get_task_result = AsyncMock(return_value=MagicMock(
        status="completed",
        result={"output": "Success"},
        error=None
    ))
    
    return client

@pytest_asyncio.fixture
async def test_app(mock_gleitzeit_client):
    """Create test app with mocked GleitzeitClient"""
    # Set up mocked client
    app_state.client = mock_gleitzeit_client
    
    yield app
    
    # Clean up
    app_state.client = None


@pytest_asyncio.fixture
async def async_client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client"""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sync_client(test_app) -> TestClient:
    """Create synchronous test client"""
    return TestClient(test_app)


@pytest.fixture
def sample_task_request():
    """Sample task request data"""
    return {
        "name": "Test Task",
        "protocol": "python/v1",
        "method": "python/execute",
        "params": {
            "code": "result = 2 + 2"
        },
        "priority": "normal"
    }


@pytest.fixture
def sample_workflow_request():
    """Sample workflow request data"""
    return {
        "name": "Test Workflow",
        "description": "Test workflow description",
        "tasks": [
            {
                "id": "task1",
                "name": "First Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = 10"
                },
                "priority": "normal"
            },
            {
                "id": "task2",
                "name": "Second Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = 20"
                },
                "dependencies": ["task1"],
                "priority": "normal"
            }
        ],
        "metadata": {
            "test": True
        }
    }


@pytest.fixture
def sample_task_result():
    """Sample task result"""
    result = MagicMock(spec=TaskResult)
    result.status = "completed"
    result.result = {"output": "Success", "result": 4}
    result.error = None
    result.execution_time = 0.5
    return result


@pytest.fixture
def sample_batch_request():
    """Sample batch processing request"""
    return {
        "directory": "/tmp/test",
        "pattern": "*.txt",
        "prompt": "Summarize this file",
        "model": "llama3.2:latest",
        "max_concurrent": 5
    }


@pytest.fixture
def temp_workflow_file():
    """Create a temporary workflow file"""
    content = """
name: Test Workflow File
description: Workflow from file
tasks:
  - id: file_task
    name: File Task
    protocol: python/v1
    method: python/execute
    params:
      code: "result = 42"
    priority: normal
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(content)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def mock_template_result():
    """Mock template execution result"""
    return {
        "template_type": "research",
        "workflow_id": "template_research_12345",
        "topic": "test topic",
        "status": "completed",
        "steps_planned": 5,
        "execution_time": 120.5,
        "report": "# Research Report\n\nTest research report content...",
        "workflow_tasks": ["plan", "research", "analyze", "synthesize", "report"],
        "success": True
    }


class MockBatchResult:
    """Mock batch processing result"""
    def __init__(self):
        self.batch_id = "batch_12345"
        self.total_files = 10
        self.successful = 9
        self.failed = 1
        self.processing_time = 45.67
        self.results = {
            "file1.txt": {"status": "success", "content": "Processed file1"},
            "file2.txt": {"status": "success", "content": "Processed file2"}
        }


@pytest.fixture
def mock_batch_result():
    """Create mock batch result"""
    return MockBatchResult()