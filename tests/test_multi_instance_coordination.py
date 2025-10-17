"""
Tests for Multi-Instance Coordination System

Tests instance identity, leader election, shard assignment, and reconciliation.
"""

import pytest
import pytest_asyncio
import asyncio
import redis.asyncio as aioredis
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from gleitzeit.core.instance import InstanceIdentity, initialize_instance, get_current_instance, _current_instance
from gleitzeit.core.leader_election import LeaderElection, LeaderStatus
from gleitzeit.core.reconciliation_sharding import ReconciliationShardAssignment


class TestInstanceIdentity:
    """Test instance identity initialization and management"""

    def setup_method(self):
        """Reset global instance before each test"""
        global _current_instance
        import gleitzeit.core.instance
        gleitzeit.core.instance._current_instance = None

    def test_initialize_instance(self):
        """Test instance initialization creates unique ID"""
        instance = initialize_instance(instance_name="test-instance")

        assert instance is not None
        # Instance ID format is {prefix}-{uuid[:8]}, e.g. "test-ins-abc12345"
        assert instance.instance_id.startswith("test-ins-")
        assert len(instance.instance_id) == 17  # "test-ins-" (9 chars) + 8 char uuid
        assert instance.role == "standalone"

    def test_get_current_instance_after_init(self):
        """Test get_current_instance returns initialized instance"""
        instance = initialize_instance(instance_name="test-instance")
        retrieved = get_current_instance()

        assert retrieved is instance
        assert retrieved.instance_id == instance.instance_id

    def test_get_current_instance_before_init(self):
        """Test get_current_instance returns None before initialization"""
        assert get_current_instance() is None

    def test_instance_identity_fields(self):
        """Test instance identity has required fields"""
        instance = initialize_instance(instance_name="test-instance", role="worker")

        assert hasattr(instance, 'instance_id')
        assert hasattr(instance, 'instance_name')
        assert hasattr(instance, 'machine_id')
        assert hasattr(instance, 'role')
        assert hasattr(instance, 'started_at')
        assert instance.role == "worker"

    def test_multiple_initialize_overwrites_instance(self):
        """Test multiple initializations overwrite the global instance"""
        instance1 = initialize_instance(instance_name="test-instance")
        instance2 = initialize_instance(instance_name="test-instance-2")

        # Second initialization overwrites the global - they have different IDs
        assert instance1.instance_id != instance2.instance_id
        # get_current_instance should return the most recent one
        assert get_current_instance() is instance2


class TestLeaderElection:
    """Test leader election mechanism"""

    @pytest_asyncio.fixture
    async def redis_mock(self):
        """Create a mock Redis client"""
        mock = AsyncMock(spec=aioredis.Redis)
        return mock

    @pytest.mark.asyncio
    async def test_leader_election_initialization(self, redis_mock):
        """Test LeaderElection initializes correctly"""
        election = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:leader",
            worker_id="test-worker-1",
            ttl=10
        )

        assert election.leader_key == "test:leader"
        assert election.worker_id == "test-worker-1"
        assert election.ttl == 10
        assert election.is_leader is False

    @pytest.mark.asyncio
    async def test_try_elect_becomes_leader(self, redis_mock):
        """Test try_elect returns BECAME_LEADER when acquiring lock"""
        # Mock successful lock acquisition (eval returns 1 for success)
        async def mock_eval(script, num_keys, *args):
            return 1
        redis_mock.eval = mock_eval

        election = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:leader",
            worker_id="test-worker-1",
            ttl=10
        )

        status = await election.try_elect()

        assert status == LeaderStatus.BECAME_LEADER
        assert election.is_leader is True

    @pytest.mark.asyncio
    async def test_try_elect_not_leader(self, redis_mock):
        """Test try_elect returns NOT_LEADER when lock held by another"""
        # Mock failed lock acquisition (eval returns 0 for failure)
        async def mock_eval(script, num_keys, *args):
            return 0
        redis_mock.eval = mock_eval

        election = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:leader",
            worker_id="test-worker-1",
            ttl=10
        )

        status = await election.try_elect()

        assert status == LeaderStatus.NOT_LEADER
        assert election.is_leader is False

    @pytest.mark.asyncio
    async def test_try_elect_maintains_leadership(self, redis_mock):
        """Test try_elect returns STILL_LEADER when refreshing lock"""
        # Mock successful lock acquisition and refresh (eval always returns 1)
        async def mock_eval(script, num_keys, *args):
            return 1
        redis_mock.eval = mock_eval

        election = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:leader",
            worker_id="test-worker-1",
            ttl=10
        )

        # First call - become leader
        status1 = await election.try_elect()
        assert status1 == LeaderStatus.BECAME_LEADER

        # Second call - maintain leadership
        status2 = await election.try_elect()
        assert status2 == LeaderStatus.STILL_LEADER
        assert election.is_leader is True

    @pytest.mark.asyncio
    async def test_release_leadership(self, redis_mock):
        """Test release removes leader key"""
        # Track whether release was called
        released = [False]

        async def mock_eval(script, num_keys, *args):
            # Check if this is the release script (has 2 args: key and worker_id)
            if len(args) == 2:
                released[0] = True
                return 1  # Successfully released
            # Otherwise it's election (has 3 args: key, worker_id, ttl)
            return 1  # Successfully elected

        redis_mock.eval = mock_eval

        election = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:leader",
            worker_id="test-worker-1",
            ttl=10
        )

        await election.try_elect()
        assert election.is_leader is True

        await election.release()
        assert released[0] is True
        assert election.is_leader is False


