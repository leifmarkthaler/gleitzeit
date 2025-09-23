"""
Test Ollama handler functionality.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, Mock
import json

from gleitzeit.handlers.ollama import OllamaHandler
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.core.errors import GleitzeitError, ErrorCode


@pytest.fixture
def ollama_handler():
    """Create Ollama handler instance"""
    config = {
        'base_url': 'http://localhost:11434',
        'timeout': 30,
        'default_model': 'llama2'
    }
    return OllamaHandler(config)


@pytest.fixture
def sample_task():
    """Create sample task for testing"""
    return Task(
        id='test-task-1',
        workflow_id='test-workflow-1',
        name='test-ollama-task',
        protocol='ollama/v1',
        method='ollama/generate',
        params={
            'prompt': 'Hello, how are you?',
            'model': 'llama2'
        }
    )


class TestOllamaHandler:
    """Test Ollama handler functionality"""

    def test_capabilities(self):
        """Test handler capabilities"""
        caps = OllamaHandler.get_capabilities()

        assert caps['protocol'] == 'ollama/v1'
        assert 'ollama' in caps['task_types']
        assert 'llm' in caps['task_types']

        # Check methods
        assert 'ollama/generate' in caps['methods']
        assert 'ollama/chat' in caps['methods']
        assert 'ollama/embeddings' in caps['methods']
        assert 'ollama/list_models' in caps['methods']
        assert 'ollama/pull_model' in caps['methods']

    @pytest.mark.asyncio
    async def test_generate_success(self, ollama_handler, sample_task):
        """Test successful text generation"""
        mock_response = {
            'response': 'I am doing well, thank you!',
            'model': 'llama2',
            'created_at': '2024-01-01T00:00:00Z',
            'total_duration': 1000000000,
            'eval_count': 10
        }

        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up the mock response
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            # Set up the mock post context manager
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=mock_post_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(sample_task)

            assert result.status == TaskStatus.COMPLETED
            assert result.result['response'] == 'I am doing well, thank you!'
            assert result.result['model'] == 'llama2'
            assert result.error is None

    @pytest.mark.asyncio
    async def test_chat_completion(self, ollama_handler):
        """Test chat completion"""
        task = Task(
            id='test-task-2',
            workflow_id='test-workflow-1',
            name='test-chat',
            protocol='ollama/v1',
            method='ollama/chat',
            params={
                'messages': [
                    {'role': 'user', 'content': 'Hello!'},
                    {'role': 'assistant', 'content': 'Hi there!'},
                    {'role': 'user', 'content': 'How are you?'}
                ],
                'model': 'llama2'
            }
        )

        mock_response = {
            'message': {
                'role': 'assistant',
                'content': 'I am doing great, thanks for asking!'
            },
            'model': 'llama2',
            'created_at': '2024-01-01T00:00:00Z',
            'total_duration': 2000000000
        }

        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up the mock response
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            # Set up the mock post context manager
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=mock_post_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(task)

            assert result.status == TaskStatus.COMPLETED
            assert result.result['message']['role'] == 'assistant'
            assert result.result['message']['content'] == 'I am doing great, thanks for asking!'

    @pytest.mark.asyncio
    async def test_embeddings(self, ollama_handler):
        """Test embedding generation"""
        task = Task(
            id='test-task-3',
            workflow_id='test-workflow-1',
            name='test-embeddings',
            protocol='ollama/v1',
            method='ollama/embeddings',
            params={
                'prompt': 'Generate embeddings for this text',
                'model': 'llama2'
            }
        )

        mock_response = {
            'embedding': [0.1, 0.2, 0.3, 0.4, 0.5],
            'model': 'llama2'
        }

        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up the mock response
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            # Set up the mock post context manager
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=mock_post_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(task)

            assert result.status == TaskStatus.COMPLETED
            assert result.result['embedding'] == [0.1, 0.2, 0.3, 0.4, 0.5]
            assert result.result['model'] == 'llama2'

    @pytest.mark.asyncio
    async def test_list_models(self, ollama_handler):
        """Test listing available models"""
        task = Task(
            id='test-task-4',
            workflow_id='test-workflow-1',
            name='test-list-models',
            protocol='ollama/v1',
            method='ollama/list_models',
            params={}
        )

        mock_response = {
            'models': [
                {
                    'name': 'llama2:latest',
                    'modified_at': '2024-01-01T00:00:00Z',
                    'size': 3825819519
                },
                {
                    'name': 'codellama:latest',
                    'modified_at': '2024-01-01T00:00:00Z',
                    'size': 4825819519
                }
            ]
        }

        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up the mock response
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            # Set up the mock get context manager
            mock_get_cm = AsyncMock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.get = Mock(return_value=mock_get_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(task)

            assert result.status == TaskStatus.COMPLETED
            assert len(result.result) == 2
            assert result.result[0]['name'] == 'llama2:latest'
            assert result.result[1]['name'] == 'codellama:latest'

    @pytest.mark.asyncio
    async def test_api_error_handling(self, ollama_handler, sample_task):
        """Test API error handling"""
        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up the mock response
            mock_resp = AsyncMock()
            mock_resp.status = 500
            mock_resp.text = AsyncMock(return_value='Internal Server Error')

            # Set up the mock post context manager
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=mock_post_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(sample_task)

            assert result.status == TaskStatus.FAILED
            assert 'Ollama API error' in result.error
            assert result.metadata['error_code'] == ErrorCode.PROVIDER_ERROR.value

    @pytest.mark.asyncio
    async def test_connection_error(self, ollama_handler, sample_task):
        """Test connection error handling"""
        import aiohttp

        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up to raise ClientError when entering the post context manager
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__.side_effect = aiohttp.ClientError('Connection refused')
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=mock_post_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(sample_task)

            assert result.status == TaskStatus.FAILED
            assert 'Failed to connect to Ollama server' in result.error

    @pytest.mark.asyncio
    async def test_timeout_handling(self, ollama_handler, sample_task):
        """Test timeout handling"""
        sample_task.timeout = 0.001  # Very short timeout

        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up the mock response to raise TimeoutError
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(side_effect=asyncio.TimeoutError())

            # Set up the mock post context manager
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=mock_post_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(sample_task)

            assert result.status == TaskStatus.FAILED
            # Could be either timeout from aiohttp or our handler
            assert 'timeout' in result.error.lower() or 'timed out' in result.error.lower()

    @pytest.mark.asyncio
    async def test_stream_generation(self, ollama_handler):
        """Test streaming text generation"""
        task = Task(
            id='test-task-5',
            workflow_id='test-workflow-1',
            name='test-stream',
            protocol='ollama/v1',
            method='ollama/generate',
            params={
                'prompt': 'Tell me a story',
                'model': 'llama2',
                'stream': True
            }
        )

        # Simulate streaming response
        stream_data = [
            json.dumps({'response': 'Once ', 'done': False}).encode() + b'\n',
            json.dumps({'response': 'upon ', 'done': False}).encode() + b'\n',
            json.dumps({'response': 'a time...', 'done': True, 'total_duration': 1000000000}).encode() + b'\n'
        ]

        with patch('aiohttp.ClientSession') as mock_session_class:
            # Set up the mock response
            mock_resp = AsyncMock()
            mock_resp.status = 200

            # Create async generator for streaming
            async def async_gen():
                for item in stream_data:
                    yield item

            mock_resp.content = async_gen()

            # Set up the mock post context manager
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            # Set up the mock session
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=mock_post_cm)

            # Set up the ClientSession context manager
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_cm

            result = await ollama_handler.execute(task)

            assert result.status == TaskStatus.COMPLETED
            assert result.result['response'] == 'Once upon a time...'
            assert result.result['total_duration'] == 1000000000

    @pytest.mark.asyncio
    async def test_invalid_message_format(self, ollama_handler):
        """Test validation of message format for chat"""
        task = Task(
            id='test-task-6',
            workflow_id='test-workflow-1',
            name='test-invalid-chat',
            protocol='ollama/v1',
            method='ollama/chat',
            params={
                'messages': 'invalid',  # Should be a list
                'model': 'llama2'
            }
        )

        result = await ollama_handler.execute(task)

        assert result.status == TaskStatus.FAILED
        assert 'Messages must be a list' in result.error

    @pytest.mark.asyncio
    async def test_missing_required_params(self, ollama_handler):
        """Test validation of required parameters"""
        task = Task(
            id='test-task-7',
            workflow_id='test-workflow-1',
            name='test-missing-params',
            protocol='ollama/v1',
            method='ollama/generate',
            params={}  # Missing 'prompt' and 'model'
        )

        result = await ollama_handler.execute(task)

        assert result.status == TaskStatus.FAILED
        assert 'Missing required parameter' in result.error
        assert result.metadata['error_code'] == ErrorCode.INVALID_PARAMS.value


if __name__ == '__main__':
    pytest.main([__file__, '-v'])