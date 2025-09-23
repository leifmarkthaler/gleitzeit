"""
HTTP/External API Handler for Gleitzeit 0.0.7

Provides HTTP client capabilities for external API integration.
"""

import asyncio
import aiohttp
import json
import time
import logging
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

logger = logging.getLogger(__name__)


class HttpMethod(str, Enum):
    """HTTP methods"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"


@HandlerRegistry.register
class HttpHandler(BaseHandler):
    """
    HTTP/REST API handler for external service calls.

    Features:
    - Multiple HTTP methods
    - JSON/form data support
    - Authentication (bearer, basic, api_key)
    - Response validation
    - Automatic retries via Gleitzeit retry system
    """

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiters: Dict[str, asyncio.Semaphore] = {}

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Return handler capabilities"""
        return {
            'protocol': 'http/v1',
            'task_types': ['http', 'rest', 'api'],  # backward compatibility
            'methods': {
                'http/get': {
                    'description': 'HTTP GET request',
                    'required': ['url'],
                    'optional': ['headers', 'params', 'timeout', 'auth']
                },
                'http/post': {
                    'description': 'HTTP POST request',
                    'required': ['url'],
                    'optional': ['headers', 'json', 'data', 'timeout', 'auth']
                },
                'http/put': {
                    'description': 'HTTP PUT request',
                    'required': ['url'],
                    'optional': ['headers', 'json', 'data', 'timeout', 'auth']
                },
                'http/delete': {
                    'description': 'HTTP DELETE request',
                    'required': ['url'],
                    'optional': ['headers', 'params', 'timeout', 'auth']
                },
                'http/patch': {
                    'description': 'HTTP PATCH request',
                    'required': ['url'],
                    'optional': ['headers', 'json', 'data', 'timeout', 'auth']
                }
            }
        }

    async def initialize_session(self):
        """Initialize HTTP session if not exists"""
        if not self._session:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300
            )

            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=60)
            )
            logger.info("HTTP session initialized")

    async def execute(self, task: Task) -> TaskResult:
        """Execute HTTP request"""
        start_time = asyncio.get_event_loop().time()

        try:
            # Record metrics if available
            if self.metrics:
                metric_start = await self.metrics.record_task_start()

            # Validate task
            await self.validate(task)

            # Initialize session if needed
            await self.initialize_session()

            # Extract method from task.method
            http_method = task.method.split('/')[-1].upper()

            # Build request from task params
            request_kwargs = await self._build_request(task, http_method)

            # Apply rate limiting if configured
            await self._apply_rate_limit(task)

            # Execute request
            async with self._session.request(
                http_method,
                task.params['url'],
                **request_kwargs
            ) as response:

                # Validate response if configured
                await self._validate_response(response, task)

                # Parse response
                result = await self._parse_response(response, task)

                # Record success metrics
                if self.metrics:
                    await self.metrics.record_task_end(metric_start, success=True)

                return self.create_result(
                    task=task,
                    status=TaskStatus.COMPLETED,
                    result=result,
                    metadata={
                        'status_code': response.status,
                        'headers': dict(response.headers),
                        'url': str(response.url)
                    },
                    duration_seconds=asyncio.get_event_loop().time() - start_time
                )

        except asyncio.TimeoutError:
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False)

            timeout = task.params.get('timeout', 30)
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=f"HTTP request timed out after {timeout}s",
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except aiohttp.ClientError as e:
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=f"HTTP client error: {str(e)}",
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

            logger.error(f"HTTP request failed: {e}", exc_info=True)

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=f"Unexpected error: {str(e)}",
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

    async def _build_request(self, task: Task, method: str) -> Dict[str, Any]:
        """Build request kwargs from task params"""
        params = task.params
        kwargs = {}

        # Headers
        if 'headers' in params:
            kwargs['headers'] = params['headers']

        # Query parameters (for GET)
        if 'params' in params:
            kwargs['params'] = params['params']

        # JSON body
        if 'json' in params:
            kwargs['json'] = params['json']
            if 'headers' not in kwargs:
                kwargs['headers'] = {}
            kwargs['headers']['Content-Type'] = 'application/json'

        # Form data
        elif 'data' in params:
            kwargs['data'] = params['data']

        # Timeout
        timeout = params.get('timeout', 30)
        kwargs['timeout'] = aiohttp.ClientTimeout(total=timeout)

        # Authentication
        if 'auth' in params:
            await self._add_auth(kwargs, params['auth'])

        # SSL verification
        kwargs['ssl'] = params.get('verify_ssl', True)

        return kwargs

    async def _add_auth(self, kwargs: Dict, auth_config: Dict):
        """Add authentication to request"""
        auth_type = auth_config.get('type', 'bearer')

        if 'headers' not in kwargs:
            kwargs['headers'] = {}

        if auth_type == 'bearer':
            token = auth_config.get('token')
            if not token:
                raise GleitzeitError(
                    "Bearer token not provided",
                    code=ErrorCode.INVALID_CONFIGURATION,
                    data={'auth_type': 'bearer'}
                )
            kwargs['headers']['Authorization'] = f"Bearer {token}"

        elif auth_type == 'basic':
            username = auth_config.get('username')
            password = auth_config.get('password')
            if not username or not password:
                raise GleitzeitError(
                    "Username or password not provided",
                    code=ErrorCode.INVALID_CONFIGURATION,
                    data={'auth_type': 'basic'}
                )
            auth = aiohttp.BasicAuth(username, password)
            kwargs['auth'] = auth

        elif auth_type == 'api_key':
            key = auth_config.get('key')
            header_name = auth_config.get('header_name', 'X-API-Key')
            if not key:
                raise GleitzeitError(
                    "API key not provided",
                    code=ErrorCode.INVALID_CONFIGURATION,
                    data={'auth_type': 'api_key'}
                )
            kwargs['headers'][header_name] = key

        else:
            raise GleitzeitError(
                f"Unsupported auth type: {auth_type}",
                code=ErrorCode.INVALID_CONFIGURATION,
                data={'auth_type': auth_type}
            )

    async def _apply_rate_limit(self, task: Task):
        """Apply rate limiting if configured"""
        params = task.params

        if 'rate_limit' not in params:
            return

        rate_limit = params['rate_limit']  # requests per second
        rate_limit_key = params.get('rate_limit_key', params['url'])

        # Get or create semaphore for this endpoint
        if rate_limit_key not in self._rate_limiters:
            self._rate_limiters[rate_limit_key] = asyncio.Semaphore(rate_limit)

        semaphore = self._rate_limiters[rate_limit_key]

        # Acquire semaphore
        async with semaphore:
            # Hold for 1/rate_limit seconds
            await asyncio.sleep(1.0 / rate_limit)

    async def _validate_response(self, response: aiohttp.ClientResponse, task: Task):
        """Validate response against expected criteria"""
        params = task.params

        # Check expected status codes
        if 'expected_status' in params:
            expected = params['expected_status']
            if not isinstance(expected, list):
                expected = [expected]

            if response.status not in expected:
                content = await response.text()
                raise GleitzeitError(
                    f"Unexpected status code: {response.status}",
                    code=ErrorCode.PROVIDER_ERROR,
                    data={
                        'expected': expected,
                        'actual': response.status,
                        'response': content[:500]  # First 500 chars
                    }
                )

    async def _parse_response(self, response: aiohttp.ClientResponse, task: Task) -> Any:
        """Parse response based on configuration"""
        params = task.params
        response_type = params.get('response_type', 'auto')

        # Auto-detect based on content-type
        if response_type == 'auto':
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                response_type = 'json'
            elif 'text/' in content_type:
                response_type = 'text'
            else:
                response_type = 'binary'

        # Parse based on type
        if response_type == 'json':
            data = await response.json()

            # Extract specific path if configured
            if 'extract_path' in params:
                import jsonpath_ng
                path = jsonpath_ng.parse(params['extract_path'])
                matches = path.find(data)
                if matches:
                    return matches[0].value
                else:
                    raise GleitzeitError(
                        f"JSONPath '{params['extract_path']}' not found",
                        code=ErrorCode.VALIDATION_FAILED,
                        data={'path': params['extract_path'], 'response': data}
                    )

            return data

        elif response_type == 'text':
            return await response.text()

        elif response_type == 'binary':
            return await response.read()

        else:
            raise GleitzeitError(
                f"Unknown response type: {response_type}",
                code=ErrorCode.INVALID_CONFIGURATION,
                data={'response_type': response_type}
            )

    def create_result(
        self,
        task: Task,
        status: TaskStatus,
        result: Any = None,
        error: str = None,
        metadata: Dict = None,
        duration_seconds: float = None
    ) -> TaskResult:
        """Create a TaskResult with appropriate data"""
        return TaskResult(
            task_id=task.id,
            status=status,
            result=result,
            error=error,
            metadata=metadata or {},
            duration_seconds=duration_seconds,
            handler_id=self.handler_id,
            handler_class=self.__class__.__name__
        )

    async def cleanup(self):
        """Cleanup resources"""
        if self._session:
            await self._session.close()
            logger.info("HTTP session closed")
            self._session = None