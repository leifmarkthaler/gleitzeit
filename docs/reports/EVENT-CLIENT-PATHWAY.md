# Event-Driven Client Implementation Pathway

## Overview
Transform the Gleitzeit client from a polling-based architecture to an event-driven architecture that aligns with the server's event-driven design.

## Implementation Phases

### Phase 1: Core Event Infrastructure (Foundation)
**Goal**: Establish the event-driven foundation without breaking existing functionality.

#### 1.1 ClientEventBus Component
- **File**: `src/gleitzeit/client/events/client_event_bus.py`
- **Purpose**: Local event bus for client-side event handling
- **Features**:
  - Event registration and emission
  - Async event handlers
  - Event filtering and routing
  - Error handling for failed handlers

#### 1.2 WebSocket Manager
- **File**: `src/gleitzeit/client/events/websocket_manager.py`
- **Purpose**: Manage persistent WebSocket connections
- **Features**:
  - Auto-reconnection with exponential backoff
  - Connection health monitoring
  - Message queuing during disconnection
  - Multiple endpoint support

#### 1.3 Event Types and Models
- **File**: `src/gleitzeit/client/events/models.py`
- **Purpose**: Client-specific event types and models
- **Features**:
  - Client event types (connection, subscription, etc.)
  - Event serialization/deserialization
  - Type safety with Pydantic models

### Phase 2: Event-Driven Adapters (Integration)
**Goal**: Create adapters that support both polling and event-driven modes.

#### 2.1 EventDrivenAdapter Base
- **File**: `src/gleitzeit/client/adapters/event_driven.py`
- **Purpose**: Base adapter with event capabilities
- **Features**:
  - WebSocket connection management
  - Event subscription methods
  - Fallback to polling when needed
  - Hybrid operation mode

#### 2.2 EventAPIAdapter
- **File**: `src/gleitzeit/client/adapters/event_api.py`
- **Purpose**: API adapter with WebSocket support
- **Extends**: EventDrivenAdapter and APIAdapter
- **Features**:
  - WebSocket for events, REST for commands
  - Automatic event stream subscription
  - Server event translation to client events

#### 2.3 EventNativeAdapter
- **File**: `src/gleitzeit/client/adapters/event_native.py`
- **Purpose**: Native adapter with direct event bus access
- **Extends**: EventDrivenAdapter and NativeAdapter
- **Features**:
  - Direct subscription to server EventBus
  - In-process event handling (no WebSocket needed)
  - Zero-latency event delivery

### Phase 3: Event-Driven Mixins (Functionality)
**Goal**: Add event-driven capabilities to client mixins.

#### 3.1 EventWorkflowMixin
- **File**: `src/gleitzeit/client/mixins/event_workflow.py`
- **Purpose**: Event-driven workflow operations
- **Features**:
  - Subscribe to workflow events on submission
  - Real-time progress callbacks
  - Automatic completion detection
  - Event-based error handling

#### 3.2 EventTaskMixin
- **File**: `src/gleitzeit/client/mixins/event_task.py`
- **Purpose**: Event-driven task operations
- **Features**:
  - Task lifecycle event handlers
  - Real-time status updates
  - Retry event notifications
  - Result streaming via events

#### 3.3 EventMonitoringMixin
- **File**: `src/gleitzeit/client/mixins/event_monitoring.py`
- **Purpose**: Real-time monitoring via events
- **Features**:
  - Live metric updates
  - Performance event streams
  - Alert subscriptions
  - System event filtering

### Phase 4: EventDrivenClient (Integration)
**Goal**: Create the main event-driven client class.

#### 4.1 EventDrivenClient
- **File**: `src/gleitzeit/client/event_client.py`
- **Purpose**: Main event-driven client implementation
- **Features**:
  - Automatic WebSocket connection on init
  - Event handler decorators
  - Lifecycle management
  - Backward compatibility mode

#### 4.2 Event Handlers Registry
- **File**: `src/gleitzeit/client/events/handlers.py`
- **Purpose**: Default event handlers
- **Features**:
  - Task completion handlers
  - Workflow progress handlers
  - Error recovery handlers
  - Retry coordination handlers

