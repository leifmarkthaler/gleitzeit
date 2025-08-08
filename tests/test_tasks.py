"""
Tests for Task functionality
"""

import pytest
from datetime import datetime
from unittest.mock import Mock

from gleitzeit_cluster.core.task import (
    Task, TaskType, TaskStatus, TaskPriority, 
    TaskParameters, TaskRequirements, TaskResult
)


class TestTask:
    """Test Task class functionality"""
    
    def test_task_creation(self):
        """Test basic task creation"""
        task = Task(
            name="test_task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="test_function",
                kwargs={"param1": "value1"}
            )
        )
        
        assert task.name == "test_task"
        assert task.task_type == TaskType.FUNCTION
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.NORMAL
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert isinstance(task.created_at, datetime)
        assert task.id is not None
    
    def test_task_with_requirements(self):
        """Test task with resource requirements"""
        requirements = TaskRequirements(
            cpu_cores=2.0,
            memory_mb=1024,
            requires_gpu=True,
            required_models=["llama3"]
        )
        
        task = Task(
            name="gpu_task",
            task_type=TaskType.VISION,
            requirements=requirements
        )
        
        assert task.requirements.cpu_cores == 2.0
        assert task.requirements.memory_mb == 1024
        assert task.requirements.requires_gpu is True
        assert "llama3" in task.requirements.required_models
    
    def test_task_dependencies(self):
        """Test task dependency handling"""
        task = Task(
            name="dependent_task",
            task_type=TaskType.TEXT,
            dependencies=["task1", "task2"]
        )
        
        # Should not be ready with incomplete dependencies
        assert not task.is_ready_to_execute(set())
        assert not task.is_ready_to_execute({"task1"})
        
        # Should be ready when all dependencies are completed
        assert task.is_ready_to_execute({"task1", "task2"})
        assert task.is_ready_to_execute({"task1", "task2", "task3"})
    
    def test_task_status_updates(self):
        """Test task status update mechanism"""
        task = Task(name="status_test", task_type=TaskType.FUNCTION)
        
        # Test queued status
        task.update_status(TaskStatus.QUEUED)
        assert task.status == TaskStatus.QUEUED
        assert task.queued_at is not None
        
        # Test processing status
        task.update_status(TaskStatus.PROCESSING)
        assert task.status == TaskStatus.PROCESSING
        assert task.started_at is not None
        
        # Test completion
        task.update_status(TaskStatus.COMPLETED)
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        
        # Test failure with error
        task.update_status(TaskStatus.FAILED, "Test error")
        assert task.status == TaskStatus.FAILED
        assert task.error == "Test error"
    
    def test_retry_logic(self):
        """Test task retry functionality"""
        task = Task(
            name="retry_test",
            task_type=TaskType.FUNCTION,
            max_retries=2
        )
        
        # Fresh task should not be retryable
        assert not task.can_retry()
        
        # Failed task should be retryable
        task.update_status(TaskStatus.FAILED, "Connection error")
        assert task.can_retry()
        
        # After first retry
        task.retry_count = 1
        assert task.can_retry()
        
        # After max retries reached
        task.retry_count = 2
        assert not task.can_retry()
    
    def test_task_serialization(self):
        """Test task to/from dict conversion"""
        task = Task(
            name="serialize_test",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Test prompt",
                model_name="llama3"
            ),
            dependencies=["dep1"],
            metadata={"custom": "value"}
        )
        
        # Convert to dict
        task_dict = task.to_dict()
        assert isinstance(task_dict, dict)
        assert task_dict["name"] == "serialize_test"
        assert task_dict["task_type"] == "text"
        assert task_dict["dependencies"] == ["dep1"]
        
        # Convert back from dict
        restored_task = Task.from_dict(task_dict)
        assert restored_task.name == task.name
        assert restored_task.task_type == task.task_type
        assert restored_task.dependencies == task.dependencies
        assert restored_task.metadata == task.metadata


class TestTaskParameters:
    """Test TaskParameters functionality"""
    
    def test_text_parameters(self):
        """Test text task parameters"""
        params = TaskParameters(
            prompt="Test prompt",
            model_name="llama3",
            temperature=0.8,
            max_tokens=100
        )
        
        assert params.prompt == "Test prompt"
        assert params.model_name == "llama3"
        assert params.temperature == 0.8
        assert params.max_tokens == 100
    
    def test_vision_parameters(self):
        """Test vision task parameters"""
        params = TaskParameters(
            prompt="Describe this image",
            image_path="/path/to/image.jpg",
            model_name="llava"
        )
        
        assert params.prompt == "Describe this image"
        assert params.image_path == "/path/to/image.jpg"
        assert params.model_name == "llava"
    
    def test_function_parameters(self):
        """Test function task parameters"""
        params = TaskParameters(
            function_name="fibonacci",
            args=[10],
            kwargs={"start": 0, "step": 1}
        )
        
        assert params.function_name == "fibonacci"
        assert params.args == [10]
        assert params.kwargs == {"start": 0, "step": 1}
    
    def test_http_parameters(self):
        """Test HTTP task parameters"""
        params = TaskParameters(
            url="https://api.example.com/data",
            method="POST",
            headers={"Content-Type": "application/json"},
            data={"key": "value"}
        )
        
        assert params.url == "https://api.example.com/data"
        assert params.method == "POST"
        assert params.headers["Content-Type"] == "application/json"
        assert params.data == {"key": "value"}


class TestTaskResult:
    """Test TaskResult functionality"""
    
    def test_result_creation(self):
        """Test task result creation"""
        result = TaskResult(
            task_id="test_task_123",
            status=TaskStatus.COMPLETED,
            result="Task completed successfully",
            execution_time_seconds=1.5,
            executor_node_id="node_1"
        )
        
        assert result.task_id == "test_task_123"
        assert result.status == TaskStatus.COMPLETED
        assert result.result == "Task completed successfully"
        assert result.execution_time_seconds == 1.5
        assert result.executor_node_id == "node_1"
    
    def test_failed_result(self):
        """Test failed task result"""
        result = TaskResult(
            task_id="failed_task",
            status=TaskStatus.FAILED,
            error="Connection timeout",
            execution_time_seconds=30.0
        )
        
        assert result.status == TaskStatus.FAILED
        assert result.error == "Connection timeout"
        assert result.result is None


@pytest.mark.unit
class TestTaskTypes:
    """Test TaskType enum and related functionality"""
    
    def test_task_type_values(self):
        """Test TaskType enum values"""
        assert TaskType.TEXT.value == "text"
        assert TaskType.VISION.value == "vision"
        assert TaskType.FUNCTION.value == "function"
        assert TaskType.HTTP.value == "http"
        assert TaskType.FILE.value == "file"
    
    def test_legacy_task_type_mapping(self):
        """Test legacy TaskType name mapping"""
        # Test _missing_ method handles legacy names
        assert TaskType._missing_("text_prompt") == TaskType.TEXT
        assert TaskType._missing_("vision_task") == TaskType.VISION
        assert TaskType._missing_("python_function") == TaskType.FUNCTION
        assert TaskType._missing_("http_request") == TaskType.HTTP
        assert TaskType._missing_("file_operation") == TaskType.FILE
        
        # Test unknown value returns None
        assert TaskType._missing_("unknown_type") is None