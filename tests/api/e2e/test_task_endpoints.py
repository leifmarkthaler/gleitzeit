"""
End-to-end tests for task-related API endpoints
"""

import pytest
import asyncio
import json
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_task_full_lifecycle():
    """Test complete task lifecycle including new endpoints"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # 1. Submit a task
        task_data = {
            "name": "E2E Test Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": "import time\nresult = {'computed': 100, 'message': 'Task complete'}\nprint('Processing...')"
            },
            "priority": "normal"
        }
        
        response = await client.post("/tasks", json=task_data)
        assert response.status_code == 200
        task_response = response.json()
        task_id = task_response["task_id"]
        assert task_id is not None
        assert task_response["status"] == "submitted"
        
        # 2. Get task details
        response = await client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        task_details = response.json()
        assert task_details["task_id"] == task_id
        
        # 3. Get task result (new endpoint)
        response = await client.get(f"/tasks/{task_id}/result")
        assert response.status_code in [200, 404]  # May be 404 if not completed yet
        if response.status_code == 200:
            result_response = response.json()
            assert result_response["task_id"] == task_id
            assert "status" in result_response
            assert "result" in result_response
        
        # 4. Get task logs (new endpoint)
        response = await client.get(f"/tasks/{task_id}/logs")
        assert response.status_code == 200
        logs_response = response.json()
        assert logs_response["task_id"] == task_id
        assert "logs" in logs_response
        assert isinstance(logs_response["logs"], list)
        assert "total_lines" in logs_response
        assert "tail" in logs_response
        
        # 5. List tasks with filtering
        response = await client.get("/tasks", params={"limit": 10})
        assert response.status_code == 200
        list_response = response.json()
        assert "tasks" in list_response
        assert "total" in list_response
        
        # 6. Delete the task
        response = await client.delete(f"/tasks/{task_id}")
        assert response.status_code == 200
        delete_response = response.json()
        assert delete_response["success"] == True


@pytest.mark.asyncio
async def test_task_result_endpoint():
    """Test the GET /tasks/{id}/result endpoint specifically"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # Create a task that produces a result
        task_data = {
            "name": "Result Producer",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": "result = {'answer': 42, 'details': {'computed': True}}"
            }
        }
        
        response = await client.post("/tasks", json=task_data)
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        
        # Wait a bit for potential execution
        await asyncio.sleep(2)
        
        # Get result
        response = await client.get(f"/tasks/{task_id}/result")
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            result = response.json()
            assert result["task_id"] == task_id
            assert "status" in result
            assert "result" in result
            assert "error" in result
            assert "completed_at" in result
        
        # Clean up
        await client.delete(f"/tasks/{task_id}")


@pytest.mark.asyncio
async def test_task_logs_endpoint():
    """Test the GET /tasks/{id}/logs endpoint"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # Create a task that generates logs
        task_data = {
            "name": "Log Generator",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": """
print('Starting process...')
print('Step 1: Initialize')
print('Step 2: Compute')
print('Step 3: Finalize')
result = 'done'
"""
            }
        }
        
        response = await client.post("/tasks", json=task_data)
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        
        # Wait for execution
        await asyncio.sleep(2)
        
        # Get logs with default tail
        response = await client.get(f"/tasks/{task_id}/logs")
        assert response.status_code == 200
        logs = response.json()
        assert logs["task_id"] == task_id
        assert isinstance(logs["logs"], list)
        assert logs["tail"] == 50
        
        # Get logs with custom tail
        response = await client.get(f"/tasks/{task_id}/logs", params={"tail": 10})
        assert response.status_code == 200
        logs = response.json()
        assert logs["tail"] == 10
        if len(logs["logs"]) > 10:
            assert len(logs["logs"]) <= 10
        
        # Clean up
        await client.delete(f"/tasks/{task_id}")


@pytest.mark.asyncio
async def test_nonexistent_task_endpoints():
    """Test endpoints with non-existent task ID"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        fake_id = "nonexistent_task_123"
        
        # Result endpoint should return 404
        response = await client.get(f"/tasks/{fake_id}/result")
        assert response.status_code == 404
        
        # Logs endpoint should return a not found message
        response = await client.get(f"/tasks/{fake_id}/logs")
        assert response.status_code == 200
        logs = response.json()
        assert logs["task_id"] == fake_id
        assert len(logs["logs"]) >= 1
        assert "not found" in logs["logs"][0].lower()


@pytest.mark.asyncio
async def test_task_list_with_filters():
    """Test task listing with various filters"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # Create a workflow with tasks first
        workflow_data = {
            "name": "Filter Test Workflow",
            "tasks": [
                {
                    "id": "filter_task_1",
                    "name": "Filter Task 1",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = 1"}
                },
                {
                    "id": "filter_task_2",
                    "name": "Filter Task 2",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = 2"}
                }
            ]
        }
        
        response = await client.post("/workflows", json=workflow_data)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        await asyncio.sleep(1)
        
        # Test filtering by workflow_id
        response = await client.get("/tasks", params={"workflow_id": workflow_id})
        assert response.status_code == 200
        tasks = response.json()
        assert "tasks" in tasks
        
        # Test filtering by status
        response = await client.get("/tasks", params={"status": "completed"})
        assert response.status_code == 200
        
        # Test pagination
        response = await client.get("/tasks", params={"limit": 5, "offset": 0})
        assert response.status_code == 200
        tasks = response.json()
        assert "limit" in tasks
        assert "offset" in tasks
        
        # Clean up
        await client.delete(f"/workflows/{workflow_id}")