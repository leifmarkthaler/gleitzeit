"""
Global pytest configuration for Gleitzeit test suite

Provides common fixtures, markers, and test configuration for all test modules.
"""

import pytest
import asyncio
import logging
import os
import tempfile
import shutil
from pathlib import Path
from typing import Generator, Dict, Any, Optional
from unittest.mock import Mock, AsyncMock
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gleitzeit.core.models import Task, Workflow, Priority
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.core.protocol import ProtocolSpec

# Configure logging for tests
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Suppress verbose loggers during tests
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('aioredis').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)


# ================== Test Markers ==================

def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line(
        "markers", "unit: Unit tests for isolated components"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests for component interactions"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end workflow tests"
    )
    config.addinivalue_line(
        "markers", "slow: Long-running tests (>5 seconds)"
    )
    config.addinivalue_line(
        "markers", "redis: Tests requiring Redis connection"
    )
    config.addinivalue_line(
        "markers", "docker: Tests requiring Docker"
    )
    config.addinivalue_line(
        "markers", "ollama: Tests requiring Ollama"
    )
    config.addinivalue_line(
        "markers", "performance: Performance benchmark tests"
    )


# ================== Event Loop Fixtures ==================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for test session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def async_client():
    """Async client for testing"""
    # Placeholder for async client setup
    yield None


# ================== Environment Fixtures ==================

@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment variables for each test"""
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def temp_dir():
    """Provide temporary directory for test files"""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path, ignore_errors=True)


# ================== Mock Fixtures ==================

@pytest.fixture
def mock_ollama_response():
    """Mock Ollama LLM response"""
    return {
        "response": "This is a mock LLM response",
        "model": "llama3.2",
        "created_at": "2024-01-01T00:00:00Z",
        "done": True,
        "context": [],
        "total_duration": 1000000000,
        "eval_count": 100
    }


@pytest.fixture
def mock_provider():
    """Mock protocol provider"""
    provider = AsyncMock(spec=ProtocolProvider)
    provider.id = "mock_provider"
    provider.protocol_id = "mock/v1"
    provider.health_check.return_value = True
    provider.execute.return_value = {"status": "success", "result": "mock result"}
    provider.__aenter__.return_value = provider
    provider.__aexit__.return_value = None
    return provider


# ================== Task & Workflow Fixtures ==================

@pytest.fixture
def sample_task():
    """Simple task for testing"""
    return Task(
        id="test_task_1",
        name="Test Task",
        protocol="llm/v1",
        method="chat",
        params={
            "model": "llama3.2",
            "messages": [{"role": "user", "content": "Hello"}]
        },
        priority=Priority.NORMAL,
        workflow_id="test_workflow_1"
    )


@pytest.fixture
def sample_workflow():
    """Simple workflow for testing"""
    task1 = Task(
        id="task_1",
        name="First Task",
        protocol="llm/v1",
        method="chat",
        params={"model": "llama3.2", "messages": []},
        priority=Priority.NORMAL,
        workflow_id="workflow_1"
    )
    
    task2 = Task(
        id="task_2",
        name="Second Task",
        protocol="llm/v1",
        method="chat",
        params={"model": "llama3.2", "messages": []},
        priority=Priority.NORMAL,
        workflow_id="workflow_1",
        dependencies=["task_1"]
    )
    
    return Workflow(
        id="workflow_1",
        name="Test Workflow",
        description="A test workflow",
        tasks=[task1, task2]
    )


@pytest.fixture
def parallel_workflow():
    """Workflow with parallel tasks"""
    tasks = []
    for i in range(3):
        task = Task(
            id=f"parallel_task_{i}",
            name=f"Parallel Task {i}",
            protocol="llm/v1",
            method="chat",
            params={"model": "llama3.2", "messages": []},
            priority=Priority.NORMAL,
            workflow_id="parallel_workflow"
        )
        tasks.append(task)
    
    return Workflow(
        id="parallel_workflow",
        name="Parallel Test Workflow",
        description="Workflow with parallel tasks",
        tasks=tasks
    )


# ================== Execution Engine Fixtures ==================

@pytest.fixture
async def execution_engine(mock_provider):
    """Configured execution engine for testing"""
    registry = ProtocolProviderRegistry()
    queue_manager = QueueManager()
    dependency_resolver = DependencyResolver()
    
    engine = ExecutionEngine(
        registry=registry,
        queue_manager=queue_manager,
        dependency_resolver=dependency_resolver,
        max_concurrent_tasks=5
    )
    
    # Register mock provider
    mock_protocol = ProtocolSpec(name="mock", version="v1", description="Mock Protocol")
    engine.registry.register_protocol(mock_protocol)
    engine.registry.register_provider("mock_provider", "mock/v1", mock_provider)
    
    yield engine
    
    # Cleanup
    await engine.stop()


# ================== Hub Fixtures ==================

@pytest.fixture
async def ollama_hub():
    """Mock Ollama hub for testing"""
    from gleitzeit.hub.ollama_hub import OllamaHub
    hub = OllamaHub()
    # Don't actually start Ollama
    hub.ensure_started = AsyncMock(return_value=True)
    hub.health_check = AsyncMock(return_value=True)
    yield hub
    await hub.cleanup()


@pytest.fixture
async def docker_hub():
    """Mock Docker hub for testing"""
    from gleitzeit.hub.docker_hub import DockerHub
    hub = DockerHub()
    # Mock Docker operations
    hub.start_container = AsyncMock(return_value="mock_container_id")
    hub.stop_container = AsyncMock()
    yield hub
    await hub.cleanup()


# ================== Persistence Fixtures ==================

@pytest.fixture
async def memory_persistence():
    """In-memory persistence for testing"""
    from gleitzeit.persistence.unified_persistence import UnifiedPersistence
    
    # Force memory backend only
    os.environ["GLEITZEIT_PERSISTENCE_BACKEND"] = "memory"
    os.environ["GLEITZEIT_REDIS_ENABLED"] = "false"
    os.environ["GLEITZEIT_SQL_ENABLED"] = "false"
    
    persistence = UnifiedPersistence()
    await persistence.initialize()
    yield persistence
    await persistence.close()


@pytest.fixture
def redis_available():
    """Check if Redis is available"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 6379))
        sock.close()
        
        if result != 0:
            pytest.skip("Redis not available on localhost:6379")
    except Exception as e:
        pytest.skip(f"Cannot check Redis availability: {e}")


