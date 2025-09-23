# Gleitzeit 0.0.7 API Server Implementation Plan
## Based on 0.0.6 Architecture Analysis

## Executive Summary

Gleitzeit 0.0.6 had a complete FastAPI-based API server with authentication, client pooling, and WebSocket support. Version 0.0.7 currently has no API server - only workers and CLI. This plan reimplements the API server adapted for 0.0.7's worker-based architecture.

## Current Gap Analysis

### What 0.0.6 Had:
- ✅ FastAPI server with 15+ route modules
- ✅ JWT/Session-based authentication
- ✅ Client connection pooling
- ✅ WebSocket real-time events
- ✅ Complete Python client SDK
- ✅ Auto-login for development
- ✅ Provider pooling system

### What 0.0.7 Currently Has:
- ✅ Worker-based processing
- ✅ Redis stream orchestration
- ✅ CLI management tools
- ❌ **No API server**
- ❌ **No authentication**
- ❌ **No client SDK**
- ❌ **No connection pooling**

## Implementation Plan

### Phase 1: Core API Server (Week 1-2)

#### 1.1 FastAPI Application Structure
```python
# src/gleitzeit/api/main.py

from fastapi import FastAPI
from contextlib import asynccontextmanager
import redis.asyncio as aioredis

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.redis = await aioredis.from_url("redis://localhost:6379")
    app.state.client_pool = ClientPool()
    await app.state.client_pool.initialize()

    yield

    # Shutdown
    await app.state.redis.close()
    await app.state.client_pool.shutdown()

app = FastAPI(
    title="Gleitzeit API",
    version="0.0.7",
    lifespan=lifespan
)
```

#### 1.2 Core Routes
```python
# src/gleitzeit/api/routes/

# workflows.py
@router.post("/workflows")
async def submit_workflow(workflow: WorkflowRequest, auth: User = Depends(get_current_user)):
    # Submit to Redis stream for workflow_loader_worker

@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    # Query Redis for workflow state

# tasks.py
@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    # Query Redis for task state

# system.py
@router.get("/health")
async def health_check():
    # Check Redis, workers, orchestrator

@router.get("/metrics")
async def get_metrics():
    # Aggregate metrics from Redis
```

#### 1.3 Server Runner
```python
# src/gleitzeit/api/run_server.py

import uvicorn

def run_server(host="0.0.0.0", port=8000, reload=False):
    uvicorn.run(
        "gleitzeit.api.main:app",
        host=host,
        port=port,
        reload=reload,
        access_log=True
    )
```

### Phase 2: Authentication System (Week 3-4)

#### 2.1 Auth Dependencies
```python
# src/gleitzeit/api/auth/dependencies.py

from fastapi import Depends, HTTPException, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session_id: Optional[str] = Cookie(None),
    redis: aioredis.Redis = Depends(get_redis)
) -> User:
    # Try JWT token first
    if credentials:
        user = await validate_jwt(credentials.credentials, redis)
        if user:
            return user

    # Try session cookie
    if session_id:
        user = await get_session_user(session_id, redis)
        if user:
            return user

    # Auto-create basic user for development
    if settings.AUTO_LOGIN_ENABLED:
        return await create_basic_user(redis)

    raise HTTPException(status_code=401, detail="Not authenticated")
```

#### 2.2 JWT Management
```python
# src/gleitzeit/api/auth/jwt.py

import jwt
from datetime import datetime, timedelta

class JWTManager:
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm

    def create_token(self, user_id: str, expiry_hours: int = 24) -> str:
        payload = {
            "user_id": user_id,
            "exp": datetime.utcnow() + timedelta(hours=expiry_hours),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.secret_key, self.algorithm)

    def verify_token(self, token: str) -> Optional[Dict]:
        try:
            return jwt.decode(token, self.secret_key, [self.algorithm])
        except jwt.InvalidTokenError:
            return None
```

#### 2.3 Session Management
```python
# src/gleitzeit/api/auth/sessions.py

class SessionManager:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.session_ttl = 86400  # 24 hours

    async def create_session(self, user: User) -> str:
        session_id = str(uuid.uuid4())
        key = f"session:{session_id}"

        await self.redis.hset(key, mapping={
            "user_id": user.id,
            "username": user.username,
            "created_at": datetime.utcnow().isoformat()
        })
        await self.redis.expire(key, self.session_ttl)

        return session_id

    async def get_session(self, session_id: str) -> Optional[User]:
        key = f"session:{session_id}"
        data = await self.redis.hgetall(key)

        if data:
            # Refresh TTL on access
            await self.redis.expire(key, self.session_ttl)
            return User(**data)

        return None
```

