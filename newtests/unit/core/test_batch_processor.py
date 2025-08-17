"""
Test module for BatchProcessor

Tests cover:
- Directory scanning for files
- Batch workflow creation
- Parallel task generation
- Result aggregation
- Error handling in batch processing

Related components:
- ExecutionEngine
- Task
- Workflow
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from typing import List, Dict, Any

from gleitzeit.core.batch_processor import BatchProcessor, BatchResult
from gleitzeit.core.models import Task, Workflow, TaskStatus
from gleitzeit.core.errors import ConfigurationError, TaskValidationError


@pytest.mark.unit
class TestBatchProcessor:
    """Unit tests for BatchProcessor"""
    
    @pytest.fixture
    def batch_processor(self):
        """Create BatchProcessor instance"""
        return BatchProcessor()
    
    @pytest.fixture
    def sample_files(self, temp_dir):
        """Create sample files for testing"""
        files = []
        for i in range(3):
            file_path = temp_dir / f"test_file_{i}.txt"
            file_path.write_text(f"Content of file {i}")
            files.append(str(file_path))
        return files
    
    @pytest.fixture
    def mock_execution_engine(self):
        """Mock execution engine for batch processing"""
        engine = AsyncMock()
        engine.submit_workflow = AsyncMock()
        engine._execute_workflow = AsyncMock()
        engine.task_results = {}
        return engine
    
    # ==================== Directory Scanning Tests ====================
    
    def test_scan_directory_finds_matching_files(self, batch_processor, temp_dir):
        """Test that scan_directory finds files matching pattern"""
        # Create test files
        (temp_dir / "test1.txt").write_text("content")
        (temp_dir / "test2.txt").write_text("content")
        (temp_dir / "other.md").write_text("content")
        
        # Scan for .txt files
        files = batch_processor.scan_directory(str(temp_dir), "*.txt")
        
        assert len(files) == 2
        assert all(f.endswith(".txt") for f in files)
        assert any("test1.txt" in f for f in files)
        assert any("test2.txt" in f for f in files)
    
    def test_scan_directory_excludes_directories(self, batch_processor, temp_dir):
        """Test that scan_directory excludes subdirectories"""
        # Create file and directory
        (temp_dir / "file.txt").write_text("content")
        (temp_dir / "subdir").mkdir()
        
        files = batch_processor.scan_directory(str(temp_dir), "*")
        
        assert len(files) == 1
        assert "file.txt" in files[0]
    
    def test_scan_directory_raises_on_missing_directory(self, batch_processor):
        """Test that scan_directory raises error for non-existent directory"""
        with pytest.raises(ConfigurationError, match="Directory not found"):
            batch_processor.scan_directory("/non/existent/path")
    
    def test_scan_directory_raises_on_file_path(self, batch_processor, temp_dir):
        """Test that scan_directory raises error when given file path"""
        file_path = temp_dir / "file.txt"
        file_path.write_text("content")
        
        with pytest.raises(ConfigurationError, match="Not a directory"):
            batch_processor.scan_directory(str(file_path))
    
    # ==================== Workflow Creation Tests ====================
    
    def test_create_batch_workflow_creates_parallel_tasks(self, batch_processor, sample_files):
        """Test that batch workflow creates parallel tasks for each file"""
        workflow = batch_processor.create_batch_workflow(
            files=sample_files,
            method="llm/chat",
            prompt="Analyze this file",
            model="llama3.2"
        )
        
        assert workflow.id.startswith("batch-")
        assert len(workflow.tasks) == len(sample_files)
        
        # Check all tasks are independent (no dependencies)
        for task in workflow.tasks:
            assert task.dependencies == []
            assert task.protocol == "llm/v1"
            assert task.method == "llm/chat"
    
    def test_create_batch_workflow_handles_image_files(self, batch_processor, temp_dir):
        """Test that image files use vision method"""
        image_files = [
            str(temp_dir / "image1.png"),
            str(temp_dir / "image2.jpg")
        ]
        
        # Create dummy files
        for f in image_files:
            Path(f).write_text("dummy")
        
        workflow = batch_processor.create_batch_workflow(
            files=image_files,
            method="llm/vision",
            prompt="Describe this image",
            model="llava"
        )
        
        # Check tasks use image_path parameter
        for task in workflow.tasks:
            assert "image_path" in task.params
            assert task.method == "llm/vision"
    
    def test_create_batch_workflow_raises_on_empty_files(self, batch_processor):
        """Test that empty file list raises validation error"""
        with pytest.raises(TaskValidationError, match="No files provided"):
            batch_processor.create_batch_workflow(
                files=[],
                method="llm/chat",
                prompt="Test"
            )
    
    def test_create_batch_workflow_sets_metadata(self, batch_processor, sample_files):
        """Test that workflow metadata is properly set"""
        workflow = batch_processor.create_batch_workflow(
            files=sample_files,
            method="llm/chat",
            prompt="Test prompt",
            model="test-model",
            name="Custom Batch"
        )
        
        assert workflow.name == "Custom Batch"
        assert workflow.metadata["batch"] is True
        assert workflow.metadata["file_count"] == len(sample_files)
        assert workflow.metadata["prompt"] == "Test prompt"
        assert workflow.metadata["model"] == "test-model"
    
    # ==================== Batch Processing Tests ====================
    
    @pytest.mark.asyncio
    async def test_process_batch_with_file_list(
        self, batch_processor, mock_execution_engine, sample_files
    ):
        """Test batch processing with explicit file list"""
        # Setup mock results with correct task ID format
        for i, file_path in enumerate(sample_files):
            # Match the format from batch_processor.py: f"process-{file_name.replace('.', '-')}-{i}"
            from pathlib import Path
            file_name = Path(file_path).name  # test_file_0.txt
            task_id = f"process-{file_name.replace('.', '-')}-{i}"  # process-test_file_0-txt-0
            mock_execution_engine.task_results[task_id] = Mock(
                status="completed",
                result={"response": f"Processed file {i}"}
            )
        
        result = await batch_processor.process_batch(
            execution_engine=mock_execution_engine,
            files=sample_files,
            prompt="Analyze content"
        )
        
        assert result.total_files == len(sample_files)
        assert result.successful == len(sample_files)
        assert result.failed == 0
        assert len(result.results) == len(sample_files)
    
    @pytest.mark.asyncio
    async def test_process_batch_with_directory_scan(
        self, batch_processor, mock_execution_engine, temp_dir
    ):
        """Test batch processing with directory scanning"""
        # Create test files
        for i in range(2):
            (temp_dir / f"test_{i}.txt").write_text(f"Content {i}")
        
        # Mock results
        mock_execution_engine.task_results = {
            "process-test-0-txt-0": Mock(status="completed", result={"response": "Result 0"}),
            "process-test-1-txt-1": Mock(status="completed", result={"response": "Result 1"})
        }
        
        result = await batch_processor.process_batch(
            execution_engine=mock_execution_engine,
            directory=str(temp_dir),
            pattern="*.txt",
            prompt="Process file"
        )
        
        assert result.total_files == 2
        assert result.successful == 2
    
    @pytest.mark.asyncio
    async def test_process_batch_handles_failures(
        self, batch_processor, mock_execution_engine, sample_files
    ):
        """Test that batch processing handles task failures"""
        # Setup mixed results with correct task ID format
        mock_execution_engine.task_results = {
            "process-test_file_0-txt-0": Mock(
                status="completed",
                result={"response": "Success"}
            ),
            "process-test_file_1-txt-1": Mock(
                status="failed",
                result=None,
                error="Processing error"
            ),
            "process-test_file_2-txt-2": Mock(
                status="completed",
                result={"response": "Success"}
            )
        }
        
        result = await batch_processor.process_batch(
            execution_engine=mock_execution_engine,
            files=sample_files,
            prompt="Test"
        )
        
        assert result.successful == 2
        assert result.failed == 1
        assert result.total_files == 3
    
    @pytest.mark.asyncio
    async def test_process_batch_raises_without_files_or_directory(
        self, batch_processor, mock_execution_engine
    ):
        """Test that process_batch requires either files or directory"""
        with pytest.raises(TaskValidationError, match="Either 'files' or 'directory'"):
            await batch_processor.process_batch(
                execution_engine=mock_execution_engine,
                prompt="Test"
            )
    
    @pytest.mark.asyncio
    async def test_process_batch_saves_results(
        self, batch_processor, mock_execution_engine, sample_files, temp_dir
    ):
        """Test that batch results are saved to file"""
        mock_execution_engine.task_results = {}
        
        with patch.object(BatchResult, 'save_to_file') as mock_save:
            mock_save.return_value = temp_dir / "batch_result.json"
            
            result = await batch_processor.process_batch(
                execution_engine=mock_execution_engine,
                files=sample_files,
                prompt="Test"
            )
            
            mock_save.assert_called_once()
    
    # ==================== BatchResult Tests ====================
    
    def test_batch_result_to_dict(self):
        """Test BatchResult serialization to dict"""
        result = BatchResult("test-batch-123")
        result.total_files = 2
        result.successful = 1
        result.failed = 1
        result.results = {
            "file1.txt": {"status": "success", "content": "Result 1"},
            "file2.txt": {"status": "failed", "error": "Error message"}
        }
        
        data = result.to_dict()
        
        assert data["batch_id"] == "test-batch-123"
        assert data["summary"]["total"] == 2
        assert data["summary"]["successful"] == 1
        assert data["summary"]["failed"] == 1
        assert "results" in data
    
    def test_batch_result_to_markdown(self):
        """Test BatchResult markdown formatting"""
        result = BatchResult("test-batch")
        result.total_files = 2
        result.successful = 1
        result.failed = 1
        result.results = {
            "success.txt": {"status": "success", "content": "Processed successfully"},
            "failed.txt": {"status": "failed", "error": "Processing failed"}
        }
        
        markdown = result.to_markdown()
        
        assert "# Batch Processing Results" in markdown
        assert "✅ success.txt" in markdown
        assert "❌ failed.txt" in markdown
        assert "Processed successfully" in markdown
        assert "Processing failed" in markdown
    
    def test_batch_result_truncates_long_content(self):
        """Test that long content is truncated in markdown"""
        result = BatchResult("test")
        long_content = "x" * 1000
        result.results = {
            "file.txt": {"status": "success", "content": long_content}
        }
        
        markdown = result.to_markdown()
        
        assert len(markdown) < 2000  # Should be truncated
        assert "..." in markdown
    
    # ==================== History Tracking Tests ====================
    
    @pytest.mark.asyncio
    async def test_batch_processor_tracks_history(
        self, batch_processor, mock_execution_engine, sample_files
    ):
        """Test that batch processor maintains history"""
        mock_execution_engine.task_results = {}
        
        result = await batch_processor.process_batch(
            execution_engine=mock_execution_engine,
            files=sample_files,
            prompt="Test"
        )
        
        assert batch_processor.current_batch == result
        assert result.batch_id in batch_processor.batch_history
    
    # ==================== Performance Tests ====================
    
    @pytest.mark.asyncio
    async def test_process_batch_measures_time(
        self, batch_processor, mock_execution_engine, sample_files, performance_timer
    ):
        """Test that batch processing measures execution time"""
        mock_execution_engine.task_results = {}
        
        performance_timer.start()
        result = await batch_processor.process_batch(
            execution_engine=mock_execution_engine,
            files=sample_files,
            prompt="Test"
        )
        performance_timer.stop()
        
        assert result.processing_time > 0
        assert result.processing_time <= performance_timer.duration