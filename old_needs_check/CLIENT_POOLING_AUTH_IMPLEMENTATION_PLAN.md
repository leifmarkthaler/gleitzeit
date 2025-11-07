# Client Pooling and Authentication Implementation Plan
## For Gleitzeit 0.0.7 - Reimplementation from 0.0.6

## Current State Analysis

### Existing in 0.0.7:
1. **Subprocess Pool** (`subprocess_pool.py`)
   - Already implements pooling for Python processes
   - Features: warm processes, health checks, retirement policy
   - Pattern: acquire/release with context manager

2. **HTTP Handler** (`handlers/http.py`)
   - Has basic auth support (bearer, basic, api_key)
   - Uses single aiohttp session (not pooled per endpoint)
   - No connection pooling per API endpoint

### Missing from 0.0.6 Features:
1. **Client Connection Pooling**
   - Per-endpoint connection pools
   - Connection reuse and lifecycle management
   - Rate limiting per endpoint
   - Circuit breaker per endpoint

2. **Advanced Authentication**
   - Token refresh/rotation
   - OAuth2 flow support
   - Credential vault integration
   - Per-handler auth configuration

## Implementation Plan

### Phase 1: Generic Client Pool Infrastructure

#### 1.1 Base Client Pool Framework
```python
# src/gleitzeit/core/client_pool.py

class ClientPoolConfig:
    max_clients: int = 10
    min_clients: int = 2
    max_age_seconds: int = 300
    max_requests: int = 1000
    health_check_interval: int = 30

class BaseClientPool:
    """Generic client connection pool"""
    - acquire(): Get client from pool
    - release(): Return client to pool
    - health_check(): Validate client health
    - retire(): Remove unhealthy/old clients
    - metrics(): Pool statistics

class PooledClient:
    """Wrapper for pooled connections"""
    - client: Actual client instance
    - created_at: Timestamp
    - request_count: Usage counter
    - last_used: Last activity time
    - metadata: Custom client metadata
```

#### 1.2 HTTP Client Pool
```python
# src/gleitzeit/core/http_client_pool.py

class HttpClientPool(BaseClientPool):
    """HTTP/HTTPS connection pooling"""
    - Per-endpoint pools
    - Connection reuse
    - SSL session caching
    - Cookie jar per pool

class EndpointPool:
    """Pool for specific API endpoint"""
    - base_url: str
    - auth_config: Dict
    - rate_limiter: RateLimiter
    - circuit_breaker: CircuitBreaker
```

### Phase 2: Authentication System

#### 2.1 Auth Provider Interface
```python
# src/gleitzeit/auth/base.py

class AuthProvider(ABC):
    """Base authentication provider"""
    async def authenticate(self, request: Dict) -> Dict
    async def refresh(self) -> bool
    def is_expired(self) -> bool

class AuthRegistry:
    """Registry for auth providers"""
    register(name: str, provider: AuthProvider)
    get(name: str) -> AuthProvider
```

#### 2.2 Auth Implementations
```python
# src/gleitzeit/auth/providers/

# bearer.py
class BearerAuthProvider(AuthProvider):
    - Static tokens
    - Token refresh logic
    - Expiry tracking

# oauth2.py
class OAuth2Provider(AuthProvider):
    - Client credentials flow
    - Authorization code flow
    - Token refresh
    - PKCE support

# api_key.py
class ApiKeyProvider(AuthProvider):
    - Header injection
    - Query parameter
    - Custom placement

# vault.py
class VaultProvider(AuthProvider):
    - HashiCorp Vault integration
    - AWS Secrets Manager
    - Azure Key Vault
    - Automatic rotation
```

### Phase 3: Integration with Handlers

#### 3.1 Enhanced HTTP Handler
```python
# src/gleitzeit/handlers/http_v2.py

class HttpHandlerV2(BaseHandler):
    def __init__(self):
        self.client_pools: Dict[str, HttpClientPool] = {}
        self.auth_providers: Dict[str, AuthProvider] = {}

    async def execute_task(self, task: Task):
        # Get or create pool for endpoint
        pool = self.get_or_create_pool(task.endpoint)

        # Get auth provider
        auth = self.get_auth_provider(task.auth_config)

        # Acquire client from pool
        async with pool.acquire() as client:
            # Apply authentication
            await auth.authenticate(request)

            # Execute request
            response = await client.request(...)

            # Handle token refresh if needed
            if response.status == 401:
                if await auth.refresh():
                    # Retry with new token
                    response = await client.request(...)
```

