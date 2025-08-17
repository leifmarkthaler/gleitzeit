# Task Queue and Persistence Architecture for Gleitzeit V4

## Overview

Gleitzeit V4 implements a sophisticated task queue and persistence system designed for reliability, scalability, and fault tolerance. This document details the complete architecture of task queuing, dependency resolution, and persistence backends.

## Architecture Components

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Task Submit   │───▶│   Queue Manager  │───▶│ Dependency      │
│                 │    │                  │    │ Resolver        │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │                          │
                              ▼                          ▼
                    ┌──────────────────┐    ┌─────────────────┐
                    │ Persistence      │    │ Execution       │
                    │ Backend          │    │ Engine          │
                    └──────────────────┘    └─────────────────┘
                              │
                    ┌──────────────────┐
                    │ Redis / SQLite   │
                    │ Storage          │
                    └──────────────────┘
```

## Core Components

### QueueManager (`task_queue/task_queue.py`)

The `QueueManager` is the central coordinator for all task queueing operations.

#### Responsibilities
- **Task Submission**: Accept and validate incoming tasks
- **Priority Management**: Handle task priorities and ordering
- **Queue Operations**: Enqueue, dequeue, and requeue operations
- **Event Emission**: Notify system of queue state changes
- **Workflow Coordination**: Manage workflow-level operations

#### Key Methods

```python
class QueueManager:
    async def submit_task(self, task: Task) -> str:
        """Submit a single task for execution"""
        
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit a complete workflow with dependencies"""
        
    async def get_next_task(self, capabilities: List[str] = None) -> Optional[Task]:
        """Get next available task for execution"""
        
    async def complete_task(self, task_id: str, result: TaskResult) -> None:
        """Mark task as completed with results"""
        
    async def fail_task(self, task_id: str, error: str, is_retryable: bool = True) -> None:
        """Mark task as failed"""
        
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics and health metrics"""
```

#### Task Submission Flow

```
Task Creation → Validation → Dependency Check → Queue Assignment → Persistence
     │              │             │                    │              │
     ▼              ▼             ▼                    ▼              ▼
Task Schema    Required     Dependency        Priority Queue    Database
Validation     Fields       Analysis          Selection         Storage
```

#### Event Emissions

The QueueManager emits the following events:

- `queue:task_enqueued` - When task is added to queue
- `queue:task_dequeued` - When task is removed for execution  
- `queue:workflow_submitted` - When workflow is submitted
- `queue:full` - When queue reaches capacity
- `queue:empty` - When queue becomes empty
- `queue:priority_changed` - When task priority is modified

### DependencyResolver (`task_queue/dependency_resolver.py`)

Handles complex task dependencies and parameter substitution.

#### Responsibilities
- **Dependency Analysis**: Build dependency graphs
- **Parameter Substitution**: Replace placeholders with actual values
- **Execution Ordering**: Determine optimal execution sequence
- **Circular Detection**: Prevent circular dependency deadlocks
- **Workflow Validation**: Ensure workflow integrity

#### Dependency Types

1. **Simple Dependencies**
   ```yaml
   tasks:
     - id: task_a
       method: "process_data"
       
     - id: task_b
       method: "analyze_results"
       dependencies: ["task_a"]  # Simple dependency
   ```

2. **Parameter Dependencies**
   ```yaml
   tasks:
     - id: fetch_data
       method: "data/fetch"
       parameters:
         source: "database"
         
     - id: process_data
       method: "data/process"
       dependencies: ["fetch_data"]
       parameters:
         input: "${fetch_data.result.data}"  # Parameter substitution
   ```

3. **Conditional Dependencies**
   ```yaml
   tasks:
     - id: validate_data
       method: "data/validate"
       
     - id: clean_data
       method: "data/clean"
       dependencies: ["validate_data"]
       conditions:
         - "${validate_data.result.is_valid} == false"  # Only run if invalid
   ```

#### Parameter Substitution Engine

The dependency resolver supports sophisticated parameter substitution:

```python
# Substitution patterns supported:
"${task_id.result}"                    # Full result
"${task_id.result.field}"             # Specific field
"${task_id.result.nested.field}"      # Nested field access
"${task_id.metadata.duration}"        # Task metadata
"${workflow.variables.global_var}"    # Workflow variables
"${env.ENVIRONMENT_VAR}"              # Environment variables
"${config.setting.value}"             # Configuration values
```

#### Dependency Graph Example

```
Workflow: Data Processing Pipeline
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ fetch_data  │───▶│ validate    │───▶│ clean_data  │
│             │    │ _data       │    │             │
└─────────────┘    └─────────────┘    └─────────────┘
                          │                  │
                          ▼                  ▼
                   ┌─────────────┐    ┌─────────────┐
                   │ generate    │    │ process     │
                   │ _report     │    │ _data       │
                   └─────────────┘    └─────────────┘
                          │                  │
                          └──────┬───────────┘
                                 ▼
                          ┌─────────────┐
                          │ final       │
                          │ _output     │
                          └─────────────┘
