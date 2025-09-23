# Event Timeline Documentation

## Overview

Gleitzeit provides comprehensive event tracking for workflow execution, enabling full visibility into what happens during workflow runs. Every significant state change is captured as an event, creating a complete timeline that can be viewed, analyzed, and used for replay.

## Event Types

### Workflow Events

| Event | When Emitted | Data Captured |
|-------|--------------|---------------|
| `WORKFLOW_STARTED` | Workflow submission accepted | worker_id, timestamp |
| `WORKFLOW_COMPLETED` | All tasks finished successfully | completed_tasks, skipped_tasks, blocked_tasks |
| `WORKFLOW_FAILED` | Workflow failed (has failed/blocked tasks) | failed_tasks, blocked_tasks, status |

### Task Lifecycle Events

| Event | When Emitted | Data Captured |
|-------|--------------|---------------|
| `TASK_READY` | Dependencies satisfied | is_initial, triggered_by, dependencies |
| `TASK_STARTED` | Execution begins | protocol, handler_id, execution_id |
| `TASK_COMPLETED` | Task succeeds | result, handler_id, worker_id |
| `TASK_FAILED` | Task fails | error, worker_id |
| `TASK_SKIPPED` | Validation causes skip | reason, validation_task, on_failure |
| `TASK_CANCELLED` | Task blocked by validation | reason, validation_task, status |

### Special Events

| Event | When Emitted | Data Captured |
|-------|--------------|---------------|
| `TASK_SLEEPING` | Timer task waiting | duration, wake_time |
| `TASK_WAITING` | Signal task waiting | signal_name, timeout |
| `WORKFLOW_RESUMED` | Replay started | replay_id, mode, tasks_to_replay |

## Event Levels

Events are categorized by importance:

- **CRITICAL** - State changes (started, completed, failed)
- **IMPORTANT** - Task ready, skipped, blocked
- **DETAIL** - Parameter resolution, validation checks
- **DEBUG** - Internal state, timing details

## Viewing the Timeline

### CLI Command

```bash
# View complete timeline
gleitzeit replay timeline <workflow_id>

# Filter by event level
gleitzeit replay timeline <workflow_id> --level important

# Show only critical events
gleitzeit replay timeline <workflow_id> --level critical
```

### Example Output

```
Timeline for workflow payment_flow_123:
================================================================================
[2024-01-20T10:30:00.123] 🏁 Workflow STARTED
[2024-01-20T10:30:00.234] ⏳ Task get_payment_info READY
    Initial task (no dependencies)
[2024-01-20T10:30:00.345] 🚀 Task get_payment_info STARTED
    Protocol: python/v1
    Execution ID: exec_abc123def456
[2024-01-20T10:30:00.567] ✅ Task get_payment_info COMPLETED
    Result: {"payment_type": "credit_card", "amount": 100}
[2024-01-20T10:30:00.678] ⏳ Task validate_credit_card READY
    Triggered by: get_payment_info
[2024-01-20T10:30:00.789] 🚀 Task validate_credit_card STARTED
    Protocol: validation/v1
[2024-01-20T10:30:00.890] ✅ Task validate_credit_card COMPLETED
    Result: {"valid": true}
[2024-01-20T10:30:00.901] ⏳ Task validate_paypal READY
    Triggered by: get_payment_info
[2024-01-20T10:30:01.012] 🚀 Task validate_paypal STARTED
    Protocol: validation/v1
[2024-01-20T10:30:01.123] ✅ Task validate_paypal COMPLETED
    Result: {"valid": false, "on_failure": "skip"}
[2024-01-20T10:30:01.234] ⏳ Task process_credit_card READY
    Triggered by: validate_credit_card
[2024-01-20T10:30:01.345] 🚀 Task process_credit_card STARTED
[2024-01-20T10:30:01.567] ✅ Task process_credit_card COMPLETED
[2024-01-20T10:30:01.678] ⏭️  Task process_paypal SKIPPED
    Reason: Validation validate_paypal returned false
    Validation: validate_paypal
[2024-01-20T10:30:01.789] 🎉 Workflow COMPLETED
    Completed: 5 tasks
    Skipped: 1 tasks
================================================================================
Summary:
  Total events: 15
  Tasks started: 5
  Tasks completed: 5
  Tasks skipped: 1
  Validation tasks: 2
```

