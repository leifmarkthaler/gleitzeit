# Gleitzeit Signals Documentation

## Overview

Signals provide a mechanism for external communication with running workflows in Gleitzeit. They enable workflows to wait for external events, approvals, or triggers before proceeding, making workflows interactive and event-driven.

## Architecture

The signal system follows Gleitzeit's stateless, provider-based architecture and is fully integrated with SystemManager:

```
┌─────────────────┐
│ SystemManager   │  Manages signal lifecycle
└────────┬────────┘
         │
┌────────▼────────┐
│ SignalManager   │  Coordinates signal services
└────────┬────────┘
         │
┌────────▼────────┐
│  Signal API     │  REST endpoints for sending signals
└────────┬────────┘
         │
┌────────▼────────┐
│ Signal Provider │  Handles signal/v1 protocol tasks
└────────┬────────┘
         │
┌────────▼────────┐
│ Signal Handler  │  Manages Redis state for signals
└────────┬────────┘
         │
┌────────▼────────┐
│ Redis Streams   │  Persistent signal storage
└────────┬────────┘
         │
┌────────▼────────┐
│ Signal Monitor  │  Background service processing signals
└─────────────────┘
```

## Components

### 1. SignalManager (`src/gleitzeit/signals/signal_manager.py`)
- Centralized management of signal services
- Integrated with SystemManager for lifecycle management
- Handles distributed mode with leader election
- Manages SignalMonitorService lifecycle
- Provides signal statistics and monitoring

### 2. Signal Provider (`src/gleitzeit/providers/signal_provider.py`)
- Implements the `signal/v1` protocol
- Registered with SystemManager via SimpleProviderHub
- Returns `TaskStatus.SLEEPING` for waiting operations
- Handles all signal-related task methods

### 3. Signal Task Handler (`src/gleitzeit/signals/handler.py`)
- Manages signal operations in Redis
- Registers signal waiters with metadata
- Handles timeout scheduling
- Supports different wait modes (single, any, all)

### 4. Signal Monitor Service (`src/gleitzeit/signals/monitor.py`)
- Background service that continuously monitors signal streams
- Processes incoming signals and wakes waiting tasks
- Handles signal timeouts via timer integration
- Managed by SignalManager (started/stopped automatically)

### 5. Signal API Routes (`src/gleitzeit/api/routes/signals.py`)
- REST endpoints for external signal interaction
- Authentication-aware signal sending
- Signal statistics and monitoring
- Uses SystemManager's persistence layer

## Signal Methods

### wait
Wait for a specific signal.

```yaml
- name: wait_for_approval
  protocol: signal/v1
  method: signal/wait
  params:
    signal: manager_approval
    timeout: 300  # Optional: timeout in seconds
```

### wait_any
Wait for any of multiple signals (first one wins).

```yaml
- name: wait_for_any_signal
  protocol: signal/v1
  method: signal/wait_any
  params:
    signals:
      - urgent_signal
      - normal_signal
      - low_priority_signal
    timeout: 60
```

### wait_all
Wait for all specified signals before proceeding.

```yaml
- name: wait_for_all_approvals
  protocol: signal/v1
  method: signal/wait_all
  params:
    signals:
      - manager_approval
      - director_approval
      - compliance_approval
    timeout: 3600
```

### send
Send a signal from within a workflow to another workflow.

```yaml
- name: notify_next_workflow
  protocol: signal/v1
  method: signal/send
  params:
    target_workflow: "{{next_workflow_id}}"
    signal: processing_complete
    payload:
      status: success
      processed_items: 100
```

### broadcast
Broadcast a signal to all workflows waiting for it.

```yaml
- name: broadcast_shutdown
  protocol: signal/v1
  method: signal/broadcast
  params:
    signal: system_shutdown
    payload:
      reason: maintenance
      resume_time: "2024-01-01T10:00:00Z"
```

## REST API Endpoints

### Send Signal to Workflow
```http
POST /signals/workflows/{workflow_id}/send
Content-Type: application/json
Authorization: Bearer <token>

{
  "signal_name": "manager_approval",
  "payload": {
    "approved": true,
    "manager": "john.doe",
    "notes": "Approved for production"
  }
}
```

### List Waiting Signals
```http
GET /signals/workflows/{workflow_id}/waiting
Authorization: Bearer <token>

Response:
{
  "workflow_id": "wf_123",
  "waiting_count": 2,
  "waiting_signals": [
    {
      "signal": "manager_approval",
      "task_id": "task_456",
      "timeout": 300,
      "created_at": "1234567890"
    }
  ]
}
```

