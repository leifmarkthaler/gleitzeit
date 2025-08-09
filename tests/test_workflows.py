"""
Tests for Workflow functionality
"""

import pytest
from unittest.mock import Mock

from gleitzeit_cluster.core.workflow import (
    Workflow, WorkflowStatus, WorkflowErrorStrategy, WorkflowResult
)
from gleitzeit_cluster.core.task import Task, TaskType, TaskParameters, TaskStatus


class TestWorkflow:
    """Test Workflow class functionality"""
    
    def test_workflow_creation(self):
        """Test basic workflow creation"""
        workflow = Workflow(
            name="test_workflow",
            description="Test workflow for unit testing"
        )
        
        assert workflow.name == "test_workflow"
        assert workflow.description == "Test workflow for unit testing"
        assert workflow.status == WorkflowStatus.PENDING
        assert workflow.error_strategy == WorkflowErrorStrategy.CONTINUE_ON_ERROR
        assert len(workflow.tasks) == 0
        assert len(workflow.task_order) == 0
        assert workflow.id is not None
    
    def test_add_task(self):
        """Test adding tasks to workflow"""
        workflow = Workflow(name="task_test")
        
        task = Task(
            name="test_task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(function_name="test_func")
        )
        
        workflow.add_task(task)
        
        assert task.id in workflow.tasks
        assert task.id in workflow.task_order
        assert task.workflow_id == workflow.id
        assert len(workflow.tasks) == 1
    
    def test_add_text_task_convenience(self):
        """Test add_text_task convenience method"""
        workflow = Workflow(name="text_workflow")
        
        task = workflow.add_text_task(
            name="analyze_text",
            prompt="Analyze this text",
            model="llama3",
            dependencies=["prev_task"]
        )
        
        assert task.name == "analyze_text"
        assert task.task_type == TaskType.TEXT
        assert task.parameters.prompt == "Analyze this text"
        assert task.parameters.model == "llama3"
        assert task.dependencies == ["prev_task"]
        assert task.id in workflow.tasks
    
    def test_add_vision_task_convenience(self):
        """Test add_vision_task convenience method"""
        workflow = Workflow(name="vision_workflow")
        
        task = workflow.add_vision_task(
            name="analyze_image",
            prompt="Describe this image",
            image_path="/path/to/image.jpg",
            model="llava"
        )
        
        assert task.name == "analyze_image"
        assert task.task_type == TaskType.VISION
        assert task.parameters.prompt == "Describe this image"
        assert task.parameters.image_path == "/path/to/image.jpg"
        assert task.parameters.model == "llava"
        assert task.requirements.requires_gpu is True
    
    def test_add_python_task_convenience(self):
        """Test add_python_task convenience method"""
        workflow = Workflow(name="python_workflow")
        
        task = workflow.add_python_task(
            name="calculate",
            function_name="fibonacci",
            args=[10],
            kwargs={"start": 0},
            dependencies=["data_prep"]
        )
        
        assert task.name == "calculate"
        assert task.task_type == TaskType.FUNCTION
        assert task.parameters.function_name == "fibonacci"
        assert task.parameters.args == [10]
        assert task.parameters.kwargs == {"start": 0}
        assert task.dependencies == ["data_prep"]
    
    def test_workflow_dependencies(self):
        """Test workflow dependency resolution"""
        workflow = Workflow(name="dependency_test")
        
        # Add tasks with dependencies
        task1 = Task(id="task1", name="First", task_type=TaskType.FUNCTION)
        task2 = Task(id="task2", name="Second", task_type=TaskType.FUNCTION, dependencies=["task1"])
        task3 = Task(id="task3", name="Third", task_type=TaskType.FUNCTION, dependencies=["task1", "task2"])
        
        workflow.add_task(task1)
        workflow.add_task(task2)
        workflow.add_task(task3)
        
        # Initially, only task1 should be ready
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == "task1"
        
        # After completing task1, task2 should be ready
        workflow.completed_tasks.add("task1")
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == "task2"
        
        # After completing task2, task3 should be ready
        workflow.completed_tasks.add("task2")
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == "task3"
    
    def test_workflow_progress(self):
        """Test workflow progress calculation"""
        workflow = Workflow(name="progress_test")
        
        # Add three tasks
        for i in range(3):
            task = Task(id=f"task_{i}", name=f"Task {i}", task_type=TaskType.FUNCTION)
            workflow.add_task(task)
        
        # No tasks completed
        progress = workflow.get_progress()
        assert progress["total_tasks"] == 3
        assert progress["completed_tasks"] == 0
        assert progress["failed_tasks"] == 0
        assert progress["progress_percent"] == 0.0
        
        # Complete one task
        workflow.completed_tasks.add("task_0")
        progress = workflow.get_progress()
        assert progress["completed_tasks"] == 1
        assert abs(progress["progress_percent"] - 33.33) < 0.1
        
        # Fail one task
        workflow.failed_tasks.add("task_1")
        progress = workflow.get_progress()
        assert progress["failed_tasks"] == 1
        assert progress["completed_tasks"] == 1
        
        # Complete remaining task
        workflow.completed_tasks.add("task_2")
        progress = workflow.get_progress()
        assert progress["completed_tasks"] == 2
        assert abs(progress["progress_percent"] - 66.67) < 0.1
    
    def test_error_strategies(self):
        """Test different workflow error strategies"""
        # Stop on first error
        workflow_stop = Workflow(
            name="stop_on_error",
            error_strategy=WorkflowErrorStrategy.STOP_ON_FIRST_ERROR
        )
        
        task1 = Task(id="task1", name="Task1", task_type=TaskType.FUNCTION)
        task2 = Task(id="task2", name="Task2", task_type=TaskType.FUNCTION)
        workflow_stop.add_task(task1)
        workflow_stop.add_task(task2)
        
        # Simulate task failure
        workflow_stop.failed_tasks.add("task1")
        
        # Should stop execution
        assert workflow_stop.should_stop_on_error()
        
        # Continue on error
        workflow_continue = Workflow(
            name="continue_on_error",
            error_strategy=WorkflowErrorStrategy.CONTINUE_ON_ERROR
        )
        
        workflow_continue.failed_tasks.add("task1")
        assert not workflow_continue.should_stop_on_error()
    
    def test_workflow_status_determination(self):
        """Test workflow status determination logic"""
        workflow = Workflow(name="status_test")
        
        # Add tasks
        for i in range(3):
            task = Task(id=f"task_{i}", name=f"Task {i}", task_type=TaskType.FUNCTION)
            workflow.add_task(task)
        
        # Pending state
        assert workflow.get_current_status() == WorkflowStatus.PENDING
        
        # Running state (some tasks completed, some pending)
        workflow.completed_tasks.add("task_0")
        workflow.current_tasks.add("task_1")  # Currently executing
        assert workflow.get_current_status() == WorkflowStatus.RUNNING
        
        # All completed
        workflow.completed_tasks.add("task_1")
        workflow.completed_tasks.add("task_2")
        workflow.current_tasks.clear()
        assert workflow.get_current_status() == WorkflowStatus.COMPLETED
        
        # Some failed
        workflow.failed_tasks.add("task_2")
        workflow.completed_tasks.remove("task_2")
        
        # With continue strategy, should still be completed if other tasks done
        workflow.error_strategy = WorkflowErrorStrategy.CONTINUE_ON_ERROR
        status = workflow.get_current_status()
        # Status depends on implementation - could be COMPLETED or FAILED
        assert status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]
    
    def test_workflow_validation(self):
        """Test workflow validation"""
        workflow = Workflow(name="validation_test")
        
        # Add tasks with circular dependency (should be detected)
        task1 = Task(id="task1", name="Task1", task_type=TaskType.FUNCTION, dependencies=["task2"])
        task2 = Task(id="task2", name="Task2", task_type=TaskType.FUNCTION, dependencies=["task1"])
        
        workflow.add_task(task1)
        workflow.add_task(task2)
        
        # Should detect circular dependency
        validation_result = workflow.validate()
        assert not validation_result["is_valid"]
        assert "circular" in validation_result["errors"][0].lower() or "cycle" in validation_result["errors"][0].lower()
    
    def test_workflow_serialization(self):
        """Test workflow to/from dict conversion"""
        workflow = Workflow(
            name="serialize_test",
            description="Test serialization",
            error_strategy=WorkflowErrorStrategy.RETRY_FAILED_TASKS,
            max_parallel_tasks=5
        )
        
        # Add a task
        task = Task(name="test_task", task_type=TaskType.FUNCTION)
        workflow.add_task(task)
        
        # Convert to dict
        workflow_dict = workflow.to_dict()
        assert isinstance(workflow_dict, dict)
        assert workflow_dict["name"] == "serialize_test"
        assert workflow_dict["description"] == "Test serialization"
        assert workflow_dict["max_parallel_tasks"] == 5
        
        # Convert back from dict
        restored_workflow = Workflow.from_dict(workflow_dict)
        assert restored_workflow.name == workflow.name
        assert restored_workflow.description == workflow.description
        assert restored_workflow.max_parallel_tasks == workflow.max_parallel_tasks
        assert len(restored_workflow.tasks) == 1


