"""
Tests for Handler-Container Integration

Tests that PythonHandler correctly integrates with ContainerExecutor
when execution_mode is set to 'container'.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from gleitzeit.handlers.python import PythonHandler
from gleitzeit.core.models import Task, TaskStatus


class TestContainerIntegration:
    """Test PythonHandler integration with ContainerExecutor"""

    @pytest.mark.asyncio
    async def test_container_mode_routing(self):
        """Test that execution_mode: 'container' routes to ContainerExecutor"""

        # Create handler with container mode
        config = {
            'execution_mode': 'container',
            'container_config': {
                'image': 'python:3.11-slim',
                'memory_limit': '512m'
            }
        }

        handler = PythonHandler(config)

        # Create a test task
        task = Task(
            id='test-task-1', name='test_container_routing',
            workflow_id='workflow-1',
            method='python/execute',
            params={
                'code': 'result = 2 + 2',
                'inputs': {}
            },
            timeout=30
        )

        # Mock ContainerExecutor
        with patch('gleitzeit.handlers.python.ContainerExecutor') as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_executor.is_available.return_value = True
            mock_executor.execute = AsyncMock(return_value={
                'success': True,
                'result': 4,
                'output': 'Success',
                'exit_code': 0,
                'container_id': 'abc123'
            })

            # Execute task
            result = await handler.execute(task)

            # Verify ContainerExecutor was used
            assert MockExecutor.called
            assert mock_executor.execute.called

            # Verify execution parameters
            call_kwargs = mock_executor.execute.call_args[1]
            assert call_kwargs['code'] == 'result = 2 + 2'
            assert call_kwargs['inputs'] == {}
            assert call_kwargs['runtime'] == 'python'
            assert call_kwargs['timeout'] == 30

            # Verify result
            assert result.status == TaskStatus.COMPLETED
            assert result.result == 4

    @pytest.mark.asyncio
    async def test_container_mode_fallback_to_pool(self):
        """Test fallback to pool mode when Docker is not available"""

        config = {
            'execution_mode': 'container',
            'subprocess_pool_enabled': True
        }

        handler = PythonHandler(config)

        task = Task(
            id='test-task-2', name='test_fallback_to_pool',
            workflow_id='workflow-2',
            method='python/execute',
            params={
                'code': 'result = 3 + 3',
                'inputs': {}
            },
            timeout=30
        )

        # Mock ContainerExecutor to be unavailable
        with patch('gleitzeit.handlers.python.ContainerExecutor') as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_executor.is_available.return_value = False

            # Mock pool execution
            if handler.pool:
                with patch.object(handler.pool, 'execute_code', new_callable=AsyncMock) as mock_pool:
                    mock_pool.return_value = {'success': True, 'result': 6}

                    result = await handler.execute(task)

                    # Verify it fell back to pool
                    assert mock_pool.called
                    assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_container_execution_failure(self):
        """Test that container execution failures are handled properly"""

        config = {
            'execution_mode': 'container'
        }

        handler = PythonHandler(config)

        task = Task(
            id='test-task-3', name='test_execution_failure',
            workflow_id='workflow-3',
            method='python/execute',
            params={
                'code': 'raise Exception("Test error")',
                'inputs': {}
            },
            timeout=30
        )

        # Mock ContainerExecutor with failure
        with patch('gleitzeit.handlers.python.ContainerExecutor') as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_executor.is_available.return_value = True
            mock_executor.execute = AsyncMock(return_value={
                'success': False,
                'output': 'Exception: Test error',
                'exit_code': 1,
                'container_id': 'abc123'
            })

            result = await handler.execute(task)

            # Verify failure is handled
            assert result.status == TaskStatus.FAILED
            assert 'Container execution failed' in result.error

    @pytest.mark.asyncio
    async def test_container_timeout_handling(self):
        """Test that container timeouts are handled properly"""

        config = {
            'execution_mode': 'container'
        }

        handler = PythonHandler(config)

        task = Task(
            id='test-task-4', name='test_timeout_handling',
            workflow_id='workflow-4',
            method='python/execute',
            params={
                'code': 'import time; time.sleep(1000)',
                'inputs': {}
            },
            timeout=5
        )

        # Mock ContainerExecutor with timeout
        with patch('gleitzeit.handlers.python.ContainerExecutor') as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_executor.is_available.return_value = True
            mock_executor.execute = AsyncMock(side_effect=asyncio.TimeoutError('Timeout'))

            result = await handler.execute(task)

            # Verify timeout is handled
            assert result.status == TaskStatus.FAILED
            assert 'timeout' in result.error.lower()

    @pytest.mark.asyncio
    async def test_pool_mode_still_works(self):
        """Test that pool mode (default) still works after container integration"""

        config = {
            'execution_mode': 'pool',
            'subprocess_pool_enabled': True
        }

        handler = PythonHandler(config)

        task = Task(
            id='test-task-5', name='test_pool_mode',
            workflow_id='workflow-5',
            method='python/execute',
            params={
                'code': 'result = 5 + 5',
                'inputs': {}
            },
            timeout=30
        )

        # Mock pool execution
        if handler.pool:
            with patch.object(handler.pool, 'execute_code', new_callable=AsyncMock) as mock_pool:
                mock_pool.return_value = {'success': True, 'result': 10}

                result = await handler.execute(task)

                # Verify pool mode works
                assert mock_pool.called
                assert result.status == TaskStatus.COMPLETED
                assert result.result == 10


class TestContainerExecutorFixes:
    """Test that ContainerExecutor bug fixes work correctly"""

    @pytest.mark.asyncio
    async def test_collect_results_timeout_protection(self):
        """Test that _collect_results has timeout protection (no infinite loop)"""
        from gleitzeit.core.container_executor import ContainerExecutor

        config = {'image': 'python:3.11-slim'}
        executor = ContainerExecutor(config)

        # Mock a hung container
        mock_container = MagicMock()
        mock_container.status = 'running'  # Never changes to 'exited'
        mock_container.reload = MagicMock()
        mock_container.kill = MagicMock()

        # Test that timeout is enforced
        with pytest.raises(TimeoutError) as exc_info:
            await executor._collect_results(mock_container, timeout=1)

        assert 'did not exit' in str(exc_info.value).lower()
        # Verify container was killed
        assert mock_container.kill.called

    @pytest.mark.asyncio
    async def test_cleanup_container_on_error(self):
        """Test that containers are cleaned up on errors"""
        from gleitzeit.core.container_executor import ContainerExecutor

        config = {'image': 'python:3.11-slim'}
        executor = ContainerExecutor(config)

        mock_container = MagicMock()
        mock_container.short_id = 'test123'
        mock_container.kill = MagicMock()
        mock_container.remove = MagicMock()

        # Test cleanup
        await executor._cleanup_container(mock_container)

        # Verify both kill and remove were called
        assert mock_container.kill.called
        assert mock_container.remove.called

    @pytest.mark.asyncio
    async def test_cleanup_on_execution_error(self):
        """Test that execute() cleans up container on error"""
        from gleitzeit.core.container_executor import ContainerExecutor

        config = {'image': 'python:3.11-slim'}
        executor = ContainerExecutor(config)

        # Mock Docker client
        executor.docker_client = MagicMock()
        executor._initialized = True

        mock_container = MagicMock()
        mock_container.short_id = 'test456'
        mock_container.kill = MagicMock()
        mock_container.remove = MagicMock()

        # Mock _run_container to return container, then _collect_results to fail
        with patch.object(executor, '_run_container', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_container

            with patch.object(executor, '_collect_results', new_callable=AsyncMock) as mock_collect:
                mock_collect.side_effect = Exception('Test error')

                with patch.object(executor, '_cleanup_container', new_callable=AsyncMock) as mock_cleanup:
                    # Execute should catch error and cleanup
                    with pytest.raises(Exception):
                        await executor.execute('print("test")', {}, 30, 'python')

                    # Verify cleanup was called
                    assert mock_cleanup.called
                    assert mock_cleanup.call_args[0][0] == mock_container


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
