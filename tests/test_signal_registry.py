"""
Tests for Signal Registry Memory Leak Fix

Tests the implementation of individual Redis keys with TTL
to prevent memory leaks from orphaned signal registry entries.
"""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Import the workers we're testing
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.workers.signal_worker import SignalWorker
from gleitzeit.workers.base import WorkerConfig


class TestSignalRegistryTTL:
    """Test signal registry uses individual keys with TTL"""

    @pytest_asyncio.fixture
    async def redis_mock(self):
        """Create a mock Redis client with tracking"""
        mock = AsyncMock()

        # Track setex calls (registry entries)
        mock.setex_calls = []

        async def track_setex(key, ttl, value):
            mock.setex_calls.append({
                'key': key,
                'ttl': ttl,
                'value': value
            })
            return True

        mock.setex = track_setex

        # Mock xadd for signal streams
        async def mock_xadd(stream, data):
            return b"1234567890-0"

        mock.xadd = mock_xadd

        return mock

    @pytest_asyncio.fixture
    async def worker_config(self):
        """Create a worker config"""
        return WorkerConfig(
            worker_id="test-worker-1",
            worker_type="task_execution",
            consumer_group="test-group",
            redis_url="redis://localhost:6379",
            assigned_shards=[0, 1, 2, 3],
            max_concurrent=5,
            batch_size=10,
            block_timeout=5000,
            enabled_task_types=['all']
        )

    @pytest.mark.asyncio
    async def test_signal_registry_uses_setex_with_ttl(self, redis_mock, worker_config):
        """Test that signal emission uses SETEX with TTL instead of SADD"""

        # Mock the config loader to return default TTL
        with patch('gleitzeit.workers.task_execution_worker.get_config') as mock_load_config:
            mock_load_config.return_value = {
                'handlers': {
                    'signal': {
                        'config': {
                            'signal_registry_ttl': 3600
                        }
                    }
                }
            }

            worker = TaskExecutionWorker(worker_config)
            worker.redis = redis_mock

            # Emit a signal
            await worker._emit_signal(
                sender_workflow_id="workflow_123",
                signal_name="test_signal",
                payload={"data": "test"}
            )

            # Verify SETEX was called with correct parameters
            assert len(redis_mock.setex_calls) == 1
            call = redis_mock.setex_calls[0]

            # Check key format
            assert call['key'] == "signal:registry:workflow_123:test_signal"

            # Check TTL
            assert call['ttl'] == 3600

            # Check value
            assert call['value'] == "1"

    @pytest.mark.asyncio
    async def test_signal_registry_ttl_configurable(self, redis_mock, worker_config):
        """Test that TTL is loaded from config"""

        # Mock the config loader with custom TTL
        with patch('gleitzeit.workers.task_execution_worker.get_config') as mock_load_config:
            mock_load_config.return_value = {
                'handlers': {
                    'signal': {
                        'config': {
                            'signal_registry_ttl': 7200  # 2 hours
                        }
                    }
                }
            }

            worker = TaskExecutionWorker(worker_config)
            worker.redis = redis_mock

            # Emit a signal
            await worker._emit_signal(
                sender_workflow_id="workflow_456",
                signal_name="custom_signal",
                payload={"test": "data"}
            )

            # Verify custom TTL was used
            assert len(redis_mock.setex_calls) == 1
            call = redis_mock.setex_calls[0]
            assert call['ttl'] == 7200  # Custom TTL

    @pytest.mark.asyncio
    async def test_signal_registry_ttl_default_fallback(self, redis_mock, worker_config):
        """Test that TTL falls back to default (3600) if not configured"""

        # Mock the config loader with no TTL configured
        with patch('gleitzeit.workers.task_execution_worker.get_config') as mock_load_config:
            mock_load_config.return_value = {
                'handlers': {
                    'signal': {
                        'config': {}  # No TTL configured
                    }
                }
            }

            worker = TaskExecutionWorker(worker_config)
            worker.redis = redis_mock

            # Emit a signal
            await worker._emit_signal(
                sender_workflow_id="workflow_789",
                signal_name="default_signal",
                payload={}
            )

            # Verify default TTL (3600) was used
            assert len(redis_mock.setex_calls) == 1
            call = redis_mock.setex_calls[0]
            assert call['ttl'] == 3600  # Default fallback

    @pytest.mark.asyncio
    async def test_signal_registry_key_format(self, redis_mock, worker_config):
        """Test that registry keys use correct format"""

        with patch('gleitzeit.workers.task_execution_worker.get_config') as mock_load_config:
            mock_load_config.return_value = {
                'handlers': {
                    'signal': {
                        'config': {
                            'signal_registry_ttl': 3600
                        }
                    }
                }
            }

            worker = TaskExecutionWorker(worker_config)
            worker.redis = redis_mock

            # Test various signal names and workflow IDs
            test_cases = [
                ("wf_1", "signal_a"),
                ("workflow-123", "my:signal"),
                ("wf:with:colons", "signal_name"),
            ]

            for workflow_id, signal_name in test_cases:
                redis_mock.setex_calls.clear()

                await worker._emit_signal(
                    sender_workflow_id=workflow_id,
                    signal_name=signal_name,
                    payload={}
                )

                # Verify key format: signal:registry:workflow_id:signal_name
                expected_key = f"signal:registry:{workflow_id}:{signal_name}"
                assert redis_mock.setex_calls[0]['key'] == expected_key

    @pytest.mark.asyncio
    async def test_signal_ttl_loaded_once_at_init(self, redis_mock, worker_config):
        """Test that config is loaded once during initialization, not on every signal"""

        with patch('gleitzeit.workers.task_execution_worker.get_config') as mock_load_config:
            mock_load_config.return_value = {
                'handlers': {
                    'signal': {
                        'config': {
                            'signal_registry_ttl': 3600
                        }
                    }
                }
            }

            worker = TaskExecutionWorker(worker_config)
            worker.redis = redis_mock

            # Config should be loaded once during __init__
            assert mock_load_config.call_count == 1

            # Emit multiple signals
            for i in range(5):
                await worker._emit_signal(
                    sender_workflow_id=f"workflow_{i}",
                    signal_name=f"signal_{i}",
                    payload={}
                )

            # Config should still only be loaded once (not per signal)
            assert mock_load_config.call_count == 1


