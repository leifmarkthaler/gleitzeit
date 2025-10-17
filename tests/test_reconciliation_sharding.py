"""
Tests for reconciliation worker sharding (Phase 2 horizontal scaling).

Tests cover:
- Shard assignment algorithm
- Dynamic rebalancing
- Instance registration and heartbeat
- Shard ownership locks
- Multi-instance coordination
"""

import pytest
import pytest_asyncio
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import redis.asyncio as aioredis

from gleitzeit.core.reconciliation_sharding import ReconciliationShardAssignment
from gleitzeit.core.instance import InstanceIdentity


@pytest_asyncio.fixture
async def redis_mock():
    """Create a mock Redis client"""
    mock = AsyncMock(spec=aioredis.Redis)
    return mock


@pytest.fixture
def mock_instance():
    """Mock current instance"""
    instance = MagicMock(spec=InstanceIdentity)
    instance.instance_id = 'test-instance-1'
    instance.machine_id = 'test-machine'
    with patch('gleitzeit.core.reconciliation_sharding.get_current_instance', return_value=instance):
        yield instance


class TestShardAssignment:
    """Test shard assignment algorithm"""

    @pytest.mark.asyncio
    async def test_single_instance_gets_all_shards(self, redis_mock, mock_instance):
        """Test that single instance gets all 16 shards"""
        # Mock single instance
        redis_mock.keys.return_value = [b'global:reconciliation:shard_assignment:test-instance-1']

        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=16)
        shards = await assignment.get_assigned_shards()

        assert len(shards) == 16
        assert shards == list(range(16))

    @pytest.mark.asyncio
    async def test_two_instances_split_evenly(self, redis_mock, mock_instance):
        """Test that two instances split shards evenly"""
        # Mock two instances
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:test-instance-1',
            b'global:reconciliation:shard_assignment:test-instance-2'
        ]

        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=16)
        shards = await assignment.get_assigned_shards()

        # First instance (sorted order) should get shards 0-7
        assert len(shards) == 8
        assert shards == list(range(8))

    @pytest.mark.asyncio
    async def test_four_instances_split_evenly(self, redis_mock, mock_instance):
        """Test that four instances split shards evenly"""
        # Mock four instances
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:test-instance-1',
            b'global:reconciliation:shard_assignment:test-instance-2',
            b'global:reconciliation:shard_assignment:test-instance-3',
            b'global:reconciliation:shard_assignment:test-instance-4'
        ]

        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=16)
        shards = await assignment.get_assigned_shards()

        # Each instance should get 4 shards
        assert len(shards) == 4

    @pytest.mark.asyncio
    async def test_uneven_distribution_with_remainder(self, redis_mock, mock_instance):
        """Test shard distribution when total doesn't divide evenly"""
        # 3 instances, 16 shards = 5,5,6 distribution
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:test-instance-1',
            b'global:reconciliation:shard_assignment:test-instance-2',
            b'global:reconciliation:shard_assignment:test-instance-3'
        ]

        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=16)
        shards = await assignment.get_assigned_shards()

        # First instance should get 6 shards (5 base + 1 remainder)
        # Actual allocation depends on sorted order - test that it's reasonable
        assert 5 <= len(shards) <= 6

    @pytest.mark.asyncio
    async def test_consistent_ordering_across_calls(self, redis_mock, mock_instance):
        """Test that shard assignment is consistent across multiple calls"""
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:test-instance-1',
            b'global:reconciliation:shard_assignment:test-instance-2'
        ]

        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=16)

        # Get shards multiple times
        shards1 = await assignment.get_assigned_shards()
        shards2 = await assignment.get_assigned_shards()
        shards3 = await assignment.get_assigned_shards()

        # Should be identical
        assert shards1 == shards2 == shards3


