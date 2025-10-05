# WebSocket Error and Logging Broadcasting Design V2

## Overview

This document extends the WebSocket implementation to broadcast errors and logs by hooking into the **existing StatelessLogService infrastructure**. The system already has comprehensive error/log storage - we just need to broadcast these logs to WebSocket clients in real-time.

## Current WebSocket Implementation Audit

### What's Already Implemented

The WebSocket infrastructure is **already functional** for workflow/task events. Here's what exists:

#### 1. EventBroadcaster Service
**Location:** `/src/gleitzeit/api/services/event_broadcaster.py`

**Status:** ✅ Fully implemented

**Features:**
- Subscribes to Redis Pub/Sub channel `gleitzeit:events`
- Manages WebSocket client connections
- Broadcasts events to connected clients
- Supports workflow/task ID filtering
- Auto-reconnection handling
- Graceful cleanup on shutdown

**Key Code:**
```python
class EventBroadcaster:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.pubsub = None
        self.active_connections: Set[WebSocket] = set()
        self.subscription_filters: Dict[WebSocket, Set[str]] = {}

    async def start(self):
        """Subscribe to Redis pub/sub channel"""
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe('gleitzeit:events')
        self._listen_task = asyncio.create_task(self._listen_to_redis())

    async def broadcast_event(self, event: dict):
        """Broadcast event to subscribed WebSocket clients"""
        for websocket in self.active_connections:
            # Apply filters (workflow_id, task_id)
            filters = self.subscription_filters.get(websocket, set())
            if filters:
                workflow_id = event.get('workflow_id')
                task_id = event.get('task_id')
                if not (workflow_id in filters or task_id in filters):
                    continue
            await websocket.send_json(event)
```

#### 2. WebSocket Route
**Location:** `/src/gleitzeit/api/routes/websocket.py`

**Status:** ✅ Fully implemented

**Endpoint:** `ws://localhost:8000/ws/events`

**Features:**
- Accepts WebSocket connections
- Sends connection confirmation
- Handles subscription filter updates
- Responds to ping/pong
- Graceful disconnect handling

**Key Code:**
```python
@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    broadcaster = get_broadcaster()
    await websocket.accept()
    await broadcaster.add_client(websocket, [])

    await websocket.send_json({
        "type": "connected",
        "message": "WebSocket connected successfully"
    })

    # Listen for client messages (subscribe, ping, etc.)
    while True:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            filters = data.get("workflow_ids", []) + data.get("task_ids", [])
            await broadcaster.update_filters(websocket, filters)
```

#### 3. EventStore Integration
**Location:** `/src/gleitzeit/core/event_store.py:138-154`

**Status:** ✅ Fully implemented

**What It Does:**
- Stores workflow/task events in Redis Streams
- **Publishes events to `gleitzeit:events` Pub/Sub channel**
- EventBroadcaster picks up these events and broadcasts to WebSocket clients

**Key Code:**
```python
# Store in Redis stream
await self.redis.xadd(stream_key.encode(), event.to_redis_message(), ...)

# Publish to pub/sub channel for WebSocket broadcasting
await self.redis.publish(
    'gleitzeit:events',
    json.dumps({
        'type': 'workflow_event',
        'workflow_id': workflow_id,
        'task_id': task_id,
        'event_type': event_type.value,
        'timestamp': event.timestamp,
        'level': level.value,
        'data': data or {}
    })
)
```

#### 4. API Integration
**Location:** `/src/gleitzeit/api/main.py:87-93, 138-140`

**Status:** ✅ Fully implemented

**What It Does:**
- Initializes EventBroadcaster on startup
- Registers WebSocket route
- Cleans up on shutdown

**Key Code:**
```python
# Startup (line 87-93)
from .services.event_broadcaster import EventBroadcaster, set_broadcaster
broadcaster = EventBroadcaster(app.state.redis)
await broadcaster.start()
set_broadcaster(broadcaster)
app.state.broadcaster = broadcaster
logger.info("Event broadcaster initialized for WebSocket support")

# Shutdown (line 138-140)
if hasattr(app.state, 'broadcaster'):
    await app.state.broadcaster.stop()
```

#### 5. UI Client
**Location:** `/src/gleitzeit/ui2/templates/workflows.html:100-144`

