# Handler Tracking and Identification

## Overview

Gleitzeit 0.0.7 includes comprehensive handler tracking that provides full visibility into which handler instances process each task. This feature enables debugging, performance monitoring, and capacity planning across distributed deployments.

## Features

### 1. Unique Handler Identification

Every handler instance gets a unique ID and captures metadata about its environment:

```python
class BaseHandler:
    def __init__(self, config: Dict[str, Any] = None):
        self.handler_id = str(uuid.uuid4())  # Unique handler ID
        self.created_at = datetime.utcnow()
        self.metadata = self._capture_metadata()  # System info
```

### 2. System Metadata Capture

Handlers automatically capture:
- Process information (PID, Python version)
- System details (hostname, OS, CPU count)
- Memory statistics
- Configuration hash
- Backend instance URL (e.g., Ollama server URL)

### 3. Task Result Enhancement

TaskResult now includes handler tracking fields:

```python
@dataclass
class TaskResult:
    # ... existing fields ...

    # Handler tracking
    handler_id: Optional[str]           # Handler that executed the task
    worker_id: Optional[str]            # Worker that owns the handler
    provider_url: Optional[str]         # Provider/backend service URL (e.g., http://ollama:11434)
    worker_instance_url: Optional[str]  # Worker location (e.g., node-1.cluster.local)
```

### 4. Stream Message Enrichment

Existing Redis streams are enriched with handler data without breaking compatibility:

```python
# task:completed stream message
{
    b"workflow_id": workflow_id,
    b"task_id": task_id,
    b"result": result_json,
    # New handler tracking fields
    b"handler_id": handler_id,
    b"worker_id": worker_id,
    b"handler_protocol": protocol,
    b"provider_url": provider_url,           # Backend service URL
    b"worker_instance_url": worker_hostname  # Where worker runs
```

## Storage Schema

### Handler Registry
```
Key: handler:registry:{handler_id}
Type: Hash
TTL: 24 hours

Fields:
  handler_id: Unique handler instance ID
  handler_class: Handler class name (e.g., OllamaHandler)
  protocol: Protocol identifier (e.g., ollama/v1)
  worker_id: Worker that owns this handler
  worker_instance_url: Hostname where worker runs
  provider_url: Backend service URL (if applicable)
  created_at: Handler creation timestamp
  metadata: JSON with system/process info
```

### Task-to-Handler Mapping
```
Key: task:handler:{task_id}
Type: String
Value: handler_id
TTL: 24 hours
```

### Enhanced Task Data
```
Key: {shard:N}:task:status:{task_id}
Type: Hash

New fields:
  handler_id: Handler that processed the task
  worker_id: Worker that executed the task
```

### Enhanced Stream Messages
```
Stream: {shard:N}:task:completed

New fields in messages:
  handler_id: Handler instance ID
  worker_id: Worker ID
  handler_protocol: Protocol used
  provider_url: Backend service URL (e.g., Ollama endpoint)
  worker_instance_url: Worker hostname/location
```

## Usage Examples

### Finding Which Handler Processed a Task

```python
import redis.asyncio as aioredis

async def get_task_handler(task_id: str):
    redis = aioredis.from_url("redis://localhost:6379")
    
    # Quick lookup via mapping
    handler_id = await redis.get(f"task:handler:{task_id}")
    
    if handler_id:
        # Get handler details
        handler_info = await redis.hgetall(
            f"handler:registry:{handler_id.decode()}"
        )
        return handler_info
    
    return None
```

### Querying Handler Performance

```python
async def get_handler_tasks(handler_id: str):
    """Get all tasks processed by a specific handler"""
    redis = aioredis.from_url("redis://localhost:6379")
    
    # Find all task mappings
    all_mappings = await redis.keys(b"task:handler:*")
    
    tasks = []
    for key in all_mappings:
        stored_handler_id = await redis.get(key)
        if stored_handler_id and stored_handler_id.decode() == handler_id:
            task_id = key.decode().split(":")[-1]
            tasks.append(task_id)
    
    return tasks
```

### Monitoring Active Handlers

```python
async def list_active_handlers():
    """List all registered handlers"""
    redis = aioredis.from_url("redis://localhost:6379")
    
    handler_keys = await redis.keys(b"handler:registry:*")
    
    handlers = []
    for key in handler_keys:
        handler_data = await redis.hgetall(key)
        handlers.append({
            'handler_id': key.decode().split(':')[-1],
            'protocol': handler_data.get(b'protocol', b'').decode(),
            'worker_id': handler_data.get(b'worker_id', b'').decode(),
            'created_at': handler_data.get(b'created_at', b'').decode()
        })
    
    return handlers
```

### Analyzing Task Distribution

```python
async def analyze_task_distribution():
    """Analyze how tasks are distributed across handlers"""
    redis = aioredis.from_url("redis://localhost:6379")
    
    # Get all completed task streams
    streams = await redis.keys(b"*:task:completed")
    
    handler_counts = {}
    
    for stream_key in streams:
        messages = await redis.xrange(stream_key, "-", "+")
        
        for msg_id, data in messages:
            handler_id = data.get(b"handler_id")
            if handler_id:
                handler_id = handler_id.decode()
                handler_counts[handler_id] = handler_counts.get(handler_id, 0) + 1
    
    return handler_counts
```

## Configuration

### Worker Configuration with Handler Tracking

```yaml
# worker-config.yaml
worker:
  id: exec-worker-1
  type: TaskExecutionWorker
  
  # Handler configurations
  handler_configs:
    ollama/v1:
      base_url: http://ollama-1:11434
      timeout: 300
    
    python/v1:
      sandbox: true
      max_memory: 512MB
```

