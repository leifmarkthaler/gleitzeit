# Signal Send and Broadcast Documentation

## Overview

Gleitzeit supports three types of signal operations for workflow synchronization and communication:
- **Wait** - Wait for signals to arrive
- **Send** - Send signals to specific workflows
- **Broadcast** - Send signals system-wide

## Signal Task Types

### 1. Signal Wait Operations

Wait for one or more signals before proceeding.

#### `signal/wait` - Wait for a single signal
```python
{
    'id': 'wait_for_approval',
    'type': 'signal',
    'signal_action': 'wait',
    'signal_name': 'approval-signal',
    'timeout': 60  # Optional timeout in seconds
}
```

#### `signal/wait_any` - Wait for any of multiple signals
```python
{
    'id': 'wait_for_any',
    'type': 'signal',
    'signal_action': 'wait_any',
    'signal_names': ['signal-a', 'signal-b', 'signal-c'],
    'timeout': 60
}
```

#### `signal/wait_all` - Wait for all specified signals
```python
{
    'id': 'wait_for_all',
    'type': 'signal',
    'signal_action': 'wait_all',
    'signal_names': ['config-ready', 'data-loaded', 'auth-complete'],
    'timeout': 120
}
```

### 2. Signal Send Operation

Send a signal to the current workflow or specific target workflows.

#### Send to Current Workflow (Default)
```python
{
    'id': 'send_internal',
    'type': 'signal',
    'signal_action': 'send',
    'signal_name': 'process-complete',
    'payload': {
        'status': 'success',
        'processed_items': 100
    }
    # No target_workflows specified - sends to current workflow
}
```

#### Send to Specific Workflows
```python
{
    'id': 'notify_others',
    'type': 'signal',
    'signal_action': 'send',
    'signal_name': 'data-ready',
    'target_workflows': ['workflow-abc123', 'workflow-def456'],
    'payload': {
        'data_location': '/path/to/data',
        'format': 'json'
    }
}
```

### 3. Signal Broadcast Operation

Broadcast a signal system-wide to all workflows.

```python
{
    'id': 'system_announcement',
    'type': 'signal',
    'signal_action': 'broadcast',
    'signal_name': 'maintenance-mode',
    'payload': {
        'message': 'System entering maintenance',
        'duration': 3600,
        'timestamp': '2024-01-01T12:00:00Z'
    }
    # No target needed - broadcasts to entire system
}
```

## Implementation Architecture

### Signal Handler Methods

The `SignalHandler` class implements the following methods:

| Method | Description | Required Params | Optional Params |
|--------|-------------|-----------------|-----------------|
| `signal/wait` | Wait for a single signal | `signal_name` | `timeout` |
| `signal/wait_any` | Wait for any signal from a list | `signal_names` | `timeout` |
| `signal/wait_all` | Wait for all signals in a list | `signal_names` | `timeout` |
| `signal/send` | Send signal to workflow(s) | `signal_name` | `payload`, `target_workflows` |
| `signal/broadcast` | Broadcast signal system-wide | `signal_name` | `payload` |

### Execution Flow

1. **Signal Send/Broadcast Tasks**:
   - SignalHandler validates parameters
   - Returns COMPLETED status with `emit_signal: true` metadata
   - TaskExecutionWorker detects the flag and calls StatelessSignalManager
   - Signal is emitted to appropriate scope

2. **Signal Wait Tasks**:
   - SignalHandler validates parameters
   - Returns WAITING status
   - SignalWorker monitors for matching signals
   - Task completes when signal(s) arrive or timeout occurs

### Scoping Rules

- **Send without targets**: Signal is sent only to the current workflow
- **Send with targets**: Signal is sent only to specified workflow IDs
- **Broadcast**: Signal is sent system-wide (no workflow filtering)

## Complete Examples

### Example 1: Internal Workflow Coordination
```python
workflow = {
    'name': 'data-processing',
    'tasks': [
        {
            'id': 'process_data',
            'type': 'python',
            'code': '# Process data here'
        },
        {
            'id': 'signal_complete',
            'type': 'signal',
            'signal_action': 'send',
            'signal_name': 'processing-done',
            'dependencies': ['process_data']
        },
        {
            'id': 'cleanup_task',
            'type': 'signal',
            'signal_action': 'wait',
            'signal_name': 'processing-done',
            'dependencies': ['signal_complete']
        },
        {
            'id': 'final_cleanup',
            'type': 'python',
            'code': '# Cleanup code',
            'dependencies': ['cleanup_task']
        }
    ]
}
```

