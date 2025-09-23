# Task-Specific Timeline Documentation

## Overview

Gleitzeit provides granular task-level event tracking that enables detailed visibility into individual task execution within workflows. This feature is essential for debugging, performance analysis, and building UI dashboards that show task-specific execution details.

## Core Features

### Task Timeline Retrieval

Get all events related to a specific task within a workflow:

```python
from gleitzeit.core.event_store import EventStore

event_store = EventStore(redis_client)

# Get timeline for a specific task
events = await event_store.get_task_timeline(
    workflow_id="payment_flow_123",
    task_id="process_payment"
)

# Returns list of WorkflowEvent objects for this task
for event in events:
    print(f"[{event.timestamp}] {event.event_type}: {event.data}")
```

### Task Execution Details

Get comprehensive execution information for a task:

```python
# Get detailed task execution info
details = await event_store.get_task_execution_details(
    workflow_id="payment_flow_123",
    task_id="process_payment"
)

# Returns dictionary with:
# - Status (completed/failed/skipped/blocked/unknown)
# - Timing (start_time, end_time, duration_ms)
# - Execution details (protocol, execution_id, handler_id)
# - Results or errors
# - Retry information
# - Complete event history
```

## Data Structure

### Task Timeline Events

The `get_task_timeline()` method returns events that:
1. Have `task_id` matching the requested task
2. Are workflow-level events that reference the task in their data:
   - `tasks_to_replay` - Task marked for replay
   - `failed_tasks` - Task failed in workflow
   - `completed_tasks` - Task completed in workflow
   - `skipped_tasks` - Task was skipped
   - `blocked_tasks` - Task was blocked

### Task Execution Details Structure

```python
{
    'task_id': 'process_payment',
    'workflow_id': 'payment_flow_123',
    'status': 'completed',  # completed/failed/skipped/blocked/unknown
    'start_time': '2024-01-20T10:30:00.123',
    'end_time': '2024-01-20T10:30:01.456',
    'duration_ms': 1333.0,
    'execution_id': 'exec_abc123',
    'protocol': 'python/v1',
    'handler_id': 'payment_processor',
    'worker_id': 'worker_001',
    'result': {'payment_id': 'pay_123', 'status': 'success'},
    'error': None,
    'skip_reason': None,
    'validation_task': None,
    'retry_count': 0,
    'is_validation': False,
    'events': [
        {
            'timestamp': '2024-01-20T10:30:00.123',
            'type': 'task:started',
            'data': {...}
        },
        # ... more events
    ]
}
```

## CLI Commands

### View Task Timeline

```bash
# Show timeline for a specific task
gleitzeit replay timeline <workflow_id> --task <task_id>

# Example
gleitzeit replay timeline payment_flow_123 --task process_payment
```

### Get Task Details

```bash
# Show detailed execution info for a task
gleitzeit replay task-details <workflow_id> <task_id>

# Example
gleitzeit replay task-details payment_flow_123 process_payment
```

Example output:
```
📊 Task Execution Details
============================================================
Task ID: process_payment
Workflow ID: payment_flow_123
Status: COMPLETED
Protocol: python/v1
Execution ID: exec_abc123

⏱️  Timing:
  Started: 2024-01-20T10:30:00.123
  Ended: 2024-01-20T10:30:01.456
  Duration: 1333.0ms

✅ Result:
  {
    "payment_id": "pay_123",
    "status": "success",
    "amount": 100
  }

📜 Event History (5 events):
  [2024-01-20T10:30:00.000] ⏳ task:ready
  [2024-01-20T10:30:00.123] 🚀 task:started
  [2024-01-20T10:30:01.456] ✅ task:completed
```

## Use Cases

### 1. Debugging Task Failures

Understand why a specific task failed:

```python
details = await event_store.get_task_execution_details(workflow_id, task_id)

if details['status'] == 'failed':
    print(f"Task failed with error: {details['error']}")
    print(f"Failed at: {details['end_time']}")
    print(f"Worker: {details['worker_id']}")

    # Check if it was retried
    if details['retry_count'] > 0:
        print(f"Task was retried {details['retry_count']} times")
```

### 2. Performance Analysis

Analyze task execution duration:

