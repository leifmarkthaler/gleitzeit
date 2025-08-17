# Unified Persistence Architecture

## Overview

The Unified Persistence Architecture consolidates Gleitzeit's persistence systems (task/workflow persistence and hub resource persistence) into a single, cohesive layer. This provides better coordination between tasks and resources, simplified configuration, and improved maintainability.

## Architecture Design

### Unified Architecture

```
┌─────────────────────────────────────────────┐
│              Client/API Layer               │
├─────────────────────────────────────────────┤
│       UnifiedPersistenceAdapter             │
│                                             │
│  ┌──────────────┬────────────────┐         │
│  │Task/Workflow │ Hub Resources   │         │
│  │  Operations  │   Operations    │         │
│  └──────────────┴────────────────┘         │
│                                             │
│         Cross-Domain Operations             │
├─────────────────────────────────────────────┤
│            Implementations                  │
│                                             │
│  • UnifiedSQLAlchemyAdapter (default)      │
│  • UnifiedRedisAdapter (coming soon)       │
│  • UnifiedInMemoryAdapter (testing)        │
└─────────────────────────────────────────────┘
```

## Core Components

### 1. UnifiedPersistenceAdapter (Abstract Base)

The main interface that all persistence implementations must follow:

```python
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter

class UnifiedPersistenceAdapter(ABC):
    """
    Unified persistence interface for both task and hub resource management.
    """
    
    # Lifecycle
    async def initialize() -> None
    async def shutdown() -> None
    
    # Task/Workflow Operations
    async def save_task(task: Task) -> None
    async def get_task(task_id: str) -> Optional[Task]
    async def get_tasks_by_status(status: str) -> List[Task]
    async def save_workflow(workflow: Workflow) -> None
    async def get_workflow(workflow_id: str) -> Optional[Workflow]
    # ... more task operations
    
    # Hub Resource Operations  
    async def save_instance(hub_id: str, instance: ResourceInstance) -> None
    async def load_instance(instance_id: str) -> Optional[Dict[str, Any]]
    async def save_metrics(instance_id: str, metrics: ResourceMetrics) -> None
    async def acquire_lock(resource_id: str, owner_id: str, timeout: int) -> bool
    # ... more resource operations
    
    # Cross-Domain Operations
    async def get_tasks_for_resource(resource_id: str) -> List[Task]
    async def get_resource_for_task(task_id: str) -> Optional[Dict[str, Any]]
    async def get_resource_utilization(hub_id: str) -> Dict[str, Any]
```

### 2. UnifiedSQLAlchemyAdapter

Production-ready implementation using SQLAlchemy ORM:

- **Default Database**: SQLite (file-based or in-memory)
- **Supported Databases**: PostgreSQL, MySQL, Oracle, SQL Server
- **Features**:
  - Automatic table creation
  - Transaction support
  - Connection pooling (for non-SQLite)
  - Optimized indexes
  - Cascade deletes
  - 24-hour metrics retention

### 3. UnifiedInMemoryAdapter

Lightweight implementation for testing and development:

- Pure Python dictionaries
- No external dependencies
- Fast performance
- Automatic lock expiration
- Limited metrics history (last 100 entries)

## Configuration

### Basic Usage

```python
from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter

# Default SQLite configuration
adapter = UnifiedSQLAlchemyAdapter()
await adapter.initialize()

# Custom SQLite path
adapter = UnifiedSQLAlchemyAdapter(db_path="/path/to/database.db")

# In-memory SQLite (for testing)
adapter = UnifiedSQLAlchemyAdapter(db_path=":memory:")

# PostgreSQL
adapter = UnifiedSQLAlchemyAdapter(
    connection_string="postgresql+asyncpg://user:pass@localhost/gleitzeit"
)

# MySQL
adapter = UnifiedSQLAlchemyAdapter(
    connection_string="mysql+aiomysql://user:pass@localhost/gleitzeit"
)
```

