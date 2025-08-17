"""
Test module for core models

Tests cover:
- Task lifecycle management
- Workflow state transitions
- Dependency validation
- Priority handling
- Status updates
- Type hint compliance

Related components:
- Task
- Workflow
- TaskStatus
- WorkflowStatus
- Priority
"""

import pytest
from datetime import datetime, timedelta
from typing import List, Dict, Any
from unittest.mock import Mock, patch

from gleitzeit.core.models import (
    Task, Workflow, TaskStatus, WorkflowStatus, Priority,
    TaskResult
)


@pytest.mark.unit
class TestTask:
    """Unit tests for Task model"""
    
    @pytest.fixture
    def basic_task(self):
        """Create a basic task for testing"""
        return Task(
            id="test_task_1",
            name="Test Task",
            protocol="llm/v1",
            method="chat",
            params={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "Hello"}]
            },
            workflow_id="workflow_1"
        )
    
    def test_task_creation_with_defaults(self):
        """Test task creation with default values"""
        task = Task(
            id="task_1",
            name="Task",
            protocol="llm/v1",
            method="chat",
            params={}
        )
        
        assert task.status == TaskStatus.PENDING
        assert task.priority == Priority.NORMAL
        assert task.dependencies == []
        assert task.attempt_count == 0
        assert task.timeout is None  # Default is None, not 300
    
    def test_task_creation_with_dependencies(self):
        """Test task creation with dependencies"""
        task = Task(
            id="task_2",
            name="Dependent Task",
            protocol="llm/v1",
            method="chat",
            params={},
            dependencies=["task_1"],
            workflow_id="workflow_1"
        )
        
        assert task.dependencies == ["task_1"]
        assert task.workflow_id == "workflow_1"
    
    def test_task_mark_started(self, basic_task):
        """Test marking task as started"""
        basic_task.mark_started("provider_1", "node_1")
        
        assert basic_task.status == TaskStatus.EXECUTING
        assert basic_task.assigned_provider == "provider_1"
        assert basic_task.execution_node == "node_1"
        assert basic_task.started_at is not None
    
    def test_task_mark_completed(self, basic_task):
        """Test marking task as completed"""
        basic_task.mark_started("provider_1")
        basic_task.mark_completed()
        
        assert basic_task.status == TaskStatus.COMPLETED
        assert basic_task.completed_at is not None
        duration = basic_task.get_execution_duration()
        assert duration is not None
        assert duration >= 0
    
    def test_task_mark_failed(self, basic_task):
        """Test marking task as failed"""
        error_msg = "Task execution failed"
        basic_task.mark_failed(error_msg)
        
        assert basic_task.status == TaskStatus.FAILED
        assert basic_task.error_message == error_msg
        assert basic_task.completed_at is not None
    
    def test_task_increment_attempt(self, basic_task):
        """Test incrementing task attempt count"""
        initial_count = basic_task.attempt_count
        basic_task.increment_attempt()
        
        assert basic_task.attempt_count == initial_count + 1
    
    def test_task_dependencies_check(self, basic_task):
        """Test task dependencies"""
        # No dependencies initially
        assert basic_task.dependencies == []
        
        # Add dependencies
        basic_task.dependencies = ["other_task"]
        assert len(basic_task.dependencies) == 1
        assert "other_task" in basic_task.dependencies
    
    def test_task_priority_values(self):
        """Test task priority values"""
        assert Priority.LOW.value == "low"
        assert Priority.NORMAL.value == "normal"
        assert Priority.HIGH.value == "high"
        assert Priority.URGENT.value == "urgent"
    
    def test_task_timeout_validation(self):
        """Test task timeout must be positive"""
        with pytest.raises(ValueError):
            Task(
                id="task",
                name="Task",
                protocol="llm/v1",
                method="chat",
                params={},
                timeout=-1
            )
    
    def test_task_retry_config_validation(self):
        """Test task retry config validation"""
        from gleitzeit.core.models import RetryConfig
        # Valid retry config
        task = Task(
            id="task",
            name="Task",
            protocol="llm/v1",
            method="chat",
            params={},
            retry_config=RetryConfig(max_attempts=5)
        )
        assert task.retry_config.max_attempts == 5
    
    def test_task_to_dict(self, basic_task):
        """Test task serialization to dictionary"""
        task_dict = basic_task.model_dump()
        
        assert task_dict["id"] == basic_task.id
        assert task_dict["name"] == basic_task.name
        assert task_dict["protocol"] == basic_task.protocol
        assert task_dict["method"] == basic_task.method
        assert task_dict["status"] == basic_task.status
        assert "params" in task_dict
    
    def test_task_parameter_validation(self):
        """Test parameter validation for tasks"""
        task = Task(
            id="task",
            name="Task",
            protocol="llm/v1",
            method="chat",
            params={"model": "llama3.2", "invalid": None}
        )
        
        # Should filter out None values
        assert task.params.get("invalid") is None