```

#### Execution Levels

The dependency resolver organizes tasks into execution levels:

```python
Level 0: [fetch_data]                    # No dependencies
Level 1: [validate_data]                 # Depends on Level 0
Level 2: [clean_data, generate_report]   # Depends on Level 1  
Level 3: [process_data]                  # Depends on Level 2
Level 4: [final_output]                  # Depends on Level 3
```

## Persistence Architecture

### Persistence Backend Interface (`persistence/base.py`)

All persistence backends implement the `PersistenceBackend` interface:

```python
class PersistenceBackend(ABC):
    @abstractmethod
    async def store_task(self, task: Task) -> None:
        """Store a task in the persistence layer"""
        
    @abstractmethod 
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID"""
        
    @abstractmethod
    async def update_task_status(self, task_id: str, status: TaskStatus, 
                               result: Optional[TaskResult] = None) -> None:
        """Update task status and optionally store result"""
        
    @abstractmethod
    async def store_workflow(self, workflow: Workflow) -> None:
        """Store a complete workflow"""
        
    @abstractmethod
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Retrieve a workflow by ID"""
        
    @abstractmethod
    async def list_pending_tasks(self, limit: Optional[int] = None) -> List[Task]:
        """Get list of tasks pending execution"""
        
    @abstractmethod
    async def cleanup_completed_tasks(self, before: datetime) -> int:
        """Clean up old completed tasks"""
```

### Redis Backend (`persistence/redis_backend.py`)

High-performance, distributed persistence using Redis.

#### Redis Data Structure

```redis
# Task Storage
task:{task_id} -> JSON serialized Task object
task:{task_id}:result -> JSON serialized TaskResult
task:{task_id}:metadata -> Task metadata (timestamps, attempts, etc.)

# Workflow Storage  
workflow:{workflow_id} -> JSON serialized Workflow object
workflow:{workflow_id}:tasks -> Set of task IDs in workflow
workflow:{workflow_id}:status -> Workflow status

# Queue Structures
queue:pending -> List of pending task IDs (FIFO)
queue:executing -> Set of currently executing task IDs
queue:completed -> Sorted set of completed tasks (by timestamp)
queue:failed -> Sorted set of failed tasks (by timestamp)

# Dependency Tracking
deps:{task_id}:depends_on -> Set of task IDs this task depends on
deps:{task_id}:dependents -> Set of task IDs that depend on this task
deps:{workflow_id}:graph -> JSON serialized dependency graph