### Environment Variables

```bash
# Set persistence type
export GLEITZEIT_PERSISTENCE_TYPE=sqlalchemy  # or redis, memory

# SQLAlchemy connection string
export GLEITZEIT_SQL_CONNECTION="postgresql+asyncpg://user:pass@localhost/gleitzeit"

# Or use SQLite path
export GLEITZEIT_DB_PATH="/var/lib/gleitzeit/database.db"
```

### Configuration File

```yaml
persistence:
  type: sqlalchemy
  sqlalchemy:
    connection_string: "postgresql+asyncpg://user:pass@localhost/gleitzeit"
    # Or for SQLite:
    # db_path: "/var/lib/gleitzeit/database.db"
    
    # Engine options
    pool_size: 20
    max_overflow: 40
    pool_timeout: 30
    echo: false  # SQL query logging
    
  # Metrics retention
  metrics_retention_hours: 24
  
  # Lock settings
  default_lock_timeout: 30
```

## Database Schema

### Task/Workflow Tables

#### tasks
- **id** (PK): Unique task identifier
- **name**: Task name
- **protocol**: Protocol identifier (llm, python, etc.)
- **method**: Method to execute
- **params**: JSON parameters
- **priority**: Task priority level
- **status**: Current status
- **assigned_provider**: Links to resource instance
- **workflow_id**: Parent workflow
- Indexes: status+priority, workflow_id, assigned_provider

#### task_results
- **task_id** (PK, FK): References tasks.id
- **status**: Execution status
- **result**: JSON result data
- **error_message**: Error details if failed
- **execution_time**: Duration in seconds

#### workflows
- **id** (PK): Unique workflow identifier
- **name**: Workflow name
- **tasks**: JSON array of task definitions
- **metadata**: JSON metadata

#### workflow_executions
- **execution_id** (PK): Unique execution identifier
- **workflow_id** (FK): References workflows.id
- **status**: Execution status
- **progress**: JSON progress information

#### queue_states
- **queue_name** (PK): Queue identifier
- **state**: JSON queue state
- **updated_at**: Last update timestamp

### Hub Resource Tables

#### resource_instances
- **instance_id** (PK): Unique instance identifier
- **hub_id**: Parent hub identifier
- **type**: Resource type (ollama, docker, etc.)
- **endpoint**: Connection endpoint
- **status**: Health status
- **metadata**: JSON configuration
- Indexes: hub_id+status

#### resource_metrics
- **id** (PK): Auto-incrementing ID
- **instance_id** (FK): References resource_instances.instance_id
- **timestamp**: Metric timestamp
- **cpu_percent**, **memory_mb**: Resource usage
- **request_count**, **error_count**: Request statistics
- **avg_response_time_ms**, **p95_response_time_ms**, **p99_response_time_ms**: Performance metrics
- Indexes: instance_id+timestamp

#### resource_locks
- **resource_id** (PK): Resource identifier
- **owner_id**: Lock owner identifier
- **expires_at**: Lock expiration time
- Index: expires_at

## Usage Examples

### Basic Task Management

```python
from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from gleitzeit.core.models import Task

# Initialize adapter
adapter = UnifiedSQLAlchemyAdapter()
await adapter.initialize()

# Save a task
task = Task(
    id="task-123",
    name="Generate text",
    protocol="llm",
    method="llm/complete",
    params={"prompt": "Hello world"},
    priority="normal"
)
await adapter.save_task(task)

# Retrieve task
task = await adapter.get_task("task-123")

# Get tasks by status
queued_tasks = await adapter.get_tasks_by_status("queued")

# Save task result
result = TaskResult(
    task_id="task-123",
    status="completed",
    result={"text": "Hello! How can I help?"},
    duration_seconds=1.5
)
await adapter.save_task_result(result)
```

### Resource Management

