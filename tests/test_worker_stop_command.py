"""
Tests for the 'gleitzeit worker stop' command.

Tests cover:
- Stopping Docker workers
- Stopping native workers
- Graceful vs force shutdown
- Redis registry cleanup
- Worker name matching (various formats)
- Multiple worker instances
- Error handling
- Mixed Docker/native environments
"""

import pytest
import pytest_asyncio
import asyncio
import subprocess
import psutil
import redis
from unittest.mock import Mock, MagicMock, patch, call
from click.testing import CliRunner

from gleitzeit.cli.main import cli


class TestWorkerStopCommand:
    """Test suite for gleitzeit worker stop command"""

    @pytest.fixture
    def runner(self):
        """Provide Click test runner"""
        return CliRunner()

    @pytest.fixture
    def mock_redis(self):
        """Provide mock Redis client"""
        with patch('redis.Redis') as mock:
            redis_instance = MagicMock()
            mock.return_value = redis_instance

            # Default: no workers in registry
            redis_instance.scan_iter.return_value = iter([])
            redis_instance.hgetall.return_value = {}

            yield redis_instance

    @pytest.fixture
    def mock_psutil(self):
        """Provide mock psutil"""
        with patch('psutil.process_iter') as mock_iter, \
             patch('psutil.wait_procs') as mock_wait, \
             patch('psutil.Process') as mock_process:

            # Default: no processes
            mock_iter.return_value = iter([])
            mock_wait.return_value = ([], [])  # (gone, alive)

            yield {
                'process_iter': mock_iter,
                'wait_procs': mock_wait,
                'Process': mock_process
            }

    @pytest.fixture
    def mock_docker(self):
        """Provide mock subprocess for Docker commands"""
        with patch('subprocess.run') as mock:
            # Default: Docker not available
            mock.side_effect = FileNotFoundError("docker not found")
            yield mock


