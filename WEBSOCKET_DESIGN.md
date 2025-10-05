# Gleitzeit WebSocket Integration Design

## Overview
Design for adding event-driven WebSocket support to Gleitzeit API (port 8000) to enable real-time UI updates without polling.

## Current Architecture Analysis

### Existing Components
1. **Redis Streams**: Core event bus using Redis streams for workflow/task events
   - `workflow:submission` - New workflow submissions
   - `workflow:state` - Workflow state changes
   - `task:execution` - Task execution events
   - Event streams per workflow

2. **EventStore** (`/core/event_store.py`): Persists workflow/task events to Redis
   - Stores timeline events
   - Provides execution summaries
   - Tracks task execution order

3. **Workers**: Subscribe to Redis streams
   - `workflow_submission_worker` - Processes new workflows
   - `task_execution_worker` - Executes tasks
   - `workflow_monitor_worker` - Monitors workflow state

4. **API** (`/api/main.py`): REST API on port 8000
   - Has `app.state.redis` - Redis connection available
   - Uses FastAPI with lifespan events
   - Routes in separate files (`/api/routes/`)

5. **UI2** (port 3000): Current implementation
   - Has WebSocket endpoint with polling (to be replaced)

## Design Goals

✅ **Event-Driven**: No polling - use Redis Pub/Sub for real-time events
✅ **Architecture-Aligned**: Leverage existing EventStore and Redis infrastructure
✅ **Scalable**: Multiple API instances can broadcast to their own WebSocket clients
✅ **Non-Breaking**: Existing REST API continues to work
✅ **Selective Updates**: Clients can subscribe to specific workflows/tasks

## Proposed Architecture

```
┌─────────────┐
│   Workers   │────► Redis Streams ────► EventStore.record_event()
└─────────────┘             │
                            │
                            ▼
                    Redis Pub/Sub Channel
                   "gleitzeit:events"
                            │
                            ▼
┌─────────────────────────────────────────────┐
│  API (Port 8000)                            │
│  ┌───────────────────────────────────────┐  │
│  │  EventBroadcaster                     │  │
│  │  - Subscribes to Redis Pub/Sub       │  │
│  │  - Broadcasts to WebSocket clients   │  │
│  └───────────────────────────────────────┘  │
│              │                               │
│              ▼                               │
│  ┌───────────────────────────────────────┐  │
│  │  WebSocket Endpoint /ws/events        │  │
│  │  - Accepts client connections         │  │
│  │  - Handles subscriptions              │  │
│  │  - Manages connection lifecycle       │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
                    │
                    ▼
            ┌───────────────┐
            │  UI2 Browser  │
            │  WebSocket    │
            │  Client       │
            └───────────────┘
```

## Implementation Plan

### Phase 1: Core Event Broadcasting Infrastructure

#### 1.1 Create Event Broadcaster Service
**File**: `/src/gleitzeit/api/services/event_broadcaster.py`

```python
class EventBroadcaster:
    """Subscribes to Redis Pub/Sub and broadcasts to WebSocket clients"""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.pubsub = None
        self.active_connections: Set[WebSocket] = set()
        self.subscription_filters: Dict[WebSocket, Set[str]] = {}

    async def start(self):
        """Subscribe to Redis pub/sub channel"""

    async def stop(self):
        """Cleanup pub/sub subscription"""

    async def broadcast_event(self, event: dict):
        """Broadcast event to subscribed WebSocket clients"""

    async def add_client(self, websocket: WebSocket, filters: List[str]):
        """Add WebSocket client with optional workflow/task filters"""

    async def remove_client(self, websocket: WebSocket):
        """Remove WebSocket client"""
```

**Integration Points**:
- Uses existing `app.state.redis` connection
- Integrates with FastAPI lifespan events
- Filters events based on client subscriptions

#### 1.2 Modify EventStore to Publish Events
**File**: `/src/gleitzeit/core/event_store.py`

Add pub/sub publishing after recording events:

```python
async def record_event(self, event: WorkflowEvent):
    # ... existing code to store in Redis ...

    # NEW: Publish to pub/sub channel for WebSocket broadcasting
    await self.redis.publish(
        "gleitzeit:events",
        json.dumps({
            "type": "workflow_event",
            "workflow_id": event.workflow_id,
            "task_id": event.task_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "data": event.data
        })
    )
```

### Phase 2: WebSocket Endpoint

#### 2.1 Create WebSocket Route
**File**: `/src/gleitzeit/api/routes/websocket.py`

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..services.event_broadcaster import get_broadcaster

router = APIRouter()