### Broadcast Signal
```http
POST /signals/broadcast?signal_name=deployment_complete
Content-Type: application/json
Authorization: Bearer <token>

{
  "version": "1.2.3",
  "environment": "production"
}
```

### Get Signal Statistics
```http
GET /signals/stats
Authorization: Bearer <token>

Response:
{
  "signal_monitor": {
    "available": true,
    "running": true
  },
  "signal_waiters": {
    "manager_approval": 3,
    "system_ready": 1
  },
  "signal_streams": 5
}
```

## Usage Examples

### Example 1: Approval Workflow

```yaml
name: purchase_approval_workflow
version: 1.0.0

tasks:
  - name: submit_request
    protocol: python/v1
    method: python/execute
    params:
      file: submit_purchase_request.py

  - name: wait_manager_approval
    protocol: signal/v1
    method: signal/wait
    params:
      signal: manager_approval
      timeout: 86400  # 24 hours
    dependencies:
      - submit_request

  - name: process_approval
    protocol: python/v1
    method: python/execute
    params:
      file: process_approval.py
    dependencies:
      - wait_manager_approval
```

Python code to send approval:
```python
import requests

# Send approval signal
response = requests.post(
    f"http://localhost:8000/signals/workflows/{workflow_id}/send",
    json={
        "signal_name": "manager_approval",
        "payload": {
            "approved": True,
            "manager_id": "mgr_123",
            "approval_date": "2024-01-01"
        }
    },
    headers={"Authorization": f"Bearer {token}"}
)
```

### Example 2: Multi-Signal Coordination

```yaml
name: multi_approval_workflow
version: 1.0.0

tasks:
  - name: request_approvals
    protocol: python/v1
    method: python/execute
    params:
      file: send_approval_requests.py

  - name: wait_all_approvals
    protocol: signal/v1
    method: signal/wait_all
    params:
      signals:
        - legal_approval
        - finance_approval
        - technical_approval
      timeout: 7200  # 2 hours
    dependencies:
      - request_approvals

  - name: proceed_with_project
    protocol: python/v1
    method: python/execute
    params:
      file: start_project.py
    dependencies:
      - wait_all_approvals
```

### Example 3: Event-Driven Processing

```yaml
name: event_processor_workflow
version: 1.0.0

tasks:
  - name: initialize
    protocol: python/v1
    method: python/execute
    params:
      file: init_processor.py

  - name: wait_for_event
    protocol: signal/v1
    method: signal/wait_any
    params:
      signals:
        - high_priority_event
        - normal_event
        - batch_complete
      timeout: 3600
    dependencies:
      - initialize

  - name: process_event
    protocol: python/v1
    method: python/execute
    params:
      file: handle_event.py
    dependencies:
      - wait_for_event
```

## CLI Integration

Send signals via the Gleitzeit CLI:

```bash
# Send a signal to a workflow
gleitzeit signal send <workflow_id> <signal_name> --payload '{"key": "value"}'

# List waiting signals for a workflow
gleitzeit signal list <workflow_id>

# Broadcast a signal to all waiters
gleitzeit signal broadcast <signal_name> --payload '{"message": "hello"}'

# Get signal statistics
gleitzeit signal stats
```

## Signal State Management

Signals are managed in Redis with the following data structures:

1. **Signal Waiters Set**: `signal:{signal_name}:waiters`
   - Contains workflow:task pairs waiting for each signal

2. **Waiter Metadata Hash**: `signal:waiter:{signal_id}`
   - Stores detailed information about each waiter

3. **Signal Streams**: `workflow:signals:{workflow_id}`
   - Redis stream containing signals sent to a workflow

4. **Received Signals**: `signal:waiter:{signal_id}:received`
   - Tracks received signals for wait_all operations

## Timeout Handling

Signal timeouts are integrated with the timer system:
- Timeouts are registered as timer tasks
- Timer monitor processes timeouts
- On timeout, tasks wake with timeout status
- Cleanup of waiter registrations

## Best Practices

1. **Use Appropriate Timeouts**
   - Always set reasonable timeouts to prevent indefinite waiting
   - Consider business requirements for response times

2. **Signal Naming Conventions**
   - Use descriptive, action-oriented names: `approval_granted`, `data_ready`
   - Use consistent naming across workflows

3. **Payload Structure**
   - Keep payloads small and focused
   - Use structured data (JSON) for complex information
   - Include relevant context for decision making

4. **Error Handling**
   - Handle timeout scenarios gracefully
   - Provide fallback logic for missing signals
   - Log signal events for debugging

5. **Security Considerations**
   - Validate signal payloads
   - Use authentication for signal endpoints
   - Implement authorization checks for sensitive signals

