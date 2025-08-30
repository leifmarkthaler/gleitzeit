# Gleitzeit Persistence Backend Documentation

## Overview

The Gleitzeit persistence layer provides a unified interface for storing and retrieving workflow data, task states, and system metadata across different backend implementations. The system supports three backend types: Redis (distributed), SQL (persistent), and Memory (ephemeral).

## Architecture

### Unified Persistence Adapter

The `UnifiedPersistenceAdapter` abstract class defines the complete interface that all persistence backends must implement. This ensures consistent behavior across different storage systems.

```python
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
```

### Backend Selection

Backend type is configured via environment variable or client configuration:

```bash
# Environment variable
export GLEITZEIT_PERSISTENCE_TYPE=redis  # or 'sql' or 'memory'

# Client configuration
client = GleitzeitClient(
    native_config={
        'persistence': {'type': 'sql'}
    }
)
```

### Automatic Fallback

The system automatically falls back to available backends:
```
Redis → SQL → Memory
```

## Core Operations

### Task Operations

#### Create/Update Operations
- `save_task(task: Task) -> None` - Save or update a task
- `save_task_result(task_result: TaskResult) -> None` - Save task execution result
- `save_tasks_batch(tasks: List[Task]) -> None` - Batch save multiple tasks

#### Read Operations
- `get_task(task_id: str) -> Optional[Task]` - Get a single task by ID
- `get_task_result(task_id: str) -> Optional[TaskResult]` - Get task execution result
- `get_tasks_by_status(status: str) -> List[Task]` - Get all tasks with specific status
- `get_tasks_by_workflow(workflow_id: str) -> List[Task]` - Get all tasks for a workflow
- `get_all_queued_tasks() -> List[Task]` - Get all tasks ready for execution
- `get_task_count_by_status() -> Dict[str, int]` - Get task counts grouped by status

#### Delete Operations
- `delete_task(task_id: str) -> bool` - Delete a single task and its results
  - Returns `True` if task was deleted, `False` if not found
  - Removes task from all indexes (status, workflow, provider)
  - Cascades to delete associated task results

#### List Operations (UI/API)
- `list_tasks(workflow_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]`
  - Returns paginated list of tasks with optional filtering
  - Response format:
    ```json
    {
      "tasks": [...],      // List of task objects
      "total": 100,        // Total count matching filters
      "limit": 50,         // Page size
      "offset": 0          // Starting position
    }
    ```

### Workflow Operations

#### Create/Update Operations
- `save_workflow(workflow: Workflow) -> None` - Save or update a workflow
- `save_workflow_execution(execution: WorkflowExecution) -> None` - Save workflow execution state

#### Read Operations
- `get_workflow(workflow_id: str) -> Optional[Workflow]` - Get a workflow by ID
- `get_workflow_execution(execution_id: str) -> Optional[WorkflowExecution]` - Get workflow execution state

#### Delete Operations
- `delete_workflow(workflow_id: str) -> bool` - **Delete a workflow and ALL associated data**
  - Deletes all tasks belonging to the workflow
  - Deletes all task results for those tasks
  - Deletes workflow execution records
  - Deletes the workflow itself
  - **Cleans queue state references to deleted tasks**
  - Returns `True` if workflow was deleted, `False` if not found

#### List Operations (UI/API)
- `list_workflows(status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]`
  - Returns paginated list of workflows
  - Response format similar to `list_tasks`

### Queue State Operations

#### Queue State Management
- `save_queue_state(queue_name: str, state: Dict[str, Any]) -> None` - Save queue recovery state
- `get_queue_state(queue_name: str) -> Optional[Dict[str, Any]]` - Get saved queue state
- `delete_queue_state(queue_name: str) -> bool` - Delete queue state

#### Queue State Structure
```python
{
    'total_enqueued': 1000,
    'total_dequeued': 950,
    'completed_tasks': ['task_id1', 'task_id2', ...],
    'failed_tasks': ['task_id3', 'task_id4', ...],
    'queue_size': 50,
    'updated_at': '2025-01-01T00:00:00'
}
```