class TestInstanceRegistration:
    """Test instance registration and heartbeat"""

    @pytest.mark.asyncio
    async def test_register_instance(self, redis_mock, mock_instance):
        """Test registering instance in Redis"""
        assignment = ReconciliationShardAssignment(redis=redis_mock, heartbeat_interval=30)
        await assignment._register_instance()

        # Verify setex was called with correct parameters
        redis_mock.setex.assert_called_once()
        call_args = redis_mock.setex.call_args
        assert 'test-instance-1' in call_args[0][0]
        assert call_args[0][1] == 60  # 30s interval * 2

    @pytest.mark.asyncio
    async def test_get_active_instances(self, redis_mock, mock_instance):
        """Test retrieving active instances"""
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:instance-1',
            b'global:reconciliation:shard_assignment:instance-2',
            b'global:reconciliation:shard_assignment:instance-3'
        ]

        assignment = ReconciliationShardAssignment(redis=redis_mock)
        instances = await assignment._get_active_instances()

        assert len(instances) == 3
        assert 'instance-1' in instances
        assert 'instance-2' in instances
        assert 'instance-3' in instances

    @pytest.mark.asyncio
    async def test_heartbeat_registers_periodically(self, redis_mock, mock_instance):
        """Test that heartbeat registers instance periodically"""
        assignment = ReconciliationShardAssignment(redis=redis_mock, heartbeat_interval=0.1)

        # Start heartbeat
        task = asyncio.create_task(assignment.start_heartbeat())

        # Wait for a few heartbeats
        await asyncio.sleep(0.35)

        # Stop heartbeat
        await assignment.stop_heartbeat()
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have registered multiple times
        assert redis_mock.setex.call_count >= 2

    @pytest.mark.asyncio
    async def test_stop_heartbeat_unregisters(self, redis_mock, mock_instance):
        """Test that stopping heartbeat unregisters instance"""
        assignment = ReconciliationShardAssignment(redis=redis_mock)
        assignment.running = True  # Simulate running state

        await assignment.stop_heartbeat()

        # Verify delete was called
        redis_mock.delete.assert_called_once()
        call_args = redis_mock.delete.call_args
        assert 'test-instance-1' in call_args[0][0]


class TestRebalancing:
    """Test shard rebalancing when instances change"""

    @pytest.mark.asyncio
    async def test_detect_rebalance_on_instance_add(self, redis_mock, mock_instance):
        """Test rebalancing detection when instance is added"""
        assignment = ReconciliationShardAssignment(redis=redis_mock)
        assignment._last_known_instances = {'instance-1'}

        # Simulate new instance added
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:instance-1',
            b'global:reconciliation:shard_assignment:instance-2'  # New!
        ]

        needs_rebalance = await assignment.detect_rebalance()

        assert needs_rebalance is True
        assert len(assignment._last_known_instances) == 2

    @pytest.mark.asyncio
    async def test_detect_rebalance_on_instance_remove(self, redis_mock, mock_instance):
        """Test rebalancing detection when instance is removed"""
        assignment = ReconciliationShardAssignment(redis=redis_mock)
        assignment._last_known_instances = {'instance-1', 'instance-2'}

        # Simulate instance removed
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:instance-1'
        ]

        needs_rebalance = await assignment.detect_rebalance()

        assert needs_rebalance is True
        assert len(assignment._last_known_instances) == 1

    @pytest.mark.asyncio
    async def test_no_rebalance_when_stable(self, redis_mock, mock_instance):
        """Test no rebalancing when instances unchanged"""
        assignment = ReconciliationShardAssignment(redis=redis_mock)
        assignment._last_known_instances = {'instance-1', 'instance-2'}

        # Simulate same instances
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:instance-1',
            b'global:reconciliation:shard_assignment:instance-2'
        ]

        needs_rebalance = await assignment.detect_rebalance()

        assert needs_rebalance is False

    @pytest.mark.asyncio
    async def test_shard_reassignment_on_instance_add(self, redis_mock, mock_instance):
        """Test that shards are reassigned when instance is added"""
        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=16)

        # Start with 1 instance - gets all 16 shards
        redis_mock.keys.return_value = [b'global:reconciliation:shard_assignment:test-instance-1']
        shards_before = await assignment.get_assigned_shards()
        assert len(shards_before) == 16

        # Add second instance - should get 8 shards
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:test-instance-1',
            b'global:reconciliation:shard_assignment:test-instance-2'
        ]
        shards_after = await assignment.get_assigned_shards()
        assert len(shards_after) == 8

        # Verify assignment changed
        assert shards_before != shards_after


