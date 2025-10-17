"""
Tests for health check system (Phase 2 horizontal scaling).

Tests cover:
- Health check base classes
- Leader election health check
- Service registry health check
- Stream consumer health check
- Sharding configuration health check
- Health check runner
"""

import pytest
import pytest_asyncio
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import redis.asyncio as aioredis

from gleitzeit.core.health_checks import (
    HealthResult,
    HealthCheck,
    LeaderElectionHealthCheck,
    ServiceRegistryHealthCheck,
    StreamConsumerHealthCheck,
    ShardingConfigHealthCheck,
    HealthCheckRunner
)


@pytest_asyncio.fixture
async def redis_mock():
    """Create a mock Redis client"""
    mock = AsyncMock(spec=aioredis.Redis)
    return mock


@pytest.fixture
def mock_psutil():
    """Mock psutil for process checking"""
    with patch('gleitzeit.core.health_checks.psutil') as mock:
        yield mock


class TestHealthResult:
    """Test HealthResult dataclass"""

    def test_health_result_creation(self):
        """Test creating a HealthResult"""
        result = HealthResult(
            healthy=True,
            issues=[],
            metadata={'test': 'value'},
            check_name='test_check'
        )

        assert result.healthy is True
        assert result.issues == []
        assert result.metadata == {'test': 'value'}
        assert result.check_name == 'test_check'
        assert isinstance(result.timestamp, float)

    def test_health_result_unhealthy(self):
        """Test unhealthy result with issues"""
        result = HealthResult(
            healthy=False,
            issues=['Error 1', 'Error 2'],
            check_name='failing_check'
        )

        assert result.healthy is False
        assert len(result.issues) == 2
        assert 'Error 1' in result.issues

    def test_health_result_to_dict(self):
        """Test converting HealthResult to dictionary"""
        result = HealthResult(
            healthy=True,
            issues=[],
            metadata={'count': 5},
            check_name='test'
        )

        data = result.to_dict()
        assert data['healthy'] is True
        assert data['check_name'] == 'test'
        assert data['metadata']['count'] == 5
        assert 'timestamp' in data


class TestLeaderElectionHealthCheck:
    """Test leader election health check"""

    @pytest.mark.asyncio
    async def test_all_leaders_present(self, redis_mock):
        """Test when all leaders are present and registered"""
        # Configure AsyncMock to return values properly
        async def mock_get(key):
            return b'instance-1'

        async def mock_exists(key):
            return True

        redis_mock.get = mock_get
        redis_mock.exists = mock_exists

        check = LeaderElectionHealthCheck()
        result = await check.execute(redis_mock)

        assert result.healthy is True
        assert len(result.issues) == 0
        assert result.metadata['services_checked'] == ['timer', 'signal', 'loki_exporter']

    @pytest.mark.asyncio
    async def test_missing_leader(self, redis_mock):
        """Test when a leader is missing"""
        call_count = [0]

        async def mock_get(key):
            call_count[0] += 1
            if call_count[0] == 1:  # First call (timer)
                return None
            return b'instance-1'

        async def mock_exists(key):
            return True

        redis_mock.get = mock_get
        redis_mock.exists = mock_exists

        check = LeaderElectionHealthCheck()
        result = await check.execute(redis_mock)

        assert result.healthy is False
        assert any('No leader for timer' in issue for issue in result.issues)

    @pytest.mark.asyncio
    async def test_leader_not_registered(self, redis_mock):
        """Test when leader instance is not registered"""
        call_count = [0]

        async def mock_get(key):
            call_count[0] += 1
            if call_count[0] == 1:  # First call (timer)
                return b'instance-zombie'
            return b'instance-1'

        async def mock_exists(key):
            # key might be string or bytes
            key_str = key.decode() if isinstance(key, bytes) else key
            return 'zombie' not in key_str

        redis_mock.get = mock_get
        redis_mock.exists = mock_exists

        check = LeaderElectionHealthCheck()
        result = await check.execute(redis_mock)

        assert result.healthy is False
        assert any('not registered' in issue for issue in result.issues)