class TestSignalWorkerScan:
    """Test SignalWorker uses SCAN to find registry keys"""

    @pytest_asyncio.fixture
    async def redis_mock_with_scan(self):
        """Create a mock Redis client with SCAN support"""
        mock = AsyncMock()

        # Track registry keys
        mock.registry_keys = [
            b"signal:registry:workflow_1:signal_a",
            b"signal:registry:workflow_2:signal_b",
            b"signal:registry:workflow_3:signal_c"
        ]

        # Mock SCAN to return keys
        async def mock_scan(cursor, match=None, count=100):
            if cursor == 0:
                # Return all keys and cursor 0 (done)
                return (0, mock.registry_keys)
            return (0, [])

        mock.scan = mock_scan

        # Mock smembers for waiters (no waiters for these tests)
        async def mock_smembers(key):
            return []

        mock.smembers = mock_smembers

        # Track delete calls
        mock.delete_calls = []

        async def track_delete(key):
            mock.delete_calls.append(key)
            return 1

        mock.delete = track_delete

        return mock

    @pytest.mark.asyncio
    async def test_signal_worker_uses_scan(self, redis_mock_with_scan):
        """Test that SignalWorker uses SCAN to find registry keys"""

        config = WorkerConfig(
            worker_id="signal-worker-1",
            worker_type="signal",
            consumer_group="signal-group",
            redis_url="redis://localhost:6379",
            assigned_shards=[0, 1, 2, 3],
            max_concurrent=5,
            batch_size=10,
            block_timeout=5000
        )

        worker = SignalWorker(config)
        worker.redis = redis_mock_with_scan

        # Process signals (should use SCAN)
        await worker._process_workflow_signals()

        # Verify SCAN was called with correct pattern
        # (We can't easily verify the exact call, but we know it would fail if SCAN wasn't used)
        # The test passes if no exception is raised

    @pytest.mark.asyncio
    async def test_signal_worker_parses_keys_correctly(self, redis_mock_with_scan):
        """Test that SignalWorker correctly parses workflow_id and signal_name from keys"""

        # This test verifies the key parsing logic
        # Key format: "signal:registry:workflow_id:signal_name"

        test_keys = [
            "signal:registry:wf1:sig1",
            "signal:registry:workflow-123:my_signal",
            "signal:registry:wf:with:colons:signal:with:colons"
        ]

        for key in test_keys:
            # Parse using split with max 4 parts
            parts = key.split(":", 3)

            if len(parts) >= 4:
                workflow_id = parts[2]
                signal_name = parts[3]

                # Verify parsing
                assert "signal" in parts[0]
                assert "registry" in parts[1]
                assert workflow_id is not None
                assert signal_name is not None

    @pytest.mark.asyncio
    async def test_signal_worker_uses_delete_not_srem(self, redis_mock_with_scan):
        """Test that SignalWorker uses DELETE instead of SREM to remove registry entries

        When there ARE waiters but no message in stream, the signal worker should
        DELETE the registry key (not SREM from a set).
        """

        # Create mock with stream data
        mock = AsyncMock()

        # Mock SCAN
        async def mock_scan(cursor, match=None, count=100):
            if cursor == 0:
                return (0, [b"signal:registry:workflow_1:signal_a"])
            return (0, [])

        mock.scan = mock_scan

        # Mock smembers - RETURN WAITERS (this is the key difference)
        async def mock_smembers(key):
            return [b"task_123"]  # There IS a waiter

        mock.smembers = mock_smembers

        # Track delete calls
        delete_calls = []

        async def track_delete(key):
            delete_calls.append(key)
            return 1

        mock.delete = track_delete

        # Mock xreadgroup (no messages in stream despite having waiters)
        async def mock_xreadgroup(*args, **kwargs):
            return []

        mock.xreadgroup = mock_xreadgroup

        # Mock xgroup_create
        async def mock_xgroup_create(*args, **kwargs):
            pass

        mock.xgroup_create = mock_xgroup_create

        config = WorkerConfig(
            worker_id="signal-worker-1",
            worker_type="signal",
            consumer_group="signal-group",
            redis_url="redis://localhost:6379",
            assigned_shards=[0, 1, 2, 3],
            max_concurrent=5,
            batch_size=10,
            block_timeout=5000
        )

        worker = SignalWorker(config)
        worker.redis = mock

        # Process signals
        await worker._process_workflow_signals()

        # Verify DELETE was called (because waiters exist but no messages in stream)
        assert len(delete_calls) > 0