#### 3.2 Database Handler with Connection Pooling
```python
# src/gleitzeit/handlers/database_v2.py

class DatabaseHandlerV2(BaseHandler):
    def __init__(self):
        self.connection_pools: Dict[str, DatabasePool] = {}

    async def execute_query(self, task: Task):
        pool = self.get_pool(task.db_config)
        async with pool.acquire() as conn:
            return await conn.execute(task.query)
```

### Phase 4: Configuration and Management

#### 4.1 Configuration Schema
```yaml
# config/handlers.yaml

handlers:
  http:
    pools:
      github_api:
        base_url: https://api.github.com
        max_clients: 20
        auth:
          type: bearer
          provider: vault
          vault_path: /secrets/github/token
        rate_limit:
          requests_per_second: 10
          burst: 20

      internal_api:
        base_url: http://internal.service
        max_clients: 50
        auth:
          type: oauth2
          client_id: ${CLIENT_ID}
          client_secret_vault: /secrets/internal/secret
          token_endpoint: http://auth.service/token

  database:
    pools:
      primary:
        connection_string_vault: /secrets/db/primary
        max_connections: 100
        min_connections: 10
```

#### 4.2 Monitoring and Metrics
```python
# src/gleitzeit/monitoring/pool_metrics.py

class PoolMetrics:
    """Collect and expose pool metrics"""
    - Active connections
    - Pool utilization
    - Request latency
    - Auth refresh rate
    - Circuit breaker state

    export_prometheus()
    export_json()
```

### Phase 5: Migration Strategy

#### 5.1 Backward Compatibility
- Keep existing handlers working
- Add feature flags for new pooling
- Gradual migration per handler type

#### 5.2 Migration Steps
1. **Week 1-2**: Implement base client pool framework
2. **Week 3-4**: Add auth provider system
3. **Week 5-6**: Integrate with HTTP handler
4. **Week 7-8**: Add database pooling
5. **Week 9-10**: Testing and optimization

### Phase 6: Testing Strategy

#### 6.1 Unit Tests
```python
# tests/test_client_pool.py
- Pool creation and teardown
- Client acquisition/release
- Health checks
- Retirement policies
- Concurrent access

# tests/test_auth_providers.py
- Token refresh
- OAuth2 flows
- Vault integration
- Expiry handling
```

#### 6.2 Integration Tests
```python
# tests/integration/test_pooled_handlers.py
- End-to-end HTTP requests
- Database transactions
- Auth token rotation
- Circuit breaker triggers
- Rate limiting
```

#### 6.3 Performance Tests
```python
# tests/performance/test_pool_performance.py
- Connection reuse benefits
- Pool size optimization
- Latency improvements
- Memory usage
```

## Benefits

1. **Performance**
   - 50-80% reduction in connection overhead
   - Improved request latency
   - Better resource utilization

2. **Reliability**
   - Circuit breaker protection
   - Automatic retry with pooled connections
   - Health check based rotation

3. **Security**
   - Centralized auth management
   - Automatic token rotation
   - Vault integration
   - No hardcoded credentials

4. **Scalability**
   - Per-endpoint pool sizing
   - Dynamic pool adjustment
   - Rate limiting per service

## Risk Mitigation

1. **Connection Leaks**
   - Implement timeout-based cleanup
   - Track connection lifecycle
   - Alert on pool exhaustion

2. **Auth Token Expiry**
   - Proactive refresh before expiry
   - Graceful fallback
   - Alert on refresh failures

3. **Pool Starvation**
   - Queue with timeout
   - Dynamic pool expansion
   - Metrics and alerting

## Success Metrics

- **Connection Reuse Rate**: >80%
- **Auth Refresh Success**: >99.9%
- **Pool Utilization**: 60-80%
- **Request Latency**: -40% reduction
- **Error Rate**: <0.1% due to connection issues

## Timeline

- **Month 1**: Core infrastructure (Phases 1-2)
- **Month 2**: Handler integration (Phase 3)
- **Month 3**: Testing and optimization (Phases 4-6)
- **Month 4**: Production rollout and monitoring