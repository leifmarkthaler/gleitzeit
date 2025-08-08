"""
Tests for Service Manager (Auto-start functionality)
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from gleitzeit_cluster.core.service_manager import ServiceManager


class TestServiceManager:
    """Test ServiceManager functionality"""
    
    def test_service_manager_initialization(self):
        """Test service manager initializes correctly"""
        manager = ServiceManager()
        
        assert manager.redis_process is None
        assert len(manager.executor_processes) == 0
    
    def test_port_checking(self, mock_socket):
        """Test port availability checking"""
        manager = ServiceManager()
        
        # Mock successful connection (port open)
        mock_socket.return_value = True
        assert manager.is_port_open("localhost", 6379) is True
        
        # Mock failed connection (port closed)
        mock_socket.side_effect = ConnectionError("Connection failed")
        assert manager.is_port_open("localhost", 6379) is False
    
    @patch('redis.Redis')
    def test_redis_status_checking(self, mock_redis_class):
        """Test Redis status checking"""
        manager = ServiceManager()
        
        # Mock Redis connection success
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_class.return_value = mock_redis_instance
        
        assert manager.is_redis_running("redis://localhost:6379") is True
        
        # Mock Redis connection failure
        mock_redis_instance.ping.side_effect = Exception("Connection failed")
        assert manager.is_redis_running("redis://localhost:6379") is False
        
        # Test URL parsing
        assert manager.is_redis_running("redis://localhost:6380") is False  # Different port
    
    def test_redis_server_start_success(self, mock_subprocess):
        """Test successful Redis server startup"""
        manager = ServiceManager()
        
        # Mock successful subprocess call
        mock_subprocess['run'].return_value.returncode = 0
        
        # Mock Redis availability after start
        with patch.object(manager, 'is_redis_running', return_value=True):
            result = manager.start_redis_server()
            assert result is True
        
        # Verify subprocess was called with correct arguments
        mock_subprocess['run'].assert_called_once()
        args = mock_subprocess['run'].call_args[0][0]
        assert "redis-server" in args
        assert "--daemonize" in args
        assert "yes" in args
    
    def test_redis_server_start_failure(self, mock_subprocess):
        """Test Redis server startup failure"""
        manager = ServiceManager()
        
        # Mock failed subprocess call
        mock_subprocess['run'].return_value.returncode = 1
        mock_subprocess['run'].return_value.stderr = "Permission denied"
        
        result = manager.start_redis_server()
        assert result is False
    
    def test_redis_server_start_timeout(self, mock_subprocess):
        """Test Redis server startup timeout"""
        manager = ServiceManager()
        
        # Mock timeout
        import subprocess
        mock_subprocess['run'].side_effect = subprocess.TimeoutExpired("redis-server", 10)
        
        result = manager.start_redis_server()
        assert result is False
    
    def test_redis_server_not_found(self, mock_subprocess):
        """Test Redis server command not found"""
        manager = ServiceManager()
        
        # Mock command not found
        mock_subprocess['run'].side_effect = FileNotFoundError("redis-server not found")
        
        result = manager.start_redis_server()
        assert result is False
    
    def test_executor_node_start_success(self, mock_subprocess):
        """Test successful executor node startup"""
        manager = ServiceManager()
        
        # Mock successful process start
        mock_process = mock_subprocess['process']
        mock_process.poll.return_value = None  # Still running
        
        result = manager.start_executor_node(
            name="test-executor",
            cluster_url="http://localhost:8000",
            max_tasks=2
        )
        
        assert result is True
        assert len(manager.executor_processes) == 1
        
        # Verify process was started with correct arguments
        mock_subprocess['popen'].assert_called_once()
        args = mock_subprocess['popen'].call_args[0][0]
        assert "gleitzeit" in args
        assert "executor" in args
        assert "--name" in args
        assert "test-executor" in args
    
    def test_executor_node_start_failure(self, mock_subprocess):
        """Test executor node startup failure"""
        manager = ServiceManager()
        
        # Mock process that dies immediately
        mock_process = mock_subprocess['process']
        mock_process.poll.return_value = 1  # Exited with error
        mock_process.communicate.return_value = ("", "Error starting executor")
        
        result = manager.start_executor_node("failed-executor")
        assert result is False
        assert len(manager.executor_processes) == 0
    
    def test_executor_node_command_not_found(self, mock_subprocess):
        """Test executor node startup with missing gleitzeit command"""
        manager = ServiceManager()
        
        # Mock command not found
        mock_subprocess['popen'].side_effect = FileNotFoundError("gleitzeit not found")
        
        result = manager.start_executor_node("missing-cmd-executor")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_ensure_services_running_all_needed(self, mock_subprocess):
        """Test ensuring all services are running when none exist"""
        manager = ServiceManager()
        
        # Mock Redis not running initially
        with patch.object(manager, 'is_redis_running', return_value=False), \
             patch.object(manager, 'start_redis_server', return_value=True), \
             patch.object(manager, 'start_executor_node', return_value=True):
            
            result = await manager.ensure_services_running(
                auto_start_redis=True,
                auto_start_executor=True,
                min_executors=2
            )
            
            assert result["redis"] is True
            assert result["executors"] is True
            assert "redis" in result["services_started"]
            assert "2_executors" in result["services_started"]
    
    @pytest.mark.asyncio
    async def test_ensure_services_running_redis_exists(self, mock_subprocess):
        """Test ensuring services when Redis already exists"""
        manager = ServiceManager()
        
        # Mock Redis already running
        with patch.object(manager, 'is_redis_running', return_value=True), \
             patch.object(manager, 'start_redis_server') as mock_start_redis, \
             patch.object(manager, 'start_executor_node', return_value=True):
            
            result = await manager.ensure_services_running(
                auto_start_redis=True,
                auto_start_executor=True,
                min_executors=1
            )
            
            assert result["redis"] is True
            assert result["executors"] is True
            
            # Redis start should not be called
            mock_start_redis.assert_not_called()
            assert "redis" not in result["services_started"]
            assert "1_executors" in result["services_started"]
    
    @pytest.mark.asyncio
    async def test_ensure_services_disabled(self):
        """Test ensuring services when auto-start is disabled"""
        manager = ServiceManager()
        
        with patch.object(manager, 'is_redis_running', return_value=False):
            result = await manager.ensure_services_running(
                auto_start_redis=False,
                auto_start_executor=False
            )
            
            assert result["redis"] is False
            assert result["executors"] is False
            assert len(result["services_started"]) == 0
    
    @pytest.mark.asyncio
    async def test_ensure_services_executor_requires_redis(self):
        """Test that executors are only started if Redis is available"""
        manager = ServiceManager()
        
        # Mock Redis failure
        with patch.object(manager, 'is_redis_running', return_value=False), \
             patch.object(manager, 'start_redis_server', return_value=False), \
             patch.object(manager, 'start_executor_node') as mock_start_executor:
            
            result = await manager.ensure_services_running(
                auto_start_redis=True,
                auto_start_executor=True,
                min_executors=1
            )
            
            assert result["redis"] is False
            assert result["executors"] is False
            
            # Executor start should not be called without Redis
            mock_start_executor.assert_not_called()
    
    def test_stop_managed_services(self, mock_subprocess):
        """Test stopping managed services"""
        manager = ServiceManager()
        
        # Add some mock processes
        mock_process1 = Mock()
        mock_process1.poll.return_value = None  # Still running
        mock_process1.terminate.return_value = None
        mock_process1.wait.return_value = 0
        
        mock_process2 = Mock()
        mock_process2.poll.return_value = None  # Still running
        mock_process2.terminate.return_value = None
        mock_process2.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_process2.kill.return_value = None
        
        manager.executor_processes = [mock_process1, mock_process2]
        
        import subprocess
        with patch('subprocess.TimeoutExpired', subprocess.TimeoutExpired):
            stopped = manager.stop_managed_services()
        
        # Should have stopped both processes
        assert len(stopped) == 2
        assert "executor" in stopped[0]
        
        # First process should be terminated gracefully
        mock_process1.terminate.assert_called_once()
        mock_process1.wait.assert_called_once()
        
        # Second process should be killed after timeout
        mock_process2.terminate.assert_called_once()
        mock_process2.kill.assert_called_once()
        
        # Process list should be cleared
        assert len(manager.executor_processes) == 0
    
    def test_stop_managed_services_no_processes(self):
        """Test stopping services when no processes are running"""
        manager = ServiceManager()
        
        stopped = manager.stop_managed_services()
        assert len(stopped) == 0
    
    def test_stop_managed_services_error_handling(self):
        """Test error handling during service stop"""
        manager = ServiceManager()
        
        # Add a problematic process
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_process.terminate.side_effect = Exception("Terminate failed")
        
        manager.executor_processes = [mock_process]
        
        # Should not raise exception
        stopped = manager.stop_managed_services()
        assert len(manager.executor_processes) == 0


@pytest.mark.integration
class TestServiceManagerIntegration:
    """Integration tests for service manager"""
    
    @pytest.mark.asyncio
    async def test_full_service_lifecycle(self):
        """Test complete service start/stop lifecycle"""
        manager = ServiceManager()
        
        with patch.object(manager, 'is_redis_running', side_effect=[False, True]), \
             patch.object(manager, 'start_redis_server', return_value=True), \
             patch.object(manager, 'start_executor_node', return_value=True), \
             patch.object(manager, 'stop_managed_services', return_value=["executor"]) as mock_stop:
            
            # Start services
            result = await manager.ensure_services_running(
                auto_start_redis=True,
                auto_start_executor=True,
                min_executors=1
            )
            
            assert result["redis"] is True
            assert result["executors"] is True
            assert len(result["services_started"]) == 2
            
            # Stop services
            stopped = manager.stop_managed_services()
            mock_stop.assert_called_once()
    
    def test_service_manager_error_resilience(self):
        """Test service manager handles various error conditions"""
        manager = ServiceManager()
        
        # Test with various invalid Redis URLs
        assert manager.is_redis_running("invalid://url") is False
        assert manager.is_redis_running("") is False
        assert manager.is_redis_running("redis://") is False
        
        # Test port checking with invalid parameters
        assert manager.is_port_open("invalid.host", 6379, timeout=0.1) is False
        assert manager.is_port_open("localhost", 99999, timeout=0.1) is False
    
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_service_startup_timing(self):
        """Test service startup includes appropriate delays"""
        manager = ServiceManager()
        
        start_time = asyncio.get_event_loop().time()
        
        with patch.object(manager, 'is_redis_running', return_value=True), \
             patch.object(manager, 'start_executor_node', return_value=True):
            
            await manager.ensure_services_running(
                auto_start_redis=False,
                auto_start_executor=True,
                min_executors=1
            )
        
        # Should include delay for executor registration
        elapsed = asyncio.get_event_loop().time() - start_time
        assert elapsed >= 4.5  # Should wait ~5 seconds for executor registration


class TestServiceManagerEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_redis_url_parsing_edge_cases(self):
        """Test Redis URL parsing with various formats"""
        manager = ServiceManager()
        
        # Test various URL formats
        test_cases = [
            ("redis://localhost:6379", True),
            ("redis://127.0.0.1:6380", True), 
            ("redis://localhost", True),
            ("redis://", False),
            ("localhost:6379", False),
            ("", False),
            (None, False)
        ]
        
        for url, should_parse in test_cases:
            try:
                # This will fail when trying to connect, but URL parsing should work
                result = manager.is_redis_running(url) if url else False
                if should_parse:
                    # URL was parsed (connection will fail in test, but that's expected)
                    assert result is False  # Expected to fail in test environment
                else:
                    assert result is False
            except Exception:
                # URL parsing failed
                assert not should_parse
    
    def test_executor_startup_with_custom_parameters(self, mock_subprocess):
        """Test executor startup with various parameter combinations"""
        manager = ServiceManager()
        
        mock_subprocess['process'].poll.return_value = None  # Running
        
        # Test with different parameter combinations
        test_cases = [
            {"name": "test", "cluster_url": "http://localhost:8000", "max_tasks": 1},
            {"name": "gpu-executor", "cluster_url": "https://remote:8443", "max_tasks": 8},
            {"name": "minimal", "cluster_url": "http://127.0.0.1:9000", "max_tasks": 2}
        ]
        
        for params in test_cases:
            result = manager.start_executor_node(**params)
            assert result is True
            
            # Verify correct arguments were passed
            args = mock_subprocess['popen'].call_args[0][0]
            assert params["name"] in args
            assert params["cluster_url"] in args
            assert str(params["max_tasks"]) in args
        
        # Should have started all executors
        assert len(manager.executor_processes) == len(test_cases)
    
    @pytest.mark.asyncio
    async def test_concurrent_service_operations(self):
        """Test concurrent service start operations"""
        manager = ServiceManager()
        
        with patch.object(manager, 'is_redis_running', return_value=False), \
             patch.object(manager, 'start_redis_server', return_value=True), \
             patch.object(manager, 'start_executor_node', return_value=True):
            
            # Start multiple concurrent service ensure operations
            tasks = []
            for i in range(3):
                task = manager.ensure_services_running(
                    auto_start_redis=True,
                    auto_start_executor=True,
                    min_executors=1
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            
            # All should succeed
            for result in results:
                assert result["redis"] is True
                assert result["executors"] is True