@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint for real-time workflow/task events

    Client can send subscription filters:
    {
        "action": "subscribe",
        "workflow_ids": ["workflow-123", "workflow-456"],
        "task_ids": ["task-789"]
    }
    """
    broadcaster = get_broadcaster()
    await broadcaster.add_client(websocket, [])

    try:
        await websocket.accept()
        await websocket.send_json({"type": "connected"})

        while True:
            data = await websocket.receive_json()

            if data.get("action") == "subscribe":
                # Update client filters
                filters = data.get("workflow_ids", []) + data.get("task_ids", [])
                await broadcaster.update_filters(websocket, filters)

            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        await broadcaster.remove_client(websocket)
```

#### 2.2 Register WebSocket Route
**File**: `/src/gleitzeit/api/main.py`

```python
# Add to imports
from .routes import websocket as websocket_routes
from .services.event_broadcaster import EventBroadcaster, set_broadcaster

# In lifespan function - startup
async def lifespan(app: FastAPI):
    # ... existing startup code ...

    # Initialize event broadcaster
    broadcaster = EventBroadcaster(redis_url)
    await broadcaster.start()
    set_broadcaster(broadcaster)
    app.state.broadcaster = broadcaster

    yield

    # Cleanup
    await broadcaster.stop()
    # ... existing cleanup ...

# Register WebSocket routes
app.include_router(websocket_routes.router, tags=["websocket"])
```

### Phase 3: UI2 Integration

#### 3.1 Update UI2 to Connect to API WebSocket
**File**: `/src/gleitzeit/ui2/api/app.py`

Remove polling code (lines 222-248) and update to proxy to API WebSocket:

```python
# Remove poll_and_broadcast() function
# Remove @app.on_event("startup")

# Update WebSocket endpoint to be a proxy
@app.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket):
    """Proxy WebSocket connection to API"""
    await websocket.accept()

    # Connect to API WebSocket
    api_ws_url = API_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/events'

    async with websockets.connect(api_ws_url) as api_ws:
        # Bi-directional proxy
        async def forward_to_api():
            while True:
                data = await websocket.receive_text()
                await api_ws.send(data)

        async def forward_to_client():
            while True:
                data = await api_ws.recv()
                await websocket.send_text(data)

        await asyncio.gather(forward_to_api(), forward_to_client())
```

**OR** simpler approach - UI2 client connects directly to API:

#### 3.2 Update UI2 Frontend to Connect Directly to API
**File**: `/src/gleitzeit/ui2/templates/workflows.html`

```javascript
// Change WebSocket URL to connect to API instead of UI
const wsUrl = `ws://localhost:8000/ws/events`;  // API port
```

### Phase 4: Event Types & Message Format

#### 4.1 Event Message Structure
```json
{
  "type": "workflow_event",
  "workflow_id": "workflow-uuid",
  "task_id": "task-uuid",         // optional
  "event_type": "workflow.started|workflow.completed|task.started|task.completed|task.failed",
  "timestamp": "2025-10-02T10:30:00Z",
  "data": {
    "status": "running",
    "message": "Workflow started"
  }
}
```

#### 4.2 Client Subscription Messages
```json
{
  "action": "subscribe",
  "workflow_ids": ["workflow-123"],
  "task_ids": []
}
```

## Security Considerations

1. **Authentication**: WebSocket should use same auth as REST API
   - Check session/token on connection
   - Validate client can access requested workflows

2. **Rate Limiting**: Limit WebSocket connections per user
   - Reuse existing `RateLimitMiddleware` concepts

3. **Message Validation**: Validate all client messages
   - Sanitize workflow/task IDs
   - Prevent injection attacks

## Performance Considerations

1. **Connection Limits**: Set max WebSocket connections per API instance
   - Default: 1000 concurrent connections

2. **Event Filtering**: Only send relevant events to clients
   - Client subscribes to specific workflows
   - Server filters before broadcasting

3. **Backpressure**: Handle slow clients
   - Use asyncio queues with size limits
   - Drop messages if client can't keep up

## Configuration

Add to `gleitzeit.yaml`:

```yaml
websocket:
  enabled: true
  max_connections: 1000
  ping_interval: 30  # seconds
  message_queue_size: 100
```

## Testing Plan

1. **Unit Tests**:
   - EventBroadcaster subscribe/unsubscribe
   - Message filtering logic
   - Connection lifecycle

2. **Integration Tests**:
   - Submit workflow → WebSocket receives event
   - Task completion → WebSocket notified
   - Multiple clients receive broadcasts

3. **Load Tests**:
   - 100 concurrent WebSocket connections
   - 1000 events/second broadcast rate

## Migration Path

1. ✅ Phase 1: Implement API-side WebSocket (backward compatible)
2. ✅ Phase 2: Update UI2 to use API WebSocket
3. ✅ Phase 3: Remove UI2 polling code
4. ✅ Phase 4: Add authentication/authorization
5. ✅ Phase 5: Performance tuning

## Alternative Approaches Considered

### Alternative 1: Server-Sent Events (SSE)
- **Pros**: Simpler than WebSocket, HTTP-based
- **Cons**: Uni-directional, no client subscriptions
- **Decision**: Rejected - need bi-directional for subscriptions

### Alternative 2: Keep UI2 Polling
- **Pros**: Simple, already implemented
- **Cons**: Not event-driven, inefficient, 5-second delay
- **Decision**: Rejected - user explicitly requested no polling

### Alternative 3: Direct Redis Pub/Sub in UI2
- **Pros**: Truly event-driven
- **Cons**: UI2 needs direct Redis access, security concerns
- **Decision**: Rejected - breaks architecture, security risk

## Files to Create/Modify

### New Files:
1. `/src/gleitzeit/api/services/event_broadcaster.py` - Event broadcaster service
2. `/src/gleitzeit/api/routes/websocket.py` - WebSocket route
3. `/WEBSOCKET_DESIGN.md` - This document

### Modified Files:
1. `/src/gleitzeit/api/main.py` - Register WebSocket route, start broadcaster
2. `/src/gleitzeit/core/event_store.py` - Add pub/sub publishing
3. `/src/gleitzeit/ui2/api/app.py` - Remove polling, update WebSocket
4. `/src/gleitzeit/ui2/templates/workflows.html` - Connect to API WebSocket
5. `/gleitzeit.yaml` - Add WebSocket configuration

## Success Criteria

✅ WebSocket connects to API (port 8000) successfully
✅ Events published when workflows/tasks change state
✅ UI2 receives real-time updates without polling
✅ Multiple clients can connect and receive broadcasts
✅ Client can filter events by workflow/task ID
✅ Graceful handling of disconnections/reconnections
✅ No performance degradation under 100 concurrent connections

## Next Steps

1. Review and approve this design
2. Implement Phase 1 (Event Broadcaster)
3. Implement Phase 2 (WebSocket Endpoint)
4. Update UI2 to use new WebSocket
5. Test and validate
6. Remove polling code from UI2
