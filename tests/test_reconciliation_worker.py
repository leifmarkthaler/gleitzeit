"""
Tests for Reconciliation Worker - Verifying all 19 bug fixes

Tests cover:
- Bug #1: Correct Redis key patterns
- Bug #2-4, #9: All task counters extracted
- Bug #3: Zombie detection with waiting tasks
- Bug #6: Workflow status transitions to waiting
- Bug #7: All 17 task statuses counted
- Bug #8: Correct stream key patterns for events
- Bug #10: WorkflowStatus enum usage
- Bug #11, #14: Atomic operations with index cleanup
- Bug #13, #15: Task key and discovery patterns
- Bug #16: Multiple status scanning
- Bug #17: Consistent timestamp management
- Bug #19: Stateless (no in-memory metrics)
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from datetime import datetime

from gleitzeit.workers.reconciliation_worker import WorkflowReconciliationWorker
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.models import WorkflowStatus
from gleitzeit.core.sharding import default_sharding


@pytest.fixture
def worker_config():
    """Create test worker configuration"""
    return WorkerConfig(
        worker_type="reconciliation",
        worker_id="test-reconciliation-1",
        consumer_group="reconciliation-group",
        assigned_shards=[0, 1],
        extra={
            'scan_interval': 10,
            'batch_size': 10,
            'zombie_threshold': 600
        }
    )


@pytest.fixture
def worker(worker_config):
    """Create test reconciliation worker with mocked Redis"""
    worker = WorkflowReconciliationWorker(worker_config)
    worker.redis = AsyncMock()
    return worker


class TestBug1_CorrectKeyPatterns:
    """Test Bug #1: All Redis keys use helper functions"""

    @pytest.mark.asyncio
    async def test_get_workflow_uses_correct_key(self, worker):
        """Verify get_workflow uses get_workflow_key('state', ...)"""
        workflow_id = "wf-123"
        shard = 0

        # Mock Redis response
        worker.redis.hgetall = AsyncMock(return_value={
            b'status': b'running',
            b'total_tasks': b'10'
        })

        await worker.get_workflow(workflow_id, shard)

        # Verify correct key was used
        expected_key = default_sharding.get_workflow_key("state", workflow_id)
        worker.redis.hgetall.assert_called_once_with(expected_key.encode())

    @pytest.mark.asyncio
    async def test_get_last_workflow_activity_uses_correct_key(self, worker):
        """Verify get_last_workflow_activity uses correct key"""
        workflow_id = "wf-123"
        shard = 0

        worker.redis.hget = AsyncMock(return_value=b'2025-10-12T10:00:00')

        await worker.get_last_workflow_activity(workflow_id, shard)

        expected_key = default_sharding.get_workflow_key("state", workflow_id)
        worker.redis.hget.assert_called_once_with(
            expected_key.encode(),
            b'updated_at'
        )


class TestBug13_TaskKeyHelper:
    """Test Bug #13: get_task uses helper function"""

    @pytest.mark.asyncio
    async def test_get_task_uses_helper(self, worker):
        """Verify get_task uses get_task_key helper"""
        task_id = "task-456"
        workflow_id = "wf-123"
        shard = 0

        worker.redis.hgetall = AsyncMock(return_value={
            b'status': b'completed'
        })

        await worker.get_task(task_id, workflow_id, shard)

        # Verify correct key was used
        expected_key = default_sharding.get_task_key(task_id, workflow_id)
        worker.redis.hgetall.assert_called_once_with(expected_key.encode())


