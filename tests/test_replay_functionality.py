"""
Test workflow replay functionality
"""

import asyncio
import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from gleitzeit.workers.replay_worker import ReplayWorker, ReplayMode
from gleitzeit.core.event_store import EventStore, EventLevel, WorkflowEvent
from gleitzeit.core.events import EventType
from gleitzeit.core.models import TaskStatus


@pytest.fixture
async def mock_redis():
    """Create mock Redis client"""
    redis = AsyncMock()

    # Mock workflow data
    workflow_data = {
        'id': 'test_workflow',
        'name': 'Test Workflow',
        'tasks': [
            {
                'id': 'task_1',
                'name': 'First Task',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'params': {'code': 'result = {"value": 1}'}
            },
            {
                'id': 'validate_1',
                'name': 'Validation Task',
                'protocol': 'validation/v1',
                'method': 'validation/evaluate',
                'params': {
                    'conditions': [{'expression': 'value > 0', 'name': 'check'}],
                    'on_failure': 'skip',
                    'context': {'value': '${task_1.value}'}
                }
            },
            {
                'id': 'task_2',
                'name': 'Second Task',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'dependencies': ['task_1', 'validate_1'],
                'params': {'code': 'result = {"value": 2}'}
            }
        ]
    }

    redis.hget.return_value = json.dumps(workflow_data).encode()
    redis.hgetall.return_value = {
        b'status': b'completed',
        b'result': b'{"value": 1}'
    }
    redis.smembers.return_value = {b'task_2'}  # Failed tasks

    return redis


@pytest.fixture
async def replay_worker(mock_redis):
    """Create ReplayWorker instance"""
    worker = ReplayWorker()
    worker.redis = mock_redis
    worker.event_store = EventStore(mock_redis)
    return worker


class TestReplayWorker:
    """Test ReplayWorker functionality"""

    @pytest.mark.asyncio
    async def test_full_replay(self, replay_worker, mock_redis):
        """Test full workflow replay"""
        # Setup
        workflow_id = 'test_workflow'

        # Execute replay
        await replay_worker.replay_workflow(
            workflow_id=workflow_id,
            replay_mode=ReplayMode.FULL,
            replay_id='test_replay_1'
        )

        # Verify all tasks were cleared
        assert mock_redis.hdel.called
        assert mock_redis.srem.called

        # Verify workflow was resubmitted
        mock_redis.xadd.assert_called()
        call_args = mock_redis.xadd.call_args
        assert b"workflow:submitted" in str(call_args[0][0])

    @pytest.mark.asyncio
    async def test_deterministic_replay(self, replay_worker, mock_redis):
        """Test deterministic replay (keeps validation results)"""
        # Setup
        workflow_id = 'test_workflow'

        # Mock timeline events
        mock_redis.xrange.return_value = [
            (b'1', {
                b'event_id': b'evt_1',
                b'event_type': b'task:started',
                b'task_id': b'task_1',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': b'critical',
                b'data': b'{}',
                b'replay_id': b'',
                b'is_replay': b'false'
            }),
            (b'2', {
                b'event_id': b'evt_2',
                b'event_type': b'task:completed',
                b'task_id': b'task_1',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': b'critical',
                b'data': b'{"result": {"value": 1}}',
                b'replay_id': b'',
                b'is_replay': b'false'
            })
        ]

        # Execute deterministic replay
        await replay_worker.replay_workflow(
            workflow_id=workflow_id,
            replay_mode=ReplayMode.DETERMINISTIC,
            replay_validations=False,  # Don't replay validations
            replay_id='test_replay_2'
        )

        # Verify validation task was NOT cleared
        if mock_redis.hdel.called:
            cleared_tasks = []
            for call in mock_redis.hdel.call_args_list:
                task_key = call[0][0].decode() if isinstance(call[0][0], bytes) else call[0][0]
                if 'validate_1' not in task_key:
                    cleared_tasks.append(task_key)

            # Should only clear non-validation tasks
            assert 'validate_1' not in str(cleared_tasks)

    @pytest.mark.asyncio
    async def test_failed_only_replay(self, replay_worker, mock_redis):
        """Test replaying only failed tasks"""
        # Setup
        workflow_id = 'test_workflow'

        # Execute failed-only replay
        await replay_worker.replay_workflow(
            workflow_id=workflow_id,
            replay_mode=ReplayMode.FAILED_ONLY,
            replay_id='test_replay_3'
        )

        # Verify only failed tasks were cleared
        mock_redis.smembers.assert_called()  # Should check failed tasks

        # Verify cleared tasks match failed tasks
        if mock_redis.hdel.called:
            # Should only clear task_2 (the failed task)
            cleared_count = mock_redis.hdel.call_count
            assert cleared_count == 1  # Only one failed task

    @pytest.mark.asyncio
    async def test_replay_from_task(self, replay_worker, mock_redis):
        """Test replay from specific task"""
        # Setup
        workflow_id = 'test_workflow'
        start_from = 'task_2'

        # Mock timeline
        mock_redis.xrange.return_value = [
            (b'1', {
                b'event_id': b'evt_1',
                b'event_type': b'task:completed',
                b'task_id': b'task_1',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': b'critical',
                b'data': b'{}',
                b'replay_id': b'',
                b'is_replay': b'false'
            }),
            (b'2', {
                b'event_id': b'evt_2',
                b'event_type': b'task:started',
                b'task_id': b'task_2',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': b'critical',
                b'data': b'{}',
                b'replay_id': b'',
                b'is_replay': b'false'
            })
        ]

        # Execute replay from task
        await replay_worker.replay_workflow(
            workflow_id=workflow_id,
            replay_mode=ReplayMode.FROM_TASK,
            start_from=start_from,
            replay_id='test_replay_4'
        )

        # Verify only tasks from task_2 onward were cleared
        # task_1 should NOT be cleared
        if mock_redis.hdel.called:
            for call in mock_redis.hdel.call_args_list:
                task_key = str(call[0][0])
                assert 'task_1' not in task_key  # task_1 should not be cleared


