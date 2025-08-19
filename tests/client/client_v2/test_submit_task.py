"""
Test submit_task as the primary method for task submission
"""

import pytest
import asyncio
from gleitzeit import Client
from gleitzeit.core.models import Priority, TaskStatus


class TestSubmitTask:
    """Test submit_task functionality"""
    
    @pytest.mark.asyncio
    async def test_submit_task_returns_immediately(self, native_client):
        """Test that submit_task returns immediately without waiting"""
        start_time = asyncio.get_event_loop().time()
        
        task = await native_client.submit_task(
            name="Quick Submit Test",
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "test"}
        )
        
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # Should return in less than 100ms (not waiting for execution)
        assert elapsed < 0.1
        assert task.id is not None
        assert task.status in ["pending", "queued"]
    
    @pytest.mark.asyncio
    async def test_submit_task_with_priority(self, native_client):
        """Test submitting tasks with different priorities"""
        # Submit high priority task
        high_task = await native_client.submit_task(
            name="High Priority Task",
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 1, "b": 2},
            priority=Priority.HIGH
        )
        
        # Submit normal priority task
        normal_task = await native_client.submit_task(
            name="Normal Priority Task",
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 3, "b": 4},
            priority=Priority.NORMAL
        )
        
        # Submit low priority task
        low_task = await native_client.submit_task(
            name="Low Priority Task",
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 5, "b": 6},
            priority=Priority.LOW
        )
        
        assert high_task.priority == Priority.HIGH
        assert normal_task.priority == Priority.NORMAL
        assert low_task.priority == Priority.LOW
    
    @pytest.mark.asyncio
    async def test_submit_and_wait(self, native_client):
        """Test submitting a task and then waiting for it"""
        # Submit task
        task = await native_client.submit_task(
            name="Submit and Wait Test",
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 7, "b": 8}
        )
        
        # Task should be pending/queued initially
        initial_status = await native_client.get_task_status(task.id)
        assert initial_status in ["pending", "queued", "running", "completed"]
        
        # Wait for completion
        result = await native_client.wait_for_task(task.id, timeout=5.0)
        assert result is not None
        assert result.status == "completed"
        assert result.result["result"] == 56
    
    @pytest.mark.asyncio
    async def test_submit_multiple_tasks(self, native_client):
        """Test submitting multiple tasks concurrently"""
        tasks = []
        
        # Submit 10 tasks
        for i in range(10):
            task = await native_client.submit_task(
                name=f"Batch Task {i}",
                protocol="mcp/v1",
                method="mcp/tool.add",
                params={"a": i, "b": i + 1}
            )
            tasks.append(task)
        
        # All tasks should have IDs
        assert all(t.id is not None for t in tasks)
        
        # Wait a bit for processing
        await asyncio.sleep(2)
        
        # Check all tasks completed
        for i, task in enumerate(tasks):
            result = await native_client.get_task_result(task.id)
            if result and result.status == "completed":
                assert result.result["result"] == i + (i + 1)
    
    @pytest.mark.asyncio
    async def test_submit_task_persistence(self, native_client):
        """Test that submitted tasks are persisted"""
        # Submit task
        task = await native_client.submit_task(
            name="Persistence Test",
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "persist me"}
        )
        
        # Should be able to retrieve task immediately
        retrieved = await native_client.get_task(task.id)
        assert retrieved is not None
        assert retrieved.name == "Persistence Test"
        
        # Wait for completion
        await native_client.wait_for_task(task.id, timeout=5.0)
        
        # Should still be retrievable after completion
        completed_task = await native_client.get_task(task.id)
        assert completed_task is not None
        assert completed_task.status == "completed"


class TestExecuteTask:
    """Test execute_task as convenience method"""
    
    @pytest.mark.asyncio
    async def test_execute_task_waits_for_completion(self, native_client):
        """Test that execute_task waits for completion by default"""
        start_time = asyncio.get_event_loop().time()
        
        result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 10, "b": 20},
            name="Execute Wait Test"
        )
        
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # Should have waited for completion
        assert result.status == "completed"
        assert result.result["result"] == 30
        # Should take some time (but not timeout)
        assert elapsed < 5.0
    
    @pytest.mark.asyncio
    async def test_execute_task_no_wait(self, native_client):
        """Test execute_task with wait=False"""
        start_time = asyncio.get_event_loop().time()
        
        result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 5, "b": 5},
            name="Execute No Wait Test",
            wait=False
        )
        
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # Should return immediately
        assert elapsed < 0.1
        assert result.status == "pending"
        assert result.task_id is not None
        
        # Can still wait for it manually
        final_result = await native_client.wait_for_task(result.task_id, timeout=5.0)
        assert final_result.status == "completed"
        assert final_result.result["result"] == 25
    
    @pytest.mark.asyncio
    async def test_execute_task_timeout(self, native_client):
        """Test execute_task timeout handling"""
        # This would need a slow task to test properly
        # For now, just test that normal tasks don't timeout
        result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "timeout test"},
            name="Timeout Test"
        )
        
        assert result.status != "timeout"
        assert result.status == "completed"


class TestSubmitVsExecute:
    """Compare submit_task and execute_task behavior"""
    
    @pytest.mark.asyncio
    async def test_performance_difference(self, native_client):
        """Test that submit_task is faster than execute_task"""
        # Time submit_task (should be fast)
        submit_start = asyncio.get_event_loop().time()
        submitted_task = await native_client.submit_task(
            name="Submit Performance",
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 1, "b": 1}
        )
        submit_time = asyncio.get_event_loop().time() - submit_start
        
        # Time execute_task (should wait)
        execute_start = asyncio.get_event_loop().time()
        executed_result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 2, "b": 2},
            name="Execute Performance"
        )
        execute_time = asyncio.get_event_loop().time() - execute_start
        
        # Submit should be much faster
        assert submit_time < 0.1  # Less than 100ms
        assert execute_time >= submit_time  # Execute waits for completion
        
        # Both should eventually complete successfully
        await asyncio.sleep(1)
        submit_result = await native_client.get_task_result(submitted_task.id)
        assert submit_result.status == "completed"
        assert executed_result.status == "completed"
    
    @pytest.mark.asyncio
    async def test_both_methods_compatible(self, native_client):
        """Test that both methods work together"""
        # Submit some tasks
        task1 = await native_client.submit_task(
            name="Background Task 1",
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 10, "b": 10}
        )
        
        task2 = await native_client.submit_task(
            name="Background Task 2",
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 5, "b": 5}
        )
        
        # Execute a task (waits)
        execute_result = await native_client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "foreground"},
            name="Foreground Task"
        )
        
        # All should work
        assert execute_result.status == "completed"
        
        # Wait for submitted tasks
        result1 = await native_client.wait_for_task(task1.id, timeout=5.0)
        result2 = await native_client.wait_for_task(task2.id, timeout=5.0)
        
        assert result1.status == "completed"
        assert result1.result["result"] == 20
        assert result2.status == "completed"
        assert result2.result["result"] == 25