## SystemManager Integration

The signal system is fully integrated with SystemManager and starts automatically when the server starts:

### Automatic Startup
When SystemManager initializes, it:
1. Creates a SignalManager instance with Redis persistence
2. Initializes the SignalTaskHandler and SignalMonitorService
3. Registers the signal provider with SimpleProviderHub
4. Starts the SignalMonitorService (in non-distributed mode or when leader)
5. Registers components in the distributed registry

### Configuration
Signal system can be configured via environment variables:
- `GLEITZEIT_SIGNAL_DISTRIBUTED`: Enable distributed mode (default: false)
- `GLEITZEIT_SIGNAL_MONITOR_INTERVAL`: Monitor check interval in seconds (default: 1.0)
- `GLEITZEIT_SIGNAL_BATCH_SIZE`: Number of signals to process per batch (default: 100)
- `GLEITZEIT_SIGNAL_LEADER_TTL`: Leader TTL in seconds for distributed mode (default: 30)

### Distributed Mode
In distributed mode:
- Only the leader instance runs the SignalMonitorService
- Leader election is handled by SystemManager
- SignalManager responds to leadership changes
- All instances can send/receive signals via Redis

## Performance Considerations

- **Scalability**: Signal system is stateless and horizontally scalable
- **Persistence**: All signal state stored in Redis, survives restarts
- **Monitoring**: Signal monitor runs as separate service, can be distributed
- **Efficiency**: Uses Redis Streams for efficient signal delivery
- **SystemManager**: Lifecycle managed by SystemManager for reliability

## Troubleshooting

### Common Issues

1. **Signals Not Received**
   - Check signal name spelling
   - Verify workflow is in RUNNING or SLEEPING state
   - Ensure signal monitor service is running

2. **Timeout Errors**
   - Verify timeout value is reasonable
   - Check if signals are being sent correctly
   - Review signal monitor logs

3. **Performance Issues**
   - Monitor Redis memory usage
   - Check signal stream sizes
   - Review number of concurrent waiters

### Debugging Commands

```bash
# Check Redis for signal waiters
redis-cli SMEMBERS "signal:manager_approval:waiters"

# View signal stream
redis-cli XRANGE "workflow:signals:wf_123" - +

# Check waiter metadata
redis-cli HGETALL "signal:waiter:signal_123"
```

## Integration with Other Systems

Signals can be triggered from:
- External webhooks
- CI/CD pipelines
- Monitoring systems
- User interfaces
- Other workflows
- Scheduled jobs

Example webhook integration:
```python
@app.post("/webhook/github")
async def github_webhook(payload: dict):
    # Process GitHub event
    if payload["action"] == "merged":
        # Send signal to deployment workflow
        await send_signal(
            workflow_id=deployment_workflow_id,
            signal="code_merged",
            payload={"pr_number": payload["number"]}
        )
```

## Recent Fixes

### Signal Task Completion Issue (FIXED)
**Status: FIXED** - Signal tasks were not completing when signals arrived.

**Issue Details:**
- Signal tasks remained in WAITING status even after receiving signals
- Signal monitor was only sending `signal_wake` events to workflow event streams
- No consumer was processing these events to complete the tasks

**Root Cause:** 
- SignalMonitorService wasn't receiving the event_bus instance
- Signal monitor only sent events to Redis streams, not to the event bus
- Unlike timer monitor which properly emitted TASK_COMPLETED events

**Solution Implemented:**
1. Pass event_bus to SignalMonitorService in SignalManager initialization
2. Update SignalMonitorService._wake_task to:
   - Set task status to COMPLETED in Redis
   - Store signal result in task data
   - Emit TASK_COMPLETED event to event bus (with fallback to Redis stream)
3. This matches the timer monitor's behavior exactly

**Files Modified:**
- `/src/gleitzeit/signals/signal_manager.py` - Pass event_bus to monitor
- `/src/gleitzeit/signals/monitor.py` - Complete tasks properly on signal wake

## Integration Status

The signal system is now fully operational:
- ✅ Signal provider registered in SimpleProviderHub
- ✅ Signal API routes registered in OpenAPI spec
- ✅ SignalManager initializes with event bus properly
- ✅ SignalMonitorService receives event bus for task completion
- ✅ Signal tasks complete when signals are received
- ✅ Workflow progression works after signal wake
- ✅ Signal functionality fully operational

## Future Enhancements

Planned improvements for the signal system:
- Signal filtering and routing rules
- Signal persistence and replay
- Signal analytics and metrics
- WebSocket support for real-time signaling
- Signal templates and schemas
- Advanced correlation patterns
- Fix event publishing in SignalManager initialization