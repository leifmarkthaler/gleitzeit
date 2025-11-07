# Handler Identification and Event Tracing Design

## Overview

This document outlines a comprehensive system for identifying handlers, tracking their execution history, and capturing hardware/process metadata to enable full observability of task execution in Gleitzeit.

## Core Concepts

### Handler Identity Model

```python
@dataclass
class HandlerIdentity:
    """Unique identification for a handler instance"""

    # Unique IDs
    handler_id: str          # Unique handler instance ID (UUID)
    worker_id: str           # Worker that owns this handler
    protocol: str            # e.g., "ollama/v1"
    instance_url: str        # Backend URL (e.g., "http://localhost:11434")

    # Metadata
    created_at: datetime
    version: str             # Handler version
    capabilities_hash: str   # Hash of handler capabilities for change detection

    # Configuration
    config_hash: str         # Hash of handler configuration
    config_metadata: Dict    # Non-sensitive config info (timeouts, models, etc.)
```

### Handler Runtime Metadata

```python
@dataclass
class HandlerMetadata:
    """Runtime information about handler and its environment"""

    # Process Information
    process_id: int
    parent_process_id: int
    process_start_time: datetime
    python_version: str

    # System Information
    hostname: str
    os_name: str
    os_version: str
    cpu_count: int
    cpu_model: str
    memory_total_gb: float
    memory_available_gb: float

    # Network Information
    ip_address: str
    port: Optional[int]

    # Container/VM Information (if applicable)
    container_id: Optional[str]
    container_runtime: Optional[str]  # docker, kubernetes, etc.
    kubernetes_pod: Optional[str]
    kubernetes_namespace: Optional[str]

    # Hardware Acceleration (for AI workloads)
    gpu_available: bool
    gpu_model: Optional[str]
    gpu_memory_gb: Optional[float]
    cuda_version: Optional[str]

    # Handler-Specific Metadata
    backend_info: Dict[str, Any]  # e.g., Ollama model info, DB version
```

## Event History Tracking

### Event Model

```python
@dataclass
class HandlerEvent:
    """Single event in handler execution history"""

    event_id: str            # Unique event ID
    event_type: EventType    # STARTED, COMPLETED, FAILED, etc.
    timestamp: datetime

    # Context
    task_id: str
    workflow_id: str
    handler_id: str
    worker_id: str

    # Execution Details
    duration_ms: Optional[float]
    input_size_bytes: Optional[int]
    output_size_bytes: Optional[int]

    # Result
    status: str              # success, failed, timeout
    error: Optional[str]

    # Metadata
    metadata: Dict[str, Any]  # Additional event-specific data
```

### Event Types

```python
class EventType(Enum):
    # Lifecycle Events
    HANDLER_INITIALIZED = "handler_initialized"
    HANDLER_SHUTDOWN = "handler_shutdown"

    # Task Events
    TASK_RECEIVED = "task_received"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_RETRIED = "task_retried"
    TASK_TIMEOUT = "task_timeout"

    # Health Events
    HEALTH_CHECK_SUCCESS = "health_check_success"
    HEALTH_CHECK_FAILED = "health_check_failed"
    BACKEND_CONNECTED = "backend_connected"
    BACKEND_DISCONNECTED = "backend_disconnected"

    # Performance Events
    SLOW_EXECUTION = "slow_execution"
    MEMORY_WARNING = "memory_warning"
    RATE_LIMITED = "rate_limited"
```

## Storage Schema

### Redis Storage Structure

```
# Handler Registry
handler:registry:{handler_id} → Hash
  - handler_id
  - worker_id
  - protocol
  - instance_url
  - created_at
  - status (active/inactive)
  - last_heartbeat

# Handler Metadata
handler:metadata:{handler_id} → Hash
  - process_id
  - hostname
  - cpu_info
  - memory_info
  - gpu_info
  - backend_info

# Event History (Time Series)
handler:events:{handler_id} → Stream
  - event_id
  - event_type
  - timestamp
  - task_id
  - duration_ms
  - status

# Task-to-Handler Mapping
task:handler:{task_id} → String (handler_id)

# Handler Performance Metrics (Sliding Window)
handler:metrics:{handler_id}:{metric_name} → Sorted Set
  - timestamp → value
```

### Event History Retention

```yaml
retention_policy:
  events:
    default: 7d        # Keep all events for 7 days
    failed: 30d        # Keep failed task events for 30 days
    slow_execution: 14d # Keep slow execution events for 14 days

  aggregation:
    hourly: 30d        # Keep hourly aggregates for 30 days
    daily: 365d        # Keep daily aggregates for 1 year

  cleanup:
    batch_size: 1000
    interval: 1h
```

## Implementation Changes

### 1. Handler Base Class Enhancement

```python
class BaseHandler(ABC):
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)

        # Generate unique handler ID
        self.handler_id = str(uuid4())

        # Capture metadata at initialization
        self.metadata = self._capture_metadata()

        # Initialize event tracker
        self.event_tracker = HandlerEventTracker(self.handler_id)

        # Register handler
        self._register_handler()

    def _capture_metadata(self) -> HandlerMetadata:
        """Capture system and process metadata"""
        return HandlerMetadata(
            process_id=os.getpid(),
            hostname=socket.gethostname(),
            cpu_count=psutil.cpu_count(),
            memory_total_gb=psutil.virtual_memory().total / (1024**3),
            # ... more metadata
        )

    async def execute(self, task: Task) -> TaskResult:
        """Enhanced execute with event tracking"""
        # Record task received
        await self.event_tracker.record(EventType.TASK_RECEIVED, task_id=task.id)

        # Record task started
        start_event = await self.event_tracker.record(EventType.TASK_STARTED, task_id=task.id)

        try:
            # Execute task
            result = await self._execute_impl(task)

            # Record completion
            await self.event_tracker.record(
                EventType.TASK_COMPLETED,
                task_id=task.id,
                duration_ms=(time.time() - start_event.timestamp) * 1000,
                status="success"
            )

            # Store handler mapping
            await self._store_handler_mapping(task.id, self.handler_id)

            return result

        except Exception as e:
            # Record failure
            await self.event_tracker.record(
                EventType.TASK_FAILED,
                task_id=task.id,
                error=str(e)
            )
            raise
```