### Example 2: Cross-Workflow Communication
```python
# Producer workflow
producer = {
    'name': 'data-producer',
    'tasks': [
        {
            'id': 'generate_data',
            'type': 'python',
            'code': '# Generate data'
        },
        {
            'id': 'notify_consumers',
            'type': 'signal',
            'signal_action': 'send',
            'signal_name': 'data-available',
            'target_workflows': ['consumer-1', 'consumer-2'],
            'payload': {
                'data_id': '12345',
                'size': 1024
            },
            'dependencies': ['generate_data']
        }
    ]
}

# Consumer workflow
consumer = {
    'name': 'data-consumer',
    'tasks': [
        {
            'id': 'wait_for_data',
            'type': 'signal',
            'signal_action': 'wait',
            'signal_name': 'data-available'
        },
        {
            'id': 'process_data',
            'type': 'python',
            'code': '# Process received data',
            'dependencies': ['wait_for_data']
        }
    ]
}
```

### Example 3: System-Wide Broadcast
```python
# Admin workflow
admin_workflow = {
    'name': 'admin-operations',
    'tasks': [
        {
            'id': 'announce_maintenance',
            'type': 'signal',
            'signal_action': 'broadcast',
            'signal_name': 'system-maintenance',
            'payload': {
                'start_time': '2024-01-01T22:00:00Z',
                'expected_duration': 7200
            }
        }
    ]
}

# Worker workflow (multiple instances)
worker_workflow = {
    'name': 'worker',
    'tasks': [
        {
            'id': 'monitor_system',
            'type': 'signal',
            'signal_action': 'wait',
            'signal_name': 'system-maintenance'
        },
        {
            'id': 'graceful_shutdown',
            'type': 'python',
            'code': '# Save state and shutdown',
            'dependencies': ['monitor_system']
        }
    ]
}
```

## Testing

### Unit Tests
Run the signal handler tests:
```bash
pytest tests/test_signal_send_handler.py -v
```

### Integration Tests
Test signal send/receive within a workflow:
```bash
python test_signal_send.py
```

Test broadcast to multiple workflows:
```bash
python test_signal_broadcast.py
```

## Best Practices

1. **Use appropriate scoping**:
   - Use default (current workflow) for internal coordination
   - Use targeted send for specific inter-workflow communication
   - Use broadcast sparingly for true system-wide events

2. **Include meaningful payloads**:
   - Add context information to help receiving tasks
   - Include timestamps for debugging
   - Keep payloads JSON-serializable

3. **Set reasonable timeouts**:
   - Always set timeouts on wait operations
   - Consider network latency and processing time
   - Handle timeout failures gracefully

4. **Naming conventions**:
   - Use descriptive signal names (e.g., `user-registration-complete`)
   - Consider namespacing for complex systems (e.g., `auth:login-success`)
   - Be consistent across workflows

## Migration Guide

If you have existing workflows using the old signal format:

### Old Format (Single Target)
```python
{
    'signal_action': 'send',
    'target_workflow': 'workflow-123'  # Single string
}
```

### New Format (Multiple Targets)
```python
{
    'signal_action': 'send',
    'target_workflows': ['workflow-123']  # List of strings
}
```

### For Current Workflow
Simply omit the `target_workflows` parameter:
```python
{
    'signal_action': 'send',
    'signal_name': 'my-signal'
    # Automatically sends to current workflow
}
```

## Troubleshooting

### Common Issues

1. **Signal not received**:
   - Check workflow IDs match exactly
   - Verify signal names are identical (case-sensitive)
   - Ensure SignalWorker is running for the target shard

2. **Broadcast not working**:
   - Confirm using `signal_action: 'broadcast'`
   - Check SignalWorker is running on all shards
   - Verify no workflow filtering in signal processing

3. **Timeout errors**:
   - Increase timeout value
   - Check if sender task is executing
   - Verify dependencies are correctly set

### Debug Tips

Enable debug logging for signal operations:
```python
import logging
logging.getLogger('gleitzeit.handlers.signal').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.workers.signal_worker').setLevel(logging.DEBUG)
```

Monitor Redis for signal activity:
```bash
redis-cli MONITOR | grep signal
```

## API Reference

### SignalHandler Class

```python
from gleitzeit.handlers.signal import SignalHandler

handler = SignalHandler()

# Get supported capabilities
capabilities = handler.get_capabilities()
# Returns: {
#     'protocol': 'signal/v1',
#     'task_types': ['signal', 'sync', 'event'],
#     'methods': {...}
# }
```

### Task Model

```python
from gleitzeit.core.models import Task

task = Task(
    id="signal-task-1",
    name="Send Notification",
    workflow_id="workflow-123",
    protocol="signal/v1",
    method="signal/send",
    params={
        "signal_name": "notification",
        "payload": {"message": "Hello"},
        "target_workflows": ["workflow-456"]
    }
)
```

### StatelessSignalManager

Used internally by TaskExecutionWorker:
```python
from gleitzeit.signals.stateless_signal_manager import StatelessSignalManager

# Send to specific workflow
signal_id = await StatelessSignalManager.send_signal(
    redis=redis_client,
    signal_name="my-signal",
    workflow_id="workflow-123",
    payload={"key": "value"}
)

# Broadcast (workflow_id=None)
signal_id = await StatelessSignalManager.send_signal(
    redis=redis_client,
    signal_name="system-event",
    workflow_id=None,  # Broadcast
    payload={"event": "maintenance"}
)
```