### Phase 3: Client Connection Pooling (Week 5-6)

#### 3.1 Shared Client Pool
```python
# src/gleitzeit/api/pools/client_pool.py

class ClientPool:
    """Pool for API client connections"""

    def __init__(self, max_clients_per_user: int = 10):
        self.max_clients_per_user = max_clients_per_user
        self.pools: Dict[str, UserPool] = {}
        self.lock = asyncio.Lock()

    async def get_pool(self, user_id: str) -> UserPool:
        if user_id not in self.pools:
            async with self.lock:
                if user_id not in self.pools:
                    self.pools[user_id] = UserPool(
                        user_id=user_id,
                        max_connections=self.max_clients_per_user
                    )

        return self.pools[user_id]

    async def cleanup_idle(self):
        """Clean up idle connections periodically"""
        for user_id, pool in list(self.pools.items()):
            if await pool.is_idle():
                await pool.shutdown()
                del self.pools[user_id]
```

#### 3.2 User Connection Pool
```python
# src/gleitzeit/api/pools/user_pool.py

class UserPool:
    """Per-user connection pool"""

    def __init__(self, user_id: str, max_connections: int):
        self.user_id = user_id
        self.max_connections = max_connections
        self.connections: List[ClientConnection] = []
        self.available: asyncio.Queue = asyncio.Queue()
        self.last_used = time.time()

    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool"""
        # Try to get available connection
        try:
            conn = await asyncio.wait_for(self.available.get(), timeout=1.0)
            if await conn.is_healthy():
                yield conn
                return
        except asyncio.TimeoutError:
            pass

        # Create new connection if under limit
        if len(self.connections) < self.max_connections:
            conn = await self.create_connection()
            self.connections.append(conn)
            yield conn
        else:
            # Wait for connection to become available
            conn = await self.available.get()
            yield conn

        # Return to pool
        await self.available.put(conn)
        self.last_used = time.time()
```

### Phase 4: Client SDK (Week 7-8)

#### 4.1 Gleitzeit Client
```python
# src/gleitzeit/client/client.py

class GleitzeitClient:
    """Client for Gleitzeit API"""

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        auto_start_server: bool = True
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None

        if auto_start_server:
            self._ensure_server_running()

    async def submit_workflow(self, workflow: Dict) -> WorkflowResponse:
        """Submit a workflow for execution"""
        async with self._request("POST", "/workflows", json=workflow) as resp:
            return WorkflowResponse(**await resp.json())

    async def get_task(self, task_id: str) -> TaskResponse:
        """Get task status and result"""
        async with self._request("GET", f"/tasks/{task_id}") as resp:
            return TaskResponse(**await resp.json())

    async def stream_events(self, workflow_id: str):
        """Stream real-time events via WebSocket"""
        ws_url = self.api_url.replace("http", "ws") + f"/ws/{workflow_id}"

        async with websockets.connect(ws_url) as ws:
            self.ws = ws
            async for message in ws:
                event = json.loads(message)
                yield Event(**event)

    # Synchronous wrappers for notebooks
    def submit_workflow_sync(self, workflow: Dict) -> WorkflowResponse:
        """Sync wrapper for submit_workflow"""
        return asyncio.run(self.submit_workflow(workflow))

    def wait_for_completion(self, workflow_id: str, timeout: int = 300):
        """Wait for workflow to complete"""
        start = time.time()

        while time.time() - start < timeout:
            status = self.get_workflow_sync(workflow_id)
            if status.state in ["completed", "failed"]:
                return status
            time.sleep(1)

        raise TimeoutError(f"Workflow {workflow_id} did not complete")
```

#### 4.2 Connection Pooling in Client
```python
# src/gleitzeit/client/pooled_client.py

class PooledGleitzeitClient(GleitzeitClient):
    """Client with connection pooling"""

    def __init__(self, *args, pool_size: int = 5, **kwargs):
        super().__init__(*args, **kwargs)
        self.pool_size = pool_size
        self.pool: List[aiohttp.ClientSession] = []
        self.available: asyncio.Queue = asyncio.Queue()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get session from pool"""
        try:
            return await asyncio.wait_for(self.available.get(), timeout=0.1)
        except asyncio.TimeoutError:
            if len(self.pool) < self.pool_size:
                session = aiohttp.ClientSession()
                self.pool.append(session)
                return session
            else:
                # Wait for available session
                return await self.available.get()

    async def _return_session(self, session: aiohttp.ClientSession):
        """Return session to pool"""
        await self.available.put(session)
```

### Phase 5: WebSocket & Real-time (Week 9-10)