class TestShardLocking:
    """Test shard ownership locks"""

    @pytest.mark.asyncio
    async def test_acquire_shard_lock_success(self, redis_mock, mock_instance):
        """Test successfully acquiring shard lock"""
        redis_mock.set.return_value = True  # Lock acquired

        assignment = ReconciliationShardAssignment(redis=redis_mock)
        acquired = await assignment.acquire_shard_lock(shard=5, ttl=90)

        assert acquired is True
        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        assert 'reconciliation:shard:5:lock' in call_args[0][0]

    @pytest.mark.asyncio
    async def test_acquire_shard_lock_failure(self, redis_mock, mock_instance):
        """Test failing to acquire shard lock (another instance owns it)"""
        redis_mock.set.return_value = False  # Lock not acquired

        assignment = ReconciliationShardAssignment(redis=redis_mock)
        acquired = await assignment.acquire_shard_lock(shard=5, ttl=90)

        assert acquired is False

    @pytest.mark.asyncio
    async def test_release_shard_lock_when_owner(self, redis_mock, mock_instance):
        """Test releasing shard lock when we own it"""
        redis_mock.get.return_value = b'test-instance-1'  # We own it

        assignment = ReconciliationShardAssignment(redis=redis_mock)
        released = await assignment.release_shard_lock(shard=5)

        assert released is True
        redis_mock.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_release_when_not_owner(self, redis_mock, mock_instance):
        """Test not releasing lock when another instance owns it"""
        redis_mock.get.return_value = b'other-instance'  # Different owner

        assignment = ReconciliationShardAssignment(redis=redis_mock)
        released = await assignment.release_shard_lock(shard=5)

        assert released is False
        redis_mock.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_lock_ttl_parameter(self, redis_mock, mock_instance):
        """Test that lock TTL is set correctly"""
        redis_mock.set.return_value = True

        assignment = ReconciliationShardAssignment(redis=redis_mock)
        await assignment.acquire_shard_lock(shard=3, ttl=120)

        call_args = redis_mock.set.call_args
        assert call_args[1]['ex'] == 120  # TTL in seconds


class TestStats:
    """Test shard assignment statistics"""

    @pytest.mark.asyncio
    async def test_get_stats(self, redis_mock, mock_instance):
        """Test retrieving shard assignment statistics"""
        redis_mock.keys.return_value = [
            b'global:reconciliation:shard_assignment:test-instance-1',
            b'global:reconciliation:shard_assignment:test-instance-2'
        ]

        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=16, heartbeat_interval=30)
        await assignment.get_assigned_shards()  # Populate assigned_shards

        stats = assignment.get_stats()

        assert stats['instance_id'] == 'test-instance-1'
        assert stats['num_assigned_shards'] == 8  # 16 shards / 2 instances
        assert stats['total_shards'] == 16
        assert stats['num_instances'] == 2
        assert stats['heartbeat_interval'] == 30
        assert len(stats['assigned_shards']) == 8


class TestEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_no_instances_registered(self, redis_mock, mock_instance):
        """Test behavior when no instances are registered"""
        redis_mock.keys.return_value = []

        assignment = ReconciliationShardAssignment(redis=redis_mock)

        # Should still work, defaulting to self
        shards = await assignment.get_assigned_shards()
        assert len(shards) > 0  # Should get some shards

    @pytest.mark.asyncio
    async def test_instance_without_identity_raises_error(self, redis_mock):
        """Test that initialization fails without instance identity"""
        with patch('gleitzeit.core.reconciliation_sharding.get_current_instance', return_value=None):
            with pytest.raises(RuntimeError, match="Instance identity not initialized"):
                ReconciliationShardAssignment(redis=redis_mock)

    @pytest.mark.asyncio
    async def test_custom_shard_count(self, redis_mock, mock_instance):
        """Test with non-default shard count"""
        redis_mock.keys.return_value = [b'global:reconciliation:shard_assignment:test-instance-1']

        # Use 32 shards instead of 16
        assignment = ReconciliationShardAssignment(redis=redis_mock, total_shards=32)
        shards = await assignment.get_assigned_shards()

        assert len(shards) == 32
        assert shards == list(range(32))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