class TestReconciliationShardAssignment:
    """Test reconciliation worker shard assignment"""

    def setup_method(self):
        """Reset global instance before each test"""
        global _current_instance
        import gleitzeit.core.instance
        gleitzeit.core.instance._current_instance = None

    @pytest_asyncio.fixture
    async def redis_mock(self):
        """Create a mock Redis client"""
        mock = AsyncMock(spec=aioredis.Redis)
        return mock

    @pytest.mark.asyncio
    async def test_shard_assignment_with_instance_identity(self, redis_mock):
        """Test shard assignment when instance identity is initialized"""
        # Initialize instance identity
        instance = initialize_instance(instance_name="test-instance-1")

        # Mock Redis operations
        async def mock_setex(key, ttl, value):
            return True

        async def mock_keys(pattern):
            # Only this instance registered - use actual instance ID
            return [f"global:reconciliation:shard_assignment:{instance.instance_id}".encode()]

        redis_mock.setex = mock_setex
        redis_mock.keys = mock_keys

        assignment = ReconciliationShardAssignment(
            redis=redis_mock,
            total_shards=16,
            heartbeat_interval=30
        )

        # Should get all shards (only instance)
        shards = await assignment.get_assigned_shards()

        assert len(shards) == 16
        assert shards == list(range(16))

    @pytest.mark.asyncio
    async def test_shard_assignment_without_instance_identity(self, redis_mock):
        """Test shard assignment generates fallback ID when no instance identity"""
        # Don't initialize instance identity

        # Track what keys are queried
        registered_keys = []

        async def mock_setex(key, ttl, value):
            registered_keys.append(key)
            return True

        async def mock_keys(pattern):
            # Return the keys that were registered
            return [k.encode() if isinstance(k, str) else k for k in registered_keys]

        redis_mock.setex = mock_setex
        redis_mock.keys = mock_keys

        assignment = ReconciliationShardAssignment(
            redis=redis_mock,
            total_shards=16,
            heartbeat_interval=30
        )

        # Should have generated an instance ID
        assert assignment.instance_id.startswith("reconciliation-")

        # Should get all shards (only instance)
        shards = await assignment.get_assigned_shards()
        assert len(shards) == 16

    @pytest.mark.asyncio
    async def test_shard_distribution_two_instances(self, redis_mock):
        """Test shard distribution across two instances"""
        # Initialize instance identity
        instance = initialize_instance(instance_name="instance-1")

        # Mock Redis operations
        async def mock_setex(key, ttl, value):
            return True

        async def mock_keys(pattern):
            # Two instances registered
            # The second instance ID must sort AFTER the first one alphabetically
            # Instance IDs have format "{prefix}-{uuid8}", so use "worker-" prefix which sorts after "instance-"
            return [
                f"global:reconciliation:shard_assignment:{instance.instance_id}".encode(),
                b"global:reconciliation:shard_assignment:worker-999"
            ]

        redis_mock.setex = mock_setex
        redis_mock.keys = mock_keys

        assignment = ReconciliationShardAssignment(
            redis=redis_mock,
            total_shards=16,
            heartbeat_interval=30
        )

        shards = await assignment.get_assigned_shards()

        # Should get 8 shards (16 / 2)
        assert len(shards) == 8
        # First instance gets first half (shards 0-7)
        assert shards == list(range(8))

    @pytest.mark.asyncio
    async def test_shard_distribution_three_instances(self, redis_mock):
        """Test shard distribution across three instances"""
        # Initialize instance identity
        instance = initialize_instance(instance_name="instance-1")

        # Mock Redis operations
        async def mock_setex(key, ttl, value):
            return True

        async def mock_keys(pattern):
            # Three instances registered (sorted order matters!)
            return [
                b"global:reconciliation:shard_assignment:instance-0",
                f"global:reconciliation:shard_assignment:{instance.instance_id}".encode(),
                b"global:reconciliation:shard_assignment:instance-2"
            ]

        redis_mock.setex = mock_setex
        redis_mock.keys = mock_keys

        assignment = ReconciliationShardAssignment(
            redis=redis_mock,
            total_shards=16,
            heartbeat_interval=30
        )

        shards = await assignment.get_assigned_shards()

        # 16 shards / 3 instances = 5 shards each, with 1 remainder
        # Instance at index 1 should get shards 5-9 (5 shards)
        assert len(shards) == 5

    @pytest.mark.asyncio
    async def test_register_instance(self, redis_mock):
        """Test instance registration creates heartbeat key"""
        # Initialize instance identity
        instance = initialize_instance(instance_name="test-instance")

        registered_key = None
        registered_ttl = None

        async def mock_setex(key, ttl, value):
            nonlocal registered_key, registered_ttl
            registered_key = key
            registered_ttl = ttl
            return True

        async def mock_keys(pattern):
            return [f"global:reconciliation:shard_assignment:{instance.instance_id}".encode()]

        redis_mock.setex = mock_setex
        redis_mock.keys = mock_keys

        assignment = ReconciliationShardAssignment(
            redis=redis_mock,
            total_shards=16,
            heartbeat_interval=30
        )

        await assignment.get_assigned_shards()

        # Verify registration
        assert registered_key == f"global:reconciliation:shard_assignment:{instance.instance_id}"
        assert registered_ttl == 60  # 2x heartbeat interval