class TestServiceRegistryHealthCheck:
    """Test service registry health check"""

    @pytest.mark.asyncio
    async def test_all_services_healthy(self, redis_mock, mock_psutil):
        """Test when all services are healthy"""
        current_time = time.time()

        async def mock_keys(pattern):
            return [b'service:api', b'service:worker_1']

        call_count = [0]
        async def mock_hgetall(key):
            call_count[0] += 1
            return {
                b'last_heartbeat': str(current_time - 30).encode(),
                b'pid': b'12345' if call_count[0] == 1 else b'12346'
            }

        redis_mock.keys = mock_keys
        redis_mock.hgetall = mock_hgetall
        mock_psutil.pid_exists.return_value = True

        check = ServiceRegistryHealthCheck(heartbeat_threshold=90)
        result = await check.execute(redis_mock)

        assert result.healthy is True
        assert len(result.issues) == 0
        assert result.metadata['service_count'] == 2

    @pytest.mark.asyncio
    async def test_stale_heartbeat(self, redis_mock, mock_psutil):
        """Test when a service has stale heartbeat"""
        current_time = time.time()

        async def mock_keys(pattern):
            return [b'service:api']

        async def mock_hgetall(key):
            return {
                b'last_heartbeat': str(current_time - 120).encode(),  # 120s ago (stale)
                b'pid': b'12345'
            }

        redis_mock.keys = mock_keys
        redis_mock.hgetall = mock_hgetall
        mock_psutil.pid_exists.return_value = True

        check = ServiceRegistryHealthCheck(heartbeat_threshold=90)
        result = await check.execute(redis_mock)

        assert result.healthy is False
        assert any('Stale heartbeat' in issue for issue in result.issues)

    @pytest.mark.asyncio
    async def test_dead_process(self, redis_mock, mock_psutil):
        """Test when a service PID doesn't exist"""
        current_time = time.time()

        async def mock_keys(pattern):
            return [b'service:api']

        async def mock_hgetall(key):
            return {
                b'last_heartbeat': str(current_time - 30).encode(),
                b'pid': b'99999'
            }

        redis_mock.keys = mock_keys
        redis_mock.hgetall = mock_hgetall
        mock_psutil.pid_exists.return_value = False

        check = ServiceRegistryHealthCheck()
        result = await check.execute(redis_mock)

        assert result.healthy is False
        assert any('PID 99999 not found' in issue for issue in result.issues)


class TestStreamConsumerHealthCheck:
    """Test stream consumer health check"""

    @pytest.mark.asyncio
    async def test_all_consumers_healthy(self, redis_mock):
        """Test when all stream consumers are healthy"""
        async def mock_xinfo_groups(stream):
            return [{'name': b'task_execution', 'lag': 10}]

        async def mock_xpending(stream, group):
            return [0]

        redis_mock.xinfo_groups = mock_xinfo_groups
        redis_mock.xpending = mock_xpending

        check = StreamConsumerHealthCheck(num_shards=16)
        result = await check.execute(redis_mock)

        assert result.healthy is True
        assert result.metadata['warnings'] == 0

    @pytest.mark.asyncio
    async def test_high_consumer_lag_warning(self, redis_mock):
        """Test warning level consumer lag"""
        async def mock_xinfo_groups(stream):
            return [{'name': b'task_execution', 'lag': 600}]  # Warning level

        async def mock_xpending(stream, group):
            return [0]

        redis_mock.xinfo_groups = mock_xinfo_groups
        redis_mock.xpending = mock_xpending

        check = StreamConsumerHealthCheck(lag_warning=500, lag_critical=1000)
        result = await check.execute(redis_mock)

        assert result.healthy is True  # Warning doesn't make it unhealthy
        assert result.metadata['warnings'] > 0
        assert any('High lag' in issue for issue in result.issues)

    @pytest.mark.asyncio
    async def test_critical_consumer_lag(self, redis_mock):
        """Test critical level consumer lag"""
        async def mock_xinfo_groups(stream):
            return [{'name': b'task_execution', 'lag': 1500}]  # Critical level

        async def mock_xpending(stream, group):
            return [0]

        redis_mock.xinfo_groups = mock_xinfo_groups
        redis_mock.xpending = mock_xpending

        check = StreamConsumerHealthCheck(lag_warning=500, lag_critical=1000)
        result = await check.execute(redis_mock)

        assert result.healthy is False  # Critical makes it unhealthy
        assert any('CRITICAL lag' in issue for issue in result.issues)


