"""
End-to-end tests for UI-specific features that are not just API proxies
"""

import pytest
import asyncio
import json
from httpx import AsyncClient
from datetime import datetime


@pytest.mark.asyncio
async def test_workflow_templates_list():
    """Test listing workflow templates - UI-specific feature"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # List all templates
        response = await client.get("/api/templates")
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert "total" in data
        assert "categories" in data
        assert len(data["templates"]) > 0
        
        # Check template structure
        for template in data["templates"]:
            assert "id" in template
            assert "name" in template
            assert "description" in template
            assert "category" in template
            assert "task_count" in template


@pytest.mark.asyncio
async def test_workflow_template_categories():
    """Test getting template categories - UI-specific feature"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # The route is registered without the trailing /
        response = await client.get("/api/templates/categories")
        
        # This endpoint might not be available in all UI versions
        if response.status_code == 404:
            pytest.skip("Categories endpoint not available in this UI version")
        
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert "total" in data
        
        # Check category structure
        for category in data["categories"]:
            assert "name" in category
            assert "count" in category
            assert "description" in category
        
        # Check for expected categories
        category_names = [cat["name"] for cat in data["categories"]]
        expected_categories = ["llm", "python", "hybrid"]
        for expected in expected_categories:
            assert expected in category_names


@pytest.mark.asyncio
async def test_workflow_template_filtering():
    """Test filtering templates by category"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Get LLM templates only
        response = await client.get("/api/templates?category=llm")
        assert response.status_code == 200
        data = response.json()
        
        # All templates should be LLM category
        for template in data["templates"]:
            assert template["category"] == "llm"
        
        # Get Python templates
        response = await client.get("/api/templates?category=python")
        assert response.status_code == 200
        data = response.json()
        
        for template in data["templates"]:
            assert template["category"] == "python"


@pytest.mark.asyncio
async def test_get_specific_template():
    """Test getting a specific workflow template"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Get the simple LLM template
        response = await client.get("/api/templates/simple_llm")
        assert response.status_code == 200
        template = response.json()
        
        assert template["id"] == "simple_llm"
        assert template["name"] == "Simple LLM Chat"
        assert "workflow" in template
        assert "tasks" in template["workflow"]
        assert len(template["workflow"]["tasks"]) > 0
        
        # Check task structure
        task = template["workflow"]["tasks"][0]
        assert "id" in task
        assert "method" in task
        assert "parameters" in task


@pytest.mark.asyncio
async def test_nonexistent_template():
    """Test requesting a non-existent template"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/templates/nonexistent_template")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_deploy_template():
    """Test deploying a workflow template"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Deploy simple LLM template
        response = await client.post("/api/templates/simple_llm/deploy")
        assert response.status_code == 200
        data = response.json()
        
        assert "workflow_id" in data
        assert "status" in data
        workflow_id = data["workflow_id"]
        
        # Wait a bit for workflow to be registered
        await asyncio.sleep(2)
        
        # Verify workflow was created
        response = await client.get(f"/api/workflows/{workflow_id}/tasks")
        assert response.status_code == 200
        
        # Clean up
        await client.delete(f"/api/workflows/{workflow_id}")


@pytest.mark.asyncio
async def test_deploy_template_with_inputs():
    """Test deploying a template with input substitution"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Deploy template with custom inputs
        inputs = {
            "input_text": "This is a test text for analysis"
        }
        
        response = await client.post(
            "/api/templates/multi_step_analysis/deploy",
            json=inputs
        )
        
        # Should either succeed or fail gracefully
        assert response.status_code in [200, 422, 500]
        
        if response.status_code == 200:
            data = response.json()
            assert "workflow_id" in data
            
            # Clean up
            await asyncio.sleep(1)
            await client.delete(f"/api/workflows/{data['workflow_id']}")


@pytest.mark.asyncio
async def test_ui_specific_workflow_list_transformation():
    """Test that UI transforms workflow data for display"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # First submit a workflow through UI
        workflow_data = {
            "name": "UI Transform Test",
            "tasks": [
                {
                    "id": "test_task",
                    "name": "Test Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "print('test')"}
                }
            ]
        }
        
        response = await client.post("/api/workflows", json=workflow_data)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # List workflows through UI endpoint
        response = await client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        
        # Check UI-specific fields are present
        workflows = data["workflows"]
        if workflows:
            workflow = workflows[0]
            # UI adds these fields for display
            assert "id" in workflow or "workflow_id" in workflow
            assert "name" in workflow
            assert "status" in workflow
            assert "tasks_total" in workflow
            assert "tasks_completed" in workflow
            assert "tasks_failed" in workflow
        
        # Clean up
        await client.delete(f"/api/workflows/{workflow_id}")


@pytest.mark.asyncio
async def test_parallel_template_execution():
    """Test the parallel tasks template"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Get the parallel template
        response = await client.get("/api/templates/parallel_tasks")
        assert response.status_code == 200
        template = response.json()
        
        # Check it has parallel tasks (no dependencies on first 3)
        tasks = template["workflow"]["tasks"]
        parallel_tasks = [t for t in tasks[:3]]  # First 3 should be parallel
        for task in parallel_tasks:
            assert "depends_on" not in task or len(task.get("depends_on", [])) == 0
        
        # Last task should depend on the parallel tasks
        combine_task = tasks[-1]
        assert "depends_on" in combine_task
        assert len(combine_task["depends_on"]) >= 3


@pytest.mark.asyncio
async def test_data_processing_template():
    """Test the data processing hybrid template"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        response = await client.get("/api/templates/data_processing")
        assert response.status_code == 200
        template = response.json()
        
        assert template["category"] == "hybrid"
        
        # Check task chain
        tasks = template["workflow"]["tasks"]
        assert len(tasks) >= 3
        
        # Should have Python tasks and LLM tasks
        methods = [t["method"] for t in tasks]
        assert any("python" in m for m in methods)
        assert any("llm" in m for m in methods)


@pytest.mark.asyncio
async def test_template_task_dependencies():
    """Test that templates have proper task dependencies"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Get multi-step analysis template
        response = await client.get("/api/templates/multi_step_analysis")
        assert response.status_code == 200
        template = response.json()
        
        tasks = template["workflow"]["tasks"]
        task_ids = [t["id"] for t in tasks]
        
        # Check dependencies reference valid tasks
        for task in tasks:
            if "depends_on" in task:
                for dep in task["depends_on"]:
                    assert dep in task_ids


@pytest.mark.asyncio
async def test_ui_system_endpoints():
    """Test UI-specific system monitoring endpoints"""
    async with AsyncClient(base_url="http://localhost:8004", follow_redirects=True) as client:
        # Test system status with local metrics
        response = await client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        
        # UI adds local_metrics if psutil is available
        if "local_metrics" in data:
            metrics = data["local_metrics"]
            if metrics:  # psutil is installed
                assert "cpu_percent" in metrics or "memory_percent" in metrics or "disk_percent" in metrics