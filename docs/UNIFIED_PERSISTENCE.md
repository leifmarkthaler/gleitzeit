# Unified Persistence Architecture

## Overview

Gleitzeit v0.0.5 introduces a unified persistence layer that provides a single interface for all storage needs with automatic fallback capabilities. The system automatically tries Redis first, falls back to SQLite if Redis is unavailable, and finally uses in-memory storage if neither is available.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│            Application Components                    │
│   (ExecutionEngine, Hubs, Providers, Registry)      │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│         UnifiedPersistenceAdapter                    │
│                                                      │
│  • Single API for all persistence operations         │
│  • Automatic adapter selection and fallback          │
│  • Cross-domain data management                      │
│  • Transaction support                               │
└─────────────────────┬───────────────────────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│    Redis    │ │   SQLite    │ │   Memory    │
│   Adapter   │ │   Adapter   │ │   Adapter   │
│             │ │             │ │             │
│ Production  │ │ Development │ │   Testing   │
│   Primary   │ │   Fallback  │ │  Last Resort│
└─────────────┘ └─────────────┘ └─────────────┘
```

## Key Features

### 1. Automatic Fallback Chain
```python
# System automatically tries in order:
1. Redis (if configured and available)
2. SQLite (if Redis unavailable)
3. Memory (if both unavailable)
```

### 2. Zero Configuration
```python
# Just works out of the box
from gleitzeit.persistence import UnifiedPersistenceAdapter

adapter = UnifiedPersistenceAdapter()
await adapter.initialize()
# Automatically selects best available option
```

### 3. Explicit Configuration
```python
# Or specify preference
adapter = UnifiedPersistenceAdapter(
    adapter_type="redis",
    redis_url="redis://localhost:6379",
    fallback_enabled=True  # Still allows fallback
)
```

## Implementation Details

### Core Interface

```python
from gleitzeit.persistence.base import PersistenceAdapter
from typing import Dict, Any, Optional, List

class UnifiedPersistenceAdapter:
    """Single interface for all persistence needs"""
    
    def __init__(
        self,
        adapter_type: Optional[str] = None,
        redis_url: Optional[str] = None,
        db_path: Optional[str] = None,
        fallback_enabled: bool = True
    ):
        self.adapter_type = adapter_type
        self.redis_url = redis_url or "redis://localhost:6379"
        self.db_path = db_path or "./gleitzeit.db"
        self.fallback_enabled = fallback_enabled
        self.adapter = None
    
    async def initialize(self) -> None:
        """Initialize with automatic fallback"""
        if self.adapter_type == "redis" or self.adapter_type is None:
            try:
                self.adapter = await self._init_redis()
                return
            except Exception as e:
                if not self.fallback_enabled:
                    raise
                # Fall through to SQLite
        
        if self.adapter_type == "sqlite" or self.adapter_type is None:
            try:
                self.adapter = await self._init_sqlite()
                return
            except Exception as e:
                if not self.fallback_enabled:
                    raise
                # Fall through to memory
        
        # Last resort: memory
        self.adapter = await self._init_memory()
```

### Domain-Specific Methods

The unified adapter provides methods for all domains:

```python
class UnifiedPersistenceAdapter:
    # Workflow persistence
    async def save_workflow(self, workflow: Dict[str, Any]) -> None
    async def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]
    async def list_workflows(self, status: Optional[str] = None) -> List[Dict[str, Any]]
    
    # Task persistence
    async def save_task(self, task: Dict[str, Any]) -> None
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]
    async def update_task_status(self, task_id: str, status: str) -> None
    
    # Resource persistence (for hubs)
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None
    async def get_instance(self, hub_id: str, instance_id: str) -> Optional[ResourceInstance]
    async def list_instances(self, hub_id: str) -> List[ResourceInstance]
    async def delete_instance(self, hub_id: str, instance_id: str) -> None
    
    # Provider persistence
    async def save_provider(self, provider: Dict[str, Any]) -> None
    async def get_provider(self, provider_id: str) -> Optional[Dict[str, Any]]
    
    # Result persistence
    async def save_result(self, task_id: str, result: Any) -> None
    async def get_result(self, task_id: str) -> Optional[Any]
    
    # Metrics persistence
    async def save_metrics(self, source: str, metrics: Dict[str, Any]) -> None
    async def get_metrics(self, source: str, time_range: Optional[tuple] = None) -> List[Dict[str, Any]]
    
    # Transaction support
    async def begin_transaction(self) -> None
    async def commit_transaction(self) -> None
    async def rollback_transaction(self) -> None