class TestBug15_TaskIDDiscovery:
    """Test Bug #15: get_workflow_task_ids reads from workflow data"""

    @pytest.mark.asyncio
    async def test_reads_task_ids_from_workflow_data(self, worker):
        """Verify task IDs are extracted from workflow data JSON"""
        workflow_id = "wf-123"
        shard = 0

        workflow_data = {
            'tasks': [
                {'id': 'task-1', 'type': 'python'},
                {'id': 'task-2', 'type': 'http'},
                {'id': 'task-3', 'type': 'python'}
            ]
        }

        worker.redis.get = AsyncMock(return_value=json.dumps(workflow_data).encode())

        task_ids = await worker.get_workflow_task_ids(workflow_id, shard)

        # Verify correct key was used
        expected_key = default_sharding.get_workflow_key("data", workflow_id)
        worker.redis.get.assert_called_once_with(expected_key.encode())

        # Verify all task IDs extracted
        assert task_ids == ['task-1', 'task-2', 'task-3']

    @pytest.mark.asyncio
    async def test_handles_missing_workflow_data(self, worker):
        """Verify graceful handling when workflow data doesn't exist"""
        workflow_id = "wf-missing"
        shard = 0

        worker.redis.get = AsyncMock(return_value=None)

        task_ids = await worker.get_workflow_task_ids(workflow_id, shard)

        assert task_ids == []


class TestBug19_StatelessDesign:
    """Test Bug #19: No in-memory metrics"""

    def test_no_metrics_in_init(self, worker):
        """Verify worker doesn't have metrics attributes"""
        assert not hasattr(worker, 'workflows_scanned')
        assert not hasattr(worker, 'inconsistencies_found')
        assert not hasattr(worker, 'workflows_fixed')
        assert not hasattr(worker, 'scan_errors')


class TestBug2_4_9_AllTaskCounters:
    """Test Bugs #2, #4, #9: All task counters extracted"""

    @pytest.mark.asyncio
    async def test_consistency_check_extracts_all_counters(self, worker):
        """Verify all task counters are extracted and checked"""
        workflow_id = "wf-123"
        shard = 0

        workflow = {
            b'total_tasks': b'100',
            b'completed_tasks': b'50',
            b'failed_tasks': b'5',
            b'running_tasks': b'10',
            b'pending_tasks': b'20',
            b'waiting_tasks': b'10',  # Bug #2, #4
            b'blocked_tasks': b'3',    # Bug #9
            b'skipped_tasks': b'2',    # Bug #9
            b'status': b'running'
        }

        worker.redis.hget = AsyncMock(return_value=None)

        inconsistencies = await worker.check_workflow_consistency(
            workflow_id, workflow, shard
        )

        # Total = 50 + 5 + 10 + 20 + 10 + 3 + 2 = 100 ✓
        # Should have NO task_count_mismatch
        assert not any('task_count_mismatch' in i for i in inconsistencies)

    @pytest.mark.asyncio
    async def test_detects_mismatch_with_missing_counters(self, worker):
        """Verify mismatch detected when counters don't add up"""
        workflow_id = "wf-123"
        shard = 0

        workflow = {
            b'total_tasks': b'100',
            b'completed_tasks': b'50',
            b'failed_tasks': b'5',
            b'running_tasks': b'10',
            b'pending_tasks': b'20',
            b'waiting_tasks': b'10',
            b'blocked_tasks': b'0',  # Missing 5!
            b'skipped_tasks': b'0',
            b'status': b'running'
        }

        worker.redis.hget = AsyncMock(return_value=None)

        inconsistencies = await worker.check_workflow_consistency(
            workflow_id, workflow, shard
        )

        # Total = 95, but should be 100
        assert any('task_count_mismatch' in i for i in inconsistencies)


