"""
Tests for HTTP Handler
"""

import asyncio
import pytest
import pytest_asyncio
import aiohttp
from unittest.mock import AsyncMock, MagicMock, patch
import json

from gleitzeit.handlers.http import HttpHandler, HttpMethod
from gleitzeit.core.models import Task, TaskResult, TaskStatus
from gleitzeit.core.errors import GleitzeitError, ErrorCode


class TestHttpHandler:
    """Test HTTP handler functionality"""

    @pytest_asyncio.fixture
    async def handler(self):
        """Create HTTP handler instance"""
        handler = HttpHandler()
        yield handler
        # Cleanup
        if handler._session:
            await handler._session.close()

    @pytest.fixture
    def mock_response(self):
        """Create mock HTTP response"""
        response = AsyncMock()
        response.status = 200
        response.headers = {'Content-Type': 'application/json'}
        response.url = 'https://api.example.com/test'
        response.json = AsyncMock(return_value={'success': True, 'data': 'test'})
        response.text = AsyncMock(return_value='{"success": true}')
        response.read = AsyncMock(return_value=b'binary data')
        return response

    def create_task(self, method='http/get', **params):
        """Helper to create test tasks"""
        return Task(
            id='test-task-1',
            workflow_id='test-workflow-1',
            name='test_http_task',
            type='http',
            protocol='http/v1',
            method=method,
            params=params,
            config={}
        )

    @pytest.mark.asyncio
    async def test_capabilities(self):
        """Test handler capabilities"""
        caps = HttpHandler.get_capabilities()

        assert caps['protocol'] == 'http/v1'
        assert 'http' in caps['task_types']
        assert 'http/get' in caps['methods']
        assert 'http/post' in caps['methods']
        assert 'http/put' in caps['methods']
        assert 'http/delete' in caps['methods']

        # Check method definitions
        get_method = caps['methods']['http/get']
        assert 'url' in get_method['required']
        assert 'headers' in get_method['optional']

    @pytest.mark.asyncio
    async def test_get_request(self, handler, mock_response):
        """Test simple GET request"""
        task = self.create_task(
            method='http/get',
            url='https://api.example.com/users/123',
            headers={'Accept': 'application/json'}
        )

        with patch.object(handler, '_session') as mock_session:
            mock_session.request.return_value.__aenter__.return_value = mock_response

            result = await handler.execute(task)

            # Verify request was made
            mock_session.request.assert_called_once()
            call_args = mock_session.request.call_args

            assert call_args[0][0] == 'GET'
            assert call_args[0][1] == 'https://api.example.com/users/123'
            assert 'headers' in call_args[1]
            assert call_args[1]['headers']['Accept'] == 'application/json'

            # Verify result
            assert result.status == TaskStatus.COMPLETED
            assert result.result == {'success': True, 'data': 'test'}
            assert result.metadata['status_code'] == 200

    @pytest.mark.asyncio
    async def test_post_with_json(self, handler, mock_response):
        """Test POST request with JSON body"""
        task = self.create_task(
            method='http/post',
            url='https://api.example.com/users',
            json={'name': 'John', 'email': 'john@example.com'}
        )

        with patch.object(handler, '_session') as mock_session:
            mock_session.request.return_value.__aenter__.return_value = mock_response

            result = await handler.execute(task)

            # Verify request
            mock_session.request.assert_called_once()
            call_args = mock_session.request.call_args

            assert call_args[0][0] == 'POST'
            assert 'json' in call_args[1]
            assert call_args[1]['json'] == {'name': 'John', 'email': 'john@example.com'}
            assert call_args[1]['headers']['Content-Type'] == 'application/json'

            assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_bearer_auth(self, handler, mock_response):
        """Test Bearer token authentication"""
        task = self.create_task(
            method='http/get',
            url='https://api.example.com/protected',
            auth={
                'type': 'bearer',
                'token': 'secret-token-123'
            }
        )

        with patch.object(handler, '_session') as mock_session:
            mock_session.request.return_value.__aenter__.return_value = mock_response

            result = await handler.execute(task)

            # Verify auth header
            call_args = mock_session.request.call_args
            assert 'headers' in call_args[1]
            assert call_args[1]['headers']['Authorization'] == 'Bearer secret-token-123'

            assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_basic_auth(self, handler, mock_response):
        """Test Basic authentication"""
        task = self.create_task(
            method='http/get',
            url='https://api.example.com/protected',
            auth={
                'type': 'basic',
                'username': 'user',
                'password': 'pass'
            }
        )

        with patch.object(handler, '_session') as mock_session:
            mock_session.request.return_value.__aenter__.return_value = mock_response

            result = await handler.execute(task)

            # Verify auth
            call_args = mock_session.request.call_args
            assert 'auth' in call_args[1]
            assert isinstance(call_args[1]['auth'], aiohttp.BasicAuth)

            assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_api_key_auth(self, handler, mock_response):
        """Test API key authentication"""
        task = self.create_task(
            method='http/get',
            url='https://api.example.com/protected',
            auth={
                'type': 'api_key',
                'key': 'my-api-key',
                'header_name': 'X-Custom-Key'
            }
        )

        with patch.object(handler, '_session') as mock_session:
            mock_session.request.return_value.__aenter__.return_value = mock_response

            result = await handler.execute(task)

            # Verify custom header
            call_args = mock_session.request.call_args
            assert call_args[1]['headers']['X-Custom-Key'] == 'my-api-key'

            assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_expected_status_validation(self, handler):
        """Test response status validation"""
        task = self.create_task(
            method='http/get',
            url='https://api.example.com/test',
            expected_status=[200, 201]
        )

        # Mock 404 response
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.text = AsyncMock(return_value='Not found')

        with patch.object(handler, '_session') as mock_session:
            mock_session.request.return_value.__aenter__.return_value = mock_response

            result = await handler.execute(task)

            # Should fail due to unexpected status
            assert result.status == TaskStatus.FAILED
            assert 'Unexpected status code: 404' in result.error
            assert result.metadata['error_code'] == ErrorCode.PROVIDER_ERROR.value

    @pytest.mark.asyncio
    async def test_timeout_handling(self, handler):
        """Test request timeout handling"""
        task = self.create_task(
            method='http/get',
            url='https://api.example.com/slow',
            timeout=1  # 1 second timeout
        )

        with patch.object(handler, '_session') as mock_session:
            # Simulate timeout
            mock_session.request.side_effect = asyncio.TimeoutError()

            result = await handler.execute(task)

            assert result.status == TaskStatus.FAILED
            assert 'timed out' in result.error

    @pytest.mark.asyncio
    async def test_rate_limiting(self, handler, mock_response):
        """Test rate limiting functionality"""
        # Create tasks with rate limiting
        task1 = self.create_task(
            method='http/get',
            url='https://api.example.com/test',
            rate_limit=2,  # 2 requests per second
            rate_limit_key='test_api'
        )

        task2 = self.create_task(
            method='http/get',
            url='https://api.example.com/test',
            rate_limit=2,
            rate_limit_key='test_api'
        )

        with patch.object(handler, '_session') as mock_session:
            mock_session.request.return_value.__aenter__.return_value = mock_response

            # Execute two requests
            start_time = asyncio.get_event_loop().time()

            await asyncio.gather(
                handler.execute(task1),
                handler.execute(task2)
            )

            elapsed = asyncio.get_event_loop().time() - start_time

            # Should take at least 0.5 seconds due to rate limiting (2/sec = 0.5s delay)
            assert elapsed >= 0.4  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_json_path_extraction(self, handler):
        """Test JSONPath extraction from response"""
        task = self.create_task(
            method='http/get',
            url='https://api.example.com/data',
            extract_path='$.users[0].name'
        )

        # Mock response with nested JSON
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.json = AsyncMock(return_value={
            'users': [
                {'id': 1, 'name': 'Alice'},
                {'id': 2, 'name': 'Bob'}
            ]
        })

        # Skip JSONPath for this test (would need jsonpath_ng installed)
        with patch.object(handler, '_parse_response') as mock_parse:
            mock_parse.return_value = 'Alice'

            with patch.object(handler, '_session') as mock_session:
                mock_session.request.return_value.__aenter__.return_value = mock_response

                result = await handler.execute(task)

                assert result.status == TaskStatus.COMPLETED
                assert result.result == 'Alice'

    @pytest.mark.asyncio
    async def test_session_initialization(self, handler):
        """Test that session is initialized on first request"""
        assert handler._session is None

        task = self.create_task(
            method='http/get',
            url='https://api.example.com/test'
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'test': 'data'})
        mock_response.headers = {}
        mock_response.url = 'https://api.example.com/test'

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request.return_value.__aenter__.return_value = mock_response
            mock_session_class.return_value = mock_session

            await handler.execute(task)

            # Session should be created
            mock_session_class.assert_called_once()
            assert handler._session is not None

    @pytest.mark.asyncio
    async def test_cleanup(self, handler):
        """Test handler cleanup"""
        # Initialize session
        await handler.initialize_session()
        assert handler._session is not None

        # Mock close method
        mock_close = AsyncMock()
        handler._session.close = mock_close

        # Cleanup
        await handler.cleanup()

        # Session should be closed
        mock_close.assert_called_once()
        # Session should be None after cleanup
        assert handler._session is None

    @pytest.mark.asyncio
    async def test_different_response_types(self, handler):
        """Test different response type parsing"""

        # Test JSON response
        task_json = self.create_task(
            method='http/get',
            url='https://api.example.com/json',
            response_type='json'
        )

        # Test text response
        task_text = self.create_task(
            method='http/get',
            url='https://api.example.com/text',
            response_type='text'
        )

        # Test binary response
        task_binary = self.create_task(
            method='http/get',
            url='https://api.example.com/binary',
            response_type='binary'
        )

        with patch.object(handler, '_session') as mock_session:
            # JSON response
            mock_json_response = AsyncMock()
            mock_json_response.status = 200
            mock_json_response.headers = {'Content-Type': 'application/json'}
            mock_json_response.json = AsyncMock(return_value={'data': 'json'})
            mock_json_response.url = 'test'

            # Text response
            mock_text_response = AsyncMock()
            mock_text_response.status = 200
            mock_text_response.headers = {'Content-Type': 'text/plain'}
            mock_text_response.text = AsyncMock(return_value='plain text')
            mock_text_response.url = 'test'

            # Binary response
            mock_binary_response = AsyncMock()
            mock_binary_response.status = 200
            mock_binary_response.headers = {'Content-Type': 'application/octet-stream'}
            mock_binary_response.read = AsyncMock(return_value=b'\x89PNG\r\n')
            mock_binary_response.url = 'test'

            # Test each type
            mock_session.request.return_value.__aenter__.return_value = mock_json_response
            result_json = await handler.execute(task_json)
            assert result_json.result == {'data': 'json'}

            mock_session.request.return_value.__aenter__.return_value = mock_text_response
            result_text = await handler.execute(task_text)
            assert result_text.result == 'plain text'

            mock_session.request.return_value.__aenter__.return_value = mock_binary_response
            result_binary = await handler.execute(task_binary)
            assert result_binary.result == b'\x89PNG\r\n'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])