class TestShardingConfigHealthCheck:
    """Test sharding configuration health check"""

    @pytest.mark.asyncio
    async def test_config_matches(self, redis_mock):
        """Test when stored config matches local config"""
        async def mock_get(key):
            return b'16'

        async def mock_exists(key):
            return True

        redis_mock.get = mock_get
        redis_mock.exists = mock_exists

        with patch('gleitzeit.core.sharding.default_sharding') as mock_sharding:
            mock_sharding.num_shards = 16

            check = ShardingConfigHealthCheck()
            result = await check.execute(redis_mock)

            assert result.healthy is True
            assert result.metadata['num_shards'] == '16'

    @pytest.mark.asyncio
    async def test_no_stored_config(self, redis_mock):
        """Test when no config is stored in Redis"""
        async def mock_get(key):
            return None

        redis_mock.get = mock_get

        check = ShardingConfigHealthCheck()
        result = await check.execute(redis_mock)

        assert result.healthy is False
        assert any('No sharding configuration stored' in issue for issue in result.issues)

    @pytest.mark.asyncio
    async def test_config_mismatch(self, redis_mock):
        """Test when stored config doesn't match local config"""
        async def mock_get(key):
            return b'8'

        async def mock_exists(key):
            return True

        redis_mock.get = mock_get
        redis_mock.exists = mock_exists

        with patch('gleitzeit.core.sharding.default_sharding') as mock_sharding:
            mock_sharding.num_shards = 16

            check = ShardingConfigHealthCheck()
            result = await check.execute(redis_mock)

            assert result.healthy is False
            assert any('Config mismatch' in issue for issue in result.issues)


class TestHealthCheckRunner:
    """Test health check runner"""

    @pytest.mark.asyncio
    async def test_run_once_all_healthy(self, redis_mock):
        """Test running all checks once with healthy results"""
        async def mock_setex(key, ttl, value):
            return True

        redis_mock.setex = mock_setex

        runner = HealthCheckRunner(redis=redis_mock, check_interval=30)

        # Mock all checks to return healthy
        for check in runner.checks:
            check.execute = AsyncMock(return_value=HealthResult(
                healthy=True,
                issues=[],
                check_name=check.name
            ))

        results = await runner.run_once()

        assert len(results) == 4  # 4 default checks
        assert all(result.healthy for result in results.values())

    @pytest.mark.asyncio
    async def test_run_once_with_failures(self, redis_mock):
        """Test running checks with some failures"""
        async def mock_setex(key, ttl, value):
            return True

        redis_mock.setex = mock_setex

        runner = HealthCheckRunner(redis=redis_mock)

        # Mock one check to fail
        runner.checks[0].execute = AsyncMock(return_value=HealthResult(
            healthy=False,
            issues=['Test failure'],
            check_name='failing_check'
        ))

        # Mock others to pass
        for check in runner.checks[1:]:
            check.execute = AsyncMock(return_value=HealthResult(
                healthy=True,
                issues=[],
                check_name=check.name
            ))

        results = await runner.run_once()

        assert not all(result.healthy for result in results.values())
        assert any(not result.healthy for result in results.values())

    @pytest.mark.asyncio
    async def test_store_result(self, redis_mock):
        """Test storing health check result in Redis"""
        # Track if setex was called
        setex_called = {'called': False}

        async def mock_setex(key, ttl, value):
            setex_called['called'] = True
            return True

        redis_mock.setex = mock_setex

        runner = HealthCheckRunner(redis=redis_mock, check_interval=30)
        result = HealthResult(
            healthy=True,
            issues=[],
            check_name='test_check',
            metadata={'test': 'data'}
        )

        await runner._store_result('test_check', result)

        # Verify setex was called
        assert setex_called['called'] is True

    @pytest.mark.asyncio
    async def test_run_forever_stops(self, redis_mock):
        """Test that run_forever can be stopped"""
        async def mock_setex(key, ttl, value):
            return True

        redis_mock.setex = mock_setex

        runner = HealthCheckRunner(redis=redis_mock, check_interval=0.1)

        # Mock run_once
        runner.run_once = AsyncMock()

        # Start runner in background
        task = asyncio.create_task(runner.run_forever())

        # Let it run briefly
        await asyncio.sleep(0.2)

        # Stop it
        await runner.stop()

        # Wait for task to complete
        try:
            await asyncio.wait_for(task, timeout=2)
        except asyncio.TimeoutError:
            task.cancel()

        assert not runner.running


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
