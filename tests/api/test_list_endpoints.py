"""
Tests for list endpoints (GET /workflows and GET /tasks)
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, Priority, WorkflowStatus


class TestWorkflowListEndpoint:
    """Test GET /workflows endpoint"""
    
    @pytest.mark.asyncio
    async def test_list_workflows_empty(self, async_client, mock_persistence):
        """Test listing workflows when none exist"""
        # Mock empty result from persistence
        mock_persistence.list_workflows = AsyncMock(return_value={
            "workflows": [],
            "total": 0,
            "limit": 50,
            "offset": 0
        })
        
        response = await async_client.get("/workflows")
        assert response.status_code == 200
        data = response.json()
        
        assert data["workflows"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0
    
    @pytest.mark.asyncio
    async def test_list_workflows_with_data(self, async_client, mock_persistence):
        """Test listing workflows with data"""
        # Create mock workflows
        workflow1 = Workflow(
            id="wf-1",
            name="Test Workflow 1",
            tasks=[],
            created_at=datetime.now()
        )
        workflow2 = Workflow(
            id="wf-2",
            name="Test Workflow 2",
            tasks=[],
            created_at=datetime.now()
        )
        
        # Mock persistence response
        mock_persistence.list_workflows = AsyncMock(return_value={
            "workflows": [workflow1, workflow2],
            "total": 2,
            "limit": 50,
            "offset": 0
        })
        
        # Mock get_tasks_by_workflow for status calculation
        mock_persistence.get_tasks_by_workflow = AsyncMock(return_value=[])
        
        response = await async_client.get("/workflows")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["workflows"]) == 2
        assert data["total"] == 2
        assert data["workflows"][0]["workflow_id"] == "wf-1"
        assert data["workflows"][0]["name"] == "Test Workflow 1"
        assert data["workflows"][1]["workflow_id"] == "wf-2"
    
    @pytest.mark.asyncio
    async def test_list_workflows_with_pagination(self, async_client, mock_persistence):
        """Test workflow listing with pagination"""
        workflows = [
            Workflow(id=f"wf-{i}", name=f"Workflow {i}", tasks=[], created_at=datetime.now())
            for i in range(5)
        ]
        
        # Mock paginated response
        mock_persistence.list_workflows = AsyncMock(return_value={
            "workflows": workflows[2:4],  # Return items 2 and 3
            "total": 5,
            "limit": 2,
            "offset": 2
        })
        mock_persistence.get_tasks_by_workflow = AsyncMock(return_value=[])
        
        response = await async_client.get("/workflows?limit=2&offset=2")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["workflows"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 2
        assert data["workflows"][0]["workflow_id"] == "wf-2"
    
    @pytest.mark.asyncio
    async def test_list_workflows_with_status_filter(self, async_client, mock_persistence):
        """Test filtering workflows by status"""
        workflow = Workflow(
            id="wf-completed",
            name="Completed Workflow",
            tasks=[],
            created_at=datetime.now()
        )
        
        mock_persistence.list_workflows = AsyncMock(return_value={
            "workflows": [workflow],
            "total": 1,
            "limit": 50,
            "offset": 0
        })
        
        # Mock completed tasks
        completed_task = MagicMock()
        completed_task.status = "completed"
        mock_persistence.get_tasks_by_workflow = AsyncMock(return_value=[completed_task])
        
        response = await async_client.get("/workflows?status=completed")
        assert response.status_code == 200
        data = response.json()
        
        # The endpoint calculates status based on tasks
        assert len(data["workflows"]) == 1
        assert data["workflows"][0]["status"] == "completed"
    
    @pytest.mark.asyncio
    async def test_list_workflows_calculates_task_stats(self, async_client, mock_persistence):
        """Test that workflow listing calculates task statistics"""
        workflow = Workflow(
            id="wf-with-tasks",
            name="Workflow with Tasks",
            tasks=[],
            created_at=datetime.now()
        )
        
        mock_persistence.list_workflows = AsyncMock(return_value={
            "workflows": [workflow],
            "total": 1,
            "limit": 50,
            "offset": 0
        })
        
        # Mock tasks with different statuses
        tasks = [
            MagicMock(status="completed"),
            MagicMock(status="completed"),
            MagicMock(status="failed"),
            MagicMock(status="executing"),
        ]
        mock_persistence.get_tasks_by_workflow = AsyncMock(return_value=tasks)
        
        response = await async_client.get("/workflows")
        assert response.status_code == 200
        data = response.json()
        
        wf_data = data["workflows"][0]
        assert wf_data["tasks_total"] == 4
        assert wf_data["tasks_completed"] == 2
        assert wf_data["tasks_failed"] == 1
        assert wf_data["status"] == "failed"  # Has failed tasks


class TestTaskListEndpoint:
    """Test GET /tasks endpoint"""
    
    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, async_client, mock_persistence):
        """Test listing tasks when none exist"""
        mock_persistence.list_tasks = AsyncMock(return_value={
            "tasks": [],
            "total": 0,
            "limit": 100,
            "offset": 0
        })
        
        response = await async_client.get("/tasks")
        assert response.status_code == 200
        data = response.json()
        
        assert data["tasks"] == []
        assert data["total"] == 0
        assert data["limit"] == 100
        assert data["offset"] == 0
    
    @pytest.mark.asyncio
    async def test_list_tasks_with_data(self, async_client, mock_persistence):
        """Test listing tasks with data"""
        task1 = Task(
            id="task-1",
            name="Test Task 1",
            protocol="python/v1",
            method="python/execute",
            params={},
            workflow_id="wf-1",
            status="pending",
            priority=Priority.NORMAL
        )
        task2 = Task(
            id="task-2",
            name="Test Task 2",
            protocol="llm/v1",
            method="llm/chat",
            params={},
            workflow_id="wf-1",
            status="completed",
            priority=Priority.HIGH
        )
        
        mock_persistence.list_tasks = AsyncMock(return_value={
            "tasks": [task1, task2],
            "total": 2,
            "limit": 100,
            "offset": 0
        })
        
        response = await async_client.get("/tasks")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["tasks"]) == 2
        assert data["total"] == 2
        assert data["tasks"][0]["task_id"] == "task-1"
        assert data["tasks"][0]["name"] == "Test Task 1"
        assert data["tasks"][0]["status"] == "pending"
    
    @pytest.mark.asyncio
    async def test_list_tasks_by_workflow(self, async_client, mock_persistence):
        """Test filtering tasks by workflow ID"""
        task = Task(
            id="task-wf1",
            name="Workflow 1 Task",
            protocol="python/v1",
            method="python/execute",
            params={},
            workflow_id="wf-1",
            status="pending",
            priority=Priority.NORMAL
        )
        
        mock_persistence.list_tasks = AsyncMock(return_value={
            "tasks": [task],
            "total": 1,
            "limit": 100,
            "offset": 0
        })
        
        response = await async_client.get("/tasks?workflow_id=wf-1")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["workflow_id"] == "wf-1"
    
    @pytest.mark.asyncio
    async def test_list_tasks_by_status(self, async_client, mock_persistence):
        """Test filtering tasks by status"""
        task = Task(
            id="task-completed",
            name="Completed Task",
            protocol="python/v1",
            method="python/execute",
            params={},
            workflow_id="wf-1",
            status="completed",
            priority=Priority.NORMAL
        )
        
        mock_persistence.list_tasks = AsyncMock(return_value={
            "tasks": [task],
            "total": 1,
            "limit": 100,
            "offset": 0
        })
        
        response = await async_client.get("/tasks?status=completed")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["status"] == "completed"
    
    @pytest.mark.asyncio
    async def test_list_tasks_with_pagination(self, async_client, mock_persistence):
        """Test task listing with pagination"""
        tasks = [
            Task(
                id=f"task-{i}",
                name=f"Task {i}",
                protocol="python/v1",
                method="python/execute",
                params={},
                workflow_id="wf-1",
                status="pending",
                priority=Priority.NORMAL
            )
            for i in range(10)
        ]
        
        # Return page 2 with 5 items per page
        mock_persistence.list_tasks = AsyncMock(return_value={
            "tasks": tasks[5:10],
            "total": 10,
            "limit": 5,
            "offset": 5
        })
        
        response = await async_client.get("/tasks?limit=5&offset=5")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["tasks"]) == 5
        assert data["total"] == 10
        assert data["limit"] == 5
        assert data["offset"] == 5
        assert data["tasks"][0]["task_id"] == "task-5"
    
    @pytest.mark.asyncio
    async def test_list_tasks_calculates_execution_time(self, async_client, mock_persistence):
        """Test that task listing calculates execution time"""
        task = Task(
            id="task-with-time",
            name="Timed Task",
            protocol="python/v1",
            method="python/execute",
            params={},
            workflow_id="wf-1",
            status="completed",
            priority=Priority.NORMAL
        )
        # Add timing attributes
        task.created_at = datetime(2024, 1, 1, 10, 0, 0)
        task.completed_at = datetime(2024, 1, 1, 10, 5, 30)  # 5 minutes 30 seconds later
        
        mock_persistence.list_tasks = AsyncMock(return_value={
            "tasks": [task],
            "total": 1,
            "limit": 100,
            "offset": 0
        })
        
        response = await async_client.get("/tasks")
        assert response.status_code == 200
        data = response.json()
        
        assert data["tasks"][0]["execution_time"] == 330.0  # 5 minutes 30 seconds in seconds
    
    @pytest.mark.asyncio
    async def test_list_tasks_combined_filters(self, async_client, mock_persistence):
        """Test listing tasks with multiple filters"""
        task = Task(
            id="task-filtered",
            name="Filtered Task",
            protocol="python/v1",
            method="python/execute",
            params={},
            workflow_id="wf-1",
            status="completed",
            priority=Priority.NORMAL
        )
        
        mock_persistence.list_tasks = AsyncMock(return_value={
            "tasks": [task],
            "total": 1,
            "limit": 10,
            "offset": 0
        })
        
        response = await async_client.get("/tasks?workflow_id=wf-1&status=completed&limit=10")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["workflow_id"] == "wf-1"
        assert data["tasks"][0]["status"] == "completed"
        
        # Verify the mock was called with correct parameters
        mock_persistence.list_tasks.assert_called_with(
            workflow_id="wf-1",
            status="completed",
            limit=10,
            offset=0
        )