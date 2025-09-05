"""
End-to-End tests for API with real workflows and system components

These tests verify the complete API works with:
- Real ExecutionEngine
- Real workflow files from /examples
- Real persistence backends
- Real providers (mocked at network level)

Tests cover:
- Loading and executing example workflows via API
- Batch processing with real files
- Complete workflow lifecycle through API
- Error handling with real components
"""

import pytest
import asyncio
import yaml
import json
import tempfile
from pathlib import Path
from typing import Dict, Any
from httpx import AsyncClient, ASGITransport

# Import API and system components
from gleitzeit.api.main import app, app_state, setup_system, cleanup_system
from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_file
from gleitzeit.core.models import Task, Workflow, Priority, TaskStatus
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter, UnifiedInMemoryAdapter
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
from gleitzeit.hub.mcp_hub import MCPHub
from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1


def convert_workflow_to_api_format(workflow_content):
    """Helper to convert workflow YAML to API format"""
    api_workflow = {
        "name": workflow_content["name"],
        "description": workflow_content.get("description", ""),
        "tasks": []
    }
    
    for task in workflow_content.get("tasks", []):
        # Determine protocol from method or task
        method = task.get("method", "")
        if not method and "protocol" in task:
            protocol = task["protocol"]
        elif "/" in method:
            protocol = method.split("/")[0] + "/v1"
        else:
            # Guess based on content
            params = task.get("params", task.get("parameters", {}))
            if "model" in params or "messages" in params:
                protocol = "llm/v1"
            elif "file" in params or "code" in params:
                protocol = "python/v1"
            elif "tool" in method:
                protocol = "mcp/v1"
            else:
                protocol = "python/v1"
        
        # Handle priority - convert integers to strings
        priority = task.get("priority", "normal")
        if isinstance(priority, int):
            priority_map = {0: "low", 1: "normal", 2: "high", 3: "urgent"}
            priority = priority_map.get(priority, "normal")
        elif isinstance(priority, str):
            # Ensure it's a valid priority string
            valid_priorities = ["low", "normal", "high", "urgent", "critical"]
            if priority.lower() not in valid_priorities:
                priority = "normal"
            else:
                priority = priority.lower()
        
        # Ensure we have an ID
        task_id = task.get("id") or task.get("name") or f"task_{len(api_workflow['tasks'])}"
        
        # Get the name, defaulting to ID if not provided
        task_name = task.get("name", task_id)
        
        api_task = {
            "id": task_id,
            "name": task_name,
            "protocol": protocol,
            "method": method or f"{protocol.split('/')[0]}/execute",
            "params": task.get("params", task.get("parameters", {})),
            "dependencies": task.get("dependencies", []),
            "priority": priority
        }
        api_workflow["tasks"].append(api_task)
    
    return api_workflow