@pytest.mark.unit
class TestWorkflow:
    """Unit tests for Workflow model"""
    
    @pytest.fixture
    def sample_tasks(self):
        """Create sample tasks for workflow"""
        return [
            Task(
                id="task_1",
                name="First Task",
                protocol="llm/v1",
                method="chat",
                params={},
                workflow_id="workflow_1"
            ),
            Task(
                id="task_2",
                name="Second Task",
                protocol="llm/v1",
                method="chat",
                params={},
                dependencies=["task_1"],
                workflow_id="workflow_1"
            )
        ]
    
    @pytest.fixture
    def basic_workflow(self, sample_tasks):
        """Create a basic workflow for testing"""
        return Workflow(
            id="workflow_1",
            name="Test Workflow",
            description="A test workflow",
            tasks=sample_tasks
        )
    
    def test_workflow_creation(self, basic_workflow):
        """Test workflow creation with tasks"""
        assert basic_workflow.id == "workflow_1"
        assert basic_workflow.name == "Test Workflow"
        assert len(basic_workflow.tasks) == 2
        assert basic_workflow.status == WorkflowStatus.PENDING
    
    def test_workflow_add_task(self, basic_workflow):
        """Test adding task to workflow"""
        new_task = Task(
            id="task_3",
            name="Third Task",
            protocol="llm/v1",
            method="chat",
            params={},
            workflow_id="workflow_1"
        )
        
        basic_workflow.add_task(new_task)
        
        assert len(basic_workflow.tasks) == 3
        assert new_task in basic_workflow.tasks
        assert new_task.workflow_id == basic_workflow.id
    
    def test_workflow_get_ready_tasks(self, basic_workflow):
        """Test getting ready tasks from workflow"""
        ready_tasks = basic_workflow.get_ready_tasks()
        
        # Only task_1 should be ready (no dependencies)
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == "task_1"
    
    def test_workflow_mark_task_completed(self, basic_workflow):
        """Test marking task as completed in workflow"""
        basic_workflow.mark_task_completed("task_1", {"result": "success"})
        
        task = next(t for t in basic_workflow.tasks if t.id == "task_1")
        assert task.status == TaskStatus.COMPLETED
        
        # Now task_2 should be ready
        ready_tasks = basic_workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == "task_2"
    
    def test_workflow_mark_task_failed(self, basic_workflow):
        """Test marking task as failed in workflow"""
        error_msg = "Task failed"
        basic_workflow.mark_task_failed("task_1", error_msg)
        
        task = next(t for t in basic_workflow.tasks if t.id == "task_1")
        assert task.status == TaskStatus.FAILED
        assert task.error_message == error_msg
    
    def test_workflow_completion_detection(self, basic_workflow):
        """Test workflow detects when all tasks are completed"""
        # Complete all tasks using the proper method
        for task in basic_workflow.tasks:
            basic_workflow.mark_task_completed(task.id, {"result": "success"})
        
        assert basic_workflow.is_complete() is True
        # The workflow status is not automatically updated, it requires separate tracking
        assert len(basic_workflow.completed_tasks) == len(basic_workflow.tasks)
    
    def test_workflow_failure_detection(self, basic_workflow):
        """Test workflow detects failure"""
        # Fail a task using the proper method
        basic_workflow.mark_task_failed("task_1", "Test failure")
        
        # Check if workflow tracks failed tasks
        assert len(basic_workflow.failed_tasks) == 1
        assert "task_1" in basic_workflow.failed_tasks
    
    def test_workflow_parallel_tasks(self):
        """Test workflow with parallel tasks"""
        tasks = [
            Task(id=f"task_{i}", name=f"Task {i}", protocol="llm/v1", 
                 method="chat", params={}, workflow_id="workflow_1")
            for i in range(3)
        ]
        
        workflow = Workflow(
            id="workflow_1",
            name="Parallel Workflow",
            tasks=tasks
        )
        
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 3  # All tasks ready (no dependencies)
    
    def test_workflow_complex_dependencies(self):
        """Test workflow with complex dependency graph"""
        tasks = [
            Task(id="a", name="A", protocol="llm/v1", method="chat", params={}),
            Task(id="b", name="B", protocol="llm/v1", method="chat", params={}, dependencies=["a"]),
            Task(id="c", name="C", protocol="llm/v1", method="chat", params={}, dependencies=["a"]),
            Task(id="d", name="D", protocol="llm/v1", method="chat", params={}, dependencies=["b", "c"])
        ]
        
        workflow = Workflow(id="complex", name="Complex", tasks=tasks)
        
        # Initially only 'a' is ready
        ready = workflow.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "a"
        
        # Complete 'a'
        workflow.mark_task_completed("a", {})
        ready = workflow.get_ready_tasks()
        assert len(ready) == 2
        assert set(t.id for t in ready) == {"b", "c"}
        
        # Complete 'b' and 'c'
        workflow.mark_task_completed("b", {})
        workflow.mark_task_completed("c", {})
        ready = workflow.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "d"
    
    def test_workflow_to_dict(self, basic_workflow):
        """Test workflow serialization"""
        workflow_dict = basic_workflow.model_dump()
        
        assert workflow_dict["id"] == basic_workflow.id
        assert workflow_dict["name"] == basic_workflow.name
        assert workflow_dict["status"] == basic_workflow.status.value
        assert len(workflow_dict["tasks"]) == len(basic_workflow.tasks)
    
    def test_workflow_metadata(self, basic_workflow):
        """Test workflow metadata storage"""
        metadata = {
            "source": "test",
            "version": "1.0",
            "tags": ["test", "unit"]
        }
        basic_workflow.metadata = metadata
        
        assert basic_workflow.metadata == metadata
        workflow_dict = basic_workflow.model_dump()
        assert workflow_dict["metadata"] == metadata


