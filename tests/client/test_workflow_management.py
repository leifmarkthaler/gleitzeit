"""
Tests for workflow management functionality in GleitzeitClient
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Task, Workflow, WorkflowExecution


class TestWorkflowSubmission:
    """Test workflow submission functionality"""
    
    @pytest.mark.asyncio
    async def test_submit_simple_workflow(self, client_with_mocks):
        """Test submitting a simple workflow"""
        tasks = [
            {
                "name": "task1",
                "protocol": "llm/v1",
                "method": "chat",
                "params": {"model": "llama3.2"}
            },
            {
                "name": "task2",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "print('hello')"}
            }
        ]
        
        workflow = await client_with_mocks.submit_workflow(
            name="Test Workflow",
            tasks=tasks
        )
        
        assert workflow.name == "Test Workflow"
        assert len(workflow.tasks) == 2
        client_with_mocks.adapter.save_workflow.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_workflow_with_dependencies(self, client_with_mocks):
        """Test submitting workflow with task dependencies"""
        tasks = [
            {
                "name": "fetch_data",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "data = [1,2,3]"}
            },
            {
                "name": "process_data",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "result = sum(data)"},
                "dependencies": ["fetch_data"]
            },
            {
                "name": "report",
                "protocol": "llm/v1",
                "method": "chat",
                "params": {"model": "llama3.2"},
                "dependencies": ["process_data"]
            }
        ]
        
        workflow = await client_with_mocks.submit_workflow(
            name="Data Pipeline",
            tasks=tasks
        )
        
        assert len(workflow.tasks) == 3
        
        # Check dependencies were set correctly
        assert workflow.tasks[1].dependencies == ["fetch_data"]
        assert workflow.tasks[2].dependencies == ["process_data"]
        
        # Verify tasks were saved
        assert client_with_mocks.adapter.save_task.call_count == 3
        
        # Verify workflow was saved
        client_with_mocks.adapter.save_workflow.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_workflow_with_metadata(self, client_with_mocks):
        """Test submitting workflow with metadata"""
        tasks = [{"name": "task1", "protocol": "llm/v1", "method": "chat"}]
        metadata = {
            "author": "test_user",
            "version": "1.0",
            "tags": ["test", "automated"]
        }
        
        workflow = await client_with_mocks.submit_workflow(
            name="Workflow with Metadata",
            tasks=tasks,
            metadata=metadata
        )
        
        assert workflow.metadata == metadata
    
    @pytest.mark.asyncio
    async def test_submit_workflow_with_priority(self, client_with_mocks):
        """Test that workflow tasks inherit priority"""
        tasks = [
            {
                "name": "high_priority_task",
                "protocol": "llm/v1",
                "method": "chat",
                "priority": 10
            },
            {
                "name": "normal_task",
                "protocol": "python/v1",
                "method": "execute"
            }
        ]
        
        workflow = await client_with_mocks.submit_workflow(
            name="Priority Workflow",
            tasks=tasks
        )
        
        # Check task priorities
        assert workflow.tasks[0].priority == 10
        assert workflow.tasks[1].priority == 0  # Default priority
    
    @pytest.mark.asyncio
    async def test_submit_empty_workflow(self, client_with_mocks):
        """Test submitting workflow with no tasks"""
        workflow = await client_with_mocks.submit_workflow(
            name="Empty Workflow",
            tasks=[]
        )
        
        assert workflow.name == "Empty Workflow"
        assert len(workflow.tasks) == 0
        client_with_mocks.adapter.save_workflow.assert_called_once()


class TestWorkflowRetrieval:
    """Test workflow retrieval functionality"""
    
    @pytest.mark.asyncio
    async def test_get_workflow(self, client_with_mocks, sample_workflow):
        """Test getting workflow by ID"""
        client_with_mocks.adapter.get_workflow.return_value = sample_workflow
        
        workflow = await client_with_mocks.get_workflow("wf-123")
        
        assert workflow is not None
        assert workflow.id == "wf-123"
        assert workflow.name == "Test Workflow"
        assert len(workflow.tasks) == 2
    
    @pytest.mark.asyncio
    async def test_get_workflow_not_found(self, client_with_mocks):
        """Test getting non-existent workflow"""
        client_with_mocks.adapter.get_workflow.return_value = None
        
        workflow = await client_with_mocks.get_workflow("nonexistent")
        
        assert workflow is None
    
    @pytest.mark.asyncio
    async def test_get_workflow_execution(self, client_with_mocks):
        """Test getting workflow execution details"""
        execution = WorkflowExecution(
            id="exec-123",
            workflow_id="wf-123",
            status="running",
            started_at="2024-01-01T00:00:00",
            metadata={"executor": "test"}
        )
        client_with_mocks.adapter.get_workflow_execution.return_value = execution
        
        result = await client_with_mocks.get_workflow_execution("exec-123")
        
        assert result is not None
        assert result.id == "exec-123"
        assert result.workflow_id == "wf-123"
        assert result.status == "running"
    
    @pytest.mark.asyncio
    async def test_get_workflow_tasks(self, client_with_mocks, sample_workflow):
        """Test getting tasks for a workflow"""
        client_with_mocks.adapter.get_workflow.return_value = sample_workflow
        
        tasks = await client_with_mocks.get_workflow_tasks("wf-123")
        
        assert len(tasks) == 2
        assert tasks[0].name == "First Task"
        assert tasks[1].name == "Second Task"
        assert tasks[1].dependencies == ["task-1"]
    
    @pytest.mark.asyncio
    async def test_get_workflow_tasks_not_found(self, client_with_mocks):
        """Test getting tasks for non-existent workflow"""
        client_with_mocks.adapter.get_workflow.return_value = None
        
        tasks = await client_with_mocks.get_workflow_tasks("nonexistent")
        
        assert tasks == []


class TestWorkflowExecution:
    """Test workflow execution patterns"""
    
    @pytest.mark.asyncio
    async def test_workflow_with_parameter_substitution(self, client_with_mocks):
        """Test workflow with parameter substitution between tasks"""
        tasks = [
            {
                "name": "generate_number",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "result = 42"}
            },
            {
                "name": "use_number",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "value = ${generate_number.result} * 2"},
                "dependencies": ["generate_number"]
            }
        ]
        
        workflow = await client_with_mocks.submit_workflow(
            name="Parameter Substitution",
            tasks=tasks
        )
        
        # Check that the parameter reference is preserved
        assert "${generate_number.result}" in workflow.tasks[1].params["code"]
    
    @pytest.mark.asyncio
    async def test_workflow_parallel_tasks(self, client_with_mocks):
        """Test workflow with parallel tasks (no dependencies)"""
        tasks = [
            {
                "name": "parallel_1",
                "protocol": "llm/v1",
                "method": "chat",
                "params": {"model": "llama3.2"}
            },
            {
                "name": "parallel_2",
                "protocol": "llm/v1",
                "method": "chat",
                "params": {"model": "llama3.2"}
            },
            {
                "name": "parallel_3",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "print('parallel')"}
            }
        ]
        
        workflow = await client_with_mocks.submit_workflow(
            name="Parallel Tasks",
            tasks=tasks
        )
        
        # All tasks should have no dependencies
        for task in workflow.tasks:
            assert task.dependencies == []
        
        # All tasks should be enqueued
        assert client_with_mocks.queue_manager.enqueue_task.call_count == 3
    
    @pytest.mark.asyncio
    async def test_workflow_complex_dependencies(self, client_with_mocks):
        """Test workflow with complex dependency graph"""
        tasks = [
            {"name": "A", "protocol": "llm/v1", "method": "chat"},
            {"name": "B", "protocol": "llm/v1", "method": "chat", "dependencies": ["A"]},
            {"name": "C", "protocol": "llm/v1", "method": "chat", "dependencies": ["A"]},
            {"name": "D", "protocol": "llm/v1", "method": "chat", "dependencies": ["B", "C"]},
            {"name": "E", "protocol": "llm/v1", "method": "chat", "dependencies": ["D"]}
        ]
        
        workflow = await client_with_mocks.submit_workflow(
            name="Complex Dependencies",
            tasks=tasks
        )
        
        # Verify dependency structure
        assert workflow.tasks[1].dependencies == ["A"]  # B depends on A
        assert workflow.tasks[2].dependencies == ["A"]  # C depends on A
        assert workflow.tasks[3].dependencies == ["B", "C"]  # D depends on B and C
        assert workflow.tasks[4].dependencies == ["D"]  # E depends on D


class TestWorkflowMemoryIntegration:
    """Integration tests with memory persistence"""
    
    @pytest.mark.asyncio
    async def test_workflow_lifecycle_memory(self, memory_client):
        """Test complete workflow lifecycle with memory persistence"""
        # Submit workflow
        tasks = [
            {
                "name": "step1",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "result = 'Hello'"}
            },
            {
                "name": "step2",
                "protocol": "python/v1",
                "method": "execute",
                "params": {"code": "result = '${step1.result} World'"},
                "dependencies": ["step1"]
            }
        ]
        
        workflow = await memory_client.submit_workflow(
            name="Integration Test Workflow",
            tasks=tasks,
            metadata={"test": True}
        )
        
        assert workflow.id is not None
        assert len(workflow.tasks) == 2
        
        # Get workflow
        retrieved = await memory_client.get_workflow(workflow.id)
        assert retrieved is not None
        assert retrieved.name == "Integration Test Workflow"
        
        # Get workflow tasks
        tasks = await memory_client.get_workflow_tasks(workflow.id)
        assert len(tasks) == 2
        assert tasks[0].name == "step1"
        assert tasks[1].name == "step2"
        assert tasks[1].dependencies == ["step1"]
    
    @pytest.mark.asyncio
    async def test_multiple_workflows_memory(self, memory_client):
        """Test managing multiple workflows"""
        workflows = []
        
        # Submit multiple workflows
        for i in range(3):
            workflow = await memory_client.submit_workflow(
                name=f"Workflow {i}",
                tasks=[
                    {
                        "name": f"task_{i}_1",
                        "protocol": "llm/v1",
                        "method": "chat"
                    },
                    {
                        "name": f"task_{i}_2",
                        "protocol": "python/v1",
                        "method": "execute"
                    }
                ]
            )
            workflows.append(workflow)
        
        # Verify all workflows exist
        for workflow in workflows:
            retrieved = await memory_client.get_workflow(workflow.id)
            assert retrieved is not None
            
            tasks = await memory_client.get_workflow_tasks(workflow.id)
            assert len(tasks) == 2