#### Automatic Queue State Cleanup
When `delete_workflow()` is called, the system automatically:
1. Collects all task IDs being deleted
2. Searches all queue states
3. Removes references to deleted tasks from `completed_tasks` and `failed_tasks` lists
4. Saves the cleaned queue states

This prevents queue states from accumulating references to non-existent tasks.

### Resource Management Operations

#### Instance Operations
- `save_instance(hub_id: str, instance: ResourceInstance) -> None` - Save resource instance
- `load_instance(instance_id: str) -> Optional[Dict[str, Any]]` - Load instance data
- `list_instances(hub_id: str) -> List[Dict[str, Any]]` - List all instances for a hub
- `delete_instance(instance_id: str) -> None` - Remove instance from storage

#### Metrics Operations
- `save_metrics(instance_id: str, metrics: ResourceMetrics) -> None` - Store metrics snapshot
- `get_metrics_history(instance_id: str, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]` - Get historical metrics

#### Distributed Locking
- `acquire_lock(resource_id: str, owner_id: str, timeout: int = 30) -> bool` - Acquire distributed lock
- `release_lock(resource_id: str, owner_id: str) -> None` - Release lock if owned
- `extend_lock(resource_id: str, owner_id: str, timeout: int = 30) -> bool` - Extend lock timeout
- `get_lock_owner(resource_id: str) -> Optional[str]` - Get current lock owner

### Maintenance Operations

#### Bulk Cleanup
- `cleanup_old_data(cutoff_date: datetime) -> int`
  - Removes completed/failed tasks older than cutoff date
  - Removes associated task results
  - Returns count of deleted items
  - Useful for preventing unbounded database growth

## Backend Implementations

### Redis Backend (`unified_redis.py`)

**Features:**
- High-performance distributed storage
- Atomic operations via pipelines
- TTL-based expiration support
- Pattern-based key scanning

**Configuration:**
```python
redis_url = "redis://localhost:6379/0"
adapter = UnifiedRedisAdapter(redis_url)
```

**Key Structure:**
- Tasks: `gleitzeit:task:{task_id}`
- Workflows: `gleitzeit:workflow:{workflow_id}`
- Queue states: `gleitzeit:queue_state:{queue_name}`
- Indexes: `gleitzeit:index:status:{status}`, `gleitzeit:index:workflow:{workflow_id}`

**Delete Workflow Implementation:**
- Uses pipeline for atomic deletion
- Removes from all indexes (status, workflow, provider)
- Searches for queue states by pattern `gleitzeit:queue_state:*`
- Updates each queue state to remove deleted task references

### SQL Backend (`unified_sqlalchemy.py`)

**Features:**
- Persistent storage with SQLite/PostgreSQL
- ACID transactions
- Foreign key constraints with cascade delete
- Complex queries via SQLAlchemy ORM

**Configuration:**
```python
database_url = "sqlite:///gleitzeit.db"  # or postgresql://...
adapter = UnifiedSQLAlchemyAdapter(database_url)
```

**Database Schema:**
- `tasks` table with workflow_id foreign key
- `task_results` table with task_id foreign key (CASCADE DELETE)
- `workflows` table
- `workflow_executions` table
- `queue_states` table
- `resource_instances` table
- `resource_locks` table

**Delete Workflow Implementation:**
- Gets task IDs before deletion (important for queue cleanup)
- Uses transaction for consistency
- Foreign keys cascade delete task results
- Queries all `DBQueueState` records and cleans JSON data

### Memory Backend (`UnifiedInMemoryAdapter`)

**Features:**
- In-process storage for testing
- Zero latency
- No persistence (data lost on restart)
- Automatic garbage collection

**Configuration:**
```python
adapter = UnifiedInMemoryAdapter()
```

