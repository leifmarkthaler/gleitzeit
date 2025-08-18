"""
Test task execution functionality
"""

import pytest
import asyncio
from pathlib import Path

from gleitzeit import Client
from gleitzeit.core.models import Priority


class TestTaskExecution:
    """Test task execution in different modes"""
    
    @pytest.mark.asyncio
    async def test_execute_mcp_task_native(self, native_client):
        """Test MCP task execution in native mode"""
        result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 10, "b": 20},
            name="MCP Add Task"
        )
        
        assert result is not None
        assert result.status == "completed"
        assert result.result["result"] == 30
        assert "10 + 20 = 30" in result.result.get("calculation", "")
    
    @pytest.mark.asyncio
    async def test_execute_mcp_task_api(self, api_client):
        """Test MCP task execution in API mode"""
        result = await api_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 5, "b": 6},
            name="MCP Multiply Task"
        )
        
        assert result is not None
        assert result.status == "completed"
        assert result.result["result"] == 30
        assert "5 * 6 = 30" in result.result.get("calculation", "")
    
    @pytest.mark.asyncio
    async def test_execute_python_task(self, native_client, sample_python_script):
        """Test Python script execution"""
        # Use full path to the script
        script_path = f"examples/scripts/{sample_python_script}"
        result = await native_client.execute_task(
            protocol="python/v1",
            method="python/execute",
            params={"file": script_path},
            name="Python Script Task"
        )
        
        assert result is not None
        assert result.status == "completed"
        assert "Result: 42" in str(result.result)
    
    @pytest.mark.asyncio
    async def test_task_with_no_name(self, native_client):
        """Test task execution without providing a name"""
        result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "unnamed task"}
        )
        
        assert result is not None
        assert result.status == "completed"
        assert result.result["response"] == "unnamed task"
    
    @pytest.mark.asyncio
    async def test_multiple_tasks_sequential(self, native_client):
        """Test sequential execution of multiple tasks"""
        results = []
        
        for i in range(5):
            result = await native_client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.add",
                params={"a": i, "b": i + 1},
                name=f"Sequential Task {i}"
            )
            results.append(result)
        
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result.status == "completed"
            expected = i + (i + 1)
            assert result.result["result"] == expected
    
    @pytest.mark.asyncio
    async def test_task_failure_handling(self, native_client):
        """Test handling of task failures"""
        # Try to execute a non-existent Python file
        result = await native_client.execute_task(
            protocol="python/v1",
            method="python/execute",
            params={"file": "examples/scripts/non_existent_script.py"},
            name="Failed Task"
        )
        
        assert result is not None
        assert result.status in ["failed", "retry_pending"]
        assert result.error is not None
    
    @pytest.mark.asyncio
    async def test_task_with_complex_params(self, native_client):
        """Test task with complex nested parameters"""
        # MCP concat with string parameters
        result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.concat",
            params={
                "a": "Hello",
                "b": "World"
            },
            name="Complex Params Task"
        )
        
        assert result is not None
        assert result.status == "completed"
        assert result.result["response"] == "HelloWorld"


class TestTaskModes:
    """Test task execution across different client modes"""
    
    @pytest.mark.asyncio
    async def test_same_task_different_modes(self):
        """Test same task executes correctly in all modes"""
        task_params = {
            "protocol": "mcp/v1",
            "method": "mcp/tool.add",
            "params": {"a": 100, "b": 200},
            "name": "Cross-mode Task"
        }
        
        # Test in native mode
        async with Client(mode="native") as client:
            native_result = await client.execute_task(**task_params)
            assert native_result.status == "completed"
            assert native_result.result["result"] == 300
        
        # Test in API mode
        async with Client(mode="api", auto_start_server=True) as client:
            api_result = await client.execute_task(**task_params)
            assert api_result.status == "completed"
            assert api_result.result["result"] == 300
        
        # Test in auto mode
        async with Client(mode="auto") as client:
            auto_result = await client.execute_task(**task_params)
            assert auto_result.status == "completed"
            assert auto_result.result["result"] == 300


class TestConcurrentTasks:
    """Test concurrent task execution"""
    
    @pytest.mark.asyncio
    async def test_concurrent_tasks_native(self, native_client):
        """Test concurrent task execution in native mode"""
        tasks = []
        for i in range(10):
            task = native_client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.multiply",
                params={"a": i, "b": 2},
                name=f"Concurrent Task {i}"
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 10
        for i, result in enumerate(results):
            assert result.status == "completed"
            assert result.result["result"] == i * 2
    
    @pytest.mark.asyncio
    async def test_concurrent_tasks_api(self, api_client):
        """Test concurrent task execution in API mode"""
        tasks = []
        for i in range(5):
            task = api_client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.add",
                params={"a": i, "b": 10},
                name=f"API Concurrent Task {i}"
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result.status == "completed"
            assert result.result["result"] == i + 10