### Phase 5: Testing and Migration (Validation)
**Goal**: Ensure reliability and provide migration path.

#### 5.1 Event Client Tests
- **Files**: `newtests/client/test_event_client.py`
- **Coverage**:
  - WebSocket connection/reconnection
  - Event subscription and delivery
  - Handler registration and execution
  - Fallback to polling mode

#### 5.2 Migration Guide
- **File**: `docs/EVENT_CLIENT_MIGRATION.md`
- **Content**:
  - Migration strategies
  - Code examples
  - Performance comparisons
  - Troubleshooting guide

## Implementation Order

### Week 1: Foundation
1. ClientEventBus (`client_event_bus.py`)
2. Event Models (`models.py`)
3. WebSocket Manager (`websocket_manager.py`)
4. Base tests for event bus

### Week 2: Adapters
1. EventDrivenAdapter base (`event_driven.py`)
2. EventAPIAdapter (`event_api.py`)
3. EventNativeAdapter (`event_native.py`)
4. Adapter tests

### Week 3: Mixins & Client
1. EventWorkflowMixin (`event_workflow.py`)
2. EventTaskMixin (`event_task.py`)
3. EventDrivenClient (`event_client.py`)
4. Integration tests

### Week 4: Polish & Migration
1. Event handlers (`handlers.py`)
2. EventMonitoringMixin (`event_monitoring.py`)
3. Migration guide
4. Performance testing

## Success Criteria

### Performance Metrics
- **Latency**: < 50ms event delivery (vs 1000ms+ polling)
- **CPU Usage**: 80% reduction in client CPU usage
- **Network Traffic**: 90% reduction in API calls
- **Server Load**: 70% reduction in status check requests

### Feature Completeness
- ✅ Real-time task status updates
- ✅ Live workflow progress tracking
- ✅ Automatic retry notifications
- ✅ Event filtering and subscriptions
- ✅ Graceful fallback to polling
- ✅ WebSocket auto-reconnection

### Compatibility
- ✅ Existing client code continues working
- ✅ Optional event-driven mode
- ✅ Gradual migration path
- ✅ No breaking API changes

## Risk Mitigation

### Technical Risks
1. **WebSocket Support**: Not all deployments support WebSocket
   - **Mitigation**: Automatic fallback to polling
   
2. **Event Ordering**: Events may arrive out of order
   - **Mitigation**: Event sequence numbers and buffering
   
3. **Memory Leaks**: Long-lived connections may leak memory
   - **Mitigation**: Periodic connection recycling

### Migration Risks
1. **Breaking Changes**: Existing code might break
   - **Mitigation**: Full backward compatibility layer
   
2. **Performance Regression**: New code might be slower
   - **Mitigation**: Comprehensive performance testing
   
3. **Adoption Resistance**: Users might not migrate
   - **Mitigation**: Clear benefits and easy migration

## Example Usage

### Current (Polling) Client
```python
# Polling-based approach
client = ModularGleitzeitClient()
await client.initialize()

# Submit task and poll for result
task = await client.submit_task(my_task)
result = await client.wait_for_task(task.id, timeout=300)  # Polls every second
```

### New Event-Driven Client
```python
# Event-driven approach
client = EventDrivenClient()
await client.initialize()

# Register event handlers
@client.on_event(EventType.TASK_COMPLETED)
async def on_task_complete(event):
    print(f"Task {event.task_id} completed with result: {event.result}")

@client.on_event(EventType.TASK_FAILED)
async def on_task_failed(event):
    print(f"Task {event.task_id} failed: {event.error}")

# Submit task - handlers automatically called on completion
task = await client.submit_task(my_task)
# No polling needed - events arrive instantly
```

## Next Steps

1. **Immediate**: Start implementing ClientEventBus
2. **This Week**: Complete Phase 1 (Core Infrastructure)
3. **Next Week**: Begin Phase 2 (Adapters)
4. **Testing**: Continuous integration testing throughout
5. **Documentation**: Update as we implement each component

---

**Ready to Start Implementation**: Phase 1.1 - ClientEventBus Component