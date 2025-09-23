"""Tests for WorkflowHandler implementation"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gleitzeit.handlers.workflow import WorkflowHandler
from gleitzeit.core.models import Task, TaskResult, TaskStatus
from gleitzeit.core.errors import GleitzeitError
from gleitzeit.workers.workflow_submission_worker import WorkflowSubmissionWorker
from gleitzeit.workers.workflow_monitor_worker import WorkflowMonitorWorker
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.sharding import default_sharding


class TestWorkflowHandler:
    """Test WorkflowHandler functionality"""
    
    def test_capabilities(self):
        """Test handler reports correct capabilities"""
        caps = WorkflowHandler.get_capabilities()
        
        assert caps['protocol'] == 'workflow/v1'
        assert 'workflow' in caps['task_types']
        assert 'subworkflow' in caps['task_types']
        
        # Check methods
        assert 'workflow/execute' in caps['methods']
        assert 'workflow/execute_async' in caps['methods']
        
        # Check method requirements
        execute_method = caps['methods']['workflow/execute']
        assert 'workflow_ref' in execute_method['required']
        assert 'inputs' in execute_method['optional']
        assert 'shard_preference' in execute_method['optional']
    
    @pytest.mark.asyncio
    async def test_execute_workflow_task(self):
        """Test executing a workflow as a task"""
        handler = WorkflowHandler()
        
        task = Task(
            id="test-task-1",
            name="Execute Child Workflow",
            workflow_id="parent-workflow-123",
            method="workflow/execute",
            params={
                "workflow_ref": "workflows/child.yaml",
                "inputs": {"key": "value"},
                "shard_preference": "any"
            }
        )
        
        result = await handler.execute(task)
        
        # Should return WAITING status
        assert result.status == TaskStatus.WAITING
        assert result.metadata is not None
        assert result.metadata['waiting_for'] == 'workflow'
        assert 'child_workflow_id' in result.metadata
        assert result.metadata['parent_workflow_id'] == "parent-workflow-123"
        assert result.metadata['parent_task_id'] == "test-task-1"
        assert result.metadata['workflow_ref'] == "workflows/child.yaml"
        assert result.metadata['workflow_inputs'] == {"key": "value"}
    
    @pytest.mark.asyncio
    async def test_execute_async_workflow(self):
        """Test async workflow execution (fire-and-forget)"""
        handler = WorkflowHandler()
        
        task = Task(
            id="test-task-2",
            name="Async Workflow",
            workflow_id="parent-workflow-456",
            method="workflow/execute_async",
            params={
                "workflow_ref": "workflows/background.yaml",
                "inputs": {"job": "cleanup"},
                "callback": {"signal": "job-done"}
            }
        )
        
        result = await handler.execute(task)
        
        # Async execution should return immediately
        assert result.status == TaskStatus.COMPLETED
        assert result.metadata is not None
        assert 'child_workflow_id' in result.metadata
        assert result.metadata['async'] == True
    
    @pytest.mark.asyncio
    async def test_shard_preference(self):
        """Test different shard preference strategies"""
        handler = WorkflowHandler()
        
        # Test 'same' preference
        task1 = Task(
            id="test-task-3",
            name="Same Shard",
            workflow_id="parent-workflow-789",
            method="workflow/execute",
            params={
                "workflow_ref": "test.yaml",
                "shard_preference": "same"
            }
        )
        
        result1 = await handler.execute(task1)
        parent_shard = default_sharding.get_shard("parent-workflow-789")
        assert result1.metadata['child_shard'] == parent_shard
        
        # Test 'specific' preference
        task2 = Task(
            id="test-task-4",
            name="Specific Shard",
            workflow_id="parent-workflow-789",
            method="workflow/execute",
            params={
                "workflow_ref": "test.yaml",
                "shard_preference": "specific:5"
            }
        )
        
        result2 = await handler.execute(task2)
        assert result2.metadata['child_shard'] == 5
        
        # Test 'any' preference (default)
        task3 = Task(
            id="test-task-5",
            name="Any Shard",
            workflow_id="parent-workflow-789",
            method="workflow/execute",
            params={
                "workflow_ref": "test.yaml",
                "shard_preference": "any"
            }
        )
        
        result3 = await handler.execute(task3)
        assert 'child_shard' in result3.metadata
        assert 0 <= result3.metadata['child_shard'] < 16
    
    @pytest.mark.asyncio
    async def test_invalid_method(self):
        """Test handling of invalid method"""
        handler = WorkflowHandler()

        task = Task(
            id="test-task-6",
            name="Invalid Method",
            workflow_id="parent-workflow-999",
            method="workflow/invalid",
            params={}
        )

        with pytest.raises(GleitzeitError) as exc:
            await handler.execute(task)

        assert "not supported" in str(exc.value) or "Unknown method" in str(exc.value)


class TestWorkflowSubmissionWorker:
    """Test WorkflowSubmissionWorker functionality"""
    
    @pytest.mark.asyncio
    async def test_workflow_submission(self):
        """Test submitting child workflow to target shard"""
        # Create mock Redis
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.xadd = AsyncMock()
        
        # Create worker config
        config = WorkerConfig(
            worker_type="workflow_submission",
            worker_id="test-submission-worker",
            consumer_group="test-group"
        )
        
        # Create worker
        worker = WorkflowSubmissionWorker(config)
        worker.redis = mock_redis
        worker.shard = 0
        
        # Test data
        data = {
            b'child_workflow_id': b'parent:child:123',
            b'parent_workflow_id': b'parent-workflow',
            b'parent_task_id': b'task-123',
            b'workflow_ref': b'test.yaml',
            b'inputs': b'{"key": "value"}',
            b'target_shard': b'5',
            b'timestamp': datetime.utcnow().isoformat().encode()
        }
        
        # Process message
        await worker.process_message("workflow:submit", "msg-1", data)
        
        # Verify registry update
        mock_redis.hset.assert_called()
        registry_call = mock_redis.hset.call_args_list[0]
        assert 'workflow:children:parent:child:123' in registry_call[0][0]
        
        # Verify parent children set update
        mock_redis.sadd.assert_called()
        
        # Verify submission to target shard
        mock_redis.xadd.assert_called()
        submission_call = mock_redis.xadd.call_args_list[0]
        assert 'shard:5' in submission_call[0][0]  # Target shard in key


class TestWorkflowMonitorWorker:
    """Test WorkflowMonitorWorker functionality"""
    
    @pytest.mark.asyncio
    async def test_local_completion_handling(self):
        """Test handling workflow completion on same shard"""
        # Create mock Redis
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(side_effect=[
            # First call: child registry info
            {
                b'parent_workflow_id': b'parent-wf',
                b'parent_task_id': b'parent-task',
                b'parent_shard': b'0'
            },
            # Second call: task data
            {
                b'status': b'waiting',  # TaskStatus.WAITING.value
                b'task_id': b'parent-task'
            }
        ])
        mock_redis.hset = AsyncMock()
        mock_redis.xadd = AsyncMock()
        mock_redis.srem = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # No callback
        mock_redis.delete = AsyncMock()
        
        # Create worker config
        config = WorkerConfig(
            worker_type="workflow_monitor",
            worker_id="test-monitor-worker",
            consumer_group="test-group"
        )
        
        # Create worker
        worker = WorkflowMonitorWorker(config)
        worker.redis = mock_redis
        worker.shard = 0
        
        # Test data
        data = {
            b'workflow_id': b'child-workflow-123',
            b'result': b'{"output": "success"}',
            b'status': b'completed',
            b'timestamp': datetime.utcnow().isoformat().encode()
        }
        
        # Process local completion
        await worker.process_message("{shard:0}:workflow:completed", "msg-1", data)
        
        # Verify registry update
        mock_redis.hset.assert_called()
        
        # Verify parent task wake (should emit to task:completed stream)
        mock_redis.xadd.assert_called()
        completed_call = mock_redis.xadd.call_args_list[0]
        # The stream key should contain 'task:completed'
        stream_key = completed_call[0][0].decode() if isinstance(completed_call[0][0], bytes) else completed_call[0][0]
        assert 'task:completed' in stream_key
    
    @pytest.mark.asyncio
    async def test_cross_shard_notification(self):
        """Test sending notification to parent on different shard"""
        # Create mock Redis
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            b'parent_workflow_id': b'parent-wf',
            b'parent_task_id': b'parent-task',
            b'parent_shard': b'5'  # Different shard
        })
        mock_redis.hset = AsyncMock()
        mock_redis.xadd = AsyncMock()
        
        # Create worker config
        config = WorkerConfig(
            worker_type="workflow_monitor",
            worker_id="test-monitor-worker",
            consumer_group="test-group"
        )
        
        # Create worker
        worker = WorkflowMonitorWorker(config)
        worker.redis = mock_redis
        worker.shard = 0  # Different from parent shard (5)
        
        # Test data
        data = {
            b'workflow_id': b'child-workflow-456',
            b'result': b'{"output": "success"}',
            b'status': b'completed',
            b'timestamp': datetime.utcnow().isoformat().encode()
        }
        
        # Process completion
        await worker.process_message("{shard:0}:workflow:completed", "msg-1", data)
        
        # Should send notification to parent shard
        xadd_calls = mock_redis.xadd.call_args_list
        assert len(xadd_calls) > 0
        
        # Find the notification call
        notification_sent = False
        for call in xadd_calls:
            if 'shard:5' in call[0][0] and 'workflow:child:completed' in call[0][0]:
                notification_sent = True
                break
        
        assert notification_sent, "Should send notification to parent shard"


class TestIntegration:
    """Integration tests for workflow handler system"""
    
    @pytest.mark.asyncio
    async def test_full_workflow_cycle(self):
        """Test complete parent-child workflow execution cycle"""
        # This would require a full Redis setup
        # For now, we'll mock the key components
        
        handler = WorkflowHandler()
        
        # 1. Parent task requests child workflow
        parent_task = Task(
            id="parent-task",
            name="Parent Task",
            workflow_id="parent-wf",
            method="workflow/execute",
            params={
                "workflow_ref": "child.yaml",
                "inputs": {"data": "test"},
                "shard_preference": "any"
            }
        )
        
        result = await handler.execute(parent_task)
        
        assert result.status == TaskStatus.WAITING
        child_id = result.metadata['child_workflow_id']
        
        # 2. Verify child workflow ID format
        assert child_id.startswith("parent-wf:child:")
        
        # 3. Verify metadata contains all necessary info
        assert result.metadata['parent_workflow_id'] == "parent-wf"
        assert result.metadata['parent_task_id'] == "parent-task"
        assert result.metadata['workflow_ref'] == "child.yaml"
        assert result.metadata['workflow_inputs'] == {"data": "test"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])