# HTTP/External API Handler Design for Gleitzeit 0.0.7

## Overview

Design for a production-ready HTTP handler that integrates seamlessly with Gleitzeit's architecture while providing robust external API capabilities.

## Design Principles

1. **Stateless Execution** - No persistent connections
2. **Retry-Aware** - Works with Gleitzeit's retry system
3. **Observable** - Full request/response logging
4. **Secure** - Credentials management, rate limiting
5. **Flexible** - Supports REST, GraphQL, webhooks
6. **Testable** - Can mock external services

## Architecture

### Handler Implementation

```python
# src/gleitzeit/handlers/http.py

from typing import Dict, Any, Optional, List
import aiohttp
import asyncio
from dataclasses import dataclass
from enum import Enum

from .base import BaseHandler
from ..core.retry import RetryConfig, RetryManager


class HttpMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"


@dataclass
class HttpConfig:
    """HTTP request configuration"""
    url: str
    method: HttpMethod = HttpMethod.GET
    headers: Dict[str, str] = None
    params: Dict[str, Any] = None  # Query parameters
    json: Any = None                # JSON body
    data: Any = None                # Form data
    timeout: float = 30.0

    # Authentication
    auth_type: str = None  # "bearer", "basic", "api_key", "oauth2"
    auth_config: Dict = None

    # Advanced
    follow_redirects: bool = True
    verify_ssl: bool = True

    # Rate limiting
    rate_limit: Optional[int] = None  # requests per second
    rate_limit_key: Optional[str] = None  # for per-endpoint limits

    # Circuit breaker
    circuit_breaker: bool = True
    error_threshold: int = 5
    timeout_window: int = 60

    # Response handling
    expected_status: List[int] = None  # [200, 201]
    response_type: str = "json"  # "json", "text", "binary"
    extract_path: str = None  # JSONPath for extraction


class HttpHandler(BaseHandler):
    """
    HTTP/REST API handler for external service calls.

    Features:
    - Multiple auth methods
    - Rate limiting
    - Circuit breaker
    - Response validation
    - Automatic retries
    """

    protocol = "http/v1"

    def __init__(self):
        super().__init__()
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiters: Dict[str, asyncio.Semaphore] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

    async def initialize(self):
        """Initialize HTTP session"""
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

    async def execute(
        self,
        task_id: str,
        task_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute HTTP request"""

        # Parse configuration
        config = self._parse_config(params, context)

        # Check circuit breaker
        if config.circuit_breaker:
            breaker = self._get_circuit_breaker(config.url)
            if not await breaker.can_execute():
                raise Exception(f"Circuit breaker open for {config.url}")

        # Apply rate limiting
        if config.rate_limit:
            await self._apply_rate_limit(config)

        # Build request
        request_kwargs = self._build_request(config)

        # Add authentication
        if config.auth_type:
            await self._add_auth(request_kwargs, config)

        # Execute request
        try:
            async with self._session.request(
                config.method.value,
                config.url,
                **request_kwargs
            ) as response:

                # Validate response
                if config.expected_status:
                    if response.status not in config.expected_status:
                        raise Exception(
                            f"Unexpected status {response.status}, "
                            f"expected {config.expected_status}"
                        )

                # Parse response
                result = await self._parse_response(response, config)

                # Record success
                if config.circuit_breaker:
                    await breaker.record_success()

                return {
                    "status": response.status,
                    "headers": dict(response.headers),
                    "data": result,
                    "url": str(response.url)
                }

        except asyncio.TimeoutError:
            if config.circuit_breaker:
                await breaker.record_failure()
            raise Exception(f"Request timeout after {config.timeout}s")

        except Exception as e:
            if config.circuit_breaker:
                await breaker.record_failure()
            raise

    def can_handle(self, task_type: str, protocol: str) -> bool:
        """Check if we can handle this task"""
        return protocol == self.protocol

    async def cleanup(self):
        """Cleanup resources"""
        if self._session:
            await self._session.close()
```

### Circuit Breaker Implementation

```python
# src/gleitzeit/handlers/http_circuit_breaker.py

class CircuitBreakerState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker for HTTP endpoints"""

    def __init__(self, error_threshold=5, timeout_window=60, recovery_timeout=30):
        self.error_threshold = error_threshold
        self.timeout_window = timeout_window
        self.recovery_timeout = recovery_timeout

        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.last_success_time = None

    async def can_execute(self) -> bool:
        """Check if request can proceed"""

        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            # Check if we should try half-open
            if self._should_attempt_reset():
                self.state = CircuitBreakerState.HALF_OPEN
                return True
            return False

        if self.state == CircuitBreakerState.HALF_OPEN:
            return True  # Allow one request to test

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to retry"""
        if not self.last_failure_time:
            return True

        elapsed = time.time() - self.last_failure_time
        return elapsed >= self.recovery_timeout
```