# Statistics and Monitoring
stats:tasks:total -> Counter of total tasks submitted
stats:tasks:completed -> Counter of completed tasks
stats:tasks:failed -> Counter of failed tasks
stats:workflows:active -> Set of active workflow IDs
```

#### Redis Operations

```python
class RedisBackend(PersistenceBackend):
    async def store_task(self, task: Task) -> None:
        """Store task with atomic operations"""
        async with self.redis.pipeline() as pipe:
            # Store task data
            pipe.hset(f"task:{task.id}", mapping={
                "data": task.model_dump_json(),
                "status": task.status.value,
                "created_at": task.created_at.isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            })
            
            # Add to appropriate queue
            if task.status == TaskStatus.PENDING:
                pipe.lpush("queue:pending", task.id)
            
            # Store dependencies
            if task.dependencies:
                pipe.sadd(f"deps:{task.id}:depends_on", *task.dependencies)
                for dep in task.dependencies:
                    pipe.sadd(f"deps:{dep}:dependents", task.id)
            
            # Update statistics
            pipe.incr("stats:tasks:total")
            
            await pipe.execute()
```

#### Redis Clustering Support

```python
# Redis Cluster configuration
REDIS_CLUSTER_NODES = [
    {"host": "redis-node-1", "port": 7000},
    {"host": "redis-node-2", "port": 7000}, 
    {"host": "redis-node-3", "port": 7000}
]

# Consistent hashing for task distribution
def get_redis_key_slot(task_id: str) -> int:
    """Calculate Redis cluster slot for task"""
    return crc16(task_id.encode()) % 16384
```

### SQLite Backend (`persistence/sqlite_backend.py`)

Lightweight, file-based persistence for development and small deployments.

#### Database Schema

```sql
-- Tasks table
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    workflow_id TEXT,
    name TEXT,
    protocol TEXT,
    method TEXT,
    parameters TEXT,  -- JSON
    status TEXT,
    priority TEXT DEFAULT 'normal',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    attempt_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    timeout_seconds INTEGER,
    
    FOREIGN KEY (workflow_id) REFERENCES workflows(id)
);

-- Task dependencies
CREATE TABLE task_dependencies (
    task_id TEXT,
    depends_on TEXT,
    
    PRIMARY KEY (task_id, depends_on),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (depends_on) REFERENCES tasks(id)
);