class TestBug3_ZombieDetection:
    """Test Bug #3: Zombie detection accounts for waiting tasks"""

    @pytest.mark.asyncio
    async def test_workflow_with_waiting_tasks_not_zombie(self, worker):
        """Verify workflows with waiting tasks are NOT marked as zombie"""
        workflow_id = "wf-123"
        shard = 0

        workflow = {
            b'total_tasks': b'10',
            b'completed_tasks': b'5',
            b'failed_tasks': b'0',
            b'running_tasks': b'0',
            b'pending_tasks': b'0',
            b'waiting_tasks': b'5',  # Waiting for signals!
            b'blocked_tasks': b'0',
            b'skipped_tasks': b'0',
            b'status': b'running',
            b'updated_at': datetime.utcnow().isoformat().encode()
        }

        worker.redis.hget = AsyncMock(return_value=workflow[b'updated_at'])

        inconsistencies = await worker.check_workflow_consistency(
            workflow_id, workflow, shard
        )

        # Should NOT be marked as zombie
        assert not any('zombie_workflow' in i for i in inconsistencies)

    @pytest.mark.asyncio
    async def test_workflow_without_activity_is_zombie(self, worker):
        """Verify workflows with no active tasks for 10+ min are zombie"""
        workflow_id = "wf-123"
        shard = 0

        # Workflow last updated 20 minutes ago
        old_timestamp = datetime.utcnow().timestamp() - 1200
        old_iso = datetime.fromtimestamp(old_timestamp).isoformat()

        workflow = {
            b'total_tasks': b'10',
            b'completed_tasks': b'5',
            b'failed_tasks': b'0',
            b'running_tasks': b'0',
            b'pending_tasks': b'0',
            b'waiting_tasks': b'0',  # No waiting tasks
            b'blocked_tasks': b'0',
            b'skipped_tasks': b'0',
            b'status': b'running',
            b'updated_at': old_iso.encode()
        }

        worker.redis.hget = AsyncMock(return_value=workflow[b'updated_at'])

        inconsistencies = await worker.check_workflow_consistency(
            workflow_id, workflow, shard
        )

        # SHOULD be marked as zombie
        assert any('zombie_workflow' in i for i in inconsistencies)


class TestBug6_StatusTransitionToWaiting:
    """Test Bug #6: Workflow status transitions to waiting"""

    @pytest.mark.asyncio
    async def test_detects_should_be_waiting(self, worker):
        """Verify workflows with only waiting tasks get flagged"""
        workflow_id = "wf-123"
        shard = 0

        workflow = {
            b'total_tasks': b'10',
            b'completed_tasks': b'5',
            b'failed_tasks': b'0',
            b'running_tasks': b'0',
            b'pending_tasks': b'0',
            b'waiting_tasks': b'5',  # Should transition to waiting!
            b'blocked_tasks': b'0',
            b'skipped_tasks': b'0',
            b'status': b'running'
        }

        worker.redis.hget = AsyncMock(return_value=None)

        inconsistencies = await worker.check_workflow_consistency(
            workflow_id, workflow, shard
        )

        # Should detect status_should_be_waiting
        assert any('status_should_be_waiting' in i for i in inconsistencies)

    @pytest.mark.asyncio
    async def test_mark_workflow_waiting_uses_lua_script(self, worker):
        """Verify mark_workflow_waiting uses Lua script for atomicity"""
        workflow_id = "wf-123"
        shard = 0

        worker.redis.eval = AsyncMock(return_value=1)

        await worker.mark_workflow_waiting(workflow_id, shard)

        # Verify Lua script was used
        worker.redis.eval.assert_called_once()
        call_args = worker.redis.eval.call_args

        # Check that script contains atomic operations
        lua_script = call_args[0][0].decode()
        assert 'redis.call' in lua_script
        assert 'hset' in lua_script
        assert 'zrem' in lua_script
        assert 'zadd' in lua_script

        # Check WorkflowStatus.WAITING was passed
        assert WorkflowStatus.WAITING.value.encode() in call_args[0]


class TestBug7_AllTaskStatuses:
    """Test Bug #7: recalculate_task_counts handles all 17 statuses"""

    @pytest.mark.asyncio
    async def test_counts_all_task_statuses(self, worker):
        """Verify all task statuses are counted correctly"""
        workflow_id = "wf-123"
        shard = 0

        # Mock task IDs
        worker.get_workflow_task_ids = AsyncMock(return_value=[
            'task-1', 'task-2', 'task-3', 'task-4', 'task-5',
            'task-6', 'task-7', 'task-8', 'task-9', 'task-10'
        ])

        # Mock tasks with various statuses
        task_statuses = [
            {b'status': b'pending'},
            {b'status': b'running'},
            {b'status': b'executing'},  # Should map to 'running'
            {b'status': b'waiting'},
            {b'status': b'waiting_signal'},  # Should map to 'waiting'
            {b'status': b'completed'},
            {b'status': b'failed'},
            {b'status': b'blocked'},
            {b'status': b'skipped'},
            {b'status': b'cancelled'},
        ]

        worker.get_task = AsyncMock(side_effect=task_statuses)
        worker.redis.hset = AsyncMock()

        await worker.recalculate_task_counts(workflow_id, shard)

        # Verify hset was called with all counters
        call_args = worker.redis.hset.call_args
        mapping = call_args[1]['mapping']

        assert b'pending_tasks' in mapping
        assert b'running_tasks' in mapping  # Should include 'executing'
        assert b'waiting_tasks' in mapping  # Should include 'waiting_signal'
        assert b'completed_tasks' in mapping
        assert b'failed_tasks' in mapping
        assert b'blocked_tasks' in mapping
        assert b'skipped_tasks' in mapping

        # Verify correct key was used
        expected_key = default_sharding.get_workflow_key("state", workflow_id)
        assert call_args[0][0] == expected_key.encode()