### Programmatic Configuration

```python
from gleitzeit.workers import TaskExecutionWorker, WorkerConfig

config = WorkerConfig(
    worker_id="exec-1",
    worker_type="TaskExecutionWorker",
    consumer_group="executors"
)

# Add handler configurations
config.handler_configs = {
    "ollama/v1": {
        "base_url": "http://localhost:11434",
        "worker_id": config.worker_id  # Link to worker
    }
}

worker = TaskExecutionWorker(config)
```

## Multi-Instance Deployment

### Running Multiple Ollama Instances

```bash
# Start multiple Ollama servers
ollama serve --port 11434 &  # Instance 1
ollama serve --port 11435 &  # Instance 2

# Start workers with different instances
python -m gleitzeit.workers.runner \
  --worker-id exec-1 \
  --handler-config ollama/v1:base_url=http://localhost:11434

python -m gleitzeit.workers.runner \
  --worker-id exec-2 \
  --handler-config ollama/v1:base_url=http://localhost:11435
```

### Load Distribution

With handler tracking, you can monitor and verify load distribution:

```python
async def check_instance_distribution():
    """Check distribution across Ollama instances"""
    redis = aioredis.from_url("redis://localhost:6379")
    
    instance_counts = {}
    
    # Check all task:completed streams
    streams = await redis.keys(b"*:task:completed")
    
    for stream in streams:
        messages = await redis.xrange(stream, "-", "+")
        
        for msg_id, data in messages:
            instance_url = data.get(b"instance_url")
            if instance_url:
                url = instance_url.decode()
                instance_counts[url] = instance_counts.get(url, 0) + 1
    
    print("Task distribution across instances:")
    for url, count in instance_counts.items():
        print(f"  {url}: {count} tasks")
```

## Monitoring and Debugging

### Debug a Failed Task

```python
async def debug_task(task_id: str):
    """Get complete execution trace for a task"""
    redis = aioredis.from_url("redis://localhost:6379")
    
    # Get handler ID
    handler_id = await redis.get(f"task:handler:{task_id}")
    
    if handler_id:
        handler_id = handler_id.decode()
        
        # Get handler details
        handler_info = await redis.hgetall(f"handler:registry:{handler_id}")
        
        print(f"Task {task_id} was processed by:")
        print(f"  Handler: {handler_id}")
        print(f"  Worker: {handler_info.get(b'worker_id', b'').decode()}")
        print(f"  Protocol: {handler_info.get(b'protocol', b'').decode()}")
        
        # Get metadata
        metadata = json.loads(handler_info.get(b'metadata', b'{}'))
        print(f"  Host: {metadata.get('hostname')}")
        print(f"  Process: {metadata.get('process_id')}")
        print(f"  Python: {metadata.get('python_version')}")
```

### Monitor Handler Health

```python
async def check_handler_health():
    """Check health of all registered handlers"""
    redis = aioredis.from_url("redis://localhost:6379")
    
    handler_keys = await redis.keys(b"handler:registry:*")
    
    for key in handler_keys:
        ttl = await redis.ttl(key)
        handler_data = await redis.hgetall(key)
        
        handler_id = key.decode().split(':')[-1]
        created_at = handler_data.get(b'created_at', b'').decode()
        
        # Calculate age
        from datetime import datetime
        created = datetime.fromisoformat(created_at)
        age = (datetime.utcnow() - created).total_seconds()
        
        print(f"Handler {handler_id[:8]}...")
        print(f"  Age: {age:.0f} seconds")
        print(f"  TTL: {ttl} seconds")
        print(f"  Status: {'Active' if ttl > 0 else 'Expired'}")
```

## Benefits

1. **Full Traceability**: Know exactly which handler instance processed each task
2. **Performance Analysis**: Identify slow handlers or overloaded instances
3. **Debugging**: Complete execution context for troubleshooting
4. **Capacity Planning**: Understand resource utilization patterns
5. **Audit Trail**: Complete record of all task executions
6. **Multi-Instance Support**: Track and balance across multiple backend instances

## Backward Compatibility

The handler tracking implementation is fully backward compatible:

- Existing consumers ignore unknown fields in streams
- Old workers continue functioning without handler tracking
- No changes required to existing workflows
- Gradual migration possible

## Performance Impact

- **Storage**: ~200 bytes per task for tracking data
- **Processing**: Negligible overhead (<1ms per task)
- **Network**: One additional Redis operation per task
- **Memory**: Handler metadata cached in memory (~2KB per handler)

## Best Practices

1. **Set Appropriate TTLs**: Use 24-hour TTL for handler registry to auto-cleanup
2. **Monitor Handler Distribution**: Regularly check task distribution across handlers
3. **Use Instance URLs**: Include backend URLs for multi-instance visibility
4. **Aggregate Metrics**: Periodically aggregate handler metrics for long-term analysis
5. **Clean Up Old Data**: Remove expired handler registries and mappings

## Troubleshooting

### Handler Not Found
```python
# Check if handler is registered
redis-cli keys "handler:registry:*"

# Check handler TTL
redis-cli ttl "handler:registry:handler-id"
```

### Missing Handler ID in Results
```python
# Verify handler is using create_result() helper
# Handler should use:
return self.create_result(task, status, result)

# Not:
return TaskResult(task_id=task.id, ...)
```

### Stream Messages Missing Handler Data
```python
# Check TaskExecutionWorker version
# Must be using updated emit_task_completed() method
# that includes handler tracking fields
```

## Future Enhancements

- Real-time handler monitoring dashboard
- Automatic handler health checks
- Handler performance profiling
- ML-based task routing optimization
- Handler auto-scaling based on load