-- Task results
CREATE TABLE task_results (
    task_id TEXT PRIMARY KEY,
    result_data TEXT,  -- JSON
    result_type TEXT,
    result_size INTEGER,
    execution_time REAL,
    provider_id TEXT,
    
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Workflows table
CREATE TABLE workflows (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    execution_levels INTEGER,
    total_tasks INTEGER,
    completed_tasks INTEGER DEFAULT 0,
    failed_tasks INTEGER DEFAULT 0
);

-- Workflow metadata
CREATE TABLE workflow_metadata (
    workflow_id TEXT,
    key TEXT,
    value TEXT,
    
    PRIMARY KEY (workflow_id, key),
    FOREIGN KEY (workflow_id) REFERENCES workflows(id)
);

-- Indexes for performance
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_workflow ON tasks(workflow_id);
CREATE INDEX idx_tasks_created ON tasks(created_at);
CREATE INDEX idx_dependencies_task ON task_dependencies(task_id);
CREATE INDEX idx_dependencies_depends ON task_dependencies(depends_on);
CREATE INDEX idx_workflows_status ON workflows(status);
```

#### SQLite Operations

```python
class SQLiteBackend(PersistenceBackend):
    async def store_task(self, task: Task) -> None:
        """Store task with transaction safety"""
        async with self.db.transaction():
            # Insert task
            await self.db.execute("""
                INSERT OR REPLACE INTO tasks 
                (id, workflow_id, name, protocol, method, parameters, 
                 status, priority, timeout_seconds, max_retries)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.id, task.workflow_id, task.name,
                task.protocol, task.method,
                json.dumps(task.parameters),
                task.status.value, task.priority,
                task.timeout_seconds, task.max_retries
            ))
            
            # Insert dependencies
            if task.dependencies:
                await self.db.executemany("""
                    INSERT OR IGNORE INTO task_dependencies 
                    (task_id, depends_on) VALUES (?, ?)
                """, [(task.id, dep) for dep in task.dependencies])
```

## Queue Priority System

### Priority Levels

```python
class TaskPriority(str, Enum):
    CRITICAL = "critical"    # System-critical tasks
    HIGH = "high"           # User-facing, time-sensitive
    NORMAL = "normal"       # Default priority  
    LOW = "low"            # Background, batch tasks
    BULK = "bulk"          # Large batch operations
```

### Priority Queue Implementation

```python
class PriorityQueue:
    def __init__(self):
        self._queues = {
            TaskPriority.CRITICAL: deque(),
            TaskPriority.HIGH: deque(),
            TaskPriority.NORMAL: deque(),
            TaskPriority.LOW: deque(),
            TaskPriority.BULK: deque()
        }
        self._priority_order = [
            TaskPriority.CRITICAL,
            TaskPriority.HIGH, 
            TaskPriority.NORMAL,
            TaskPriority.LOW,
            TaskPriority.BULK
        ]
    
    async def enqueue(self, task: Task) -> None:
        """Add task to appropriate priority queue"""
        queue = self._queues[task.priority]
        queue.append(task)
        
        await self._emit_event("queue:task_enqueued", {
            "task_id": task.id,
            "priority": task.priority,
            "queue_size": len(queue)
        })
    
    async def dequeue(self) -> Optional[Task]:
        """Get highest priority task available"""
        for priority in self._priority_order:
            queue = self._queues[priority]
            if queue:
                task = queue.popleft()
                await self._emit_event("queue:task_dequeued", {
                    "task_id": task.id,
                    "priority": priority
                })
                return task
        return None
```

### Priority Aging

To prevent starvation of low-priority tasks:

```python
class PriorityAging:
    def __init__(self, aging_interval: timedelta = timedelta(minutes=30)):
        self.aging_interval = aging_interval
    
    async def age_tasks(self, queue: PriorityQueue) -> None:
        """Promote old low-priority tasks"""
        now = datetime.utcnow()
        
        for priority in [TaskPriority.LOW, TaskPriority.BULK]:
            aged_tasks = []
            queue_tasks = queue._queues[priority]
            
            while queue_tasks:
                task = queue_tasks[0]
                age = now - task.created_at
                
                if age > self.aging_interval:
                    aged_task = queue_tasks.popleft()
                    # Promote to higher priority
                    aged_task.priority = TaskPriority.NORMAL
                    aged_tasks.append(aged_task)
                else:
                    break  # Queue is ordered by creation time
            
            # Re-enqueue aged tasks at higher priority
            for task in aged_tasks:
                await queue.enqueue(task)
```

## Task Lifecycle Management

### Task States

```python
class TaskStatus(str, Enum):
    PENDING = "pending"         # Waiting in queue
    QUEUED = "queued"          # Assigned to queue
    EXECUTING = "executing"     # Currently running
    COMPLETED = "completed"     # Successfully finished
    FAILED = "failed"          # Failed execution
    CANCELLED = "cancelled"     # Manually cancelled
    TIMEOUT = "timeout"        # Execution timeout
    RETRYING = "retrying"      # Scheduled for retry
```

### State Transitions

```
       ┌─────────┐
       │ PENDING │
       └────┬────┘
            │ submit
            ▼
       ┌─────────┐    ┌──────────┐
       │ QUEUED  │───▶│EXECUTING │
       └─────────┘    └────┬─────┘
            │               │
            │ cancel        │ success
            ▼               ▼
     ┌──────────┐    ┌───────────┐
     │CANCELLED │    │ COMPLETED │
     └──────────┘    └───────────┘
                            │
                     failure│timeout
                            ▼
                     ┌──────────┐    ┌──────────┐
                     │  FAILED  │───▶│RETRYING  │
                     └──────────┘    └────┬─────┘
                            │             │
                            │             │retry
                            ▼             ▼
                     ┌──────────────────────┐
                     │    QUEUED (retry)    │
                     └──────────────────────┘
```

### Task Metadata Tracking

```python
@dataclass
class TaskMetadata:
    """Extended task metadata for tracking and monitoring"""
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Execution tracking
    attempt_count: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None
    provider_id: Optional[str] = None
    
    # Performance metrics
    queue_time: Optional[timedelta] = None    # Time spent in queue
    execution_time: Optional[timedelta] = None  # Actual execution time
    total_time: Optional[timedelta] = None      # End-to-end time
    
    # Resource usage
    memory_usage: Optional[int] = None        # Peak memory in bytes
    cpu_time: Optional[float] = None          # CPU seconds used
    
    # Debugging info
    execution_node: Optional[str] = None      # Which node executed
    debug_info: Dict[str, Any] = field(default_factory=dict)
```

## Retry and Error Handling

### Retry Strategies

```python
class RetryStrategy(str, Enum):
    NONE = "none"                    # No retries
    FIXED = "fixed"                  # Fixed delay
    EXPONENTIAL = "exponential"      # Exponential backoff
    LINEAR = "linear"                # Linear backoff
    CUSTOM = "custom"                # Custom strategy
```

### Retry Configuration

```python
@dataclass
class RetryConfig:
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_attempts: int = 3
    initial_delay: timedelta = timedelta(seconds=1)
    max_delay: timedelta = timedelta(minutes=5)
    backoff_multiplier: float = 2.0
    jitter: bool = True              # Add randomization
    
    # Retry conditions
    retry_on_timeout: bool = True
    retry_on_provider_error: bool = True
    retry_on_validation_error: bool = False
    
    # Custom retry logic
    custom_retry_function: Optional[Callable] = None
```

### Retry Implementation

```python
class RetryManager:
    async def should_retry(self, task: Task, error: Exception) -> bool:
        """Determine if task should be retried"""
        if task.metadata.attempt_count >= task.retry_config.max_attempts:
            return False
        
        # Check retry conditions based on error type
        if isinstance(error, TaskTimeoutError):
            return task.retry_config.retry_on_timeout
        elif isinstance(error, ProviderError):
            return task.retry_config.retry_on_provider_error
        elif isinstance(error, ValidationError):
            return task.retry_config.retry_on_validation_error
        
        return True
    
    async def calculate_retry_delay(self, task: Task) -> timedelta:
        """Calculate delay before retry"""
        config = task.retry_config
        attempt = task.metadata.attempt_count
        
        if config.strategy == RetryStrategy.FIXED:
            delay = config.initial_delay
        elif config.strategy == RetryStrategy.LINEAR:
            delay = config.initial_delay * attempt
        elif config.strategy == RetryStrategy.EXPONENTIAL:
            delay = config.initial_delay * (config.backoff_multiplier ** attempt)
        elif config.strategy == RetryStrategy.CUSTOM:
            delay = await config.custom_retry_function(task, attempt)
        else:
            return timedelta(0)
        
        # Apply jitter to prevent thundering herd
        if config.jitter:
            jitter_factor = random.uniform(0.5, 1.5)
            delay = delay * jitter_factor
        
        # Clamp to max delay
        return min(delay, config.max_delay)
```

## Workflow Execution Patterns

### Sequential Execution

```yaml
name: "Sequential Data Processing"
execution_mode: "sequential"
tasks:
  - id: "extract"
    method: "data/extract"
    
  - id: "transform"  
    method: "data/transform"
    dependencies: ["extract"]
    parameters:
      input: "${extract.result}"
      
  - id: "load"
    method: "data/load"
    dependencies: ["transform"]
    parameters:
      data: "${transform.result}"
```

### Parallel Execution

```yaml
name: "Parallel Data Processing"
execution_mode: "parallel"
tasks:
  - id: "fetch_source_a"
    method: "data/fetch"
    parameters:
      source: "database_a"
      
  - id: "fetch_source_b"
    method: "data/fetch"
    parameters:
      source: "database_b"
      
  - id: "merge_data"
    method: "data/merge"
    dependencies: ["fetch_source_a", "fetch_source_b"]
    parameters:
      data_a: "${fetch_source_a.result}"
      data_b: "${fetch_source_b.result}"
```

### Fan-out/Fan-in Pattern

```yaml
name: "Fan-out Processing"
tasks:
  - id: "split_data"
    method: "data/split"
    parameters:
      chunk_size: 1000
      
  - id: "process_chunk_1"
    method: "data/process_chunk"
    dependencies: ["split_data"]
    parameters:
      chunk: "${split_data.result.chunks[0]}"
      
  - id: "process_chunk_2" 
    method: "data/process_chunk"
    dependencies: ["split_data"]
    parameters:
      chunk: "${split_data.result.chunks[1]}"
      
  - id: "merge_results"
    method: "data/merge_chunks"
    dependencies: ["process_chunk_1", "process_chunk_2"]
    parameters:
      chunks: ["${process_chunk_1.result}", "${process_chunk_2.result}"]
```

### Conditional Execution

```yaml
name: "Conditional Workflow"
tasks:
  - id: "validate_input"
    method: "validation/check"
    
  - id: "process_valid"
    method: "data/process"
    dependencies: ["validate_input"]
    conditions:
      - "${validate_input.result.is_valid} == true"
      
  - id: "handle_invalid"
    method: "error/handle"
    dependencies: ["validate_input"]  
    conditions:
      - "${validate_input.result.is_valid} == false"
```

## Performance Optimization

### Queue Optimization Strategies

1. **Batch Operations**
   ```python
   async def submit_tasks_batch(self, tasks: List[Task]) -> List[str]:
       """Submit multiple tasks in a single operation"""
       async with self.persistence.transaction():
           task_ids = []
           for task in tasks:
               task_id = await self._store_task(task)
               task_ids.append(task_id)
           
           # Bulk queue operations
           await self._enqueue_batch(tasks)
           
           return task_ids
   ```

2. **Connection Pooling**
   ```python
   # Redis connection pool
   redis_pool = aioredis.ConnectionPool.from_url(
       "redis://localhost:6379",
       max_connections=20,
       retry_on_timeout=True
   )
   
   # SQLite connection pool
   sqlite_pool = aiosqlite.Pool(
       database="gleitzeit.db",
       max_size=10,
       check_same_thread=False
   )
   ```

3. **Caching Strategies**
   ```python
   class CachedQueueManager:
       def __init__(self):
           self._task_cache = LRUCache(maxsize=1000)
           self._dependency_cache = LRUCache(maxsize=500)
       
       async def get_task(self, task_id: str) -> Optional[Task]:
           # Check cache first
           if task_id in self._task_cache:
               return self._task_cache[task_id]
           
           # Fetch from persistence
           task = await self.persistence.get_task(task_id)
           if task:
               self._task_cache[task_id] = task
           
           return task
   ```

### Memory Management

```python
class MemoryOptimizedQueue:
    def __init__(self, max_memory_mb: int = 100):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._current_memory = 0
        
    async def enqueue(self, task: Task) -> None:
        task_size = self._estimate_task_size(task)
        
        if self._current_memory + task_size > self.max_memory_bytes:
            # Spill to disk
            await self._spill_to_persistence()
        
        self._memory_queue.append(task)
        self._current_memory += task_size
    
    def _estimate_task_size(self, task: Task) -> int:
        """Estimate memory footprint of task"""
        return len(task.model_dump_json().encode('utf-8'))
```

## Monitoring and Observability

### Queue Metrics

```python
@dataclass
class QueueMetrics:
    """Comprehensive queue metrics"""
    
    # Current state
    total_tasks: int
    pending_tasks: int
    executing_tasks: int
    completed_tasks: int
    failed_tasks: int
    
    # Performance metrics
    average_queue_time: timedelta
    average_execution_time: timedelta
    throughput_per_minute: float
    
    # Queue health
    queue_depth_by_priority: Dict[TaskPriority, int]
    oldest_pending_task_age: timedelta
    worker_utilization: float
    
    # Error rates
    failure_rate: float
    timeout_rate: float
    retry_rate: float
    
    # Resource usage
    memory_usage_mb: float
    storage_usage_mb: float
    connection_pool_usage: float
```

### Health Checks

```python
class QueueHealthChecker:
    async def check_queue_health(self) -> HealthStatus:
        """Comprehensive queue health check"""
        checks = []
        
        # Check queue depths
        stats = await self.queue_manager.get_queue_stats()
        if stats['pending_tasks'] > 10000:
            checks.append(HealthCheck(
                name="queue_depth",
                status="warning", 
                message=f"High queue depth: {stats['pending_tasks']}"
            ))
        
        # Check persistence backend
        backend_health = await self.persistence.health_check()
        checks.append(backend_health)
        
        # Check memory usage
        memory_usage = await self._check_memory_usage()
        if memory_usage > 0.9:
            checks.append(HealthCheck(
                name="memory_usage",
                status="critical",
                message=f"High memory usage: {memory_usage:.1%}"
            ))
        
        return HealthStatus(checks=checks)
```

### Distributed Tracing

```python
class TracedQueueManager(QueueManager):
    async def submit_task(self, task: Task) -> str:
        """Task submission with distributed tracing"""
        with tracer.start_span("queue.submit_task") as span:
            span.set_attribute("task.id", task.id)
            span.set_attribute("task.protocol", task.protocol)
            span.set_attribute("task.method", task.method)
            span.set_attribute("task.priority", task.priority)
            
            try:
                task_id = await super().submit_task(task)
                span.set_attribute("task.submitted", True)
                return task_id
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR))
                raise
```

## Backup and Recovery

### Data Backup Strategies

```python
class BackupManager:
    async def create_backup(self, backup_path: str) -> None:
        """Create complete system backup"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"{backup_path}/gleitzeit_backup_{timestamp}"
        
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup tasks and workflows
        await self._backup_tasks(f"{backup_dir}/tasks.json")
        await self._backup_workflows(f"{backup_dir}/workflows.json")
        await self._backup_queue_state(f"{backup_dir}/queue_state.json")
        
        # Backup configuration
        await self._backup_config(f"{backup_dir}/config.json")
        
        # Create manifest
        manifest = {
            "backup_time": datetime.utcnow().isoformat(),
            "version": "v4.0",
            "components": ["tasks", "workflows", "queue_state", "config"]
        }
        
        with open(f"{backup_dir}/manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
    
    async def restore_backup(self, backup_path: str) -> None:
        """Restore from backup"""
        # Validate backup
        manifest_path = f"{backup_path}/manifest.json"
        if not os.path.exists(manifest_path):
            raise ValueError("Invalid backup: missing manifest")
        
        with open(manifest_path) as f:
            manifest = json.load(f)
        
        # Restore in correct order
        await self._restore_workflows(f"{backup_path}/workflows.json")
        await self._restore_tasks(f"{backup_path}/tasks.json")
        await self._restore_queue_state(f"{backup_path}/queue_state.json")
```

### Point-in-Time Recovery

```python
class PointInTimeRecovery:
    async def create_checkpoint(self) -> str:
        """Create recovery checkpoint"""
        checkpoint_id = f"checkpoint_{datetime.utcnow().timestamp()}"
        
        # Snapshot current state
        checkpoint_data = {
            "id": checkpoint_id,
            "timestamp": datetime.utcnow().isoformat(),
            "active_workflows": await self._snapshot_workflows(),
            "pending_tasks": await self._snapshot_pending_tasks(),
            "system_state": await self._snapshot_system_state()
        }
        
        await self.persistence.store_checkpoint(checkpoint_data)
        return checkpoint_id
    
    async def recover_to_checkpoint(self, checkpoint_id: str) -> None:
        """Recover system to specific checkpoint"""
        checkpoint = await self.persistence.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint not found: {checkpoint_id}")
        
        # Stop current operations
        await self.queue_manager.pause()
        
        try:
            # Restore state
            await self._restore_workflows(checkpoint["active_workflows"])
            await self._restore_tasks(checkpoint["pending_tasks"])
            await self._restore_system_state(checkpoint["system_state"])
            
        finally:
            # Resume operations
            await self.queue_manager.resume()
```

This comprehensive task queue and persistence architecture ensures Gleitzeit V4 can handle complex workflows reliably while maintaining high performance and fault tolerance.