```python
details = await event_store.get_task_execution_details(workflow_id, task_id)

if details['duration_ms']:
    if details['duration_ms'] > 5000:  # Tasks taking > 5 seconds
        print(f"Slow task detected: {task_id}")
        print(f"Duration: {details['duration_ms']}ms")
        print(f"Protocol: {details['protocol']}")
```

### 3. Validation Flow Analysis

Understand XOR patterns and validation decisions:

```python
details = await event_store.get_task_execution_details(workflow_id, task_id)

if details['status'] == 'skipped':
    print(f"Task skipped due to: {details['skip_reason']}")
    print(f"Validation task: {details['validation_task']}")

    # Get validation task details
    val_details = await event_store.get_task_execution_details(
        workflow_id,
        details['validation_task']
    )
    print(f"Validation result: {val_details['result']}")
```

### 4. UI Dashboard Integration

Build task execution views for web interfaces:

```python
from fastapi import FastAPI, HTTPException
from typing import Dict, Any

app = FastAPI()

@app.get("/api/workflows/{workflow_id}/tasks/{task_id}/timeline")
async def get_task_timeline_api(workflow_id: str, task_id: str) -> Dict[str, Any]:
    """API endpoint for task timeline"""
    event_store = EventStore(redis_client)

    # Get timeline events
    timeline = await event_store.get_task_timeline(workflow_id, task_id)

    # Get execution details
    details = await event_store.get_task_execution_details(workflow_id, task_id)

    if details['status'] == 'unknown':
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "workflow_id": workflow_id,
        "status": details['status'],
        "duration_ms": details['duration_ms'],
        "start_time": details['start_time'],
        "end_time": details['end_time'],
        "result": details['result'],
        "error": details['error'],
        "events": [
            {
                "timestamp": event.timestamp,
                "type": event.event_type.value,
                "data": event.data
            }
            for event in timeline
        ],
        "retry_count": details['retry_count'],
        "is_validation": details['is_validation']
    }

@app.get("/api/workflows/{workflow_id}/tasks/{task_id}/status")
async def get_task_status_api(workflow_id: str, task_id: str) -> Dict[str, Any]:
    """Lightweight endpoint for task status only"""
    event_store = EventStore(redis_client)

    details = await event_store.get_task_execution_details(workflow_id, task_id)

    return {
        "task_id": task_id,
        "status": details['status'],
        "duration_ms": details['duration_ms'],
        "is_running": details['status'] == 'started'
    }
```

### 5. Replay Analysis

Understand task behavior during replay:

```python
details = await event_store.get_task_execution_details(workflow_id, task_id)

# Check if task was replayed
if details['retry_count'] > 0:
    print(f"Task was replayed {details['retry_count']} time(s)")

    # Analyze event history to see both attempts
    for event in details['events']:
        if event['type'] == 'workflow:resumed':
            print(f"Replay initiated at: {event['timestamp']}")
            print(f"Replay mode: {event['data'].get('mode')}")
```

## Event Types for Tasks

Tasks can have the following events in their timeline:

| Event Type | Description | Key Data |
|------------|-------------|----------|
| `TASK_READY` | Task dependencies satisfied | `is_initial`, `triggered_by` |
| `TASK_STARTED` | Execution began | `protocol`, `execution_id`, `handler_id` |
| `TASK_COMPLETED` | Successfully finished | `result`, `worker_id` |
| `TASK_FAILED` | Execution failed | `error`, `worker_id` |
| `TASK_SKIPPED` | Skipped due to validation | `reason`, `validation_task` |
| `TASK_CANCELLED` | Blocked by validation | `reason`, `validation_task` |
| `TASK_SLEEPING` | Timer waiting | `duration`, `wake_time` |
| `TASK_WAITING` | Signal waiting | `signal_name`, `timeout` |
| `WORKFLOW_RESUMED` | Included in replay | `tasks_to_replay` containing task_id |

## Advanced Features

### Filtering Task Events

Get only specific event types for a task:

```python
# Get all events for the task
all_events = await event_store.get_task_timeline(workflow_id, task_id)

# Filter for specific types
failure_events = [
    e for e in all_events
    if e.event_type in [EventType.TASK_FAILED, EventType.TASK_CANCELLED]
]

# Get only execution events
execution_events = [
    e for e in all_events
    if e.event_type in [EventType.TASK_STARTED, EventType.TASK_COMPLETED]
]
```

