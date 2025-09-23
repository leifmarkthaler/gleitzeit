"""
Ollama LLM handler for Gleitzeit.

Provides integration with Ollama for local LLM inference.
Supports text generation, embeddings, and chat completions.
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
class OllamaHandler(BaseHandler):
    """
    Execute LLM tasks using Ollama.

    This handler:
    - Connects to local or remote Ollama instances
    - Supports text generation and chat completions
    - Handles streaming and non-streaming responses
    - Provides model management capabilities
    """

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get Ollama handler capabilities"""
        return {
            'protocol': 'ollama/v1',
            'task_types': ['ollama', 'llm'],
            'methods': {
                'ollama/generate': {
                    'description': 'Generate text from a prompt',
                    'required': ['prompt', 'model'],
                    'optional': ['options', 'system', 'template', 'context', 'stream', 'raw']
                },
                'ollama/chat': {
                    'description': 'Chat completion with conversation history',
                    'required': ['messages', 'model'],
                    'optional': ['options', 'template', 'stream']
                },
                'ollama/embeddings': {
                    'description': 'Generate embeddings for text',
                    'required': ['prompt', 'model'],
                    'optional': ['options']
                },
                'ollama/list_models': {
                    'description': 'List available models',
                    'required': [],
                    'optional': []
                },
                'ollama/pull_model': {
                    'description': 'Pull a model from Ollama registry',
                    'required': ['model'],
                    'optional': ['stream']
                }
            }
        }

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize Ollama handler.

        Config options:
            - base_url: Ollama server URL (default: http://localhost:11434)
            - timeout: Request timeout in seconds (default: 300)
            - default_model: Default model to use if not specified
            - default_options: Default generation options
            - circuit_breaker: Circuit breaker configuration
        """
        super().__init__(config)
        self.base_url = self.config.get('base_url', 'http://localhost:11434')
        self.timeout = self.config.get('timeout', 300)
        self.default_model = self.config.get('default_model', 'llama2')
        self.default_options = self.config.get('default_options', {})

        # Initialize circuit breaker for Ollama service
        circuit_config = self.config.get('circuit_breaker', {})
        self.circuit_breaker = CircuitBreaker(
            name=f"ollama_{self.base_url}",
            config=CircuitBreakerConfig(
                failure_threshold=circuit_config.get('failure_threshold', 5),
                success_threshold=circuit_config.get('success_threshold', 2),
                reset_timeout=circuit_config.get('reset_timeout', 60),
                half_open_max_calls=circuit_config.get('half_open_max_calls', 3),
                # Connection errors and timeouts should trigger circuit breaker
                failure_exceptions=(aiohttp.ClientError, asyncio.TimeoutError, Exception)
            )
        )

    async def execute(self, task: Task) -> TaskResult:
        """Execute Ollama task"""
        start_time = asyncio.get_event_loop().time()

        try:
            # Check circuit breaker first - fail fast if service is down
            if self.circuit_breaker.is_open():
                logger.warning(f"Circuit breaker OPEN for Ollama at {self.base_url}")
                return TaskResult(
                    status=TaskStatus.FAILED,
                    error=f"Ollama service at {self.base_url} is currently unavailable (circuit breaker open)",
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
            if task.method == 'ollama/generate':
                result = await self._generate(task)
            elif task.method == 'ollama/chat':
                result = await self._chat(task)
            elif task.method == 'ollama/embeddings':
                result = await self._embeddings(task)
            elif task.method == 'ollama/list_models':
                result = await self._list_models(task)
            elif task.method == 'ollama/pull_model':
                result = await self._pull_model(task)
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
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False)

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=f"Task timed out after {task.timeout or self.timeout}s",
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except GleitzeitError as e:
            # Record failure metrics
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
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            logger.error(f"Ollama execution failed: {e}", exc_info=True)
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(e),
                metadata={'error_type': type(e).__name__},
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

    async def _generate(self, task: Task) -> Dict[str, Any]:
        """Generate text from prompt"""
        prompt = task.params['prompt']
        model = task.params.get('model', self.default_model)
        options = task.params.get('options', self.default_options)
        system = task.params.get('system')
        template = task.params.get('template')
        context = task.params.get('context')
        stream = task.params.get('stream', False)
        raw = task.params.get('raw', False)

        timeout = task.timeout or self.timeout

        # Build request
        request_data = {
            'model': model,
            'prompt': prompt,
            'options': options,
            'stream': stream
        }

        if system:
            request_data['system'] = system
        if template:
            request_data['template'] = template
        if context:
            request_data['context'] = context
        if raw:
            request_data['raw'] = raw

        # Execute request through circuit breaker
        try:
            return await self.circuit_breaker.call(
                self._make_generate_request,
                request_data,
                model,
                timeout,
                stream
            )
        except CircuitOpenError as e:
            # Circuit is open - fail immediately
            logger.warning(f"Circuit breaker open for Ollama: {e}")
            raise GleitzeitError(
                f"Ollama service unavailable: {e}",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                data={'circuit_breaker': 'open', 'model': model}
            )

    async def _make_generate_request(self, request_data: Dict[str, Any], model: str,
                                    timeout: float, stream: bool) -> Dict[str, Any]:
        """Make the actual HTTP request to Ollama (called through circuit breaker)"""
        # Make request
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=request_data,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"Ollama API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'status': response.status, 'model': model}
                        )

                    if stream:
                        # Collect streamed responses
                        full_response = ""
                        async for line in response.content:
                            if line:
                                data = json.loads(line)
                                if 'response' in data:
                                    full_response += data['response']
                                if data.get('done'):
                                    return {
                                        'response': full_response,
                                        'model': model,
                                        'created_at': data.get('created_at'),
                                        'total_duration': data.get('total_duration'),
                                        'load_duration': data.get('load_duration'),
                                        'prompt_eval_count': data.get('prompt_eval_count'),
                                        'eval_count': data.get('eval_count'),
                                        'eval_duration': data.get('eval_duration')
                                    }
                    else:
                        # Non-streaming response
                        result = await response.json()
                        return {
                            'response': result.get('response'),
                            'model': model,
                            'created_at': result.get('created_at'),
                            'total_duration': result.get('total_duration'),
                            'load_duration': result.get('load_duration'),
                            'prompt_eval_count': result.get('prompt_eval_count'),
                            'eval_count': result.get('eval_count'),
                            'eval_duration': result.get('eval_duration')
                        }

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to Ollama server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'task_id': task.id, 'base_url': self.base_url}
                )

    async def _chat(self, task: Task) -> Dict[str, Any]:
        """Chat completion with conversation history"""
        messages = task.params['messages']
        model = task.params.get('model', self.default_model)
        options = task.params.get('options', self.default_options)
        template = task.params.get('template')
        stream = task.params.get('stream', False)

        timeout = task.timeout or self.timeout

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

        # Build request
        request_data = {
            'model': model,
            'messages': messages,
            'options': options,
            'stream': stream
        }

        if template:
            request_data['template'] = template

        # Make request
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=request_data,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"Ollama API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'task_id': task.id, 'status': response.status}
                        )

                    if stream:
                        # Collect streamed responses
                        full_response = ""
                        async for line in response.content:
                            if line:
                                data = json.loads(line)
                                if 'message' in data and 'content' in data['message']:
                                    full_response += data['message']['content']
                                if data.get('done'):
                                    return {
                                        'message': {
                                            'role': 'assistant',
                                            'content': full_response
                                        },
                                        'model': model,
                                        'created_at': data.get('created_at'),
                                        'total_duration': data.get('total_duration'),
                                        'load_duration': data.get('load_duration'),
                                        'prompt_eval_count': data.get('prompt_eval_count'),
                                        'eval_count': data.get('eval_count'),
                                        'eval_duration': data.get('eval_duration')
                                    }
                    else:
                        # Non-streaming response
                        result = await response.json()
                        return {
                            'message': result.get('message'),
                            'model': model,
                            'created_at': result.get('created_at'),
                            'total_duration': result.get('total_duration'),
                            'load_duration': result.get('load_duration'),
                            'prompt_eval_count': result.get('prompt_eval_count'),
                            'eval_count': result.get('eval_count'),
                            'eval_duration': result.get('eval_duration')
                        }

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to Ollama server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'task_id': task.id, 'base_url': self.base_url}
                )

    async def _embeddings(self, task: Task) -> Dict[str, Any]:
        """Generate embeddings for text"""
        prompt = task.params['prompt']
        model = task.params['model']
        options = task.params.get('options', {})

        timeout = task.timeout or self.timeout

        # Build request
        request_data = {
            'model': model,
            'prompt': prompt,
            'options': options
        }

        # Make request
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/api/embeddings",
                    json=request_data,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"Ollama API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'task_id': task.id, 'status': response.status}
                        )

                    result = await response.json()
                    return {
                        'embedding': result.get('embedding'),
                        'model': model
                    }

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to Ollama server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'task_id': task.id, 'base_url': self.base_url}
                )

    async def _list_models(self, task: Task) -> List[Dict[str, Any]]:
        """List available models"""
        timeout = task.timeout or self.timeout

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"Ollama API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'task_id': task.id, 'status': response.status}
                        )

                    result = await response.json()
                    return result.get('models', [])

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to Ollama server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'task_id': task.id, 'base_url': self.base_url}
                )

    async def _pull_model(self, task: Task) -> Dict[str, Any]:
        """Pull a model from Ollama registry"""
        model = task.params['model']
        stream = task.params.get('stream', False)

        timeout = task.timeout or self.timeout

        # Build request
        request_data = {
            'name': model,
            'stream': stream
        }

        # Make request
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/api/pull",
                    json=request_data,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise GleitzeitError(
                            f"Ollama API error (status {response.status}): {error_text}",
                            code=ErrorCode.PROVIDER_ERROR,
                            data={'task_id': task.id, 'status': response.status}
                        )

                    if stream:
                        # Collect progress updates
                        status_updates = []
                        async for line in response.content:
                            if line:
                                data = json.loads(line)
                                status_updates.append({
                                    'status': data.get('status'),
                                    'digest': data.get('digest'),
                                    'total': data.get('total'),
                                    'completed': data.get('completed')
                                })
                                if data.get('status') == 'success':
                                    return {
                                        'model': model,
                                        'status': 'success',
                                        'updates': status_updates
                                    }
                    else:
                        result = await response.json()
                        return {
                            'model': model,
                            'status': result.get('status', 'success')
                        }

            except aiohttp.ClientError as e:
                raise GleitzeitError(
                    f"Failed to connect to Ollama server: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    data={'task_id': task.id, 'base_url': self.base_url}
                )