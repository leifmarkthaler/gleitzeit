"""
Fixtures for client_v2 tests
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import AsyncGenerator

from gleitzeit import Client


@pytest.fixture
async def native_client() -> AsyncGenerator[Client, None]:
    """Create a native mode client for testing"""
    async with Client(mode="native") as client:
        yield client


@pytest.fixture
async def api_client() -> AsyncGenerator[Client, None]:
    """Create an API mode client for testing"""
    # Auto-start server if needed
    async with Client(
        mode="api",
        auto_start_server=True,
        keep_server_running=True
    ) as client:
        yield client


@pytest.fixture
async def auto_client() -> AsyncGenerator[Client, None]:
    """Create an auto mode client for testing"""
    async with Client(mode="auto") as client:
        yield client


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path)


@pytest.fixture
def sample_workflow_file(temp_dir):
    """Create a sample workflow YAML file"""
    workflow_yaml = """
name: Test Workflow
tasks:
  - id: task1
    name: Echo Task
    protocol: mcp/v1
    method: mcp/tool.echo
    params:
      message: "Hello from workflow"
  
  - id: task2
    name: Math Task
    protocol: mcp/v1
    method: mcp/tool.add
    params:
      a: 10
      b: 20
    dependencies: [task1]
"""
    workflow_file = temp_dir / "test_workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    return str(workflow_file)


@pytest.fixture
def sample_python_script():
    """Create a sample Python script for testing"""
    script_path = Path("examples/scripts/test_script.py")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    
    script_content = """
# Test script for client_v2 tests
result = 42
print(f"Result: {result}")
"""
    script_path.write_text(script_content)
    yield str(script_path.name)  # Return just the filename
    
    # Cleanup
    if script_path.exists():
        script_path.unlink()


@pytest.fixture
def batch_test_files(temp_dir):
    """Create test files for batch processing"""
    # Create test text files
    for i in range(5):
        file_path = temp_dir / f"test_{i}.txt"
        file_path.write_text(f"Test content {i}")
    
    return str(temp_dir)