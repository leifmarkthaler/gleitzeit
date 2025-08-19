# Task Management

## Task Lifecycle

Tasks in Gleitzeit follow a well-defined lifecycle managed by the ExecutionEngine:

```
PENDING → IN_PROGRESS → COMPLETED
    ↓         ↓             ↑
  FAILED ←  TIMEOUT ←  RETRYING
```

### Task States

- **PENDING**: Task queued, waiting for dependencies
- **IN_PROGRESS**: Currently executing
- **COMPLETED**: Successfully finished
- **FAILED**: Execution failed (may retry)
- **TIMEOUT**: Exceeded execution timeout
- **RETRYING**: Failed task being retried

## Task Definition

Tasks are defined in YAML workflows:

```yaml
- id: "my_task"
  method: "llm/chat"
  dependencies: ["previous_task"]
  parameters:
    model: "llama3.2"
    messages:
      - role: "user"
        content: "Process: ${previous_task.response}"
  timeout: 300
  retry_count: 3
```

### Required Fields

- `id`: Unique task identifier
- `method`: Protocol method (e.g., "llm/chat", "python/execute")

### Optional Fields

- `dependencies`: List of task IDs this task depends on
- `parameters`: Method-specific parameters
- `timeout`: Maximum execution time in seconds (default: 300)
- `retry_count`: Number of retry attempts (default: 3)

## Dependencies

### Basic Dependencies

```yaml
tasks:
  - id: "task1"
    method: "llm/chat"
    # No dependencies - runs first
    
  - id: "task2" 
    method: "llm/chat"
    dependencies: ["task1"]
    # Waits for task1 to complete
```

### Multiple Dependencies

```yaml
- id: "final_task"
  method: "python/execute"
  dependencies: ["analysis", "data_prep", "validation"]
  # Waits for ALL listed tasks to complete
```

### Dependency Resolution

The DependencyResolver ensures:
- Tasks execute in correct order
- Failed dependencies block dependent tasks
- Circular dependencies are detected and rejected
- Parameter substitution works correctly

## Parameter Substitution

Use results from completed tasks in dependent tasks:

### Basic Substitution

```yaml
parameters:
  content: "${previous_task.response}"
  count: ${data_task.count}
```

### Nested Field Access

```yaml
parameters:
  timeout: ${config_task.settings.timeout}
  model: "${llm_task.metadata.model_used}"
```

### Available Fields

Each completed task provides:
- `response`: Main task output
- `metadata`: Task execution metadata
- `duration`: Execution time
- `status`: Final task status

## Task Queue Management

### Queue Operations

The TaskQueue provides:
- Priority-based ordering
- Concurrent execution limits
- Dependency tracking
- Status monitoring

### Concurrent Execution

```python
# Configure max concurrent tasks
engine = ExecutionEngine(
    max_concurrent_tasks=10  # Adjust based on resources
)
```

## Error Handling

### Retry Logic

Tasks automatically retry on:
- Network timeouts
- Temporary provider unavailability
- Transient errors

Retry behavior:
- Exponential backoff (1s, 2s, 4s, 8s...)
- Configurable max attempts
- Different strategies per error type

### Failure Propagation

When a task fails:
1. Retry attempts are exhausted
2. Task marked as FAILED
3. Dependent tasks are cancelled
4. Workflow status updated

### Error Recovery

```yaml
# Task with custom retry settings
- id: "fragile_task"
  method: "llm/chat"
  retry_count: 5
  timeout: 600
  parameters:
    # Task configuration
```

## Monitoring Tasks

### Task Events

The system emits events for:
- Task started
- Task completed
- Task failed
- Task retrying

### Status Checking

```python
# Check task status
async with GleitzeitClient() as client:
    status = await client.get_task_status("task_id")
    print(f"Task {status.id}: {status.status}")
```

## Best Practices

### Task Design

1. **Keep tasks atomic**: Each task should do one thing well
2. **Use meaningful IDs**: Makes debugging easier
3. **Set appropriate timeouts**: Based on expected execution time
4. **Handle failures gracefully**: Design for retry scenarios

### Dependency Management

1. **Minimize dependencies**: Reduces complexity and failure points
2. **Use parallel execution**: Independent tasks can run concurrently
3. **Validate substitution**: Ensure referenced fields exist

### Performance

1. **Batch similar tasks**: Group related operations
2. **Optimize concurrent limits**: Balance throughput vs resource usage
3. **Monitor execution times**: Identify bottlenecks

## Task Persistence

Tasks are persisted through the unified persistence layer:

- **Status updates**: Tracked in real-time
- **Results**: Stored for parameter substitution
- **Metadata**: Execution context preserved
- **Retry history**: Full audit trail maintained

See [Unified Persistence](UNIFIED_PERSISTENCE.md) for storage details.