"""
End-to-end tests for UI proxy endpoints
Tests that the UI correctly proxies requests to the API
"""

import pytest
import asyncio
import json
from httpx import AsyncClient
from datetime import datetime
import time


@pytest.mark.asyncio
async def test_ui_api_info_endpoint():
    """Test the GET /api endpoint (proxies to API root)"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "Gleitzeit" in data["name"]
        assert "version" in data
        assert "status" in data


@pytest.mark.asyncio
async def test_ui_health_endpoint():
    """Test the GET /api/health endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


@pytest.mark.asyncio
async def test_ui_status_endpoint():
    """Test the GET /api/status endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "providers" in data
        assert "task_statistics" in data
        assert "uptime_seconds" in data


@pytest.mark.asyncio
async def test_ui_workflows_list_endpoint():
    """Test the GET /api/workflows endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # List workflows
        response = await client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["workflows"], list)
        
        # Test with pagination
        response = await client.get("/api/workflows?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert data["offset"] == 0
        
        # Test with status filter
        response = await client.get("/api/workflows?status=completed")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data


@pytest.mark.asyncio
async def test_ui_tasks_list_endpoint():
    """Test the GET /api/tasks endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # List all tasks
        response = await client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["tasks"], list)
        
        # Test with pagination
        response = await client.get("/api/tasks?limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        
        # Test with status filter
        response = await client.get("/api/tasks?status=completed")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data


@pytest.mark.asyncio
async def test_ui_workflow_submission_and_retrieval():
    """Test submitting a workflow through UI and retrieving it"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Submit a workflow
        workflow_data = {
            "name": "UI Test Workflow",
            "description": "Testing UI proxy endpoints",
            "tasks": [
                {
                    "id": "ui_task1",
                    "name": "UI Test Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "result = 'UI test passed'\nprint(result)"
                    },
                    "priority": "normal"
                }
            ]
        }
        
        response = await client.post("/api/workflows", json=workflow_data)
        assert response.status_code == 200
        submit_data = response.json()
        workflow_id = submit_data["workflow_id"]
        assert workflow_id is not None
        assert submit_data["status"] == "submitted"
        
        # Wait for workflow to be registered
        await asyncio.sleep(2)
        
        # Get workflow details
        response = await client.get(f"/api/workflows/{workflow_id}")
        if response.status_code == 200:
            workflow = response.json()
            assert workflow["workflow_id"] == workflow_id
        
        # Get workflow tasks
        response = await client.get(f"/api/workflows/{workflow_id}/tasks")
        assert response.status_code == 200
        tasks_data = response.json()
        assert tasks_data["workflow_id"] == workflow_id
        assert "tasks" in tasks_data
        
        # Get workflow timeline
        response = await client.get(f"/api/workflows/{workflow_id}/timeline")
        assert response.status_code == 200
        timeline_data = response.json()
        assert timeline_data["workflow_id"] == workflow_id
        assert "timeline" in timeline_data
        
        # Get workflow results
        response = await client.get(f"/api/workflows/{workflow_id}/results")
        assert response.status_code == 200
        results_data = response.json()
        assert results_data["workflow_id"] == workflow_id
        assert "results" in results_data
        
        # Delete the workflow
        response = await client.delete(f"/api/workflows/{workflow_id}")
        # Should return 200 or 404 depending on if workflow exists
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            delete_data = response.json()
            assert "success" in delete_data


@pytest.mark.asyncio
async def test_ui_task_operations():
    """Test task operations through UI"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Submit a task
        task_data = {
            "name": "UI Single Task Test",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": "result = 42\nprint(f'Answer: {result}')"
            },
            "priority": "normal"
        }
        
        response = await client.post("/api/tasks", json=task_data)
        assert response.status_code == 200
        task_response = response.json()
        task_id = task_response["task_id"]
        assert task_id is not None
        assert task_response["status"] == "submitted"
        
        # Wait a bit for task to be processed
        await asyncio.sleep(2)
        
        # Get task details
        response = await client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        task_details = response.json()
        assert task_details["task_id"] == task_id
        
        # Get task result
        response = await client.get(f"/api/tasks/{task_id}/result")
        assert response.status_code == 200
        result = response.json()
        assert result["task_id"] == task_id
        
        # Get task logs
        response = await client.get(f"/api/tasks/{task_id}/logs")
        assert response.status_code == 200
        logs = response.json()
        assert logs["task_id"] == task_id
        assert "logs" in logs
        
        # Delete the task
        response = await client.delete(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        delete_response = response.json()
        assert delete_response["success"] == True


@pytest.mark.asyncio
async def test_ui_resources_endpoint():
    """Test the GET /api/resources endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/resources")
        assert response.status_code == 200
        data = response.json()
        # Resource manager might not always be running
        if "resource_manager" in data and data["resource_manager"]:
            assert "id" in data["resource_manager"]
            assert "running" in data["resource_manager"]
        if "hubs" in data:
            assert isinstance(data["hubs"], dict)


@pytest.mark.asyncio
async def test_ui_providers_endpoint():
    """Test the GET /api/providers endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/providers")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert isinstance(data["providers"], list)


@pytest.mark.asyncio
async def test_ui_protocols_endpoint():
    """Test the GET /api/protocols endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/protocols")
        assert response.status_code == 200
        data = response.json()
        assert "protocols" in data
        assert isinstance(data["protocols"], list)
        # Check for expected protocol format
        for protocol in data["protocols"]:
            if isinstance(protocol, dict) and "name" in protocol:
                assert "/" in protocol["name"]  # Protocol names should have format like "python/v1"