#### 5.1 WebSocket Manager
```python
# src/gleitzeit/api/websocket/manager.py

class WebSocketManager:
    """Manage WebSocket connections"""

    def __init__(self):
        self.connections: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, workflow_id: str, websocket: WebSocket):
        """Register new connection"""
        await websocket.accept()

        async with self.lock:
            if workflow_id not in self.connections:
                self.connections[workflow_id] = set()
            self.connections[workflow_id].add(websocket)

    async def disconnect(self, workflow_id: str, websocket: WebSocket):
        """Remove connection"""
        async with self.lock:
            if workflow_id in self.connections:
                self.connections[workflow_id].discard(websocket)
                if not self.connections[workflow_id]:
                    del self.connections[workflow_id]

    async def broadcast(self, workflow_id: str, message: Dict):
        """Broadcast to all connections for workflow"""
        if workflow_id in self.connections:
            dead_connections = set()

            for websocket in self.connections[workflow_id]:
                try:
                    await websocket.send_json(message)
                except:
                    dead_connections.add(websocket)

            # Clean up dead connections
            for websocket in dead_connections:
                await self.disconnect(workflow_id, websocket)
```

#### 5.2 Event Streaming
```python
# src/gleitzeit/api/routes/websocket.py

@app.websocket("/ws/{workflow_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    workflow_id: str,
    manager: WebSocketManager = Depends(get_ws_manager)
):
    await manager.connect(workflow_id, websocket)

    try:
        # Subscribe to Redis events for this workflow
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"workflow:{workflow_id}:events")

        # Stream events to client
        async for message in pubsub.listen():
            if message['type'] == 'message':
                event = json.loads(message['data'])
                await websocket.send_json(event)

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(workflow_id, websocket)
        await pubsub.unsubscribe()
```

## Configuration

### API Server Config
```yaml
# config/api.yaml

server:
  host: 0.0.0.0
  port: 8000
  workers: 4
  reload: false

auth:
  jwt_secret: ${JWT_SECRET}
  jwt_algorithm: HS256
  token_expiry_hours: 24
  session_ttl: 86400
  auto_login_enabled: true  # For development

pooling:
  max_clients_per_user: 10
  idle_timeout: 300
  cleanup_interval: 60

redis:
  url: redis://localhost:6379
  decode_responses: false

cors:
  allow_origins: ["*"]
  allow_methods: ["*"]
  allow_headers: ["*"]
```

## Testing Strategy

### Unit Tests
```python
# tests/api/test_auth.py
- JWT creation and validation
- Session management
- Permission checking

# tests/api/test_pooling.py
- Connection pool limits
- Cleanup of idle connections
- Concurrent access

# tests/api/test_routes.py
- Workflow submission
- Task retrieval
- Error handling
```

### Integration Tests
```python
# tests/integration/test_api_server.py
- Full API server startup
- End-to-end workflow submission
- WebSocket event streaming
- Client SDK operations
```

### Load Tests
```python
# tests/performance/test_api_load.py
- Concurrent client connections
- Pool exhaustion handling
- WebSocket scaling
- Authentication overhead
```

## Migration Path

### Week 1-2: Basic API
- FastAPI setup
- Core routes
- Redis integration

### Week 3-4: Authentication
- JWT/Session auth
- User management
- Permission system

### Week 5-6: Pooling
- Client connection pools
- Resource management
- Cleanup tasks

### Week 7-8: Client SDK
- Python client
- Connection pooling
- Sync/async methods

### Week 9-10: Real-time
- WebSocket support
- Event streaming
- Progress tracking

## Success Metrics

- **API Response Time**: <100ms p95
- **Authentication Speed**: <10ms
- **Pool Hit Rate**: >90%
- **WebSocket Latency**: <50ms
- **Client SDK Coverage**: 100% of API endpoints

## Dependencies to Add

```python
# setup.py additions
install_requires=[
    "fastapi>=0.100.0",
    "uvicorn[standard]>=0.23.0",
    "python-multipart>=0.0.6",
    "pyjwt>=2.8.0",
    "websockets>=11.0",
    "aiohttp>=3.8.0",
    ...existing...
]
```

## Risk Mitigation

1. **Connection Exhaustion**: Implement per-user limits
2. **Auth Token Leaks**: Use short-lived tokens with refresh
3. **WebSocket Scaling**: Use Redis pub/sub for distribution
4. **Pool Starvation**: Queue with timeouts and monitoring

## Conclusion

This plan recreates Gleitzeit 0.0.6's sophisticated API infrastructure adapted for 0.0.7's worker architecture. The API server acts as a gateway, submitting work to Redis streams for workers to process while providing real-time feedback to clients.