**Status:** ✅ Fully implemented

**What It Does:**
- Connects to `ws://localhost:8000/ws/events`
- Handles `workflow_event` messages → reloads workflows
- Handles connection/disconnection
- Auto-reconnects after 5 seconds on disconnect
- Responds to ping

**Key Code:**
```javascript
const wsUrl = `${protocol}//localhost:8000/ws/events`;
ws = new WebSocket(wsUrl);

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    console.log('WebSocket message:', message);

    if (message.type === 'workflow_event') {
        // Reload workflows when workflow event received
        loadWorkflows();
    } else if (message.type === 'connected') {
        console.log('WebSocket connection confirmed:', message.message);
    }
};

ws.onclose = () => {
    console.log('WebSocket disconnected');
    wsReconnectTimeout = setTimeout(connectWebSocket, 5000);
};
```

### What Currently Broadcasts

**Events That Broadcast:** ✅
- `workflow:started`
- `workflow:completed`
- `workflow:failed`
- `task:ready`
- `task:started`
- `task:completed`
- `task:failed`
- `task:cancelled`
- All EventType events that go through EventStore

### What Does NOT Broadcast

**Logs/Errors That Don't Broadcast:** ❌

1. **Worker Errors** - Logged via `StatelessLogService.log_error()` but not published to Pub/Sub
   - Workflow validation failures
   - Task execution errors
   - Handler initialization failures
   - Configuration errors

2. **Worker Warnings** - Logged via `StatelessLogService.log_warning()` but not published to Pub/Sub
   - Unknown task types
   - Handler async init failures
   - Unknown result statuses

3. **Critical Errors** - Logged but not broadcast
   - System failures
   - Redis connection issues
   - Worker crashes

### Current Message Format

**workflow_event (Currently Broadcasts):**
```json
{
  "type": "workflow_event",
  "workflow_id": "workflow-uuid",
  "task_id": "task-uuid",
  "event_type": "workflow:started|task:failed|etc",
  "timestamp": "2025-10-02T10:30:00Z",
  "level": "important|normal|verbose",
  "data": {}
}
```

**log_event (WILL Broadcast - To Be Implemented):**
```json
{
  "type": "log_event",
  "level": "ERROR|WARNING|CRITICAL",
  "message": "Error message",
  "workflow_id": "workflow-uuid or null",
  "task_id": "task-uuid or null",
  "component": "workflow_loader|task_execution|system",
  "error_type": "ValidationError|ConnectionTimeout|etc",
  "log_id": "timestamp-uuid",
  "timestamp": "2025-10-02T10:30:00Z",
  "metadata": {}
}
```

### Current Filtering Capabilities

**Implemented:** ✅
- Filter by workflow_id
- Filter by task_id
- No filtering (receive all events)

**Not Implemented:** ❌
- Filter by message type (`workflow_event` vs `log_event`)
- Filter by log level (ERROR, WARNING, CRITICAL)
- Filter by component (workflow_loader, task_execution, etc.)

### Summary: What Needs to Change

**Existing Components (No Changes Required):**
- ✅ EventBroadcaster - Already listens to `gleitzeit:events` and broadcasts
- ✅ WebSocket Route - Already handles connections
- ✅ API Integration - Already initializes broadcaster
- ✅ Redis Pub/Sub Channel - Already set up as `gleitzeit:events`

**Components That Need Changes:**
1. ❌ **StatelessLogService** - Add Pub/Sub publishing to `log_error()`, `log_warning()`, `log_critical()`
2. ❌ **Workers** - Add missing `StatelessLogService.log_warning()` calls
3. ❌ **EventBroadcaster** - Add optional filtering by message type and log level
4. ❌ **UI Client** - Handle new `log_event` message type with error banners

## Current Infrastructure

### StatelessLogService (Already Exists!)

The system already has a complete logging infrastructure in `/src/gleitzeit/core/stateless_log_service.py`:

```python
class StatelessLogService:
    """
    Stateless log service with global index for efficient querying.

    Design:
    - Logs stored on workflow shard (locality)
    - Global index on shard 0 (queryability)
    - Metadata on shard 0 (for fetching from correct shard)
    """

    @staticmethod
    async def log_error(redis, message, workflow_id, task_id, component, ...)

    @staticmethod
    async def log_warning(redis, message, workflow_id, task_id, component, ...)

    @staticmethod
    async def log_info(redis, message, workflow_id, task_id, component, ...)

    @staticmethod
    async def query_logs(redis, workflow_id, level, limit, ...)
