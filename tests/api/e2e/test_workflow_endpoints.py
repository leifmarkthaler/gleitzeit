"""
End-to-end tests for workflow-related API endpoints
"""

import pytest
import asyncio
import json
from httpx import AsyncClient
from datetime import datetime
import time


@pytest.mark.asyncio
async def test_workflow_full_lifecycle():
    """Test complete workflow lifecycle including new endpoints"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # 1. Submit a workflow
        workflow_data = {
            "name": "E2E Test Workflow",
            "description": "Testing workflow endpoints",
            "tasks": [
                {
                    "id": "task1",
                    "name": "First Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = 10 + 20\nprint(f'Result: {result}')"
                    },
                    "priority": "normal"
                },
                {
                    "id": "task2",
                    "name": "Second Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = 30 * 2\nprint(f'Result: {result}')"
                    },
                    "dependencies": ["task1"],
                    "priority": "normal"
                }
            ]
        }
        
        response = await client.post("/workflows", json=workflow_data)
        assert response.status_code == 200
        workflow_response = response.json()
        workflow_id = workflow_response["workflow_id"]
        assert workflow_id is not None
        assert workflow_response["status"] == "submitted"
        assert workflow_response["tasks_total"] == 2
        
        # 2. Get workflow details - retry a few times as workflow runs async
        max_retries = 10
        retry_delay = 0.5
        workflow_found = False
        
        for i in range(max_retries):
            response = await client.get(f"/workflows/{workflow_id}")
            if response.status_code == 200:
                workflow_found = True
                break
            await asyncio.sleep(retry_delay)
        
        assert workflow_found, f"Workflow {workflow_id} not found after {max_retries} retries"
        assert response.status_code == 200
        workflow_details = response.json()
        assert workflow_details["workflow_id"] == workflow_id
        
        # 3. Get workflow tasks (new endpoint)
        response = await client.get(f"/workflows/{workflow_id}/tasks")
        assert response.status_code == 200
        tasks_response = response.json()
        assert tasks_response["workflow_id"] == workflow_id
        assert "tasks" in tasks_response
        assert "total" in tasks_response
        
        # Wait a bit for tasks to be created
        await asyncio.sleep(2)
        
        # 4. Get workflow timeline (new endpoint)
        response = await client.get(f"/workflows/{workflow_id}/timeline")
        assert response.status_code == 200
        timeline_response = response.json()
        assert timeline_response["workflow_id"] == workflow_id
        assert "timeline" in timeline_response
        assert "total_tasks" in timeline_response
        
        # 5. Get workflow results (new endpoint)
        response = await client.get(f"/workflows/{workflow_id}/results")
        assert response.status_code == 200
        results_response = response.json()
        assert results_response["workflow_id"] == workflow_id
        assert "status" in results_response
        assert "results" in results_response
        
        # 6. List workflows with filtering
        response = await client.get("/workflows", params={"limit": 10})
        assert response.status_code == 200
        list_response = response.json()
        assert "workflows" in list_response
        assert "total" in list_response
        
        # 7. Delete the workflow (wait for it to exist first)
        # Give the workflow time to be fully registered
        await asyncio.sleep(1)
        response = await client.delete(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        delete_response = response.json()
        assert delete_response["success"] == True
        
        # 8. Verify workflow is deleted
        response = await client.get(f"/workflows/{workflow_id}")
        # Should return 404 or empty result
        if response.status_code == 200:
            workflow = response.json()
            # If it returns 200, the workflow should be marked as not found or have no data
            assert workflow.get("status") in [None, "not_found", "deleted"]


@pytest.mark.asyncio
async def test_workflow_tasks_endpoint():
    """Test the GET /workflows/{id}/tasks endpoint specifically"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # Create a workflow with multiple tasks
        workflow_data = {
            "name": "Multi-task Workflow",
            "tasks": [
                {
                    "id": f"task_{i}",
                    "name": f"Task {i}",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": f"result = {i}"}
                }
                for i in range(5)
            ]
        }
        
        response = await client.post("/workflows", json=workflow_data)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for tasks to be registered
        await asyncio.sleep(1)
        
        # Get tasks with pagination
        response = await client.get(
            f"/workflows/{workflow_id}/tasks",
            params={"limit": 3, "offset": 0}
        )
        assert response.status_code == 200
        tasks_response = response.json()
        assert tasks_response["workflow_id"] == workflow_id
        assert isinstance(tasks_response["tasks"], list)
        
        # Clean up
        await client.delete(f"/workflows/{workflow_id}")


@pytest.mark.asyncio
async def test_workflow_timeline_endpoint():
    """Test the GET /workflows/{id}/timeline endpoint"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # Create a simple workflow
        workflow_data = {
            "name": "Timeline Test",
            "tasks": [
                {
                    "id": "quick_task",
                    "name": "Quick Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "import time\ntime.sleep(0.1)\nresult = 'done'"}
                }
            ]
        }
        
        response = await client.post("/workflows", json=workflow_data)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for task to potentially complete
        await asyncio.sleep(2)
        
        # Get timeline
        response = await client.get(f"/workflows/{workflow_id}/timeline")
        assert response.status_code == 200
        timeline = response.json()
        assert timeline["workflow_id"] == workflow_id
        assert "timeline" in timeline
        assert isinstance(timeline["timeline"], list)
        
        # Timeline entries should have required fields
        for entry in timeline["timeline"]:
            assert "task_id" in entry
            assert "name" in entry
            assert "status" in entry
            assert "started_at" in entry
        
        # Clean up
        await client.delete(f"/workflows/{workflow_id}")


@pytest.mark.asyncio
async def test_workflow_results_endpoint():
    """Test the GET /workflows/{id}/results endpoint"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        # Create a workflow that produces results
        workflow_data = {
            "name": "Results Test",
            "tasks": [
                {
                    "id": "calc_task",
                    "name": "Calculate",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'value': 42, 'status': 'calculated'}"}
                }
            ]
        }
        
        response = await client.post("/workflows", json=workflow_data)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for potential execution
        await asyncio.sleep(2)
        
        # Get results
        response = await client.get(f"/workflows/{workflow_id}/results")
        assert response.status_code == 200
        results = response.json()
        assert results["workflow_id"] == workflow_id
        assert "status" in results
        assert "results" in results
        assert isinstance(results["results"], dict)
        
        # Clean up
        await client.delete(f"/workflows/{workflow_id}")


@pytest.mark.asyncio
async def test_nonexistent_workflow_endpoints():
    """Test endpoints with non-existent workflow ID"""
    async with AsyncClient(base_url="http://localhost:8012") as client:
        fake_id = "nonexistent_workflow_123"
        
        # Tasks endpoint should return empty
        response = await client.get(f"/workflows/{fake_id}/tasks")
        assert response.status_code == 200
        tasks = response.json()
        assert tasks["workflow_id"] == fake_id
        assert tasks["tasks"] == []
        assert tasks["total"] == 0
        
        # Timeline endpoint should return empty
        response = await client.get(f"/workflows/{fake_id}/timeline")
        assert response.status_code == 200
        timeline = response.json()
        assert timeline["workflow_id"] == fake_id
        assert timeline["timeline"] == []
        assert timeline["total_tasks"] == 0
        
        # Results endpoint should return empty/unknown
        response = await client.get(f"/workflows/{fake_id}/results")
        assert response.status_code == 200
        results = response.json()
        assert results["workflow_id"] == fake_id
        assert results["results"] == {}