```

## Adapter Implementations

### Redis Adapter
```python
class RedisAdapter(PersistenceAdapter):
    """High-performance production adapter"""
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client = None
        self.pubsub = None
    
    async def initialize(self):
        import aioredis
        self.client = await aioredis.from_url(self.redis_url)
        # Test connection
        await self.client.ping()
    
    async def save(self, key: str, value: Any, ttl: Optional[int] = None):
        serialized = json.dumps(value)
        if ttl:
            await self.client.setex(key, ttl, serialized)
        else:
            await self.client.set(key, serialized)
    
    async def get(self, key: str) -> Optional[Any]:
        value = await self.client.get(key)
        return json.loads(value) if value else None
```

### SQLite Adapter
```python
class SQLiteAdapter(PersistenceAdapter):
    """File-based development adapter"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
    
    async def initialize(self):
        import aiosqlite
        self.conn = await aiosqlite.connect(self.db_path)
        await self._create_tables()
    
    async def _create_tables(self):
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS persistence (
                key TEXT PRIMARY KEY,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await self.conn.commit()
    
    async def save(self, key: str, value: Any, ttl: Optional[int] = None):
        serialized = json.dumps(value)
        await self.conn.execute(
            'INSERT OR REPLACE INTO persistence (key, value) VALUES (?, ?)',
            (key, serialized)
        )
        await self.conn.commit()
```

### Memory Adapter
```python
class MemoryAdapter(PersistenceAdapter):
    """In-memory testing adapter"""
    
    def __init__(self):
        self.storage = {}
        self.locks = {}
    
    async def initialize(self):
        # No initialization needed
        pass
    
    async def save(self, key: str, value: Any, ttl: Optional[int] = None):
        self.storage[key] = {
            'value': value,
            'timestamp': datetime.now(),
            'ttl': ttl
        }
    
    async def get(self, key: str) -> Optional[Any]:
        if key in self.storage:
            item = self.storage[key]
            # Check TTL
            if item['ttl']:
                elapsed = (datetime.now() - item['timestamp']).seconds
                if elapsed > item['ttl']:
                    del self.storage[key]
                    return None
            return item['value']
        return None
```

## Usage Examples

### Basic Usage
```python
from gleitzeit.persistence import UnifiedPersistenceAdapter

# Initialize with automatic selection
adapter = UnifiedPersistenceAdapter()
await adapter.initialize()

# Save workflow
await adapter.save_workflow({
    "id": "wf-123",
    "name": "My Workflow",
    "status": "running"
})

# Get workflow
workflow = await adapter.get_workflow("wf-123")

# Save task result
await adapter.save_result("task-456", {
    "response": "Task completed",
    "duration": 1.5
})
```

### With Explicit Configuration
```python
# Force Redis with no fallback
adapter = UnifiedPersistenceAdapter(
    adapter_type="redis",
    redis_url="redis://production-redis:6379",
    fallback_enabled=False
)

# Use SQLite for development
adapter = UnifiedPersistenceAdapter(
    adapter_type="sqlite",
    db_path="./dev.db"
)

# Use memory for testing
adapter = UnifiedPersistenceAdapter(
    adapter_type="memory"
)
```

### Hub Integration
```python
from gleitzeit.hub.base import ResourceHub
from gleitzeit.persistence import UnifiedPersistenceAdapter

class OllamaHub(ResourceHub):
    def __init__(self, persistence: UnifiedPersistenceAdapter = None):
        super().__init__()
        self.persistence = persistence or UnifiedPersistenceAdapter()
    
    async def register_instance(self, instance: ResourceInstance):
        # Save to persistence
        if self.persistence:
            await self.persistence.save_instance(
                self.hub_id,
                instance
            )
        
        # Also keep in memory for quick access
        self.instances[instance.id] = instance
```

### Transaction Support
```python
async def update_workflow_with_results(adapter, workflow_id, results):
    try:
        await adapter.begin_transaction()
        
        # Update workflow status
        workflow = await adapter.get_workflow(workflow_id)
        workflow['status'] = 'completed'
        await adapter.save_workflow(workflow)
        
        # Save all results
        for task_id, result in results.items():
            await adapter.save_result(task_id, result)
        
        await adapter.commit_transaction()
    except Exception as e:
        await adapter.rollback_transaction()
        raise
```

## Configuration Options

### Environment Variables
```bash
# Redis configuration
GLEITZEIT_REDIS_URL=redis://localhost:6379
GLEITZEIT_REDIS_PASSWORD=secret
GLEITZEIT_REDIS_DB=0

# SQLite configuration
GLEITZEIT_SQLITE_PATH=./gleitzeit.db
GLEITZEIT_SQLITE_TIMEOUT=30

# Persistence preferences
GLEITZEIT_PERSISTENCE_TYPE=redis  # redis, sqlite, memory, auto
GLEITZEIT_PERSISTENCE_FALLBACK=true
```

### Python Configuration
```python
from gleitzeit import GleitzeitClient

# Client automatically configures persistence
client = GleitzeitClient(
    persistence="redis",
    redis_url="redis://localhost:6379"
)

# Or let it auto-detect
client = GleitzeitClient()  # Uses best available
```

## Performance Characteristics

### Redis
- **Latency**: < 1ms for most operations
- **Throughput**: 100,000+ ops/sec
- **Scalability**: Horizontal with Redis Cluster
- **Best for**: Production, high-throughput scenarios

### SQLite
- **Latency**: 1-10ms for most operations
- **Throughput**: 1,000-10,000 ops/sec
- **Scalability**: Single file, limited concurrency
- **Best for**: Development, small deployments

### Memory
- **Latency**: < 0.1ms
- **Throughput**: 1,000,000+ ops/sec
- **Scalability**: Limited by RAM
- **Best for**: Testing, temporary workflows

## Migration from Old Architecture

### Old Pattern (v0.0.4)
```python
# Different persistence for each component
from gleitzeit.persistence.task_queue import TaskQueuePersistence
from gleitzeit.persistence.workflow import WorkflowPersistence

task_persistence = TaskQueuePersistence(redis_client)
workflow_persistence = WorkflowPersistence(db_connection)
```

### New Pattern (v0.0.5)
```python
# Single unified adapter
from gleitzeit.persistence import UnifiedPersistenceAdapter

adapter = UnifiedPersistenceAdapter()
await adapter.initialize()
# Use for everything
```

## Error Handling

### Connection Failures
```python
try:
    adapter = UnifiedPersistenceAdapter(adapter_type="redis")
    await adapter.initialize()
except ConnectionError as e:
    # Automatic fallback if enabled
    logger.warning(f"Redis unavailable: {e}")
    # System continues with SQLite/Memory
```

### Persistence Errors
```python
try:
    await adapter.save_workflow(workflow)
except PersistenceError as e:
    # Handle save failure
    logger.error(f"Failed to save workflow: {e}")
    # Implement retry logic if needed
```

## Best Practices

### 1. Let the System Choose
```python
# Good - automatic selection
adapter = UnifiedPersistenceAdapter()

# Only specify if you have specific requirements
```

### 2. Handle Degradation Gracefully
```python
if adapter.adapter_type == "memory":
    logger.warning("Using in-memory persistence - data will not persist")
    # Notify user or adjust behavior
```

### 3. Use Transactions for Consistency
```python
# For related updates
async with adapter.transaction():
    await adapter.save_workflow(workflow)
    await adapter.save_task(task)
    await adapter.save_result(task_id, result)
```

### 4. Configure TTL for Temporary Data
```python
# Set TTL for cache-like data
await adapter.save_with_ttl(
    key="cache:model:response",
    value=response,
    ttl=3600  # 1 hour
)
```

## Monitoring and Metrics

### Adapter Metrics
```python
metrics = await adapter.get_metrics()
# {
#     "adapter_type": "redis",
#     "operations": 10000,
#     "errors": 5,
#     "avg_latency_ms": 0.8,
#     "fallback_count": 2
# }
```

### Health Checks
```python
async def check_persistence_health(adapter):
    try:
        # Test write
        await adapter.save("health:check", {"timestamp": datetime.now()})
        # Test read
        value = await adapter.get("health:check")
        # Test delete
        await adapter.delete("health:check")
        return True
    except Exception as e:
        logger.error(f"Persistence health check failed: {e}")
        return False
```

## Troubleshooting

### Redis Connection Issues
```bash
# Check Redis is running
redis-cli ping

# Check connectivity
telnet localhost 6379

# Check logs
docker logs redis-container
```

### SQLite Lock Issues
```python
# Increase timeout
adapter = UnifiedPersistenceAdapter(
    adapter_type="sqlite",
    sqlite_timeout=30  # seconds
)
```

### Memory Limitations
```python
# Monitor memory usage
import psutil
memory_percent = psutil.virtual_memory().percent
if memory_percent > 80:
    logger.warning("High memory usage with in-memory adapter")
```

## Future Enhancements

### Planned Features
1. **Distributed Caching**: Multi-level cache with local and remote
2. **Compression**: Automatic compression for large values
3. **Encryption**: At-rest encryption for sensitive data
4. **Sharding**: Automatic data sharding for scale
5. **Backup/Restore**: Built-in backup and restore capabilities

### Potential Adapters
- PostgreSQL for complex queries
- MongoDB for document storage
- S3 for blob storage
- Kafka for event streaming

## Summary

The Unified Persistence Architecture in v0.0.5 provides:
- **Single interface** for all persistence needs
- **Automatic fallback** for reliability
- **Zero configuration** for ease of use
- **Production ready** with Redis support
- **Development friendly** with SQLite option
- **Test friendly** with memory adapter

This architecture ensures your workflows and data are always persisted using the best available option, with seamless fallback when needed.