```

**Redis Keys Used:**
- `{shard:<n>}:log:error:<log_id>` - Full log entry on workflow shard
- `{shard:0}:log:global:error` - Global error index (sorted set by timestamp)
- `{shard:0}:log:meta:<log_id>` - Metadata for fetching
- `{shard:<n>}:log:workflow:<workflow_id>:errors` - Workflow-specific errors

### BaseWorker.log_worker_error (Already Exists!)

All workers inherit from BaseWorker which provides:

```python
async def log_worker_error(
    self,
    operation: str,
    error: Exception,
    workflow_id: Optional[str] = None,
    task_id: Optional[str] = None,
    **extra_metadata
):
    """Log worker error to Redis with full context."""
    from ..core.stateless_log_service import StatelessLogService

    await StatelessLogService.log_error(
        self.redis,
        message=f"{operation} failed: {str(error)}",
        workflow_id=workflow_id,
        task_id=task_id,
        component=self.config.worker_type,
        error_type=error.__class__.__name__,
        stack_trace=traceback.format_exc(),
        metadata=extra_metadata
    )
```

## Problem Statement

Currently:
1. ✅ Errors ARE logged to Redis via StatelessLogService
2. ✅ Logs ARE queryable via API endpoints
3. ❌ Logs are NOT broadcast in real-time to WebSocket clients
4. ❌ Users must poll or manually refresh to see errors

## Solution: Hook WebSocket into StatelessLogService

Instead of creating a new logging system, **extend StatelessLogService to also publish to Redis Pub/Sub** so EventBroadcaster can relay logs to WebSocket clients.

### Architecture

```
Worker Error Occurs
       ↓
StatelessLogService.log_error()
       ↓
   ┌────────────────────────┐
   │  Store in Redis        │
   │  (existing behavior)   │
   └────────────────────────┘
       ↓
   ┌────────────────────────┐
   │  NEW: Publish to       │
   │  gleitzeit:events      │
   │  (Pub/Sub channel)     │
   └────────────────────────┘
       ↓
EventBroadcaster (existing)
       ↓
WebSocket Clients
```

## Implementation Plan

### Phase 1: Extend StatelessLogService with Pub/Sub

Modify `/src/gleitzeit/core/stateless_log_service.py` to publish logs to the same `gleitzeit:events` channel used by EventStore:

```python
# src/gleitzeit/core/stateless_log_service.py

