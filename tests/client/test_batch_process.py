"""
Test batch_process method in GleitzeitClient
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Task, Workflow, TaskResult


@pytest.mark.asyncio
class TestClientBatchProcess:
    """Test the batch_process method of GleitzeitClient"""
    
    @pytest.fixture
    async def client(self):
        """Create a test client with mocked persistence"""
        client = GleitzeitClient(persistence_type="memory")
        
        # Mock the adapter and queue manager
        client.adapter = AsyncMock()
        client.queue_manager = AsyncMock()
        client._initialized = True
        
        # Mock workflow submission
        mock_workflow = Workflow(
            id="test-workflow-123",
            name="Batch Processing",
            tasks=[],
            metadata={}
        )
        client.submit_workflow = AsyncMock(return_value=mock_workflow)
        
        # Mock get_workflow_tasks to return completed tasks
        mock_tasks = [
            Task(
                id="task-1",
                name="Process file1.txt",
                protocol="llm/v1",
                method="llm/chat",
                params={"file_path": "/tmp/file1.txt"},
                status="completed"
            ),
            Task(
                id="task-2",
                name="Process file2.txt",
                protocol="llm/v1",
                method="llm/chat",
                params={"file_path": "/tmp/file2.txt"},
                status="completed"
            )
        ]
        client.get_workflow_tasks = AsyncMock(return_value=mock_tasks)
        
        # Mock get_task_result
        mock_result = TaskResult(
            task_id="task-1",
            status="completed",
            result={"response": "Processed content"}
        )
        client.get_task_result = AsyncMock(return_value=mock_result)
        
        yield client
    
    async def test_batch_process_text_files(self, client):
        """Test batch processing of text files"""
        # Create temp directory with test files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test files
            (temp_path / "file1.txt").write_text("Test content 1")
            (temp_path / "file2.txt").write_text("Test content 2")
            (temp_path / "file3.md").write_text("# Markdown content")
            
            # Process batch
            result = await client.batch_process(
                directory=temp_dir,
                pattern="*.txt",
                prompt="Summarize this file"
            )
            
            # Verify result structure
            assert "batch_id" in result
            assert result["total_files"] == 2  # Only .txt files
            assert result["successful"] == 2
            assert result["failed"] == 0
            assert "results" in result
            assert "workflow_id" in result
            
            # Verify workflow was submitted
            client.submit_workflow.assert_called_once()
            call_args = client.submit_workflow.call_args
            assert call_args[1]["name"].startswith("Batch Processing")
            assert len(call_args[1]["tasks"]) == 2
    
    async def test_batch_process_python_files(self, client):
        """Test batch processing of Python files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create Python files
            (temp_path / "script1.py").write_text("print('Hello')")
            (temp_path / "script2.py").write_text("result = 2 + 2")
            
            # Process batch with Python execution
            result = await client.batch_process(
                directory=temp_dir,
                pattern="*.py",
                method="python/execute"
            )
            
            # Verify workflow submission
            client.submit_workflow.assert_called_once()
            call_args = client.submit_workflow.call_args
            tasks = call_args[1]["tasks"]
            
            # Check that Python tasks have correct protocol and params
            for task in tasks:
                assert task["protocol"] == "python/v1"
                assert task["method"] == "python/execute"
                assert "file" in task["params"]  # Should use 'file' not 'file_path'
    
    async def test_batch_process_no_files(self, client):
        """Test batch processing when no files match pattern"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create files that don't match pattern
            (temp_path / "file.txt").write_text("Text file")
            
            # Process batch looking for .pdf files
            result = await client.batch_process(
                directory=temp_dir,
                pattern="*.pdf"
            )
            
            # Should return empty result
            assert result["total_files"] == 0
            assert result["successful"] == 0
            assert result["failed"] == 0
            assert result["results"] == {}
            
            # Workflow should not be submitted
            client.submit_workflow.assert_not_called()
    
    async def test_batch_process_invalid_directory(self, client):
        """Test batch processing with invalid directory"""
        with pytest.raises(FileNotFoundError):
            await client.batch_process(
                directory="/nonexistent/directory",
                pattern="*.txt"
            )
    
    async def test_batch_process_vision_files(self, client):
        """Test batch processing of image files with vision model"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create image files (just empty files for testing)
            (temp_path / "image1.png").touch()
            (temp_path / "image2.jpg").touch()
            
            # Process batch with vision
            result = await client.batch_process(
                directory=temp_dir,
                pattern="*.png",
                method="llm/vision",
                prompt="Describe this image"
            )
            
            # Verify workflow submission
            client.submit_workflow.assert_called_once()
            call_args = client.submit_workflow.call_args
            tasks = call_args[1]["tasks"]
            
            # Check vision task params
            assert len(tasks) == 1
            assert tasks[0]["protocol"] == "llm/v1"
            assert tasks[0]["method"] == "llm/vision"
            assert "image_path" in tasks[0]["params"]
    
    async def test_batch_process_with_custom_name(self, client):
        """Test batch processing with custom workflow name"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "file.txt").write_text("Content")
            
            # Process with custom name
            result = await client.batch_process(
                directory=temp_dir,
                pattern="*.txt",
                name="My Custom Batch Job"
            )
            
            # Verify custom name was used
            client.submit_workflow.assert_called_once()
            call_args = client.submit_workflow.call_args
            assert call_args[1]["name"] == "My Custom Batch Job"