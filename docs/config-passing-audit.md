# Gleitzeit Configuration Passing Audit

## Current State: How Config Gets to Workers

### 1. Configuration Loading Flow

```
gleitzeit.yaml (file)
    ↓
ConfigurationManager (reads YAML)
    ↓
AsyncProcessManager.start_workers()
    ↓
WorkerConfig object (created per worker)
    ↓
BaseWorker.__init__(config: WorkerConfig)
    ↓
Worker accesses via self.config
```

### 2. Key Components

#### ConfigurationManager
- **Location**: `src/gleitzeit/core/config_manager.py`
- **Purpose**: Reads gleitzeit.yaml and provides unified config access
- **Usage**:
  ```python
  config_manager = ConfigurationManager('gleitzeit.yaml', {})
  config = config_manager.get_all_config()
  ```

#### WorkerConfig
- **Location**: `src/gleitzeit/workers/base.py`
- **Structure**:
  ```python
  @dataclass
  class WorkerConfig:
      worker_type: str
      worker_id: str
      consumer_group: str
      redis_url: str
      assigned_shards: List[int]
      max_concurrent: int
      batch_size: int
      block_timeout: int
      heartbeat_interval: int
      handler_configs: Optional[Dict[str, Any]] = None
      extra: Dict[str, Any] = field(default_factory=dict)
  ```

#### BaseWorker Pattern
- **Location**: `src/gleitzeit/workers/base.py`
- Workers receive `WorkerConfig` in `__init__`
- Workers access config via `self.config`
- Workers create Redis via `GleitzeitRedisCluster(redis_url=self.config.redis_url)`
- Workers do NOT load config themselves

### 3. Example: Task Execution Worker

```python
# In async_process_manager.py - worker creation
config = WorkerConfig(
    worker_type="task_execution",
    worker_id=worker_id,
    redis_url=redis_url,
    assigned_shards=[0],
    handler_configs=handler_configs,
    extra={"some": "config"}
)

# Worker receives and uses config
class TaskExecutionWorker(BaseWorker):
    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        # Access config
        extra_data = self.config.extra.get('some')
```

## Problem: API Worker Anti-Pattern

### Current Implementation (WRONG)

The API worker violates the standard worker pattern:

1. **FastAPI app loads config at module level**:
   ```python
   # In src/gleitzeit/api/main.py
   CONFIG = load_config(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'))
   ```

2. **Module-level config loading happens at import time**:
   - Before worker is created
   - Before WorkerConfig exists
   - Creates own ConfigurationManager instance

3. **Creates own Redis connection**:
   ```python
   app.state.redis = await aioredis.from_url(redis_url)
   ```
   - Bypasses GleitzeitRedisCluster
   - Not properly initialized
   - Causes pubsub subscribe to hang

### Why This is Wrong

1. **Inconsistent with other workers**: Other workers get config via WorkerConfig
2. **Hardcoded values**: Falls back to hardcoded defaults when config not available
3. **Timing issues**: Module import happens before worker injection
4. **Redis initialization**: Creates raw Redis connection instead of using BaseWorker's GleitzeitRedisCluster

## Design Plan: Proper Config Passing for API Worker

### Goal
Make API worker follow the same pattern as all other workers:
- Receive config via WorkerConfig
- Pass config to FastAPI app before uvicorn starts
- No module-level config loading
- No hardcoded values

### Solution Architecture

```
gleitzeit.yaml
    ↓
ConfigurationManager (in AsyncProcessManager)
    ↓
WorkerConfig (with API-specific config in .extra)
    ↓
APIWorker.on_initialize()
    ↓
Inject Redis + Config into FastAPI via set_worker_dependencies()
    ↓
FastAPI lifespan uses injected config
    ↓
FastAPI startup event configures CORS/middleware from injected config
```

### Implementation Steps

#### Step 1: Module-Level Injection Variables

**File**: `src/gleitzeit/api/main.py`

```python
# Module-level variables injected by APIWorker
_worker_redis = None
_worker_config = None

def set_worker_dependencies(redis_instance, config: Dict[str, Any]):
    """Called by APIWorker to inject Redis connection and config"""
    global _worker_redis, _worker_config
    _worker_redis = redis_instance
    _worker_config = config
    logger.info(f"Worker dependencies injected")
```

#### Step 2: Remove Module-Level Config Loading

**Remove**:
```python
# REMOVE THIS
CONFIG = load_config(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'))
```

**Replace all `CONFIG` references with `_worker_config`**:
```python
# OLD
redis_config = CONFIG.get('redis', {})

# NEW
redis_config = _worker_config.get('redis', {})
```

#### Step 3: Inject from API Worker

**File**: `src/gleitzeit/workers/api_worker.py`