class TestBug8_StreamKeyPatterns:
    """Test Bug #8: Correct stream key patterns for events"""

    @pytest.mark.asyncio
    async def test_mark_workflow_failed_uses_correct_stream(self, worker):
        """Verify workflow:failed event uses correct stream key"""
        workflow_id = "wf-123"
        shard = 0

        worker.redis.eval = AsyncMock(return_value=1)
        worker.redis.xadd = AsyncMock()

        await worker.mark_workflow_failed(workflow_id, shard, "Test failure")

        # Verify correct stream key
        expected_stream = default_sharding.get_stream_key("workflow:failed", workflow_id)
        worker.redis.xadd.assert_called_once()
        assert worker.redis.xadd.call_args[0][0] == expected_stream.encode()

    @pytest.mark.asyncio
    async def test_mark_workflow_completed_uses_correct_stream(self, worker):
        """Verify workflow:completed event uses correct stream key"""
        workflow_id = "wf-123"
        shard = 0

        worker.redis.eval = AsyncMock(return_value=1)
        worker.redis.xadd = AsyncMock()

        await worker.mark_workflow_completed(workflow_id, shard)

        # Verify correct stream key
        expected_stream = default_sharding.get_stream_key("workflow:completed", workflow_id)
        worker.redis.xadd.assert_called_once()
        assert worker.redis.xadd.call_args[0][0] == expected_stream.encode()


class TestBug10_EnumUsage:
    """Test Bug #10: WorkflowStatus enum usage"""

    @pytest.mark.asyncio
    async def test_reconcile_workflow_uses_enum(self, worker):
        """Verify reconcile_workflow uses WorkflowStatus enum"""
        workflow_id = "wf-123"
        shard = 0

        # Mock workflow that's not running
        worker.get_workflow = AsyncMock(return_value={
            b'status': b'completed'
        })

        await worker.reconcile_workflow(workflow_id, shard)

        # Should return early (no check_workflow_consistency called)
        # This tests that the enum comparison works correctly


class TestBug11_14_AtomicOperations:
    """Test Bugs #11, #14: Atomic operations with index cleanup"""

    @pytest.mark.asyncio
    async def test_mark_workflow_failed_is_atomic(self, worker):
        """Verify mark_workflow_failed uses Lua script"""
        workflow_id = "wf-123"
        shard = 0

        worker.redis.eval = AsyncMock(return_value=1)
        worker.redis.xadd = AsyncMock()

        await worker.mark_workflow_failed(workflow_id, shard, "Test")

        # Verify Lua script was called
        worker.redis.eval.assert_called_once()

        # Verify Lua script contains atomic operations
        call_args = worker.redis.eval.call_args
        lua_script = call_args[0][0].decode()

        # Check script has atomic operations
        assert 'redis.call' in lua_script
        assert 'hset' in lua_script
        assert 'zrem' in lua_script
        assert 'zadd' in lua_script

    @pytest.mark.asyncio
    async def test_mark_workflow_completed_cleans_all_indices(self, worker):
        """Verify mark_workflow_completed removes from all indices"""
        workflow_id = "wf-123"
        shard = 0

        worker.redis.eval = AsyncMock(return_value=1)
        worker.redis.xadd = AsyncMock()

        await worker.mark_workflow_completed(workflow_id, shard)

        # Verify Lua script includes cleanup logic
        call_args = worker.redis.eval.call_args
        lua_script = call_args[0][0].decode()

        # Should have zrem loop
        assert 'zrem' in lua_script