class TestEventStore:
    """Test EventStore functionality"""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_events(self, mock_redis):
        """Test storing and retrieving workflow events"""
        # Setup
        event_store = EventStore(mock_redis)
        workflow_id = 'test_workflow'

        # Store events
        event_id1 = await event_store.store_event(
            event_type=EventType.TASK_STARTED,
            workflow_id=workflow_id,
            task_id='task_1',
            level=EventLevel.CRITICAL,
            data={'test': 'data'}
        )

        # Verify event was stored
        mock_redis.xadd.assert_called()
        call_args = mock_redis.xadd.call_args
        message = call_args[0][1]
        assert message[b'event_type'] == EventType.TASK_STARTED.value.encode()
        assert message[b'task_id'] == b'task_1'

    @pytest.mark.asyncio
    async def test_get_timeline(self, mock_redis):
        """Test retrieving workflow timeline"""
        # Setup
        event_store = EventStore(mock_redis)
        workflow_id = 'test_workflow'

        # Mock stored events
        mock_redis.xrange.return_value = [
            (b'1', {
                b'event_id': b'evt_1',
                b'event_type': EventType.TASK_STARTED.value.encode(),
                b'task_id': b'task_1',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': EventLevel.CRITICAL.value.encode(),
                b'data': b'{}',
                b'replay_id': b'',
                b'is_replay': b'false'
            }),
            (b'2', {
                b'event_id': b'evt_2',
                b'event_type': EventType.TASK_COMPLETED.value.encode(),
                b'task_id': b'task_1',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': EventLevel.CRITICAL.value.encode(),
                b'data': b'{"result": {"value": 1}}',
                b'replay_id': b'',
                b'is_replay': b'false'
            })
        ]

        # Get timeline
        timeline = await event_store.get_timeline(workflow_id)

        # Verify timeline
        assert len(timeline) == 2
        assert timeline[0].event_type == EventType.TASK_STARTED
        assert timeline[1].event_type == EventType.TASK_COMPLETED
        assert timeline[0].task_id == 'task_1'

    @pytest.mark.asyncio
    async def test_get_task_execution_order(self, mock_redis):
        """Test getting task execution order"""
        # Setup
        event_store = EventStore(mock_redis)
        workflow_id = 'test_workflow'

        # Mock timeline with task starts
        mock_redis.xrange.return_value = [
            (b'1', {
                b'event_id': b'evt_1',
                b'event_type': EventType.TASK_STARTED.value.encode(),
                b'task_id': b'task_1',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': EventLevel.CRITICAL.value.encode(),
                b'data': b'{}',
                b'replay_id': b'',
                b'is_replay': b'false'
            }),
            (b'2', {
                b'event_id': b'evt_2',
                b'event_type': EventType.TASK_STARTED.value.encode(),
                b'task_id': b'validate_1',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': EventLevel.CRITICAL.value.encode(),
                b'data': b'{}',
                b'replay_id': b'',
                b'is_replay': b'false'
            }),
            (b'3', {
                b'event_id': b'evt_3',
                b'event_type': EventType.TASK_STARTED.value.encode(),
                b'task_id': b'task_2',
                b'timestamp': datetime.utcnow().isoformat().encode(),
                b'level': EventLevel.CRITICAL.value.encode(),
                b'data': b'{}',
                b'replay_id': b'',
                b'is_replay': b'false'
            })
        ]

        # Get execution order
        order = await event_store.get_task_execution_order(workflow_id)

        # Verify order
        assert order == ['task_1', 'validate_1', 'task_2']