class StatelessLogService:

    @staticmethod
    async def log_error(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        error_type: Optional[str] = None,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """Log an error to Redis with global index."""

        # ... existing code to store in Redis ...

        # NEW: Publish to WebSocket pub/sub channel
        try:
            await redis.publish(
                'gleitzeit:events',
                json.dumps({
                    'type': 'log_event',
                    'level': 'ERROR',
                    'message': message,
                    'workflow_id': workflow_id or None,
                    'task_id': task_id or None,
                    'component': component,
                    'error_type': error_type,
                    'log_id': log_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': metadata or {}
                })
            )
        except Exception as e:
            # Don't fail if pub/sub fails - logging is more important
            import logging
            logging.error(f"Failed to publish log to WebSocket: {e}")

        return log_id

    @staticmethod
    async def log_warning(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """Log a warning to Redis with global index."""

        # ... existing code to store in Redis ...

        # NEW: Publish to WebSocket pub/sub channel
        try:
            await redis.publish(
                'gleitzeit:events',
                json.dumps({
                    'type': 'log_event',
                    'level': 'WARNING',
                    'message': message,
                    'workflow_id': workflow_id or None,
                    'task_id': task_id or None,
                    'component': component,
                    'log_id': log_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': metadata or {}
                })
            )
        except Exception as e:
            import logging
            logging.error(f"Failed to publish log to WebSocket: {e}")

        return log_id

    @staticmethod
    async def log_critical(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """Log a critical error to Redis with global index."""

        # ... implement similar to log_error with level=CRITICAL ...

        # NEW: Publish to WebSocket pub/sub channel
        try:
            await redis.publish(
                'gleitzeit:events',
                json.dumps({
                    'type': 'log_event',
                    'level': 'CRITICAL',
                    'message': message,
                    'workflow_id': workflow_id or None,
                    'task_id': task_id or None,
                    'component': component,
                    'log_id': log_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': metadata or {}
                })
            )
        except Exception as e:
            import logging
            logging.error(f"Failed to publish log to WebSocket: {e}")

        return log_id
```

### Phase 2: Verify Workers Are Using log_worker_error

Audit workers to ensure they're using `log_worker_error()` method:

**Already Using (Good!):**
- `workflow_loader_worker_v2.py:303` - calls `log_worker_error`
- `workflow_loader_worker_v2.py:353` - calls `log_worker_error`

**Need to Verify:**
- Check if all error locations in workers call `log_worker_error()`
- If not, add calls to ensure errors are logged

### Phase 3: Add Missing log_warning Calls

Workers currently log warnings to Python logger but not to Redis. Add StatelessLogService calls:

**workflow_loader_worker_v2.py:499**
```python
logger.warning(f"Unknown task type '{task_type}' in task '{task_id}', using placeholder protocol '{protocol}'")

# NEW: Also log to Redis/WebSocket
await StatelessLogService.log_warning(
    self.redis,
    message=f"Unknown task type '{task_type}', using placeholder protocol '{protocol}'",
    workflow_id=workflow_id,
    task_id=task_id,
    component='workflow_loader',
    metadata={
        'task_type': task_type,
        'protocol': protocol
    }
)
```

**task_execution_worker.py:147**
```python
logger.warning(f"Failed to async initialize handler {protocol}: {e}")

# NEW: Also log to Redis/WebSocket
await StatelessLogService.log_warning(
    self.redis,
    message=f"Failed to async initialize handler {protocol}: {e}",
    component='task_execution',
    metadata={'protocol': protocol}
)
```

**task_execution_worker.py:418**
```python
logger.warning(f"Unknown result status: {result.status} for task {task_id}")

# NEW: Also log to Redis/WebSocket
await StatelessLogService.log_warning(
    self.redis,
    message=f"Unknown result status: {result.status}",
    workflow_id=workflow_id,
    task_id=task_id,
    component='task_execution',
    metadata={'result_status': result.status}
)
```

### Phase 4: Update UI to Display Log Events

The EventBroadcaster already relays all messages from `gleitzeit:events` to WebSocket clients. Just need to handle the new `log_event` message type:

```javascript
// src/gleitzeit/ui2/templates/workflows.html

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    console.log('WebSocket message:', message);

    if (message.type === 'workflow_event') {
        // Existing - reload workflows on state change
        loadWorkflows();
    }
    else if (message.type === 'log_event') {
        // NEW - Display log event
        showLogEvent(message);
    }
    else if (message.type === 'connected') {
        console.log('WebSocket connection confirmed:', message.message);
    }
};

function showLogEvent(log) {
    // Display log based on severity
    if (log.level === 'ERROR' || log.level === 'CRITICAL') {
        showErrorNotification(log);
    } else if (log.level === 'WARNING') {
        showWarningNotification(log);
    }

    // Also log to console for debugging
    const consoleMethod = {
        'ERROR': console.error,
        'WARNING': console.warn,
        'CRITICAL': console.error,
        'INFO': console.info
    }[log.level] || console.log;

    consoleMethod(`[${log.component}] ${log.message}`, log.metadata);
}

function showErrorNotification(log) {
    const banner = document.createElement('div');
    banner.className = 'error-banner';
    banner.innerHTML = `
        <strong>${log.level}:</strong> ${log.message}
        ${log.workflow_id ? `<br><small>Workflow: ${log.workflow_id}</small>` : ''}
        ${log.task_id ? `<br><small>Task: ${log.task_id}</small>` : ''}
        <br><small>Component: ${log.component}</small>
        ${log.error_type ? `<br><small>Type: ${log.error_type}</small>` : ''}
    `;

    // Add close button
    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.onclick = () => banner.remove();
    banner.appendChild(closeBtn);

    document.body.prepend(banner);

    // Auto-dismiss after 15 seconds
    setTimeout(() => banner.remove(), 15000);
}

function showWarningNotification(log) {
    const banner = document.createElement('div');
    banner.className = 'warning-banner';
    banner.innerHTML = `
        <strong>WARNING:</strong> ${log.message}
        ${log.workflow_id ? `<br><small>Workflow: ${log.workflow_id}</small>` : ''}
        ${log.task_id ? `<br><small>Task: ${log.task_id}</small>` : ''}
        <br><small>Component: ${log.component}</small>
    `;

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.onclick = () => banner.remove();
    banner.appendChild(closeBtn);

    document.body.prepend(banner);

    // Auto-dismiss after 10 seconds
    setTimeout(() => banner.remove(), 10000);
}
```

**Add CSS:**

```css
.error-banner {
    background-color: #f8d7da;
    color: #721c24;
    padding: 12px 20px;
    border: 1px solid #f5c6cb;
    border-radius: 4px;
    margin: 10px;
    position: relative;
    animation: slideDown 0.3s ease-out;
}

.warning-banner {
    background-color: #fff3cd;
    color: #856404;
    padding: 12px 20px;
    border: 1px solid #ffeeba;
    border-radius: 4px;
    margin: 10px;
    position: relative;
    animation: slideDown 0.3s ease-out;
}

.error-banner button, .warning-banner button {
    position: absolute;
    top: 5px;
    right: 10px;
    background: none;
    border: none;
    font-size: 20px;
    cursor: pointer;
    color: inherit;
}

@keyframes slideDown {
    from {
        transform: translateY(-100%);
        opacity: 0;
    }
    to {
        transform: translateY(0);
        opacity: 1;
    }
}
```

## Message Format

### log_event Message Structure

```json
{
  "type": "log_event",
  "level": "ERROR|WARNING|CRITICAL|INFO|DEBUG",
  "message": "Human-readable error message",
  "workflow_id": "workflow-uuid or null",
  "task_id": "task-uuid or null",
  "component": "workflow_loader|task_execution|system|etc",
  "error_type": "ValidationError|ConnectionTimeout|etc (for errors)",
  "log_id": "timestamp-uuid",
  "timestamp": "2025-10-02T10:30:00Z",
  "metadata": {
    "additional": "context",
    "stack_trace": "...",
    "operation": "..."
  }
}
```

### Existing workflow_event (Unchanged)

```json
{
  "type": "workflow_event",
  "workflow_id": "workflow-uuid",
  "task_id": "task-uuid",
  "event_type": "workflow:started|task:failed|etc",
  "timestamp": "2025-10-02T10:30:00Z",
  "level": "important|normal|verbose",
  "data": {}
}
```

## Filtering and Subscription

Extend EventBroadcaster filtering to support log level filtering:

```python
# src/gleitzeit/api/services/event_broadcaster.py

async def broadcast_event(self, event: dict):
    """Broadcast event to subscribed WebSocket clients"""
    if not self.active_connections:
        return

    disconnected = set()
    for websocket in self.active_connections:
        try:
            # Check filters
            filters = self.subscription_filters.get(websocket, {})

            # Filter by workflow/task ID
            if filters.get('ids'):
                workflow_id = event.get('workflow_id')
                task_id = event.get('task_id')
                if not (workflow_id in filters['ids'] or task_id in filters['ids']):
                    continue

            # NEW: Filter by message type
            if filters.get('message_types'):
                if event.get('type') not in filters['message_types']:
                    continue

            # NEW: Filter by log level
            if event.get('type') == 'log_event' and filters.get('min_log_level'):
                level_priority = {
                    'DEBUG': 0, 'INFO': 1, 'WARNING': 2,
                    'ERROR': 3, 'CRITICAL': 4
                }
                min_level = level_priority.get(filters['min_log_level'], 0)
                event_level = level_priority.get(event.get('level'), 0)
                if event_level < min_level:
                    continue

            await websocket.send_json(event)
        except Exception as e:
            logger.error(f"Error broadcasting to WebSocket: {e}")
            disconnected.add(websocket)

    # Clean up disconnected clients
    for ws in disconnected:
        await self.remove_client(ws)
```

**Client Subscription Example:**

```javascript
// Subscribe to errors and warnings only
ws.send(JSON.stringify({
    action: "subscribe",
    workflow_ids: ["workflow-123"],
    message_types: ["workflow_event", "log_event"],
    min_log_level: "WARNING"  // Only show WARNING, ERROR, CRITICAL
}));
```

## Advantages of This Approach

1. **Reuses Existing Infrastructure** - No duplicate logging system
2. **Consistent Storage** - All logs still queryable via API
3. **Minimal Changes** - Only adds pub/sub publishing to existing service
4. **Non-Breaking** - Existing log_worker_error calls just work
5. **Comprehensive** - Captures all errors workers already log

## Testing Strategy

### Unit Tests

```python
# tests/test_websocket_log_broadcasting.py

async def test_log_error_broadcasts_to_websocket():
    """Test that log_error publishes to pub/sub channel"""
    # Mock redis
    redis = MockRedis()

    # Call log_error
    log_id = await StatelessLogService.log_error(
        redis,
        message="Test error",
        workflow_id="wf-123",
        task_id="task-456",
        component="test"
    )

    # Verify published to gleitzeit:events
    assert redis.published_to('gleitzeit:events')
    message = json.loads(redis.get_published_message('gleitzeit:events'))
    assert message['type'] == 'log_event'
    assert message['level'] == 'ERROR'
    assert message['message'] == 'Test error'
    assert message['workflow_id'] == 'wf-123'
```

### Integration Tests

```python
# tests/test_websocket_error_flow.py

async def test_error_appears_in_websocket():
    """Test complete flow: worker error -> WebSocket"""

    # 1. Submit workflow with validation error
    workflow = {...}  # Invalid workflow

    # 2. Connect WebSocket
    async with websocket_connect('ws://localhost:8000/ws/events') as ws:
        messages = []

        # 3. Submit workflow
        submit_workflow(workflow)

        # 4. Wait for log_event
        for _ in range(10):
            msg = await ws.receive_json(timeout=1)
            messages.append(msg)
            if msg.get('type') == 'log_event':
                break

        # 5. Verify error received
        log_events = [m for m in messages if m['type'] == 'log_event']
        assert len(log_events) > 0
        assert log_events[0]['level'] in ['ERROR', 'CRITICAL']
```

## Configuration

Add configuration to control log broadcasting:

```yaml
# gleitzeit.yaml

websocket:
  broadcast_logs: true
  min_broadcast_level: WARNING  # Only broadcast WARNING, ERROR, CRITICAL
  broadcast_info: false  # Don't broadcast INFO logs
  broadcast_debug: false  # Don't broadcast DEBUG logs
```

## Implementation Checklist

- [ ] Phase 1: Add pub/sub publishing to StatelessLogService
  - [ ] Modify `log_error()` to publish
  - [ ] Modify `log_warning()` to publish
  - [ ] Add `log_critical()` method with publishing
  - [ ] Ensure non-blocking (errors don't break logging)

- [ ] Phase 2: Audit worker error logging
  - [ ] Verify `workflow_loader_worker_v2` uses `log_worker_error`
  - [ ] Verify `task_execution_worker` uses `log_worker_error`
  - [ ] Add missing `log_worker_error` calls if needed

- [ ] Phase 3: Add warning logging to workers
  - [ ] `workflow_loader_worker_v2:499` - unknown task type
  - [ ] `task_execution_worker:147` - handler init failure
  - [ ] `task_execution_worker:418` - unknown result status

- [ ] Phase 4: Update UI
  - [ ] Handle `log_event` messages in workflows.html
  - [ ] Add error notification banner
  - [ ] Add warning notification banner
  - [ ] Add CSS styling

- [ ] Phase 5: Testing
  - [ ] Unit tests for pub/sub publishing
  - [ ] Integration test for error flow
  - [ ] Manual test with invalid workflow
  - [ ] Manual test with failing task

## Summary

This design leverages the existing StatelessLogService infrastructure rather than creating a new system. By simply adding Redis Pub/Sub publishing to the existing logging methods, all errors and warnings automatically broadcast to WebSocket clients through the existing EventBroadcaster.

**Key Changes:**
1. Extend StatelessLogService with pub/sub publishing (3 methods)
2. Add StatelessLogService.log_warning calls to workers (3 locations)
3. Update UI to handle log_event messages (JavaScript)
4. Add filtering support for log levels (optional)

This is much simpler than the V1 design because we're hooking into existing infrastructure instead of building parallel systems.