```python
from gleitzeit.hub.base import ResourceInstance, ResourceStatus, ResourceType

# Register a resource instance
instance = ResourceInstance(
    id="ollama-1",
    name="Ollama Server 1",
    type=ResourceType.OLLAMA,
    endpoint="http://localhost:11434",
    status=ResourceStatus.HEALTHY,
    metadata={"model": "llama3.2"}
)
await adapter.save_instance("ollama-hub", instance)

# List instances for a hub
instances = await adapter.list_instances("ollama-hub")

# Save metrics
metrics = ResourceMetrics(
    cpu_percent=45.2,
    memory_mb=1024,
    request_count=150,
    error_count=2,
    avg_response_time_ms=230
)
await adapter.save_metrics("ollama-1", metrics)

# Get metrics history
from datetime import datetime, timedelta
end_time = datetime.utcnow()
start_time = end_time - timedelta(hours=1)
history = await adapter.get_metrics_history("ollama-1", start_time, end_time)
```

### Distributed Locking

```python
# Acquire a lock for resource allocation
lock_acquired = await adapter.acquire_lock(
    resource_id="ollama-1",
    owner_id="worker-abc",
    timeout=30  # seconds
)

if lock_acquired:
    try:
        # Use the resource
        await process_with_resource("ollama-1")
        
        # Extend lock if needed
        await adapter.extend_lock("ollama-1", "worker-abc", timeout=30)
        
    finally:
        # Release lock
        await adapter.release_lock("ollama-1", "worker-abc")
```

### Cross-Domain Queries

```python
# Get all tasks assigned to a resource
tasks = await adapter.get_tasks_for_resource("ollama-1")
print(f"Resource ollama-1 has {len(tasks)} active tasks")

# Get resource assigned to a task
resource = await adapter.get_resource_for_task("task-123")
if resource:
    print(f"Task is assigned to: {resource['name']}")

# Get overall resource utilization
utilization = await adapter.get_resource_utilization("ollama-hub")
print(f"Total instances: {utilization['total_instances']}")
print(f"Status distribution: {utilization['status_distribution']}")
for instance in utilization['instance_utilization']:
    print(f"  {instance['instance_id']}: {instance['active_tasks']} tasks")
```

## Performance Considerations

### Indexing Strategy

The unified adapter creates indexes on frequently queried columns:

1. **Task queries**: 
   - status + priority (for queue operations)
   - workflow_id (for workflow queries)
   - assigned_provider (for resource linkage)

2. **Resource queries**:
   - hub_id + status (for hub operations)
   - instance_id + timestamp (for metrics)

### Connection Pooling

For production deployments with PostgreSQL/MySQL:

```python
adapter = UnifiedSQLAlchemyAdapter(
    connection_string="postgresql+asyncpg://...",
    pool_size=20,        # Number of connections
    max_overflow=40,     # Maximum overflow connections
    pool_timeout=30,     # Timeout for getting connection
    pool_recycle=3600    # Recycle connections after 1 hour
)
```

### Metrics Retention

Metrics are automatically cleaned up after 24 hours to prevent unbounded growth:

```python
# Configure retention (in custom implementation)
class CustomAdapter(UnifiedSQLAlchemyAdapter):
    METRICS_RETENTION_HOURS = 48  # Keep 48 hours instead of 24
```

### Batch Operations

For bulk inserts, use batch methods:

```python
# Efficient batch insert
tasks = [task1, task2, task3, ...]
await adapter.save_tasks_batch(tasks)

# Instead of individual saves
for task in tasks:
    await adapter.save_task(task)  # Less efficient
```

## Monitoring and Maintenance

### Database Size Management

```python
# Clean up old completed tasks
from datetime import datetime, timedelta

cutoff = datetime.utcnow() - timedelta(days=30)
deleted_count = await adapter.cleanup_old_data(cutoff)
print(f"Deleted {deleted_count} old tasks")
```

### Lock Monitoring