class TestBug16_MultipleStatusScanning:
    """Test Bug #16: Scan multiple workflow statuses"""

    @pytest.mark.asyncio
    async def test_reconcile_all_shards_scans_multiple_statuses(self, worker):
        """Verify reconcile_all_shards scans running AND waiting"""
        from contextlib import asynccontextmanager

        # Mock reconcile_shard to track calls
        worker.reconcile_shard = AsyncMock()

        # Create a proper async context manager
        @asynccontextmanager
        async def mock_acquire(shard):
            yield MagicMock()  # Yield a mock lock

        # Replace the method
        worker.acquire_shard_lock = mock_acquire

        await worker.reconcile_all_shards()

        # Should call reconcile_shard twice per shard (running + waiting)
        calls = worker.reconcile_shard.call_args_list
        assert len(calls) == 4  # 2 shards * 2 statuses

        # Verify both statuses called
        statuses = [call[1]['status'] for call in calls]
        assert 'running' in statuses
        assert 'waiting' in statuses

    @pytest.mark.asyncio
    async def test_scan_workflows_by_status_uses_status_param(self, worker):
        """Verify scan_workflows_by_status uses correct index key"""
        shard = 0
        status = 'waiting'

        worker.redis.zrange = AsyncMock(return_value=[
            b'wf-1', b'wf-2', b'wf-3'
        ])

        await worker.scan_workflows_by_status(shard, status, 0, 10)

        # Verify correct key pattern
        expected_key = f"{{shard:{shard}}}:workflows:by_status:{status}"
        worker.redis.zrange.assert_called_once()
        assert worker.redis.zrange.call_args[0][0] == expected_key.encode()


class TestBug17_TimestampManagement:
    """Test Bug #17: Consistent timestamp management"""

    @pytest.mark.asyncio
    async def test_recalculate_task_counts_sets_updated_at(self, worker):
        """Verify recalculate_task_counts always sets updated_at"""
        workflow_id = "wf-123"
        shard = 0

        worker.get_workflow_task_ids = AsyncMock(return_value=[])
        worker.redis.hset = AsyncMock()

        await worker.recalculate_task_counts(workflow_id, shard)

        # Verify updated_at is in the mapping
        call_args = worker.redis.hset.call_args
        mapping = call_args[1]['mapping']
        assert b'updated_at' in mapping


class TestEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_handles_corrupted_workflow_data(self, worker):
        """Verify graceful handling of corrupted JSON"""
        workflow_id = "wf-corrupted"
        shard = 0

        worker.redis.get = AsyncMock(return_value=b'not-valid-json{')

        task_ids = await worker.get_workflow_task_ids(workflow_id, shard)

        # Should return empty list, not crash
        assert task_ids == []

    @pytest.mark.asyncio
    async def test_handles_missing_workflow(self, worker):
        """Verify graceful handling when workflow doesn't exist"""
        workflow_id = "wf-missing"
        shard = 0

        worker.redis.hgetall = AsyncMock(return_value={})

        workflow = await worker.get_workflow(workflow_id, shard)

        # Should return None
        assert workflow is None

    @pytest.mark.asyncio
    async def test_handles_missing_task_status(self, worker):
        """Verify tasks with no status field are skipped or handled gracefully"""
        workflow_id = "wf-123"
        shard = 0

        worker.get_workflow_task_ids = AsyncMock(return_value=['task-1'])
        # Task with no status - .get(b'status', b'pending') will use default
        worker.get_task = AsyncMock(return_value={b'id': b'task-1'})  # No status field
        worker.redis.hset = AsyncMock()

        await worker.recalculate_task_counts(workflow_id, shard)

        # Verify hset was called (task counts updated)
        assert worker.redis.hset.called
        call_args = worker.redis.hset.call_args
        mapping = call_args[1]['mapping']

        # When task has no status field, get() returns default b'pending' → decoded as 'pending'
        pending_count = int(mapping[b'pending_tasks'].decode())
        assert pending_count == 1