**Data Structure:**
```python
self.tasks: Dict[str, Task] = {}
self.task_results: Dict[str, TaskResult] = {}
self.workflows: Dict[str, Workflow] = {}
self.queue_states: Dict[str, Dict[str, Any]] = {}
```

**Delete Workflow Implementation:**
- Direct dictionary operations
- Iterates through tasks to find workflow matches
- Cleans queue states in-place
- No persistence, changes are immediate

## Persistence Behavior Comparison

| Feature | Redis | SQL | Memory |
|---------|-------|-----|--------|
| **Persistence** | Yes (if configured) | Yes | No |
| **Distribution** | Yes | No (unless shared DB) | No |
| **Performance** | High | Medium | Highest |
| **Transactions** | Limited | Full ACID | N/A |
| **Query Capability** | Limited | Full SQL | Limited |
| **Cascade Delete** | Manual | Automatic (FK) | Manual |
| **Queue State Cleanup** | Pattern search | Table scan | Direct iteration |

## Best Practices

### 1. Choosing a Backend

- **Development/Testing**: Use Memory backend for speed
- **Single Instance**: Use SQL backend for persistence
- **Distributed/Production**: Use Redis backend for scalability

### 2. Delete Operations

Always use the provided delete methods rather than direct backend access:
```python
# Good - uses delete_workflow which cleans everything
await adapter.delete_workflow(workflow_id)

# Bad - leaves orphaned data and stale queue references
await redis.delete(f"workflow:{workflow_id}")
```

### 3. Queue State Management

Queue states are automatically cleaned when workflows are deleted, but you can also:
- Manually clean specific queue state: `delete_queue_state(queue_name)`
- Implement periodic cleanup of references to non-existent tasks

### 4. Bulk Operations

Use batch methods when available:
```python
# Good - single operation
await adapter.save_tasks_batch(tasks)

# Less efficient - multiple operations
for task in tasks:
    await adapter.save_task(task)
```

### 5. Maintenance

Schedule regular cleanup for production systems:
```python
# Remove tasks older than 30 days
cutoff = datetime.now() - timedelta(days=30)
deleted_count = await adapter.cleanup_old_data(cutoff)
```

## Error Handling

All persistence operations include error handling:
- Operations log errors but don't raise exceptions
- Read operations return `None` or empty collections on error
- Delete operations return `False` on error
- Write operations fail silently (logged)

## Migration Guide

### Switching Backends

1. Export data from current backend (if needed)
2. Update configuration:
   ```bash
   export GLEITZEIT_PERSISTENCE_TYPE=sql
   ```
3. Restart services
4. Import data to new backend (if needed)

### Data Format Compatibility

All backends use the same Pydantic models, ensuring data compatibility:
- `Task`, `TaskResult`, `Workflow`, `WorkflowExecution` models
- JSON serialization for complex fields
- ISO format for datetime fields

## Testing

### Unit Tests
Each backend has comprehensive tests:
```bash
pytest tests/persistence/test_unified_redis.py
pytest tests/persistence/test_unified_sqlalchemy.py
pytest tests/persistence/test_unified_memory.py
```

### Integration Tests
Test backend switching:
```python
for backend_type in ['memory', 'sql', 'redis']:
    os.environ['GLEITZEIT_PERSISTENCE_TYPE'] = backend_type
    # Run tests...
```

## Performance Considerations

### Redis
- Use pipelines for batch operations
- Set appropriate TTLs to prevent memory bloat
- Consider Redis Cluster for large scale

### SQL
- Add indexes for frequently queried fields
- Use connection pooling
- Consider partitioning for large datasets

### Memory
- Monitor memory usage
- Implement size limits if needed
- Not suitable for production use

## Future Enhancements

- [ ] MongoDB adapter implementation
- [ ] Elasticsearch adapter for search capabilities
- [ ] S3/Object storage for large payloads
- [ ] Automatic data migration tools
- [ ] Real-time change notifications
- [ ] Backup and restore utilities