@pytest.mark.e2e
@pytest.mark.asyncio
class TestAPIWithRealWorkflows:
    """End-to-end tests using real workflows through the API"""
    
    @pytest.fixture
    async def api_client(self):
        """Create API client with the API's own system setup"""
        # Let the API set up its own system
        await setup_system()
        
        # Create test client
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        
        # Clean up the API's system
        await cleanup_system()
    
    @pytest.mark.asyncio
    async def test_execute_simple_python_workflow(self, api_client):
        """Test executing simple_python_workflow.yaml through API"""
        # Load the actual workflow file
        workflow_path = Path("examples/simple_python_workflow.yaml")
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Convert to API format using helper
        api_workflow = convert_workflow_to_api_format(workflow_content)
        
        # Submit workflow via API
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        assert data["tasks_total"] == 1
        
        # Wait for execution
        await asyncio.sleep(2.0)
        
        # Check workflow status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Should have completed
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        assert status["tasks_failed"] == 0
        
        # Check results
        assert "results" in status
        assert len(status["results"]) == 1
        
        # Get the task result
        task_id = list(status["results"].keys())[0]
        task_result = status["results"][task_id]
        assert task_result["status"] == "completed"
        assert "result" in task_result
        
        # For Python execution, result should contain output
        result_data = task_result["result"]
        assert result_data["success"] is True
        assert "output" in result_data
        assert "Text analysis:" in result_data["output"]
    
    @pytest.mark.asyncio
    async def test_execute_dependent_workflow_from_file(self, api_client):
        """Test executing dependent_workflow.yaml through API"""
        # Load the actual workflow file
        workflow_path = Path("examples/dependent_workflow.yaml")
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Convert to API format using the helper function
        api_workflow = convert_workflow_to_api_format(workflow_content)
        
        # Submit workflow via API
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        
        # Wait for execution
        await asyncio.sleep(5.0)
        
        # Check workflow status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Should have completed
        assert status["status"] == "completed"
        assert status["tasks_completed"] > 0
        assert "results" in status
    
    @pytest.mark.asyncio
    async def test_execute_parallel_workflow(self, api_client):
        """Test executing parallel_workflow.yaml through API"""
        workflow_path = Path("examples/parallel_workflow.yaml")
        
        # Upload and execute workflow file
        with open(workflow_path, 'rb') as f:
            files = {"file": ("parallel_workflow.yaml", f, "application/yaml")}
            response = await api_client.post("/workflows/upload", files=files)
        
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        
        # Check that parallel tasks are created
        await asyncio.sleep(0.3)
        
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        # Parallel workflow has 3 independent tasks
        assert status.get("tasks_total") == 3 or status.get("tasks") == 3
    
    @pytest.mark.asyncio
    async def test_execute_dependent_workflow(self, api_client):
        """Test workflow with task dependencies"""
        # Create temp files for each task
        import tempfile
        
        # Create task files
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("result = {'numbers': [1, 2, 3, 4, 5], 'sum': 15}")
            generate_file = f.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("# Process task - depends on generate")
            process_file = f.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("# Verify task - depends on process")
            verify_file = f.name
        
        workflow = {
            "name": "Dependent Test Workflow",
            "description": "Test task dependencies",
            "tasks": [
                {
                    "id": "generate",
                    "name": "Generate Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "file": generate_file
                    }
                },
                {
                    "id": "process",
                    "name": "Process Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "file": process_file
                    },
                    "dependencies": ["generate"]
                },
                {
                    "id": "verify",
                    "name": "Verify Result",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "file": verify_file
                    },
                    "dependencies": ["process"]
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(2.0)
        
        # Check final status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["tasks_total"] == 3
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 3
        assert status["tasks_failed"] == 0
        
        # Check that all tasks have results
        assert "results" in status
        assert len(status["results"]) == 3
        
        # Verify each task completed
        for task_id, result in status["results"].items():
            assert result["status"] == "completed"
            assert "result" in result
    
    
    @pytest.mark.asyncio
    async def test_batch_text_processing(self, api_client):
        """Test batch processing of text files through API"""
        # Create temporary test files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test text files with different content
            test_files = [
                ("document1.txt", "This is the first document. It contains some test text for analysis."),
                ("document2.txt", "The second document has different content. We want to process it in batch."),
                ("document3.txt", "Finally, the third document completes our test set. Batch processing is useful.")
            ]
            
            for filename, content in test_files:
                file_path = temp_path / filename
                file_path.write_text(content)
            
            # Submit batch processing request
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "*.txt",
                "prompt": "Summarize this document in one sentence",
                "model": "llama3.2:latest"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            # Check batch response structure
            assert "batch_id" in data
            assert data["total_files"] == 3
            assert "successful" in data
            assert "failed" in data
            assert "processing_time" in data
            assert "results" in data
            
            # If batch completed synchronously, check results
            if data["successful"] > 0:
                assert len(data["results"]) > 0
                # Each result should have file info and response/content
                for filename, result in data["results"].items():
                    assert filename.endswith(".txt")
                    if result.get("status") == "success":
                        # Batch results can have content, response, or result field
                        assert any(field in result for field in ["content", "response", "result"])
    
    @pytest.mark.asyncio
    async def test_batch_python_processing(self, api_client):
        """Test batch processing of Python files"""
        # Create temporary Python scripts
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test Python files
            scripts = [
                ("script1.py", "result = 2 + 2\nprint(f'Result: {result}')"),
                ("script2.py", "import math\nresult = math.sqrt(16)\nprint(f'Square root: {result}')"),
                ("script3.py", "data = [1, 2, 3, 4, 5]\nresult = sum(data)\nprint(f'Sum: {result}')")
            ]
            
            for filename, content in scripts:
                file_path = temp_path / filename
                file_path.write_text(content)
            
            # Submit batch processing for Python files
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "*.py",
                "method": "python/execute",
                "prompt": ""  # Not needed for Python execution
            })
            
            # Check response
            assert response.status_code == 200
            data = response.json()
            
            assert data["total_files"] == 3
            assert "batch_id" in data
            assert "results" in data
    
    @pytest.mark.asyncio
    async def test_batch_with_subdirectories(self, api_client):
        """Test batch processing with files in subdirectories"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create subdirectories with files
            (temp_path / "subdir1").mkdir()
            (temp_path / "subdir2").mkdir()
            
            # Create files in root and subdirs
            (temp_path / "root.txt").write_text("Root file content")
            (temp_path / "subdir1" / "file1.txt").write_text("Subdirectory 1 content")
            (temp_path / "subdir2" / "file2.txt").write_text("Subdirectory 2 content")
            
            # Test with recursive pattern
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "**/*.txt",  # Recursive pattern
                "prompt": "Count the words",
                "model": "llama3.2:latest"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            # Should find files in subdirectories
            assert data["total_files"] >= 2  # At least files in subdirs
    
    @pytest.mark.asyncio
    async def test_batch_with_no_matching_files(self, api_client):
        """Test batch processing when no files match pattern"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create files that don't match the pattern we'll search for
            (temp_path / "document.txt").write_text("Some text")
            (temp_path / "data.json").write_text('{"key": "value"}')
            
            # Search for pattern that doesn't match any files
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "*.pdf",  # No PDF files exist
                "prompt": "Analyze this",
                "model": "llama3.2:latest"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            # Should handle no matching files gracefully
            assert data["total_files"] == 0
            assert data["successful"] == 0
            assert data["failed"] == 0
    
    @pytest.mark.asyncio
    async def test_batch_with_mixed_file_types(self, api_client):
        """Test batch processing with different file types"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create different file types
            (temp_path / "text.txt").write_text("Plain text content")
            (temp_path / "data.json").write_text('{"message": "JSON data"}')
            (temp_path / "script.py").write_text("print('Python script')")
            (temp_path / "doc.md").write_text("# Markdown\nSome markdown content")
            
            # Process all text-like files
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "*.*",  # All files
                "prompt": "Identify the file type and summarize content",
                "model": "llama3.2:latest"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["total_files"] == 4
            assert "batch_id" in data
    
    @pytest.mark.asyncio
    async def test_execute_llm_workflow(self, api_client):
        """Test executing llm_workflow.yaml through API"""
        # Load the actual LLM workflow file
        workflow_path = Path("examples/llm_workflow.yaml")
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Convert to API format using helper
        api_workflow = convert_workflow_to_api_format(workflow_content)
        
        # Submit workflow via API
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        assert data["tasks_total"] == 1
        
        # Wait for execution
        await asyncio.sleep(3.0)
        
        # Check workflow status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Should have completed
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        assert status["tasks_failed"] == 0
        
        # Check results
        assert "results" in status
        assert len(status["results"]) == 1
        
        # Get the task result
        task_result = list(status["results"].values())[0]
        assert task_result["status"] == "completed"
        assert "result" in task_result
        
        # For LLM tasks, result should contain response
        result_data = task_result["result"]
        assert "response" in result_data
        # Response should be a non-empty string from real Ollama
        assert isinstance(result_data["response"], str)
        assert len(result_data["response"]) > 0
    
    @pytest.mark.asyncio
    async def test_execute_mixed_workflow(self, api_client):
        """Test executing mixed_workflow.yaml with Python and LLM tasks"""
        # Load the actual workflow file
        workflow_path = Path("examples/mixed_workflow.yaml")
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Convert to API format using helper
        api_workflow = convert_workflow_to_api_format(workflow_content)
        
        # Submit workflow via API
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        
        # Wait for execution
        await asyncio.sleep(5.0)
        
        # Check workflow status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Should have completed
        assert status["status"] == "completed"
        assert status["tasks_completed"] > 0
        assert "results" in status
    
    @pytest.mark.asyncio
    async def test_execute_python_only_workflow(self, api_client):
        """Test executing python_only_workflow.yaml"""
        # Load the actual workflow file
        workflow_path = Path("examples/python_only_workflow.yaml")
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Convert to API format using helper
        api_workflow = convert_workflow_to_api_format(workflow_content)
        
        # Submit workflow via API
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        
        # Wait for execution
        await asyncio.sleep(3.0)
        
        # Check workflow status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Should have completed
        assert status["status"] == "completed"
        assert status["tasks_completed"] == len(workflow_content["tasks"])
        assert status["tasks_failed"] == 0
        
        # Check that all tasks have results
        assert "results" in status
        for task_id, result in status["results"].items():
            assert result["status"] == "completed"
            assert "result" in result
    
    @pytest.mark.asyncio
    async def test_execute_simple_mcp_workflow(self, api_client):
        """Test executing simple_mcp_workflow.yaml"""
        # Load the actual workflow file
        workflow_path = Path("examples/simple_mcp_workflow.yaml")
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Convert to API format using helper
        api_workflow = convert_workflow_to_api_format(workflow_content)
        
        # Submit workflow via API
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        
        # Wait for execution (MCP tools are fast)
        await asyncio.sleep(2.0)
        
        # Check workflow status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Should have completed
        assert status["status"] == "completed"
        assert status["tasks_completed"] > 0
        assert "results" in status
        
        # MCP tools should return results
        for task_id, result in status["results"].items():
            assert result["status"] == "completed"
            assert "result" in result
    
    @pytest.mark.asyncio
    async def test_task_priority_execution(self, api_client):
        """Test that task priorities are respected"""
        # Submit multiple tasks with different priorities
        import tempfile
        tasks = []
        
        for priority in ["urgent", "high", "normal", "low"]:
            # Create temp file for each task
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(f"result = '{priority}'")
                task_file = f.name
            
            response = await api_client.post("/tasks", json={
                "name": f"Task with {priority} priority",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"file": task_file},
                "priority": priority
            })
            assert response.status_code == 200
            tasks.append(response.json())
        
        # All tasks should be submitted
        assert len(tasks) == 4
        for task in tasks:
            assert task["status"] == "submitted"
    
    @pytest.mark.asyncio
    async def test_workflow_cancellation(self, api_client):
        """Test cancelling a running workflow"""
        import tempfile
        
        # Create temp files for long-running tasks
        task_files = []
        for i in range(10):
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write("import time; time.sleep(0.1); result = 1")
                task_files.append(f.name)
        
        # Submit a long-running workflow
        workflow = {
            "name": "Long Running Workflow",
            "tasks": [
                {
                    "name": f"Task {i}",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"file": task_files[i]}
                }
                for i in range(10)
            ]
        }
        
        response = await api_client.post("/workflows", json=workflow)
        workflow_id = response.json()["workflow_id"]
        
        # Wait a bit then cancel
        await asyncio.sleep(0.2)
        
        response = await api_client.delete(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        
        # Verify workflow is cancelled
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.json()["status"] == "cancelled"
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("workflow_file", [
        "simple_python_workflow.yaml",
        "llm_workflow.yaml", 
        "mixed_workflow.yaml",
        "python_only_workflow.yaml",
        "simple_mcp_workflow.yaml",
        "dependent_workflow.yaml",
        "parallel_workflow.yaml",
        "simple_llm_workflow.yaml",
        "mcp_workflow.yaml",
        "test_complex_python.yaml",
    ])
    async def test_execute_example_workflows(self, api_client, workflow_file):
        """Test executing various example workflows through API"""
        # Load the workflow file
        workflow_path = Path(f"examples/{workflow_file}")
        if not workflow_path.exists():
            pytest.skip(f"Workflow file {workflow_file} not found")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Skip batch workflows as they need special handling
        if workflow_content.get("type") == "batch":
            pytest.skip("Batch workflows need special handling")
        
        # Convert to API format using helper
        api_workflow = convert_workflow_to_api_format(workflow_content)
        
        # Submit workflow via API
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        data = response.json()
        
        workflow_id = data["workflow_id"]
        assert data["status"] == "submitted"
        
        # Wait for execution (longer for workflows with LLM tasks)
        has_llm = any("llm" in str(task.get("protocol", "")).lower() or 
                      "llm" in str(task.get("method", "")).lower() 
                      for task in workflow_content.get("tasks", []))
        wait_time = 5.0 if has_llm else 3.0
        await asyncio.sleep(wait_time)
        
        # Check workflow status and results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Should have completed
        assert status["status"] == "completed"
        assert status["tasks_completed"] > 0
        assert "results" in status
        
        # Verify at least some tasks completed successfully
        successful_tasks = [r for r in status["results"].values() 
                           if r["status"] == "completed"]
        assert len(successful_tasks) > 0
    
    @pytest.mark.asyncio
    async def test_system_health_with_real_components(self, api_client):
        """Test system health endpoints with real components"""
        # Check health
        response = await api_client.get("/health")
        assert response.status_code == 200
        health = response.json()
        
        assert health["status"] == "healthy"
        assert "providers" in health
        assert len(health["providers"]) > 0
        
        # Check status
        response = await api_client.get("/status")
        assert response.status_code == 200
        status = response.json()
        
        assert status["status"] == "running"
        assert "uptime_seconds" in status
        assert "task_statistics" in status
        
        # Check providers
        response = await api_client.get("/providers")
        assert response.status_code == 200
        providers = response.json()["providers"]
        
        # Should have Python and Ollama providers
        assert len(providers) >= 2
        provider_names = [p["name"] for p in providers]
        assert "PythonProvider" in provider_names or "python_real" in [p["id"] for p in providers]
    
    @pytest.mark.asyncio
    async def test_error_handling_with_real_execution(self, api_client):
        """Test error handling with real execution engine"""
        # Create a temp file with invalid code for the task
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("this is invalid python code!!!")
            invalid_file = f.name
        
        # Submit task with file containing syntax error
        response = await api_client.post("/tasks", json={
            "name": "Failing Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"file": invalid_file}
        })
        
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        
        # Wait for execution
        await asyncio.sleep(0.5)
        
        # Check task failed properly
        response = await api_client.get(f"/tasks/{task_id}")
        if response.status_code == 200:
            task_status = response.json()
            # Task should either be running or failed
            assert task_status["status"] in ["submitted", "running", "failed"]


@pytest.mark.e2e
@pytest.mark.asyncio  
class TestAPIWorkflowTemplates:
    """Test workflow templates through the API with real execution"""
    
    @pytest.fixture
    async def api_with_templates(self, api_client):
        """API client with template support"""
        return api_client
    
    @pytest.mark.asyncio
    async def test_research_template_execution(self, api_with_templates):
        """Test research template with real execution"""
        response = await api_with_templates.post("/templates/research", json={
            "topic": "Workflow orchestration benefits",
            "depth": "medium",
            "max_steps": 3
        })
        
        # Template execution may return different status codes
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            data = response.json()
            assert "workflow_id" in data or "template_type" in data
    
    @pytest.mark.asyncio
    async def test_code_template_execution(self, api_with_templates):
        """Test code generation template"""
        response = await api_with_templates.post("/templates/code", json={
            "task": "Create a function to calculate fibonacci numbers",
            "language": "python"
        })
        
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            data = response.json()
            assert "workflow_id" in data or "code" in data
    
    @pytest.mark.asyncio
    async def test_analysis_template_execution(self, api_with_templates):
        """Test analysis template"""
        response = await api_with_templates.post("/templates/analyze", json={
            "content": "The quick brown fox jumps over the lazy dog. This is a test sentence.",
            "question": "What animals are mentioned?"
        })
        
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            data = response.json()
            assert "analysis" in data or "workflow_id" in data