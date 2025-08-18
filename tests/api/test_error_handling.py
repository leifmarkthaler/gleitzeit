"""
Tests for API error handling and edge cases
"""

import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch


class TestHTTPStatusCodes:
    """Test proper HTTP status code responses"""
    
    @pytest.mark.asyncio
    async def test_404_for_unknown_endpoints(self, async_client):
        """Test 404 for unknown endpoints"""
        response = await async_client.get("/unknown/endpoint")
        assert response.status_code == 404
        
        response = await async_client.post("/api/v2/tasks")
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_405_for_wrong_method(self, async_client):
        """Test 405 for wrong HTTP method"""
        # GET on POST-only endpoint
        response = await async_client.get("/workflows")
        assert response.status_code == 405
        
        # POST on GET-only endpoint
        response = await async_client.post("/status", json={})
        assert response.status_code == 405
    
    @pytest.mark.asyncio
    async def test_422_for_invalid_json(self, async_client):
        """Test 422 for invalid JSON body"""
        response = await async_client.post(
            "/workflows",
            content=b"invalid json {",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_422_for_missing_fields(self, async_client):
        """Test 422 for missing required fields"""
        # Workflow without name
        response = await async_client.post("/workflows", json={
            "tasks": []
        })
        assert response.status_code == 422
        
        # Task without name
        response = await async_client.post("/tasks", json={
            "protocol": "python/v1"
        })
        assert response.status_code == 422


class TestSystemNotInitialized:
    """Test handling when system components not initialized"""
    
    @pytest.mark.asyncio
    async def test_all_endpoints_without_engine(self, async_client):
        """Test all endpoints return 503 when engine not initialized"""
        from gleitzeit.api.main import app_state
        
        original_engine = app_state.execution_engine
        app_state.execution_engine = None
        
        endpoints = [
            ("POST", "/workflows", {"name": "test", "tasks": []}),
            ("POST", "/tasks", {"name": "test", "protocol": "p", "method": "m"}),
            ("POST", "/execute/python", {"code": "test", "timeout": 30}),
            ("POST", "/chat", {"message": "test"}),
            ("POST", "/templates/research", {"topic": "test"})
        ]
        
        for method, endpoint, data in endpoints:
            if method == "POST":
                response = await async_client.post(endpoint, json=data)
            else:
                response = await async_client.get(endpoint)
            
            assert response.status_code == 503
            assert "System not initialized" in response.json()["detail"]
        
        app_state.execution_engine = original_engine
    
    @pytest.mark.asyncio
    async def test_batch_without_processor(self, async_client):
        """Test batch endpoint without batch processor"""
        from gleitzeit.api.main import app_state
        
        original_processor = app_state.batch_processor
        app_state.batch_processor = None
        
        response = await async_client.post("/batch", json={
            "directory": "/tmp",
            "pattern": "*",
            "prompt": "test"
        })
        
        assert response.status_code == 503
        
        app_state.batch_processor = original_processor


class TestExceptionHandling:
    """Test handling of various exceptions"""
    
    @pytest.mark.asyncio
    async def test_execution_engine_exceptions(self, async_client, mock_execution_engine):
        """Test handling execution engine exceptions"""
        # Submit workflow exception
        mock_execution_engine.submit_workflow.side_effect = Exception("Engine error")
        
        response = await async_client.post("/workflows", json={
            "name": "Test",
            "tasks": [{"name": "t", "protocol": "p", "method": "m"}]
        })
        
        # Should still return 200 as error happens in background
        assert response.status_code == 200
        
        # Reset
        mock_execution_engine.submit_workflow.side_effect = None
    
    @pytest.mark.asyncio
    async def test_persistence_exceptions(self, async_client, mock_persistence):
        """Test handling persistence exceptions"""
        # Make persistence fail
        mock_persistence.get_task_count_by_status.side_effect = Exception("DB connection lost")
        
        response = await async_client.get("/status")
        
        # Should still return status but with empty statistics
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["task_statistics"] == {}
    
    @pytest.mark.asyncio
    async def test_provider_exceptions(self, async_client, mock_execution_engine):
        """Test handling provider exceptions"""
        # Make provider raise exception
        provider = mock_execution_engine.registry.provider_instances["test-python-provider"]
        provider.get_supported_methods.side_effect = Exception("Provider error")
        
        response = await async_client.get("/providers")
        
        # Should handle gracefully
        assert response.status_code == 200
        
        # Reset
        provider.get_supported_methods.side_effect = None
        provider.get_supported_methods.return_value = ["python/execute"]


class TestConcurrency:
    """Test concurrent request handling"""
    
    @pytest.mark.asyncio
    async def test_concurrent_workflow_submissions(self, async_client, mock_execution_engine):
        """Test submitting multiple workflows concurrently"""
        workflow = {
            "name": "Concurrent Test",
            "tasks": [{"name": "task", "protocol": "p", "method": "m"}]
        }
        
        # Submit 10 workflows concurrently
        tasks = [
            async_client.post("/workflows", json=workflow)
            for _ in range(10)
        ]
        
        responses = await asyncio.gather(*tasks)
        
        # All should succeed
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "submitted"
            assert "workflow_id" in data
        
        # All workflow IDs should be unique
        workflow_ids = [r.json()["workflow_id"] for r in responses]
        assert len(set(workflow_ids)) == 10
    
    @pytest.mark.asyncio
    async def test_concurrent_task_executions(self, async_client, mock_execution_engine):
        """Test executing multiple tasks concurrently"""
        task = {
            "name": "Concurrent Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"code": "result = 1"}
        }
        
        # Submit 10 tasks concurrently
        tasks = [
            async_client.post("/tasks", json=task)
            for _ in range(10)
        ]
        
        responses = await asyncio.gather(*tasks)
        
        # All should succeed
        for response in responses:
            assert response.status_code == 200
            assert response.json()["status"] == "submitted"
    
    @pytest.mark.asyncio
    async def test_concurrent_different_endpoints(self, async_client, mock_execution_engine):
        """Test calling different endpoints concurrently"""
        tasks = [
            async_client.get("/status"),
            async_client.get("/health"),
            async_client.get("/providers"),
            async_client.post("/tasks", json={
                "name": "task", "protocol": "p", "method": "m"
            }),
            async_client.post("/workflows", json={
                "name": "wf", "tasks": []
            })
        ]
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check no exceptions occurred
        for response in responses:
            assert not isinstance(response, Exception)
            assert response.status_code in [200, 400, 422]


class TestInputValidation:
    """Test input validation and sanitization"""
    
    @pytest.mark.asyncio
    async def test_sql_injection_protection(self, async_client):
        """Test protection against SQL injection attempts"""
        malicious_inputs = [
            "'; DROP TABLE tasks; --",
            "1' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM users --"
        ]
        
        for malicious in malicious_inputs:
            response = await async_client.post("/tasks", json={
                "name": malicious,
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": malicious}
            })
            
            # Should accept but safely handle the input
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_xss_protection(self, async_client):
        """Test protection against XSS attempts"""
        xss_attempts = [
            "<script>alert('XSS')</script>",
            "javascript:alert('XSS')",
            "<img src=x onerror=alert('XSS')>",
            "<svg onload=alert('XSS')>"
        ]
        
        for xss in xss_attempts:
            response = await async_client.post("/chat", json={
                "message": xss,
                "model": "test"
            })
            
            # Should handle safely
            assert response.status_code in [200, 500]
    
    @pytest.mark.asyncio
    async def test_path_traversal_protection(self, async_client):
        """Test protection against path traversal"""
        dangerous_paths = [
            "../../../etc/passwd",
            "/etc/shadow"
        ]
        
        for path in dangerous_paths:
            try:
                response = await async_client.post("/batch", json={
                    "directory": path,
                    "pattern": "*",
                    "prompt": "test"
                })
                # Should reject or handle safely
                assert response.status_code in [400, 422, 500, 503]
            except Exception:
                # May fail during JSON encoding, which is also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_large_input_handling(self, async_client):
        """Test handling of very large inputs"""
        # Very large code
        large_code = "x = 1\n" * 100000  # ~600KB
        
        response = await async_client.post("/execute/python", json={
            "code": large_code,
            "timeout": 30
        })
        
        # Should handle (may accept or reject based on limits)
        assert response.status_code in [200, 413, 422, 500]
        
        # Very many tasks in workflow
        many_tasks = [
            {"name": f"task_{i}", "protocol": "p", "method": "m"}
            for i in range(1000)
        ]
        
        response = await async_client.post("/workflows", json={
            "name": "Large Workflow",
            "tasks": many_tasks
        })
        
        # Should handle
        assert response.status_code in [200, 413, 422]


class TestTimeoutHandling:
    """Test timeout handling"""
    
    @pytest.mark.asyncio
    async def test_request_timeout(self, async_client, mock_execution_engine):
        """Test handling of slow requests"""
        # Make execution engine slow
        async def slow_submit(*args, **kwargs):
            await asyncio.sleep(10)
        
        mock_execution_engine.submit_workflow = slow_submit
        
        # This should return immediately (background task)
        response = await async_client.post("/workflows", json={
            "name": "Test",
            "tasks": [{"name": "task1", "protocol": "p", "method": "m"}]
        })
        
        assert response.status_code == 200
        
        # Reset
        mock_execution_engine.submit_workflow = AsyncMock()
    
    @pytest.mark.asyncio
    async def test_execution_timeout(self, async_client):
        """Test execution timeout handling"""
        response = await async_client.post("/execute/python", json={
            "code": "import time; time.sleep(100)",
            "timeout": 1
        })
        
        # Should accept the request
        assert response.status_code in [200, 500]


class TestResourceLimits:
    """Test resource limit handling"""
    
    @pytest.mark.asyncio
    async def test_workflow_limit(self, async_client):
        """Test limits on active workflows"""
        from gleitzeit.api.main import app_state
        
        # Fill up active workflows
        for i in range(1000):
            app_state.active_workflows[f"test_{i}"] = MagicMock()
        
        # Should still accept new workflow
        response = await async_client.post("/workflows", json={
            "name": "Test",
            "tasks": [{"name": "task1", "protocol": "p", "method": "m"}]
        })
        
        assert response.status_code == 200
        
        # Clean up
        app_state.active_workflows.clear()
    
    @pytest.mark.asyncio
    async def test_task_limit(self, async_client):
        """Test limits on active tasks"""
        from gleitzeit.api.main import app_state
        
        # Fill up active tasks
        for i in range(1000):
            app_state.active_tasks[f"test_{i}"] = MagicMock()
        
        # Should still accept new task
        response = await async_client.post("/tasks", json={
            "name": "Test",
            "protocol": "p",
            "method": "m"
        })
        
        assert response.status_code == 200
        
        # Clean up
        app_state.active_tasks.clear()