# ================== Test Helpers ==================

@pytest.fixture
def assert_no_warnings():
    """Helper to assert no warnings in test"""
    import warnings
    
    with warnings.catch_warnings(record=True) as warning_list:
        warnings.simplefilter("always")
        yield
        
        # Check for unclosed session warnings
        session_warnings = [
            w for w in warning_list 
            if "Unclosed" in str(w.message)
        ]
        assert len(session_warnings) == 0, f"Found unclosed resources: {session_warnings}"


@pytest.fixture
def performance_timer():
    """Helper for performance testing"""
    import time
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
            self.duration = None
        
        def start(self):
            self.start_time = time.perf_counter()
        
        def stop(self):
            self.end_time = time.perf_counter()
            self.duration = self.end_time - self.start_time
            return self.duration
        
        def assert_faster_than(self, seconds):
            assert self.duration < seconds, f"Operation took {self.duration:.2f}s, expected < {seconds}s"
    
    return Timer()


# ================== Test Collection Hooks ==================

def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers automatically"""
    for item in items:
        # Add markers based on test location
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
        elif "performance" in str(item.fspath):
            item.add_marker(pytest.mark.performance)
        
        # Add markers based on test name
        if 'redis' in item.nodeid.lower():
            item.add_marker(pytest.mark.redis)
        if 'docker' in item.nodeid.lower():
            item.add_marker(pytest.mark.docker)
        if 'ollama' in item.nodeid.lower():
            item.add_marker(pytest.mark.ollama)
        if 'slow' in item.nodeid.lower() or 'performance' in item.nodeid.lower():
            item.add_marker(pytest.mark.slow)
        
        # Mark async functions
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)


# ================== Async Test Support ==================
# (Handled in pytest_collection_modifyitems above)