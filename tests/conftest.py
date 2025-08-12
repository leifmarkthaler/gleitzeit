"""
Global pytest configuration and fixtures for Gleitzeit V4 tests
"""

import pytest
import asyncio
import logging
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging for tests
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('tests/test.log')
    ]
)

# Suppress noisy logs during testing
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def cleanup_tasks():
    """Automatically cleanup any remaining tasks after each test"""
    yield
    
    # Cancel any remaining tasks
    tasks = [task for task in asyncio.all_tasks() if not task.done()]
    if tasks:
        for task in tasks:
            task.cancel()
        
        # Wait for tasks to be cancelled
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for test files"""
    return tmp_path


@pytest.fixture
def mock_time():
    """Mock time for consistent testing"""
    import time
    import unittest.mock
    
    with unittest.mock.patch('time.time', return_value=1640995200.0):  # 2022-01-01 00:00:00
        yield


# Custom markers for test categorization
def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "slow: Tests that take more than 5 seconds")
    config.addinivalue_line("markers", "distributed: Tests requiring distributed setup")


# Skip distributed tests if Socket.IO is not available
def pytest_collection_modifyitems(config, items):
    """Modify test collection based on available dependencies"""
    try:
        import socketio
        socketio_available = True
    except ImportError:
        socketio_available = False
    
    if not socketio_available:
        skip_distributed = pytest.mark.skip(reason="Socket.IO not available")
        for item in items:
            if "distributed" in item.keywords:
                item.add_marker(skip_distributed)


# Test data fixtures
@pytest.fixture
def sample_task_data():
    """Provide sample task data for testing"""
    return {
        "id": "test-task-001",
        "name": "Sample Test Task",
        "protocol": "test/v1",
        "method": "echo",
        "params": {"message": "Hello, World!"},
        "priority": "normal",
        "dependencies": [],
        "timeout": 30
    }


@pytest.fixture 
def sample_workflow_data():
    """Provide sample workflow data for testing"""
    return {
        "id": "test-workflow-001",
        "name": "Sample Test Workflow",
        "description": "A sample workflow for testing",
        "tasks": [
            {
                "id": "task-1",
                "name": "First Task",
                "protocol": "test/v1",
                "method": "generate",
                "params": {"value": 42},
                "priority": "high"
            },
            {
                "id": "task-2", 
                "name": "Second Task",
                "protocol": "test/v1",
                "method": "process",
                "params": {"input": "${task-1.result.value}"},
                "dependencies": ["task-1"],
                "priority": "normal"
            }
        ]
    }


@pytest.fixture
def sample_protocol_spec():
    """Provide sample protocol specification for testing"""
    from gleitzeit_v4.core.protocol import ProtocolSpec, MethodSpec
    
    return ProtocolSpec(
        name="test",
        version="v1",
        description="Test protocol for unit testing",
        methods={
            "echo": MethodSpec(
                name="echo",
                description="Echo the input message"
            ),
            "generate": MethodSpec(
                name="generate", 
                description="Generate a test value"
            ),
            "process": MethodSpec(
                name="process",
                description="Process input data"
            )
        }
    )