class TestDockerWorkerStop(TestWorkerStopCommand):
    """Tests for stopping Docker workers"""

    def test_stop_single_docker_worker(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test stopping a single Docker worker container"""
        # Mock Docker ps output
        mock_docker.side_effect = None
        mock_docker.return_value = Mock(
            returncode=0,
            stdout="gleitzeit_worker-timer-1_abc123\n"
        )

        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])

        assert result.exit_code == 0
        assert "Found 1 Docker container(s)" in result.output
        assert "gleitzeit_worker-timer-1_abc123" in result.output
        assert "Stopped 1 worker(s)" in result.output
        assert "Docker: 1" in result.output

        # Verify docker kill was called
        kill_calls = [c for c in mock_docker.call_args_list if 'kill' in str(c)]
        assert len(kill_calls) == 1

    def test_stop_multiple_docker_workers(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test stopping multiple Docker worker instances"""
        # Mock Docker ps output with 2 task_execution workers
        mock_docker.side_effect = None
        mock_docker.return_value = Mock(
            returncode=0,
            stdout="gleitzeit_worker-task_execution-1_abc123\ngleitzeit_worker-task_execution-2_abc123\n"
        )

        result = runner.invoke(cli, ['worker', 'stop', 'task_execution'])

        assert result.exit_code == 0
        assert "Found 2 Docker container(s)" in result.output
        assert "Stopped 2 worker(s)" in result.output
        assert "Docker: 2" in result.output

    def test_stop_docker_graceful_vs_force(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test graceful vs force stopping of Docker workers"""
        mock_docker.side_effect = None
        mock_docker.return_value = Mock(
            returncode=0,
            stdout="gleitzeit_worker-timer-1_abc123\n"
        )

        # Test graceful stop
        result = runner.invoke(cli, ['worker', 'stop', 'timer'])
        assert result.exit_code == 0
        stop_calls = [c for c in mock_docker.call_args_list if 'stop' in str(c)]
        assert len(stop_calls) > 0

        # Reset mock
        mock_docker.reset_mock()
        mock_docker.return_value = Mock(
            returncode=0,
            stdout="gleitzeit_worker-timer-1_abc123\n"
        )

        # Test force stop
        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])
        assert result.exit_code == 0
        kill_calls = [c for c in mock_docker.call_args_list if 'kill' in str(c)]
        assert len(kill_calls) > 0

    def test_docker_not_available(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test handling when Docker is not available"""
        mock_docker.side_effect = FileNotFoundError("docker not found")
        mock_psutil['process_iter'].return_value = iter([])

        result = runner.invoke(cli, ['worker', 'stop', 'timer'])

        # Should not crash, just report no workers found
        assert result.exit_code == 0
        assert "No workers found" in result.output


class TestNativeWorkerStop(TestWorkerStopCommand):
    """Tests for stopping native workers"""

    def test_stop_single_native_worker(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test stopping a single native worker process"""
        # Mock a running worker process
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'name': 'python',
            'cmdline': [
                'python', '-m', 'gleitzeit.workers.runner',
                '--config-key', 'worker:config:timer-async:abc123'
            ]
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])  # Successfully stopped

        # Mock Redis registry entry
        mock_redis.scan_iter.return_value = iter(['{shard:0}:worker:registry:timer-async'])
        mock_redis.hgetall.return_value = {
            'worker_id': 'timer-async',
            'worker_type': 'timer',
            'pid': '12345'
        }

        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])

        assert result.exit_code == 0
        assert "Found 1 native process(es)" in result.output
        assert "PID 12345" in result.output
        assert "Stopped 1 worker(s)" in result.output
        assert "Native: 1" in result.output

        # Verify process was killed
        mock_proc.kill.assert_called_once()

    def test_stop_native_graceful_shutdown(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test graceful shutdown waits for process to terminate"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'name': 'python',
            'cmdline': [
                'python', '-m', 'gleitzeit.workers.runner',
                '--config-key', 'worker:config:signal-async:abc123'
            ]
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])  # Gracefully stopped

        # Mock Redis
        mock_redis.scan_iter.return_value = iter(['{shard:0}:worker:registry:signal-async'])
        mock_redis.hgetall.return_value = {
            'worker_id': 'signal-async',
            'worker_type': 'signal',
            'pid': '12345'
        }

        result = runner.invoke(cli, ['worker', 'stop', 'signal', '--timeout', '5'])

        assert result.exit_code == 0
        assert "Terminating PID 12345" in result.output
        assert "Waiting up to 5s for graceful shutdown" in result.output

        # Verify graceful termination was attempted
        mock_proc.terminate.assert_called_once()
        mock_psutil['wait_procs'].assert_called_once()

    def test_stop_native_force_kill_after_timeout(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test force killing process that doesn't stop gracefully"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'name': 'python',
            'cmdline': [
                'python', '-m', 'gleitzeit.workers.runner',
                '--config-key', 'worker:config:retry-async:abc123'
            ]
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        # Process doesn't stop gracefully
        mock_psutil['wait_procs'].return_value = ([], [mock_proc])  # Still alive

        # Mock Redis
        mock_redis.scan_iter.return_value = iter(['{shard:0}:worker:registry:retry-async'])
        mock_redis.hgetall.return_value = {
            'worker_id': 'retry-async',
            'worker_type': 'retry',
            'pid': '12345'
        }

        result = runner.invoke(cli, ['worker', 'stop', 'retry'])

        assert result.exit_code == 0
        assert "1 process(es) still running, force killing" in result.output
        assert "Force killed PID 12345" in result.output

        # Verify both terminate and kill were called
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()


class TestRedisCleanup(TestWorkerStopCommand):
    """Tests for Redis registry cleanup"""

    def test_redis_cleanup_for_dead_process(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test Redis registry is cleaned when process is dead"""
        # Mock a worker process
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'name': 'python',
            'cmdline': [
                'python', '-m', 'gleitzeit.workers.runner',
                '--config-key', 'worker:config:timer-async:abc123'
            ]
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])

        # Mock Redis registry
        mock_redis.scan_iter.return_value = iter(['{shard:0}:worker:registry:timer-async'])
        mock_redis.hgetall.return_value = {
            'worker_id': 'timer-async',
            'worker_type': 'timer',
            'pid': '12345'
        }

        # Mock psutil.Process to raise NoSuchProcess (process is dead)
        with patch('psutil.Process', side_effect=psutil.NoSuchProcess(12345)):
            result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])

        assert result.exit_code == 0
        assert "Cleaned registry: timer-async" in result.output

        # Verify Redis delete was called
        mock_redis.delete.assert_called()

    def test_redis_cleanup_skips_running_process(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test Redis registry is NOT cleaned if process still running"""
        # Mock process iteration (no processes found initially)
        mock_psutil['process_iter'].return_value = iter([])

        # Mock Redis registry with a running process
        mock_redis.scan_iter.return_value = iter(['{shard:0}:worker:registry:timer-async'])
        mock_redis.hgetall.return_value = {
            'worker_id': 'timer-async',
            'worker_type': 'timer',
            'pid': '12345'
        }

        # Mock psutil.Process to return successfully (process still alive)
        mock_running_proc = MagicMock()
        with patch('psutil.Process', return_value=mock_running_proc):
            result = runner.invoke(cli, ['worker', 'stop', 'timer'])

        # Should not delete registry entry for running process
        mock_redis.delete.assert_not_called()

    def test_redis_cleanup_handles_errors_gracefully(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test Redis cleanup handles errors without crashing"""
        # Mock a worker with timer in cmdline
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'name': 'python',
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', '--config-key', 'worker:config:timer-async:abc123']
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])

        # Mock Redis.scan_iter to raise an error during cleanup
        # (This happens after process is stopped)
        mock_redis.scan_iter.side_effect = Exception("Redis connection failed")

        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])

        # Should still succeed in stopping the process, even if Redis cleanup fails
        assert result.exit_code == 0
        assert "Stopped 1 worker(s)" in result.output
        assert "Registry cleanup failed" in result.output


