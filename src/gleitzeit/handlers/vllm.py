"""
vLLM handler for Gleitzeit.

Provides integration with vLLM for high-performance LLM inference.
vLLM uses OpenAI-compatible API for completions and chat.
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any, Optional, List
import logging

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode
from ..core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

logger = logging.getLogger(__name__)


@HandlerRegistry.register
class VllmHandler(BaseHandler):
    """
    Execute LLM tasks using vLLM.

    This handler:
    - Connects to vLLM servers (local or remote)
    - Uses OpenAI-compatible API
    - Supports completions and chat completions
    - Handles streaming and non-streaming responses
    - Provides model information capabilities
    """

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get vLLM handler capabilities"""
        return {
            'protocol': 'vllm/v1',
            'task_types': ['vllm', 'llm'],
            'methods': {
                'vllm/completions': {
                    'description': 'Generate text completions',
                    'required': ['prompt', 'model'],
                    'optional': ['max_tokens', 'temperature', 'top_p', 'top_k',
                                'frequency_penalty', 'presence_penalty', 'stop',
                                'stream', 'logprobs', 'echo', 'n', 'best_of']
                },
                'vllm/chat': {
                    'description': 'Chat completion with conversation history',
                    'required': ['messages', 'model'],
                    'optional': ['max_tokens', 'temperature', 'top_p', 'top_k',
                                'frequency_penalty', 'presence_penalty', 'stop',
                                'stream', 'logprobs', 'n']
                },
                'vllm/models': {
                    'description': 'List available models',
                    'required': [],
                    'optional': []
                }
            }
        }

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize vLLM handler.

        Config options:
            - base_url: vLLM server URL (default: http://localhost:8000)
            - timeout: Request timeout in seconds (default: 300)
            - default_model: Default model to use if not specified
            - default_max_tokens: Default max tokens for generation
            - default_temperature: Default temperature
            - circuit_breaker: Circuit breaker configuration
            - api_key: Optional API key for authentication
        """
        super().__init__(config)
        self.base_url = self.config.get('base_url', 'http://localhost:8000')
        # Remove trailing slash if present
        self.base_url = self.base_url.rstrip('/')

        self.timeout = self.config.get('timeout', 300)
        self.default_model = self.config.get('default_model')
        self.default_max_tokens = self.config.get('default_max_tokens', 256)
        self.default_temperature = self.config.get('default_temperature', 0.7)
        self.api_key = self.config.get('api_key')

        # Initialize circuit breaker for vLLM service
        circuit_config = self.config.get('circuit_breaker', {})
        self.circuit_breaker = CircuitBreaker(
            name=f"vllm_{self.base_url}",
            config=CircuitBreakerConfig(
                failure_threshold=circuit_config.get('failure_threshold', 5),
                success_threshold=circuit_config.get('success_threshold', 2),
                reset_timeout=circuit_config.get('reset_timeout', 60),
                half_open_max_calls=circuit_config.get('half_open_max_calls', 3),
                failure_exceptions=(aiohttp.ClientError, asyncio.TimeoutError, Exception)
            )
        )

    async def execute(self, task: Task) -> TaskResult:
        """Execute vLLM task"""
        start_time = asyncio.get_event_loop().time()

        try:
            # Check circuit breaker first - fail fast if service is down
            if self.circuit_breaker.is_open():
                logger.warning(f"Circuit breaker OPEN for vLLM at {self.base_url}")
                return TaskResult(
                    status=TaskStatus.FAILED,
                    error=f"vLLM service at {self.base_url} is currently unavailable (circuit breaker open)",
                    handler_id=self.handler_id,
                    metadata={
                        'circuit_breaker_state': 'open',
                        'circuit_breaker_stats': self.circuit_breaker.get_status()
                    }
                )

            # Record metrics if available
            if self.metrics:
                metric_start = await self.metrics.record_task_start()

            # Validate task
            await self.validate(task)

            # Execute based on method
            if task.method == 'vllm/completions':
                result = await self._completions(task)
            elif task.method == 'vllm/chat':
                result = await self._chat(task)
            elif task.method == 'vllm/models':
                result = await self._list_models(task)
            else:
                raise GleitzeitError(
                    f"Unknown method: {task.method}",
                    code=ErrorCode.METHOD_NOT_SUPPORTED,
                    data={'task_id': task.id, 'method': task.method}
                )

            # Record success metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=True)

            return self.create_result(
                task=task,
                status=TaskStatus.COMPLETED,
                result=result,
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except asyncio.TimeoutError:
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False)

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=f"Task timed out after {task.timeout or self.timeout}s",
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except GleitzeitError as e:
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(e),
                metadata={'error_code': e.code.value, 'error_data': e.data},
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except Exception as e:
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            logger.error(f"vLLM execution failed: {e}", exc_info=True)
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(e),
                metadata={'error_type': type(e).__name__},
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers including optional API key"""
        headers = {
            'Content-Type': 'application/json'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    async def _completions(self, task: Task) -> Dict[str, Any]:
        """Generate text completions using vLLM"""
        prompt = task.params['prompt']
        model = task.params.get('model', self.default_model)

        if not model:
            raise GleitzeitError(
                "Model must be specified in task params or handler config",
                code=ErrorCode.INVALID_PARAMS,
                data={'task_id': task.id}
            )

        # Build request with OpenAI-compatible parameters
        request_data = {
            'model': model,
            'prompt': prompt,
            'max_tokens': task.params.get('max_tokens', self.default_max_tokens),
            'temperature': task.params.get('temperature', self.default_temperature),
        }

        # Add optional parameters
        optional_params = [
            'top_p', 'top_k', 'frequency_penalty', 'presence_penalty',
            'stop', 'stream', 'logprobs', 'echo', 'n', 'best_of'
        ]
        for param in optional_params:
            if param in task.params:
                request_data[param] = task.params[param]

        stream = request_data.get('stream', False)
        timeout = task.timeout or self.timeout

        # Execute request through circuit breaker
        try:
            return await self.circuit_breaker.call(
                self._make_completions_request,
                request_data,
                model,
                timeout,
                stream
            )
        except CircuitOpenError as e:
            logger.warning(f"Circuit breaker open for vLLM: {e}")
            raise GleitzeitError(
                f"vLLM service unavailable: {e}",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                data={'circuit_breaker': 'open', 'model': model}
            )

    async def _make_completions_request(self, request_data: Dict[str, Any],
                                       model: str, timeout: float,
                                       stream: bool) -> Dict[str, Any]:
        """Make the actual HTTP request to vLLM (called through circuit breaker)"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/v1/completions",
                    json=request_data,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"vLLM API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'status': response.status, 'model': model}
                        )

                    if stream:
                        # Collect streamed responses (SSE format)
                        full_text = ""
                        chunks = []
                        async for line in response.content:
                            if line:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    data_str = line_str[6:]  # Remove 'data: ' prefix
                                    if data_str == '[DONE]':
                                        break
                                    try:
                                        data = json.loads(data_str)
                                        if 'choices' in data and len(data['choices']) > 0:
                                            text = data['choices'][0].get('text', '')
                                            full_text += text
                                            chunks.append(data)
                                    except json.JSONDecodeError:
                                        continue

                        # Return aggregated response
                        if chunks:
                            last_chunk = chunks[-1]
                            return {
                                'text': full_text,
                                'model': model,
                                'finish_reason': last_chunk['choices'][0].get('finish_reason'),
                                'usage': last_chunk.get('usage', {}),
                                'chunks': len(chunks)
                            }
                        else:
                            return {'text': full_text, 'model': model}
                    else:
                        # Non-streaming response
                        result = await response.json()
                        return {
                            'text': result['choices'][0]['text'],
                            'model': model,
                            'finish_reason': result['choices'][0].get('finish_reason'),
                            'usage': result.get('usage', {}),
                            'id': result.get('id'),
                            'created': result.get('created')
                        }

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to vLLM server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'base_url': self.base_url}
                )

    async def _chat(self, task: Task) -> Dict[str, Any]:
        """Chat completion with conversation history"""
        messages = task.params['messages']
        model = task.params.get('model', self.default_model)

        if not model:
            raise GleitzeitError(
                "Model must be specified in task params or handler config",
                code=ErrorCode.INVALID_PARAMS,
                data={'task_id': task.id}
            )

        # Validate messages format
        if not isinstance(messages, list):
            raise GleitzeitError(
                "Messages must be a list of message objects",
                code=ErrorCode.INVALID_PARAMS,
                data={'task_id': task.id}
            )

        for msg in messages:
            if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
                raise GleitzeitError(
                    "Each message must have 'role' and 'content' fields",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id}
                )

        # Build request with OpenAI-compatible parameters
        request_data = {
            'model': model,
            'messages': messages,
            'max_tokens': task.params.get('max_tokens', self.default_max_tokens),
            'temperature': task.params.get('temperature', self.default_temperature),
        }

        # Add optional parameters
        optional_params = [
            'top_p', 'top_k', 'frequency_penalty', 'presence_penalty',
            'stop', 'stream', 'logprobs', 'n'
        ]
        for param in optional_params:
            if param in task.params:
                request_data[param] = task.params[param]

        stream = request_data.get('stream', False)
        timeout = task.timeout or self.timeout

        # Make request
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=request_data,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"vLLM API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'status': response.status, 'model': model}
                        )

                    if stream:
                        # Collect streamed responses (SSE format)
                        full_content = ""
                        chunks = []
                        async for line in response.content:
                            if line:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    data_str = line_str[6:]
                                    if data_str == '[DONE]':
                                        break
                                    try:
                                        data = json.loads(data_str)
                                        if 'choices' in data and len(data['choices']) > 0:
                                            delta = data['choices'][0].get('delta', {})
                                            content = delta.get('content', '')
                                            full_content += content
                                            chunks.append(data)
                                    except json.JSONDecodeError:
                                        continue

                        # Return aggregated response
                        if chunks:
                            last_chunk = chunks[-1]
                            return {
                                'message': {
                                    'role': 'assistant',
                                    'content': full_content
                                },
                                'model': model,
                                'finish_reason': last_chunk['choices'][0].get('finish_reason'),
                                'usage': last_chunk.get('usage', {}),
                                'chunks': len(chunks)
                            }
                        else:
                            return {
                                'message': {'role': 'assistant', 'content': full_content},
                                'model': model
                            }
                    else:
                        # Non-streaming response
                        result = await response.json()
                        return {
                            'message': result['choices'][0]['message'],
                            'model': model,
                            'finish_reason': result['choices'][0].get('finish_reason'),
                            'usage': result.get('usage', {}),
                            'id': result.get('id'),
                            'created': result.get('created')
                        }

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to vLLM server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'base_url': self.base_url}
                )

    async def _list_models(self, task: Task) -> List[Dict[str, Any]]:
        """List available models"""
        timeout = task.timeout or self.timeout

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.base_url}/v1/models",
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"vLLM API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'status': response.status}
                        )

                    result = await response.json()
                    return result.get('data', [])

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to vLLM server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'base_url': self.base_url}
                )
