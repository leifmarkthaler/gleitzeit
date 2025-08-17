"""
Simple test module for core models - matches actual model structure

Tests cover:
- Task creation and validation
- Workflow operations
- TaskResult handling
- Status enums

Related components:
- Task
- Workflow
- TaskStatus
- WorkflowStatus
- Priority
"""

import pytest
from datetime import datetime
from typing import Dict, Any

from gleitzeit.core.models import (
    Task, Workflow, TaskStatus, WorkflowStatus, Priority, TaskResult
)


@pytest.mark.unit
class TestTaskModel:
    """Test Task model functionality"""
    
    def test_task_creation_minimal(self):
        """Test creating task with minimal required fields"""
        task = Task(
            name="Test Task",
            protocol="llm/v1",
            method="chat",
            params={"model": "test"}
        )
        
        assert task.name == "Test Task"
        assert task.protocol == "llm/v1"
        assert task.method == "chat"
        assert task.priority == Priority.NORMAL
        assert task.dependencies == []
    
    def test_task_with_dependencies(self):
        """Test task with dependencies"""
        task = Task(
            name="Dependent Task",
            protocol="llm/v1",
            method="chat",
            params={},
            dependencies=["task_1", "task_2"]
        )
        
        assert set(task.dependencies) == {"task_1", "task_2"}
    
    def test_task_priority_levels(self):
        """Test different priority levels"""
        high_task = Task(
            name="High Priority",
            protocol="llm/v1", 
            method="chat",
            params={},
            priority=Priority.HIGH
        )
        
        assert high_task.priority == Priority.HIGH
        assert high_task.priority == "high"  # Enum value
    
    def test_task_protocol_validation(self):
        """Test protocol field validation"""
        # Valid protocols
        valid_protocols = ["llm/v1", "mcp/v1", "python/v1", "custom-proto/v2"]
        
        for proto in valid_protocols:
            task = Task(
                name="Test",
                protocol=proto,
                method="test",
                params={}
            )
            assert task.protocol == proto
    
    def test_task_timeout_validation(self):
        """Test timeout field validation"""
        task = Task(
            name="Test",
            protocol="llm/v1",
            method="chat",
            params={},
            timeout=300
        )
        
        assert task.timeout == 300
        
        # Test invalid timeout (should raise validation error)
        with pytest.raises(Exception):  # Pydantic ValidationError
            Task(
                name="Test",
                protocol="llm/v1",
                method="chat",
                params={},
                timeout=-1  # Negative timeout not allowed
            )


@pytest.mark.unit
class TestWorkflowModel:
    """Test Workflow model functionality"""
    
    def test_workflow_creation(self):
        """Test creating workflow"""
        tasks = [
            Task(name="Task 1", protocol="llm/v1", method="chat", params={}),
            Task(name="Task 2", protocol="llm/v1", method="chat", params={})
        ]
        
        workflow = Workflow(
            name="Test Workflow",
            description="A test workflow",
            tasks=tasks
        )
        
        assert workflow.name == "Test Workflow"
        assert len(workflow.tasks) == 2
        assert workflow.status == WorkflowStatus.PENDING
    
    def test_workflow_status_values(self):
        """Test workflow status enum values"""
        workflow = Workflow(
            name="Test",
            tasks=[]
        )
        
        # Check default status
        assert workflow.status == WorkflowStatus.PENDING
        assert workflow.status == "pending"
        
        # Update status
        workflow.status = WorkflowStatus.RUNNING
        assert workflow.status == "running"


@pytest.mark.unit  
class TestTaskResult:
    """Test TaskResult model"""
    
    def test_task_result_creation(self):
        """Test creating task result"""
        result = TaskResult(
            task_id="task_123",
            status=TaskStatus.COMPLETED,
            result={"data": "test"}
        )
        
        assert result.task_id == "task_123"
        assert result.status == TaskStatus.COMPLETED
        assert result.result == {"data": "test"}
    
    def test_task_result_with_error(self):
        """Test task result with error"""
        result = TaskResult(
            task_id="task_456",
            status=TaskStatus.FAILED,
            error="Connection timeout"
        )
        
        assert result.status == TaskStatus.FAILED
        assert result.error == "Connection timeout"
        assert result.result is None
    
    def test_task_result_duration_calculation(self):
        """Test duration calculation"""
        start = datetime.now()
        end = datetime.now()
        
        result = TaskResult(
            task_id="task_789",
            status=TaskStatus.COMPLETED,
            started_at=start,
            completed_at=end,
            duration_seconds=1.5
        )
        
        assert result.duration_seconds == 1.5


@pytest.mark.unit
class TestEnums:
    """Test enum values"""
    
    def test_task_status_values(self):
        """Test TaskStatus enum values"""
        expected_statuses = [
            "queued", "validated", "routed", "executing",
            "completed", "failed", "cancelled", "retry_pending"
        ]
        
        actual_statuses = [status.value for status in TaskStatus]
        
        for expected in expected_statuses:
            assert expected in actual_statuses
    
    def test_workflow_status_values(self):
        """Test WorkflowStatus enum values"""
        expected_statuses = [
            "pending", "running", "completed", "failed", "cancelled"
        ]
        
        actual_statuses = [status.value for status in WorkflowStatus]
        
        for expected in expected_statuses:
            assert expected in actual_statuses
    
    def test_priority_values(self):
        """Test Priority enum values"""
        expected_priorities = ["low", "normal", "high", "urgent"]
        
        actual_priorities = [priority.value for priority in Priority]
        
        for expected in expected_priorities:
            assert expected in actual_priorities