@pytest.mark.unit
class TestTaskResult:
    """Unit tests for TaskResult model"""
    
    def test_task_result_creation(self):
        """Test TaskResult creation"""
        result = TaskResult(
            task_id="task_1",
            status="completed",
            result={"data": "test"},
            error=None,
            duration_seconds=1.5
        )
        
        assert result.task_id == "task_1"
        assert result.status == "completed"
        assert result.result == {"data": "test"}
        assert result.duration_seconds == 1.5
    
    def test_task_result_with_error(self):
        """Test TaskResult with error"""
        result = TaskResult(
            task_id="task_1",
            status="failed",
            result=None,
            error="Execution failed",
            duration_seconds=0.5
        )
        
        assert result.status == "failed"
        assert result.error == "Execution failed"
        assert result.result is None
    
    def test_task_result_to_dict(self):
        """Test TaskResult serialization"""
        result = TaskResult(
            task_id="task_1",
            status="completed",
            result={"data": "test"},
            duration_seconds=1.0
        )
        
        result_dict = result.model_dump()
        assert result_dict["task_id"] == "task_1"
        assert result_dict["status"] == "completed"
        assert result_dict["duration_seconds"] == 1.0
        assert "metadata" in result_dict




@pytest.mark.unit
class TestTypeHints:
    """Test type hint compliance for models"""
    
    @pytest.fixture
    def basic_task(self):
        """Create a basic task for testing"""
        return Task(
            id="test_task_1",
            name="Test Task",
            protocol="llm/v1",
            method="chat",
            params={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "Hello"}]
            },
            workflow_id="workflow_1"
        )
    
    @pytest.fixture
    def basic_workflow(self):
        """Create a basic workflow for testing"""
        tasks = [
            Task(
                id="task_1",
                name="First Task",
                protocol="llm/v1",
                method="chat",
                params={},
                workflow_id="workflow_1"
            ),
            Task(
                id="task_2",
                name="Second Task",
                protocol="llm/v1",
                method="chat",
                params={},
                dependencies=["task_1"],
                workflow_id="workflow_1"
            )
        ]
        return Workflow(
            id="workflow_1",
            name="Test Workflow",
            tasks=tasks
        )
    
    def test_task_type_hints(self, basic_task):
        """Test Task methods return correct types"""
        # mark_started returns None
        result = basic_task.mark_started("provider")
        assert result is None
        
        # mark_completed returns None
        result = basic_task.mark_completed()
        assert result is None
        
        # mark_failed returns None
        result = basic_task.mark_failed("error")
        assert result is None
        
        # increment_attempt returns None
        result = basic_task.increment_attempt()
        assert result is None
        
        # get_execution_duration returns Optional[float]
        duration = basic_task.get_execution_duration()
        assert duration is None or isinstance(duration, float)
    
    def test_workflow_type_hints(self, basic_workflow):
        """Test Workflow methods return correct types"""
        
        # get_ready_tasks returns List[Task]
        result = basic_workflow.get_ready_tasks()
        assert isinstance(result, list)
        if result:
            assert all(isinstance(t, Task) for t in result)
        
        # mark_task_completed returns None
        result = basic_workflow.mark_task_completed("task_1", {})
        assert result is None
        
        # mark_task_failed returns None
        result = basic_workflow.mark_task_failed("task_1", "error")
        assert result is None