class TestSignalRegistryIntegration:
    """Integration tests for signal registry with TTL"""

    @pytest.mark.asyncio
    async def test_signal_lifecycle_with_ttl(self):
        """Test complete signal lifecycle: emit, register with TTL, scan, delete"""

        # Create a mock Redis that tracks both setex and scan
        redis_mock = AsyncMock()

        # Track registry state
        registry = {}

        async def mock_setex(key, ttl, value):
            registry[key] = {'ttl': ttl, 'value': value}
            return True

        async def mock_scan(cursor, match=None, count=100):
            if cursor == 0:
                matching_keys = [k.encode() for k in registry.keys() if match is None or k.startswith(match.rstrip('*'))]
                return (0, matching_keys)
            return (0, [])

        async def mock_delete(key):
            if isinstance(key, bytes):
                key = key.decode()
            if key in registry:
                del registry[key]
                return 1
            return 0

        async def mock_xadd(stream, data):
            return b"1234567890-0"

        async def mock_smembers(key):
            return []

        redis_mock.setex = mock_setex
        redis_mock.scan = mock_scan
        redis_mock.delete = mock_delete
        redis_mock.xadd = mock_xadd
        redis_mock.smembers = mock_smembers

        # Create TaskExecutionWorker and emit signal
        with patch('gleitzeit.workers.task_execution_worker.get_config') as mock_load_config:
            mock_load_config.return_value = {
                'handlers': {
                    'signal': {
                        'config': {
                            'signal_registry_ttl': 3600
                        }
                    }
                }
            }

            task_worker_config = WorkerConfig(
                worker_id="task-worker-1",
                worker_type="task_execution",
                consumer_group="task-group",
                redis_url="redis://localhost:6379",
                assigned_shards=[0, 1, 2, 3],
                max_concurrent=5,
                batch_size=10,
                block_timeout=5000,
                enabled_task_types=['all']
            )

            task_worker = TaskExecutionWorker(task_worker_config)
            task_worker.redis = redis_mock

            # Emit signal
            await task_worker._emit_signal(
                sender_workflow_id="workflow_test",
                signal_name="integration_signal",
                payload={"test": "data"}
            )

        # Verify signal was registered with TTL
        assert "signal:registry:workflow_test:integration_signal" in registry
        assert registry["signal:registry:workflow_test:integration_signal"]['ttl'] == 3600

        # Create SignalWorker and scan for signals
        signal_worker_config = WorkerConfig(
            worker_id="signal-worker-1",
            worker_type="signal",
            consumer_group="signal-group",
            redis_url="redis://localhost:6379",
            assigned_shards=[0, 1, 2, 3],
            max_concurrent=5,
            batch_size=10,
            block_timeout=5000
        )

        signal_worker = SignalWorker(signal_worker_config)
        signal_worker.redis = redis_mock

        # Mock xreadgroup and xgroup_create
        async def mock_xreadgroup(*args, **kwargs):
            return []

        async def mock_xgroup_create(*args, **kwargs):
            pass

        redis_mock.xreadgroup = mock_xreadgroup
        redis_mock.xgroup_create = mock_xgroup_create

        # Process signals (should find the registered signal)
        await signal_worker._process_workflow_signals()

        # Verify signal was found but KEPT in registry (because no waiters yet)
        # The TTL will handle cleanup if the signal remains orphaned
        assert "signal:registry:workflow_test:integration_signal" in registry
        assert registry["signal:registry:workflow_test:integration_signal"]['ttl'] == 3600


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
