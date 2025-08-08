"""
Pytest configuration and shared fixtures for Gleitzeit tests
"""

import pytest
import asyncio
import tempfile
import os
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import Task, TaskType, TaskParameters
from gleitzeit_cluster.core.workflow import Workflow
from gleitzeit_cluster.core.service_manager import ServiceManager


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def cluster():
    """Create a test cluster with disabled external services"""
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False,
        auto_start_services=False
    )
    await cluster.start()
    yield cluster
    await cluster.stop()


@pytest.fixture
async def cluster_with_auto_start():
    """Create a test cluster with auto-start enabled (for testing service manager)"""
    with patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_redis_server') as mock_redis, \
         patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_executor_node') as mock_executor:
        
        mock_redis.return_value = True
        mock_executor.return_value = True
        
        cluster = GleitzeitCluster(
            enable_redis=False,  # Disable actual Redis for tests
            enable_socketio=False,  # Disable actual SocketIO for tests
            enable_real_execution=False,
            auto_start_services=True,
            auto_start_redis=True,
            auto_start_executors=True,
            min_executors=1
        )
        yield cluster


@pytest.fixture
def sample_task():
    """Create a sample task for testing"""
    return Task(
        name="test_task",
        task_type=TaskType.FUNCTION,
        parameters=TaskParameters(
            function_name="fibonacci",
            kwargs={"n": 5}
        )
    )


@pytest.fixture
def sample_workflow():
    """Create a sample workflow for testing"""
    workflow = Workflow(name="test_workflow", description="Test workflow")
    
    task1 = Task(
        id="task_1",
        name="First Task",
        task_type=TaskType.FUNCTION,
        parameters=TaskParameters(
            function_name="current_timestamp",
            kwargs={}
        )
    )
    
    task2 = Task(
        id="task_2", 
        name="Second Task",
        task_type=TaskType.TEXT,
        parameters=TaskParameters(
            prompt="Analyze this data: {{task_1.result}}",
            model_name="llama3"
        ),
        dependencies=["task_1"]
    )
    
    workflow.add_task(task1)
    workflow.add_task(task2)
    
    return workflow


@pytest.fixture
def batch_workflow():
    """Create a sample batch processing workflow for testing"""
    workflow = Workflow(name="batch_test_workflow", description="Batch processing test workflow")
    
    # Create multiple parallel tasks for batch processing
    datasets = [
        [1, 2, 3, 4, 5],
        [10, 20, 30, 40, 50],
        [100, 200, 300, 400, 500]
    ]
    
    for i, dataset in enumerate(datasets):
        task = Task(
            id=f"batch_task_{i}",
            name=f"Process Dataset {i+1}",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="analyze_numbers",
                kwargs={"numbers": dataset}
            )
        )
        workflow.add_task(task)
    
    # Add aggregation task
    aggregate_task = Task(
        id="aggregate_results",
        name="Aggregate Batch Results",
        task_type=TaskType.FUNCTION,
        parameters=TaskParameters(
            function_name="current_timestamp",
            kwargs={}
        ),
        dependencies=[f"batch_task_{i}" for i in range(len(datasets))]
    )
    workflow.add_task(aggregate_task)
    
    return workflow


@pytest.fixture
def temp_directory():
    """Create a temporary directory for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_redis():
    """Mock Redis client"""
    with patch('redis.Redis') as mock:
        mock_instance = Mock()
        mock_instance.ping.return_value = True
        mock_instance.get.return_value = None
        mock_instance.set.return_value = True
        mock_instance.delete.return_value = 1
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_ollama():
    """Mock Ollama client"""
    mock_response = {
        "model": "llama3",
        "response": "Mock response from Ollama",
        "done": True
    }
    
    with patch('httpx.AsyncClient') as mock:
        mock_instance = AsyncMock()
        mock_instance.post.return_value.json.return_value = mock_response
        mock_instance.get.return_value.json.return_value = {
            "models": [
                {"name": "llama3", "size": 1000000},
                {"name": "llava", "size": 2000000}
            ]
        }
        mock.return_value.__aenter__.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def service_manager():
    """Create a service manager for testing"""
    return ServiceManager()


@pytest.fixture
def mock_subprocess():
    """Mock subprocess operations"""
    with patch('subprocess.run') as mock_run, \
         patch('subprocess.Popen') as mock_popen:
        
        # Mock successful Redis start
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        
        # Mock successful executor process
        mock_process = Mock()
        mock_process.poll.return_value = None  # Running
        mock_process.terminate.return_value = None
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        yield {
            'run': mock_run,
            'popen': mock_popen,
            'process': mock_process
        }


@pytest.fixture
def mock_socket():
    """Mock socket operations for port checking"""
    with patch('socket.create_connection') as mock_conn:
        mock_conn.return_value.__enter__ = Mock()
        mock_conn.return_value.__exit__ = Mock()
        yield mock_conn


# Test markers for different categories
pytest.mark.unit = pytest.mark.unit
pytest.mark.integration = pytest.mark.integration
pytest.mark.slow = pytest.mark.slow