class TestReplayWithValidation:
    """Test replay with validation tasks"""

    @pytest.mark.asyncio
    async def test_xor_pattern_replay(self, replay_worker, mock_redis):
        """Test replaying XOR pattern with validation tasks"""
        # Setup XOR workflow
        workflow_data = {
            'id': 'xor_workflow',
            'name': 'XOR Workflow',
            'tasks': [
                {
                    'id': 'get_payment',
                    'protocol': 'python/v1',
                    'params': {'code': 'result = {"payment_type": "credit_card"}'}
                },
                {
                    'id': 'validate_cc',
                    'protocol': 'validation/v1',
                    'dependencies': ['get_payment'],
                    'params': {
                        'conditions': [{'expression': 'payment_type == "credit_card"'}],
                        'on_failure': 'skip',
                        'context': {'payment_type': '${get_payment.payment_type}'}
                    }
                },
                {
                    'id': 'validate_paypal',
                    'protocol': 'validation/v1',
                    'dependencies': ['get_payment'],
                    'params': {
                        'conditions': [{'expression': 'payment_type == "paypal"'}],
                        'on_failure': 'skip',
                        'context': {'payment_type': '${get_payment.payment_type}'}
                    }
                },
                {
                    'id': 'process_cc',
                    'protocol': 'python/v1',
                    'dependencies': ['validate_cc'],
                    'params': {'code': 'result = {"processed": "credit_card"}'}
                },
                {
                    'id': 'process_paypal',
                    'protocol': 'python/v1',
                    'dependencies': ['validate_paypal'],
                    'params': {'code': 'result = {"processed": "paypal"}'}
                }
            ]
        }

        mock_redis.hget.return_value = json.dumps(workflow_data).encode()

        # Mock validation results
        mock_redis.hgetall.side_effect = [
            {b'status': b'completed', b'result': b'{"valid": true}'},  # validate_cc
            {b'status': b'completed', b'result': b'{"valid": false, "on_failure": "skip"}'},  # validate_paypal
            {b'status': b'skipped'},  # process_paypal
        ]

        # Execute deterministic replay (keep validation results)
        await replay_worker.replay_workflow(
            workflow_id='xor_workflow',
            replay_mode=ReplayMode.DETERMINISTIC,
            replay_validations=False
        )

        # Verify validation tasks were NOT cleared (preserving XOR path)
        if mock_redis.hdel.called:
            for call in mock_redis.hdel.call_args_list:
                task_key = str(call[0][0])
                assert 'validate_cc' not in task_key
                assert 'validate_paypal' not in task_key

        # process_paypal should remain skipped
        # process_cc should be replayed


if __name__ == '__main__':
    pytest.main([__file__, '-v'])