```python
# Check for stuck locks
lock_owner = await adapter.get_lock_owner("resource-1")
if lock_owner:
    print(f"Resource locked by: {lock_owner}")
```

### Performance Metrics

```python
# Get task distribution
task_counts = await adapter.get_task_count_by_status()
for status, count in task_counts.items():
    print(f"{status}: {count} tasks")

# Monitor resource utilization
utilization = await adapter.get_resource_utilization("ollama-hub")
```

## Troubleshooting

### Common Issues

#### 1. Database Lock Errors (SQLite)

**Problem**: "database is locked" errors with SQLite

**Solution**: SQLite has limited concurrency. For production, use PostgreSQL:

```python
# Development (SQLite)
adapter = UnifiedSQLAlchemyAdapter(db_path="dev.db")

# Production (PostgreSQL)
adapter = UnifiedSQLAlchemyAdapter(
    connection_string="postgresql+asyncpg://..."
)
```

#### 2. Connection Pool Exhaustion

**Problem**: "TimeoutError: QueuePool limit exceeded"

**Solution**: Increase pool size or check for connection leaks:

```python
adapter = UnifiedSQLAlchemyAdapter(
    connection_string="...",
    pool_size=50,
    max_overflow=100
)
```

#### 3. Slow Queries

**Problem**: Queries taking too long

**Solution**: Enable query logging to identify slow queries:

```python
adapter = UnifiedSQLAlchemyAdapter(
    connection_string="...",
    echo=True  # Log all SQL queries
)
```

### Debug Logging

Enable detailed logging:

```python
import logging

# Set logging level
logging.getLogger('gleitzeit.persistence').setLevel(logging.DEBUG)
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

## Security Considerations

### SQL Injection Protection

All queries use parameterized statements:

```python
# Safe - uses parameters
await session.execute(
    select(DBTask).where(DBTask.id == task_id)
)

# Never do string concatenation
# UNSAFE: f"SELECT * FROM tasks WHERE id = '{task_id}'"
```

### Connection Security

For production databases, use SSL:

```python
adapter = UnifiedSQLAlchemyAdapter(
    connection_string="postgresql+asyncpg://user:pass@host/db?ssl=require"
)
```

### Secrets Management

Never hardcode credentials:

```python
import os

# Use environment variables
adapter = UnifiedSQLAlchemyAdapter(
    connection_string=os.environ['DATABASE_URL']
)

# Or use secret management service
from secret_manager import get_secret
adapter = UnifiedSQLAlchemyAdapter(
    connection_string=get_secret('db_connection')
)
```

## Future Enhancements

### Planned Features

1. **Redis Adapter**: High-performance distributed persistence
2. **MongoDB Adapter**: Document-based persistence
3. **Sharding Support**: Horizontal scaling for large deployments
4. **Read Replicas**: Separate read/write connections
5. **Caching Layer**: In-memory cache for frequently accessed data
6. **Event Streaming**: Publish persistence events for monitoring
7. **Backup/Restore**: Built-in backup and restore utilities

### Extension Points

The adapter is designed to be extensible:

```python
class CustomAdapter(UnifiedSQLAlchemyAdapter):
    """Custom adapter with additional features"""
    
    async def save_task(self, task: Task) -> None:
        # Add custom logic
        await self.publish_event('task.saved', task.id)
        
        # Call parent implementation
        await super().save_task(task)
    
    async def publish_event(self, event_type: str, data: Any):
        """Publish events to message queue"""
        # Custom implementation
        pass
```

## API Reference

See the inline documentation in:
- `src/gleitzeit/persistence/unified_persistence.py` - Base interfaces
- `src/gleitzeit/persistence/unified_sqlalchemy.py` - SQLAlchemy implementation

## Support

For issues or questions:
1. Check this documentation
2. Review the troubleshooting section
3. Check existing GitHub issues
4. Create a new issue with:
   - Gleitzeit version
   - Persistence adapter type
   - Database type and version
   - Error messages and stack traces