### Task Comparison Across Workflows

Compare same task across different workflow runs:

```python
async def compare_task_performance(task_id: str, workflow_ids: List[str]):
    """Compare task performance across multiple workflow runs"""
    results = []

    for workflow_id in workflow_ids:
        details = await event_store.get_task_execution_details(workflow_id, task_id)
        if details['status'] != 'unknown':
            results.append({
                'workflow': workflow_id,
                'duration_ms': details['duration_ms'],
                'status': details['status'],
                'retry_count': details['retry_count']
            })

    # Analyze results
    durations = [r['duration_ms'] for r in results if r['duration_ms']]
    if durations:
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)

        print(f"Task '{task_id}' performance across {len(results)} workflows:")
        print(f"  Average duration: {avg_duration:.2f}ms")
        print(f"  Min/Max: {min_duration:.2f}ms / {max_duration:.2f}ms")
```

### Real-time Task Monitoring

Monitor task execution in real-time (useful for long-running tasks):

```python
async def monitor_task_execution(workflow_id: str, task_id: str):
    """Poll task status until completion"""
    import asyncio

    while True:
        details = await event_store.get_task_execution_details(workflow_id, task_id)

        if details['status'] in ['completed', 'failed', 'skipped', 'blocked']:
            print(f"Task finished with status: {details['status']}")
            if details['duration_ms']:
                print(f"Duration: {details['duration_ms']}ms")
            break

        elif details['status'] == 'started':
            elapsed = calculate_elapsed(details['start_time'])
            print(f"Task running for {elapsed}ms...")

        else:
            print(f"Task status: {details['status']}")

        await asyncio.sleep(1)  # Poll every second
```

## Integration with Event Monitor

Task timelines integrate with the system-wide event monitor:

```python
from gleitzeit.core.event_monitor import EventMonitor

monitor = EventMonitor(redis_client)

# Find all instances of a task across all workflows
all_task_events = await monitor.get_event_centric_timeline(
    event_types=[EventType.TASK_STARTED, EventType.TASK_COMPLETED],
    limit=1000,
    time_window=timedelta(hours=1)
)

# Filter for specific task name
task_name = "process_payment"
task_instances = [
    e for e in all_task_events
    if e.task_id and task_name in e.task_id
]

print(f"Found {len(task_instances)} instances of '{task_name}' in last hour")
```

## Performance Considerations

- **Timeline Retrieval**: O(n) where n is events in workflow (filtered in-memory)
- **Detail Extraction**: Single pass through task events
- **Duration Calculation**: Automatic, based on start/end timestamps
- **Storage**: No additional storage beyond existing event stream

## Best Practices

1. **Use Task Details for UI**: The `get_task_execution_details()` method provides everything needed for UI display in a single call

2. **Cache for Completed Tasks**: Task details for completed workflows can be cached as they won't change

3. **Monitor Long-Running Tasks**: Use timeline to detect stuck or slow tasks

4. **Correlate with Logs**: Use `execution_id` to correlate with application logs

5. **Track Validation Patterns**: Use task timelines to understand XOR pattern execution

## Troubleshooting

### Task Not Found

If `get_task_execution_details()` returns status 'unknown':
- Verify the workflow_id and task_id are correct
- Check if events are being properly emitted by workers
- Ensure Redis stream hasn't been trimmed or expired

### Missing Duration

If `duration_ms` is None:
- Task may not have completed (check status)
- Task may have been skipped before starting
- Timestamp parsing may have failed (check event timestamps)

### Incorrect Retry Count

If retry count seems wrong:
- Check for multiple WORKFLOW_RESUMED events
- Verify task_id is in the `tasks_to_replay` list
- Ensure events are ordered correctly by timestamp

## Future Enhancements

- **Task Metrics Aggregation**: Average duration, success rate per task type
- **Task Dependencies Visualization**: Show upstream/downstream tasks
- **Live Task Streaming**: WebSocket endpoint for real-time updates
- **Task Performance Alerts**: Notify when tasks exceed duration thresholds
- **Task Replay History**: Detailed view of all replay attempts

## Conclusion

Task-specific timelines provide granular visibility into individual task execution within workflows. This feature is essential for debugging, performance optimization, and building rich user interfaces that show detailed task execution information.