class TestInstanceIdentityPropagation:
    """Test instance identity propagation to worker processes"""

    def test_instance_id_in_environment(self):
        """Test GLEITZEIT_INSTANCE_ID can be set in environment"""
        import os

        # Simulate environment variable being set by parent process
        test_instance_id = "gleitzei-test123"
        os.environ['GLEITZEIT_INSTANCE_ID'] = test_instance_id

        # Verify it can be retrieved
        retrieved_id = os.environ.get('GLEITZEIT_INSTANCE_ID')
        assert retrieved_id == test_instance_id

        # Cleanup
        del os.environ['GLEITZEIT_INSTANCE_ID']

    def test_worker_initialization_from_env(self):
        """Test worker can initialize instance identity from environment"""
        import os
        import gleitzeit.core.instance

        # Reset global instance
        gleitzeit.core.instance._current_instance = None

        # Simulate environment variable
        # Use short name that won't be truncated (instance name prefix is limited to 8 chars)
        test_instance_id = "worker1"
        os.environ['GLEITZEIT_INSTANCE_ID'] = test_instance_id

        # Simulate worker initialization logic
        instance_id = os.environ.get('GLEITZEIT_INSTANCE_ID')
        if instance_id and not get_current_instance():
            initialize_instance(instance_name=instance_id)

        # Verify instance was initialized
        instance = get_current_instance()
        assert instance is not None
        # Instance ID will be "worker1-{uuid}" format
        assert instance.instance_id.startswith("worker1-")

        # Cleanup
        del os.environ['GLEITZEIT_INSTANCE_ID']
        gleitzeit.core.instance._current_instance = None


class TestMultiInstanceIntegration:
    """Integration tests for multi-instance coordination"""

    @pytest_asyncio.fixture
    async def redis_mock(self):
        """Create a mock Redis client with state"""
        mock = AsyncMock(spec=aioredis.Redis)

        # Simulate Redis state for leader election
        redis_state = {}

        async def mock_eval(script, num_keys, *args):
            """Mock eval for leader election and release scripts"""
            # Election script has 3 args: key, worker_id, ttl
            if len(args) == 3:
                key = args[0]
                worker_id = args[1]
                # If key doesn't exist or is owned by this worker, grant leadership
                if key not in redis_state or redis_state[key] == worker_id:
                    redis_state[key] = worker_id
                    return 1  # Success
                else:
                    return 0  # Another worker is leader
            # Release script has 2 args: key, worker_id
            elif len(args) == 2:
                key = args[0]
                worker_id = args[1]
                if key in redis_state and redis_state[key] == worker_id:
                    del redis_state[key]
                    return 1  # Successfully released
                return 0  # Not the leader
            return 0

        mock.eval = mock_eval

        return mock

    @pytest.mark.asyncio
    async def test_leader_election_prevents_multiple_leaders(self, redis_mock):
        """Test that only one instance can be leader at a time"""
        # Create two leader election instances
        election1 = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:timer:leader",
            worker_id="worker-1",
            ttl=10
        )

        election2 = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:timer:leader",
            worker_id="worker-2",
            ttl=10
        )

        # Both try to become leader
        status1 = await election1.try_elect()
        status2 = await election2.try_elect()

        # Only one should become leader
        assert (status1 == LeaderStatus.BECAME_LEADER) != (status2 == LeaderStatus.BECAME_LEADER)
        assert election1.is_leader != election2.is_leader

    @pytest.mark.asyncio
    async def test_leader_failover(self, redis_mock):
        """Test leader failover when current leader releases"""
        election1 = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:signal:leader",
            worker_id="worker-1",
            ttl=10
        )

        election2 = LeaderElection(
            redis_client=redis_mock,
            leader_key="test:signal:leader",
            worker_id="worker-2",
            ttl=10
        )

        # Instance 1 becomes leader
        status1 = await election1.try_elect()
        assert status1 == LeaderStatus.BECAME_LEADER

        # Instance 2 tries and fails
        status2 = await election2.try_elect()
        assert status2 == LeaderStatus.NOT_LEADER

        # Instance 1 releases leadership
        await election1.release()

        # Instance 2 can now become leader
        status2_retry = await election2.try_elect()
        assert status2_retry == LeaderStatus.BECAME_LEADER
        assert election2.is_leader is True