```python
async def on_initialize(self):
    """Initialize API application"""
    from ..api.main import app, set_worker_dependencies
    from ..core.config_manager import ConfigurationManager

    # Load config from gleitzeit.yaml
    config_manager = ConfigurationManager('gleitzeit.yaml', {})
    config = config_manager.get_all_config()

    # Inject Redis and config into FastAPI
    set_worker_dependencies(self.redis, config)

    # Create uvicorn server
    # ...
```

#### Step 4: Use Injected Config in Lifespan

**File**: `src/gleitzeit/api/main.py`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global _worker_redis, _worker_config

    # Verify injection happened
    if _worker_redis is None or _worker_config is None:
        raise RuntimeError("Worker dependencies not injected")

    # Use injected Redis
    app.state.redis = _worker_redis

    # Build redis_url from injected config
    redis_config = _worker_config.get('redis', {})
    redis_url = build_redis_url(redis_config)

    # Initialize client pool
    app.state.client_pool = ClientPool(redis_url=redis_url)
    await app.state.client_pool.initialize()

    # ... rest of lifespan
```

#### Step 5: Configure CORS from Worker Config

**File**: `src/gleitzeit/api/main.py`

```python
# NO module-level CORS configuration

@app.on_event("startup")
async def startup_event():
    """Initialize middleware from worker config"""
    global _worker_config

    if _worker_config is None:
        logger.warning("Worker config not available")
        return

    # Get CORS config from gleitzeit.yaml
    cors_config = _worker_config.get('api', {}).get('cors', {})
    serve_config = _worker_config.get('serve', {})

    # Build allowed origins from serve config
    allowed_origins = []

    # Add API URL
    api_config = serve_config.get('api', {})
    api_host = api_config.get('host', 'localhost')
    api_port = api_config.get('port', 8000)
    allowed_origins.append(f"http://{api_host}:{api_port}")

    # Add UI URL
    ui_config = serve_config.get('ui', {})
    if ui_config.get('enabled', True):
        ui_host = ui_config.get('host', 'localhost')
        ui_port = ui_config.get('port', 8004)
        allowed_origins.append(f"http://{ui_host}:{ui_port}")

    # Add additional origins from config
    additional = cors_config.get('additional_origins', [])
    allowed_origins.extend(additional)

    # Add CORS middleware with config from gleitzeit.yaml
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=cors_config.get('allow_credentials', True),
        allow_methods=cors_config.get('allow_methods', ["*"]),
        allow_headers=cors_config.get('allow_headers', ["*"]),
    )

    # Add other middleware from config
    # ...
```

### Required gleitzeit.yaml Structure

```yaml
serve:
  api:
    host: 0.0.0.0
    port: 8000
  ui:
    enabled: true
    host: 0.0.0.0
    port: 8004

api:
  cors:
    allow_credentials: true
    allow_methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers: ["*"]
    additional_origins: []
  security:
    rate_limiting:
      enabled: true
      default_limit: 100
      window: 60
    audit:
      enabled: true
    ip_whitelist:
      enabled: false
      whitelist: []

auth:
  auto_login: false
  jwt:
    secret: "your-secret-key"

redis:
  mode: single
  single_node:
    host: localhost
    port: 6379
    db: 0
```

### Benefits of This Design

1. ✅ **Consistency**: API worker follows same pattern as all other workers
2. ✅ **No hardcoded values**: All config from gleitzeit.yaml
3. ✅ **Proper initialization**: Uses GleitzeitRedisCluster from BaseWorker
4. ✅ **Single source of truth**: gleitzeit.yaml is the only config source
5. ✅ **Testability**: Can inject different configs for testing
6. ✅ **Maintainability**: Config flow is predictable and documented

### Migration Checklist

- [ ] Remove `CONFIG = load_config()` from main.py
- [ ] Remove all hardcoded default values
- [ ] Replace all `CONFIG` references with `_worker_config`
- [ ] Move CORS middleware configuration to startup event
- [ ] Move security middleware configuration to startup event
- [ ] Update APIWorker to inject config via set_worker_dependencies()
- [ ] Test that API starts without errors
- [ ] Test that CORS origins come from gleitzeit.yaml
- [ ] Test that Redis connection works properly
- [ ] Verify EventBroadcaster doesn't hang

### Testing Strategy

1. **Unit test**: Verify set_worker_dependencies() sets global variables
2. **Integration test**: Start API worker and verify config is used
3. **Manual test**: Change gleitzeit.yaml values and verify they're reflected
4. **Error test**: Verify proper error when worker dependencies not injected

## Conclusion

The API worker must follow the standard Gleitzeit worker pattern:
- **Receive config via WorkerConfig**
- **No module-level config loading**
- **No hardcoded values**
- **All config from gleitzeit.yaml via worker injection**

This ensures consistency, maintainability, and proper initialization across all workers.