### 2. Task Result Enhancement

```python
@dataclass
class TaskResult:
    # Existing fields...

    # Handler tracking
    handler_id: Optional[str] = None
    worker_id: Optional[str] = None
    instance_url: Optional[str] = None

    # Execution metadata
    execution_metadata: Optional[Dict[str, Any]] = None
```

### 3. Event Tracker Component

```python
class HandlerEventTracker:
    """Tracks and stores handler events"""

    def __init__(self, handler_id: str):
        self.handler_id = handler_id
        self.redis = None  # Will be injected

    async def record(self, event_type: EventType, **kwargs) -> HandlerEvent:
        """Record an event"""
        event = HandlerEvent(
            event_id=str(uuid4()),
            event_type=event_type,
            timestamp=datetime.now(),
            handler_id=self.handler_id,
            **kwargs
        )

        # Store in Redis stream
        await self.redis.xadd(
            f"handler:events:{self.handler_id}",
            {
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
                "data": json.dumps(event.__dict__)
            }
        )

        # Update metrics
        await self._update_metrics(event)

        return event
```

## Query Interface

### Event History Queries

```python
class HandlerHistoryQuery:
    """Query interface for handler event history"""

    async def get_task_handler(self, task_id: str) -> HandlerInfo:
        """Get which handler processed a task"""
        handler_id = await redis.get(f"task:handler:{task_id}")
        return await self.get_handler_info(handler_id)

    async def get_handler_events(
        self,
        handler_id: str,
        event_types: Optional[List[EventType]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[HandlerEvent]:
        """Get events for a handler"""
        # Query Redis stream with filters
        pass

    async def get_task_trace(self, task_id: str) -> TaskTrace:
        """Get complete execution trace for a task"""
        handler_id = await redis.get(f"task:handler:{task_id}")
        events = await self.get_handler_events(
            handler_id,
            task_id=task_id
        )
        metadata = await redis.hgetall(f"handler:metadata:{handler_id}")

        return TaskTrace(
            task_id=task_id,
            handler_id=handler_id,
            handler_metadata=metadata,
            events=events
        )

    async def get_handler_performance(
        self,
        handler_id: str,
        metric: str = "duration_ms",
        period: str = "1h"
    ) -> PerformanceStats:
        """Get performance statistics for a handler"""
        # Query metrics from sorted sets
        pass
```

## Monitoring Dashboard Data

### Handler Overview
```json
{
  "handler_id": "uuid-1234",
  "protocol": "ollama/v1",
  "instance_url": "http://localhost:11434",
  "status": "active",
  "uptime": "2h 15m",
  "tasks_processed": 1523,
  "success_rate": 0.98,
  "avg_duration_ms": 1250,
  "current_load": 0.75
}
```

### Task Execution Trace
```json
{
  "task_id": "task-5678",
  "workflow_id": "workflow-1234",
  "handler": {
    "handler_id": "uuid-1234",
    "worker_id": "worker-1",
    "hostname": "node-1.cluster.local",
    "instance_url": "http://ollama-1:11434"
  },
  "events": [
    {
      "timestamp": "2024-01-19T10:00:00Z",
      "event": "task_received",
      "queue_depth": 15
    },
    {
      "timestamp": "2024-01-19T10:00:01Z",
      "event": "task_started",
      "input_size_bytes": 1024
    },
    {
      "timestamp": "2024-01-19T10:00:05Z",
      "event": "task_completed",
      "duration_ms": 4000,
      "output_size_bytes": 2048
    }
  ],
  "performance": {
    "total_duration_ms": 5000,
    "queue_time_ms": 1000,
    "execution_time_ms": 4000
  }
}
```

## Benefits

1. **Full Traceability**: Know exactly which handler instance processed each task
2. **Performance Analysis**: Identify slow handlers or instances
3. **Debugging**: Complete event history for troubleshooting
4. **Capacity Planning**: Understand handler utilization and performance
5. **Audit Trail**: Complete record of all task executions
6. **Hardware Optimization**: Track GPU usage, memory patterns, etc.

## Migration Path

### Phase 1: Basic Handler ID
- Add handler_id generation
- Store task-to-handler mapping
- Minimal changes required

### Phase 2: Metadata Collection
- Capture system/process metadata
- Store in Redis at startup
- Add to task results

### Phase 3: Event History
- Implement event tracker
- Store events in Redis streams
- Add query interface

### Phase 4: Analytics
- Implement aggregation
- Build monitoring dashboards
- Add alerting rules

## Storage Overhead

### Estimates
- Handler metadata: ~2KB per handler
- Event record: ~200 bytes per event
- Task mapping: ~50 bytes per task

### Example (1M tasks/day)
- Task mappings: 50MB/day
- Events (5 per task): 1GB/day
- With 7-day retention: ~7GB total

## Conclusion

This design provides comprehensive handler tracing and metadata collection while:
- Maintaining backward compatibility
- Keeping overhead manageable
- Enabling powerful debugging and monitoring capabilities
- Supporting future ML-based optimization (learning from execution patterns)

The phased implementation allows gradual adoption without disrupting existing workflows.