class TestWorkflowResult:
    """Test WorkflowResult functionality"""
    
    def test_result_creation(self):
        """Test workflow result creation"""
        result = WorkflowResult(
            workflow_id="test_workflow_123",
            status=WorkflowStatus.COMPLETED,
            total_tasks=5,
            completed_tasks=4,
            failed_tasks=1,
            execution_time_seconds=120.5,
            results={"task1": "result1", "task2": "result2"},
            errors={"task3": "Connection failed"}
        )
        
        assert result.workflow_id == "test_workflow_123"
        assert result.status == WorkflowStatus.COMPLETED
        assert result.total_tasks == 5
        assert result.completed_tasks == 4
        assert result.failed_tasks == 1
        assert result.execution_time_seconds == 120.5
        assert len(result.results) == 2
        assert len(result.errors) == 1


@pytest.mark.unit
class TestWorkflowUtilities:
    """Test workflow utility functions"""
    
    def test_task_ordering(self):
        """Test topological task ordering"""
        workflow = Workflow(name="ordering_test")
        
        # Create tasks with complex dependencies
        # task1 -> task2 -> task4
        #       -> task3 -> task4
        task1 = Task(id="task1", name="Start", task_type=TaskType.FUNCTION)
        task2 = Task(id="task2", name="Branch A", task_type=TaskType.FUNCTION, dependencies=["task1"])
        task3 = Task(id="task3", name="Branch B", task_type=TaskType.FUNCTION, dependencies=["task1"])
        task4 = Task(id="task4", name="Merge", task_type=TaskType.FUNCTION, dependencies=["task2", "task3"])
        
        workflow.add_task(task1)
        workflow.add_task(task2)
        workflow.add_task(task3)
        workflow.add_task(task4)
        
        # Get execution order
        ordered_tasks = workflow.get_execution_order()
        
        # task1 should be first
        assert ordered_tasks[0].id == "task1"
        
        # task4 should be last
        assert ordered_tasks[-1].id == "task4"
        
        # task2 and task3 should be after task1 but before task4
        task2_idx = next(i for i, t in enumerate(ordered_tasks) if t.id == "task2")
        task3_idx = next(i for i, t in enumerate(ordered_tasks) if t.id == "task3")
        task4_idx = next(i for i, t in enumerate(ordered_tasks) if t.id == "task4")
        
        assert task2_idx > 0  # After task1
        assert task3_idx > 0  # After task1
        assert task4_idx > task2_idx  # After task2
        assert task4_idx > task3_idx  # After task3