## Usage Examples

### Basic GET Request

```yaml
workflow:
  tasks:
    - name: fetch_user
      protocol: http/v1
      method: http/get
      params:
        url: https://api.example.com/users/123
        headers:
          Accept: application/json
        expected_status: [200]
        response_type: json
```

### POST with Authentication

```yaml
workflow:
  tasks:
    - name: create_order
      protocol: http/v1
      method: http/post
      params:
        url: https://api.shop.com/orders
        auth_type: bearer
        auth_config:
          token: "${env.API_TOKEN}"
        json:
          customer_id: "${customer.id}"
          items: "${cart.items}"
          total: "${cart.total}"
        expected_status: [201]
        extract_path: "$.order_id"
```

### GraphQL Query

```yaml
workflow:
  tasks:
    - name: graphql_query
      protocol: http/v1
      method: http/post
      params:
        url: https://api.example.com/graphql
        headers:
          Content-Type: application/json
        json:
          query: |
            query GetUser($id: ID!) {
              user(id: $id) {
                name
                email
                orders {
                  id
                  total
                }
              }
            }
          variables:
            id: "${user_id}"
        extract_path: "$.data.user"
```

### Rate Limited API

```yaml
workflow:
  tasks:
    - name: geocode_address
      protocol: http/v1
      method: http/get
      params:
        url: https://maps.api.com/geocode
        params:
          address: "${address}"
          key: "${env.MAPS_API_KEY}"
        rate_limit: 10  # 10 requests per second
        rate_limit_key: "maps_api"
        circuit_breaker: true
        error_threshold: 5
        retry:
          max_attempts: 3
          strategy: exponential
          base_delay: 1.0
```

## Security Features

### 1. Credential Management

```python
class SecureCredentialStore:
    """Secure storage for API credentials"""

    async def get_credential(self, key: str) -> str:
        """Get credential from secure store"""
        # Options:
        # 1. Environment variables
        # 2. HashiCorp Vault
        # 3. AWS Secrets Manager
        # 4. Redis encrypted keys

        # For now, use environment with fallback to Redis
        value = os.getenv(key)
        if not value:
            value = await self.redis.hget("credentials", key)
            if value:
                # Decrypt if encrypted
                value = self._decrypt(value)

        return value
```

### 2. Request Signing

```python
class RequestSigner:
    """Sign requests for APIs requiring it"""

    def sign_aws_request(self, request: Dict) -> Dict:
        """AWS Signature Version 4"""
        pass

    def sign_hmac_request(self, request: Dict, secret: str) -> Dict:
        """HMAC-SHA256 signing"""
        pass

    def sign_oauth1_request(self, request: Dict, credentials: Dict) -> Dict:
        """OAuth 1.0a signing"""
        pass
```

## Observability

### Request/Response Logging

```python
async def log_request(self, config: HttpConfig, request_id: str):
    """Log outgoing request"""
    await self.event_store.store_event(
        event_type="HTTP_REQUEST",
        workflow_id=self.workflow_id,
        task_id=self.task_id,
        data={
            "request_id": request_id,
            "url": config.url,
            "method": config.method.value,
            "headers": self._sanitize_headers(config.headers),
            "timestamp": datetime.utcnow().isoformat()
        }
    )

async def log_response(self, response: aiohttp.ClientResponse, request_id: str):
    """Log response"""
    await self.event_store.store_event(
        event_type="HTTP_RESPONSE",
        workflow_id=self.workflow_id,
        task_id=self.task_id,
        data={
            "request_id": request_id,
            "status": response.status,
            "headers": dict(response.headers),
            "latency_ms": response.elapsed.total_seconds() * 1000,
            "timestamp": datetime.utcnow().isoformat()
        }
    )
```

### Metrics

```python
class HttpMetrics:
    """Track HTTP handler metrics"""

    def record_request(self, endpoint: str, method: str):
        self.requests_total.inc(endpoint=endpoint, method=method)

    def record_response(self, endpoint: str, status: int, latency: float):
        self.response_latency.observe(latency, endpoint=endpoint)
        self.response_status.inc(endpoint=endpoint, status=status)

    def record_error(self, endpoint: str, error_type: str):
        self.errors_total.inc(endpoint=endpoint, error=error_type)
```

## Testing Support

### Mock HTTP Server

```python
class MockHttpServer:
    """Mock server for testing"""

    def __init__(self):
        self.responses = {}
        self.request_history = []

    def add_response(self, method: str, url: str, response: Dict):
        """Configure mock response"""
        key = f"{method}:{url}"
        self.responses[key] = response

    async def handle_request(self, method: str, url: str, **kwargs):
        """Handle mock request"""
        self.request_history.append({
            "method": method,
            "url": url,
            "kwargs": kwargs,
            "timestamp": time.time()
        })

        key = f"{method}:{url}"
        if key in self.responses:
            return self.responses[key]

        return {"status": 404, "body": "Not found"}
```