class TestWorkerNameMatching(TestWorkerStopCommand):
    """Tests for worker name matching patterns"""

    def test_match_with_worker_prefix(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test matching 'worker_timer' format"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', 'timer']
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])

        result = runner.invoke(cli, ['worker', 'stop', 'worker_timer', '--force'])
        assert result.exit_code == 0

    def test_match_without_worker_prefix(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test matching 'timer' format"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', 'timer']
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])

        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])
        assert result.exit_code == 0

    def test_match_case_insensitive(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test case-insensitive matching"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', 'TIMER']
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])

        result = runner.invoke(cli, ['worker', 'stop', 'TiMeR', '--force'])
        assert result.exit_code == 0

    def test_no_match_found(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test when no workers match the search"""
        mock_psutil['process_iter'].return_value = iter([])

        result = runner.invoke(cli, ['worker', 'stop', 'nonexistent'])

        assert result.exit_code == 0
        assert "No workers found matching: nonexistent" in result.output
        assert "gleitzeit worker list" in result.output


class TestMixedEnvironment(TestWorkerStopCommand):
    """Tests for mixed Docker and native environments"""

    def test_stop_both_docker_and_native(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test stopping workers in mixed environment"""
        # Mock Docker container
        mock_docker.side_effect = None
        mock_docker.return_value = Mock(
            returncode=0,
            stdout="gleitzeit_worker-timer-1_abc123\n"
        )

        # Mock native process
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', 'timer']
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])

        # Mock Redis
        mock_redis.scan_iter.return_value = iter(['{shard:0}:worker:registry:timer-async'])
        mock_redis.hgetall.return_value = {
            'worker_id': 'timer-async',
            'worker_type': 'timer',
            'pid': '12345'
        }

        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])

        assert result.exit_code == 0
        assert "Found 1 Docker container(s)" in result.output
        assert "Found 1 native process(es)" in result.output
        assert "Stopped 2 worker(s)" in result.output
        assert "Docker: 1" in result.output
        assert "Native: 1" in result.output


class TestErrorHandling(TestWorkerStopCommand):
    """Tests for error handling"""

    def test_handle_access_denied(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test handling permission errors when stopping processes"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', 'timer']
        }
        mock_proc.pid = 12345
        mock_proc.kill.side_effect = psutil.AccessDenied()

        mock_psutil['process_iter'].return_value = iter([mock_proc])

        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--force'])

        # Should not crash, just report the error
        assert result.exit_code == 0

    def test_handle_process_no_longer_exists(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test handling when process disappears during stop"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', 'timer']
        }
        mock_proc.pid = 12345
        mock_proc.terminate.side_effect = psutil.NoSuchProcess(12345)

        mock_psutil['process_iter'].return_value = iter([mock_proc])

        result = runner.invoke(cli, ['worker', 'stop', 'timer'])

        # Should handle gracefully
        assert result.exit_code == 0


class TestCommandLineInterface(TestWorkerStopCommand):
    """Tests for CLI interface and help text"""

    def test_help_text(self, runner):
        """Test worker stop help text"""
        result = runner.invoke(cli, ['worker', 'stop', '--help'])

        assert result.exit_code == 0
        assert "Stop a specific worker by name or type" in result.output
        assert "--force" in result.output
        assert "--timeout" in result.output
        assert "Examples:" in result.output

    def test_missing_worker_name(self, runner):
        """Test error when worker name not provided"""
        result = runner.invoke(cli, ['worker', 'stop'])

        assert result.exit_code != 0
        assert "Missing argument" in result.output or "WORKER_NAME" in result.output

    def test_custom_timeout(self, runner, mock_redis, mock_psutil, mock_docker):
        """Test custom timeout parameter"""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 12345,
            'cmdline': ['python', '-m', 'gleitzeit.workers.runner', 'timer']
        }
        mock_proc.pid = 12345
        mock_psutil['process_iter'].return_value = iter([mock_proc])
        mock_psutil['wait_procs'].return_value = ([mock_proc], [])

        result = runner.invoke(cli, ['worker', 'stop', 'timer', '--timeout', '30'])

        assert result.exit_code == 0
        assert "Waiting up to 30s for graceful shutdown" in result.output


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