## Programmatic Access

### Python API

```python
from gleitzeit.core.event_store import EventStore, EventLevel
from gleitzeit.core.events import EventType

# Initialize event store
event_store = EventStore(redis_client)

# Get complete timeline
timeline = await event_store.get_timeline(
    workflow_id='payment_flow_123',
    min_level=EventLevel.IMPORTANT
)

# Get specific events
timeline = await event_store.get_timeline(
    workflow_id='payment_flow_123',
    event_types=[EventType.TASK_FAILED, EventType.TASK_SKIPPED]
)

# Get execution order
task_order = await event_store.get_task_execution_order('payment_flow_123')
# Returns: ['get_payment_info', 'validate_credit_card', 'validate_paypal', 'process_credit_card']

# Get execution summary
summary = await event_store.get_execution_summary('payment_flow_123')
# Returns: {
#   'start_time': '2024-01-20T10:30:00',
#   'end_time': '2024-01-20T10:30:01',
#   'tasks_completed': 5,
#   'tasks_skipped': 1,
#   'validation_tasks': 2
# }
```

## Event Storage

### Redis Streams

Events are stored in Redis streams with automatic trimming:

```
Key: {shard:N}:events:{workflow_id}
Max Length: 10,000 events per workflow
TTL: 30 days (configurable)
```

### Configuration

```python
# In worker initialization
event_store = EventStore(redis_client, config={
    'max_events_per_workflow': 10000,    # Maximum events to keep
    'event_ttl_seconds': 86400 * 30,     # 30 days retention
    'batch_size': 100                    # Batch size for retrieval
})
```

## Use Cases

### 1. Debugging Workflow Execution

View the exact sequence of events to understand why a workflow behaved unexpectedly:

```bash
# See what happened
gleitzeit replay timeline failed_workflow_123

# Focus on failures
gleitzeit replay timeline failed_workflow_123 | grep "FAILED\|SKIPPED\|BLOCKED"
```

### 2. Performance Analysis

Analyze task timing to identify bottlenecks:

```python
timeline = await event_store.get_timeline(workflow_id)

for i, event in enumerate(timeline):
    if event.event_type == EventType.TASK_STARTED:
        # Find corresponding completion
        for j, end_event in enumerate(timeline[i:]):
            if (end_event.task_id == event.task_id and
                end_event.event_type == EventType.TASK_COMPLETED):
                duration = parse_time(end_event.timestamp) - parse_time(event.timestamp)
                print(f"Task {event.task_id}: {duration}ms")
                break
```

### 3. Audit Trail

Events provide an immutable audit log:

```python
# Get all state changes
audit_events = await event_store.get_timeline(
    workflow_id=workflow_id,
    min_level=EventLevel.CRITICAL  # Only state changes
)

for event in audit_events:
    print(f"{event.timestamp}: {event.event_type} - {event.task_id or 'workflow'}")
```

### 4. Replay Planning

Use timeline to understand execution order for replay:

```python
# Get task execution order
order = await event_store.get_task_execution_order(workflow_id)

# Replay in same order
for task_id in order:
    await replay_task(task_id)
```

### 5. XOR Pattern Visibility

See how conditional execution patterns played out:

```bash
# View validation decisions
gleitzeit replay timeline xor_workflow | grep "validate\|SKIPPED"

# Output shows which path was taken:
# ✅ Task validate_credit_card COMPLETED - Result: {"valid": true}
# ✅ Task validate_paypal COMPLETED - Result: {"valid": false}
# ⏭️ Task process_paypal SKIPPED - Validation: validate_paypal
```

## Comparing Executions

Compare two workflow runs to see differences:

```bash
# Compare two workflows
gleitzeit replay diff workflow_v1 workflow_v2

# Output:
# Comparing workflows:
#   Workflow 1: workflow_v1
#   Workflow 2: workflow_v2
# ================================================================================
# Execution Order:
#   [1] ✅ task_1
#   [2] ✅ validate_1
#   [3] ❌ task_2 != task_3  (different task executed)
#
# Execution Summary:
#   Tasks completed: 5 vs 4
#   Tasks skipped: 1 vs 2
```

## Integration with Replay

The event timeline is essential for replay functionality:

1. **Deterministic Replay** - Follow same execution order
2. **Selective Replay** - Only replay specific events
3. **Debug Replay** - Step through events one by one

```python
# Use timeline for replay
timeline = await event_store.get_timeline(workflow_id)

# Replay following original order
for event in timeline:
    if event.event_type == EventType.TASK_STARTED:
        await replay_task(event.task_id, event.data)
```

## Best Practices

1. **Use Appropriate Levels** - Emit CRITICAL for state changes, IMPORTANT for decisions
2. **Include Context** - Add relevant data to events for debugging
3. **Structured Data** - Use consistent event data formats
4. **Retention Policy** - Configure based on compliance/debugging needs
5. **Query Optimization** - Filter by level and type for performance

## Architecture & Scalability

### Stateless Design Maintained

The event system maintains Gleitzeit's stateless architecture:

- **Workers remain stateless** - Events are fire-and-forget writes to Redis
- **No inter-worker communication** - Events don't create dependencies
- **No state accumulation** - Workers hold nothing between messages
- **Pure computation** - Parameters still resolved on-demand

See [Stateless Event Architecture](../architecture/stateless_event_architecture.md) for detailed analysis.

### Scalability Preserved

Events don't affect horizontal scaling:

```yaml
# Scale identically with or without events
task_execution_worker:
  replicas: 100  # Each emits events independently

# No coordination needed between workers
```

Key properties:
- **Append-only operations** - O(1) complexity
- **Sharded by workflow** - Events follow task sharding
- **Bounded growth** - Auto-trimming prevents unbounded storage
- **Async emission** - Events don't block task execution

## Performance Considerations

- **Write Performance**: <1ms per event (async)
- **Storage**: ~100 bytes per event
- **Query Performance**:
  - Full timeline (1000 events): ~10ms
  - Filtered timeline: ~5ms
  - Execution summary: ~2ms
- **Impact on task execution**: +0.5ms async (non-blocking)

## Troubleshooting

### Missing Events

If events are missing:
1. Check worker has EventStore initialized
2. Verify Redis stream exists: `{shard:N}:events:{workflow_id}`
3. Check max_events_per_workflow setting

### Timeline Gaps

If timeline has gaps:
1. Some workers may not emit events (add event emission)
2. Event level filtering may exclude events
3. Events may have been trimmed (check retention)

## Task-Specific Timeline

For detailed visibility into individual task execution, see [Task Timeline Documentation](task_timeline.md). Key features:

- **Task Timeline Retrieval** - Get all events for a specific task
- **Task Execution Details** - Comprehensive execution information including timing, status, and results
- **CLI Commands** - `gleitzeit replay timeline <workflow_id> --task <task_id>`
- **API Integration** - Ready for UI endpoints

Example:
```python
# Get task-specific timeline
events = await event_store.get_task_timeline(workflow_id, task_id)

# Get detailed execution info
details = await event_store.get_task_execution_details(workflow_id, task_id)
```

## Future Enhancements

- **Event Webhooks** - Real-time event streaming
- **Event Aggregation** - Rollup events for long workflows
- **Event Replay** - Replay from event stream
- **Custom Events** - User-defined event types
- **Event Export** - Export to external systems (Datadog, etc.)

## Conclusion

The event timeline provides complete visibility into workflow execution, enabling debugging, performance analysis, audit trails, and intelligent replay. With comprehensive event coverage across all workers, you can understand exactly what happened during any workflow execution.