### Test Configuration

```yaml
# Test workflow with mocked HTTP
workflow:
  test_mode: true
  mocks:
    http:
      - method: GET
        url: https://api.example.com/user/123
        response:
          status: 200
          body:
            id: 123
            name: "Test User"
            email: "test@example.com"

  tasks:
    - name: fetch_user
      protocol: http/v1
      method: http/get
      params:
        url: https://api.example.com/user/123
```

## Error Handling

### Retry Strategy

```python
def get_retry_config(self, params: Dict) -> RetryConfig:
    """Get retry configuration for HTTP requests"""

    # Default retry config for HTTP
    default = RetryConfig(
        max_retries=3,
        strategy=BackoffStrategy.EXPONENTIAL,
        base_delay=1.0,
        max_delay=30.0,
        multiplier=2.0,
        jitter=0.1,
        retryable_exceptions=[
            aiohttp.ClientError,
            asyncio.TimeoutError
        ],
        retryable_status_codes=[
            429,  # Too Many Requests
            502,  # Bad Gateway
            503,  # Service Unavailable
            504   # Gateway Timeout
        ]
    )

    # Override with task-specific config
    if "retry" in params:
        default.update(params["retry"])

    return default
```

### Error Response Handling

```python
async def handle_error_response(self, response: aiohttp.ClientResponse):
    """Extract error details from response"""

    content_type = response.headers.get("Content-Type", "")

    if "application/json" in content_type:
        try:
            error_data = await response.json()

            # Common error formats
            error_message = (
                error_data.get("error") or
                error_data.get("message") or
                error_data.get("error_description") or
                str(error_data)
            )
        except:
            error_message = await response.text()
    else:
        error_message = await response.text()

    raise HttpError(
        status=response.status,
        message=error_message,
        url=str(response.url),
        headers=dict(response.headers)
    )
```

## Integration Points

### 1. With Validation Handler

```yaml
# Validate API response
tasks:
  - name: fetch_price
    protocol: http/v1
    params:
      url: https://api.pricing.com/quote

  - name: validate_price
    protocol: validation/v1
    dependencies: [fetch_price]
    params:
      conditions:
        - expression: "data.price > 0"
        - expression: "data.currency in ['USD', 'EUR']"
      context:
        data: "${fetch_price.data}"
```

### 2. With Timer Handler

```yaml
# Polling pattern
tasks:
  - name: check_status
    protocol: http/v1
    params:
      url: https://api.example.com/job/status

  - name: wait_if_pending
    protocol: timer/v1
    dependencies: [check_status]
    when: "${check_status.data.status == 'pending'}"
    params:
      delay: 10

  - name: check_again
    protocol: http/v1
    dependencies: [wait_if_pending]
    params:
      url: https://api.example.com/job/status
```

### 3. With Signal Handler

```yaml
# Webhook callback pattern
tasks:
  - name: start_async_job
    protocol: http/v1
    params:
      method: POST
      url: https://api.example.com/job/start
      json:
        callback_url: "${workflow.callback_url}"

  - name: wait_for_callback
    protocol: signal/v1
    dependencies: [start_async_job]
    params:
      signal: "job_complete_${start_async_job.data.job_id}"
      timeout: 3600
```

## Performance Considerations

### Connection Pooling

```python
class ConnectionPoolManager:
    """Manage connection pools per domain"""

    def __init__(self):
        self.pools = {}

    def get_connector(self, url: str) -> aiohttp.TCPConnector:
        """Get or create connector for domain"""
        domain = urlparse(url).netloc

        if domain not in self.pools:
            self.pools[domain] = aiohttp.TCPConnector(
                limit_per_host=30,
                keepalive_timeout=30,
                enable_cleanup_closed=True
            )

        return self.pools[domain]
```

### Response Streaming

```python
async def stream_large_response(self, response: aiohttp.ClientResponse):
    """Stream large responses to avoid memory issues"""

    chunk_size = 8192
    chunks = []

    async for chunk in response.content.iter_chunked(chunk_size):
        chunks.append(chunk)

        # If too large, write to temp file
        if len(chunks) * chunk_size > 10 * 1024 * 1024:  # 10MB
            return await self._save_to_temp_file(chunks)

    return b"".join(chunks)
```

## Conclusion

This HTTP handler design provides:

1. **Flexibility** - Supports various HTTP patterns
2. **Reliability** - Circuit breakers, retries, rate limiting
3. **Security** - Credential management, request signing
4. **Observability** - Full logging and metrics
5. **Integration** - Works seamlessly with other handlers
6. **Testing** - Built-in mocking support

The design follows Gleitzeit principles:
- Stateless execution
- Works with retry/recovery system
- Event-driven with full audit trail
- Simple YAML configuration
- Extensible for custom needs