@pytest.mark.asyncio
async def test_ui_chat_endpoint():
    """Test the POST /api/chat endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        chat_data = {
            "message": "Say 'UI test successful' and nothing else",
            "model": "llama3.2",
            "temperature": 0.1
        }
        
        # Note: This might fail if Ollama is not available
        response = await client.post("/api/chat", json=chat_data)
        if response.status_code == 200:
            data = response.json()
            assert "response" in data or "error" in data
        else:
            # It's okay if chat fails due to Ollama not being available
            assert response.status_code in [500, 503]


@pytest.mark.asyncio
async def test_ui_batch_endpoint():
    """Test the POST /api/batch endpoint"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        batch_data = {
            "directory": "/tmp",
            "pattern": "*.txt",
            "method": "llm/chat",
            "prompt": "Summarize this",
            "model": "llama3.2",
            "max_concurrent": 2,
            "name": "UI Batch Test"
        }
        
        # This might fail if directory doesn't exist or Ollama isn't available
        response = await client.post("/api/batch", json=batch_data)
        if response.status_code == 200:
            data = response.json()
            assert "batch_id" in data or "workflow_id" in data
            assert "status" in data


@pytest.mark.asyncio
async def test_ui_workflow_upload_endpoint():
    """Test the POST /api/workflows/upload endpoint"""
    import tempfile
    import os
    
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Create a temporary workflow YAML file
        workflow_yaml = """
name: UI Upload Test
description: Test workflow upload through UI
tasks:
  - id: upload_test
    name: Upload Test Task
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Workflow uploaded via UI")
        result = "success"
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(workflow_yaml)
            temp_file = f.name
        
        try:
            # Upload the file
            with open(temp_file, 'rb') as f:
                files = {'file': ('test_workflow.yaml', f, 'application/x-yaml')}
                response = await client.post(
                    "/api/workflows/upload?execute=true",
                    files=files
                )
            
            assert response.status_code == 200
            data = response.json()
            assert "workflow_id" in data
            assert "status" in data
            # Status could be submitted or completed depending on speed
            assert data["status"] in ["submitted", "completed"]
            
            # Clean up - delete the uploaded workflow
            if "workflow_id" in data:
                await asyncio.sleep(1)
                await client.delete(f"/api/workflows/{data['workflow_id']}")
        
        finally:
            # Clean up temp file
            os.unlink(temp_file)


@pytest.mark.asyncio
async def test_ui_filtering_and_pagination():
    """Test filtering and pagination through UI endpoints"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # First, create some test data
        workflow_ids = []
        for i in range(3):
            workflow_data = {
                "name": f"UI Pagination Test {i}",
                "tasks": [
                    {
                        "id": f"page_task_{i}",
                        "name": f"Page Task {i}",
                        "protocol": "python/v1",
                        "method": "python/execute",
                        "params": {"code": f"result = {i}"}
                    }
                ]
            }
            response = await client.post("/api/workflows", json=workflow_data)
            if response.status_code == 200:
                workflow_ids.append(response.json()["workflow_id"])
        
        # Wait for workflows to be registered
        await asyncio.sleep(2)
        
        # Test pagination on workflows
        response = await client.get("/api/workflows?limit=2&offset=0")
        assert response.status_code == 200
        page1 = response.json()
        assert page1["limit"] == 2
        assert page1["offset"] == 0
        
        response = await client.get("/api/workflows?limit=2&offset=2")
        assert response.status_code == 200
        page2 = response.json()
        assert page2["limit"] == 2
        assert page2["offset"] == 2
        
        # Test filtering tasks by workflow
        if workflow_ids:
            response = await client.get(f"/api/tasks?workflow_id={workflow_ids[0]}")
            assert response.status_code == 200
            tasks = response.json()
            assert "tasks" in tasks
        
        # Clean up
        for wf_id in workflow_ids:
            await client.delete(f"/api/workflows/{wf_id}")


@pytest.mark.asyncio
async def test_ui_error_handling():
    """Test error handling for non-existent resources"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Non-existent workflow
        fake_id = "non_existent_workflow_ui_test"
        
        response = await client.get(f"/api/workflows/{fake_id}")
        # Should either return 404 or empty data
        assert response.status_code in [200, 404]
        
        response = await client.get(f"/api/workflows/{fake_id}/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["tasks"] == []
        assert data["total"] == 0
        
        response = await client.get(f"/api/workflows/{fake_id}/timeline")
        assert response.status_code == 200
        data = response.json()
        assert data["timeline"] == []
        
        response = await client.get(f"/api/workflows/{fake_id}/results")
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == {}
        
        # Delete non-existent workflow - API returns 404 for non-existent workflows
        response = await client.delete(f"/api/workflows/{fake_id}")
        assert response.status_code == 404  # API returns 404 for non-existent workflow


@pytest.mark.asyncio
async def test_ui_serve_static_files():
    """Test that UI serves static files correctly"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Test root serves index.html
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        
        # Test API routes are proxied, not served as static
        response = await client.get("/api/health")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")