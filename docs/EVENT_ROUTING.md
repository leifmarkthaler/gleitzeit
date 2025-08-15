# Event Routing Architecture for Gleitzeit V4

## Overview

Gleitzeit V4 uses a centralized event-driven architecture where all components communicate through a unified event system. This document maps out the complete event flow between components, showing who emits what events and who listens to them.

## Core Event Types

All events follow the naming convention `{component}:{action}` and are defined in `core/events.py`.

### Event Categories

- **Engine Events**: `engine:*` - Execution engine lifecycle
- **Task Events**: `task:*` - Individual task execution lifecycle  
- **Workflow Events**: `workflow:*` - Workflow orchestration
- **Provider Events**: `provider:*` - Provider management and health
- **Queue Events**: `queue:*` - Task queue management
- **Pool Events**: `pool:*` - Provider pool scaling
- **Worker Events**: `worker:*` - Worker lifecycle in pools
- **Circuit Events**: `circuit:*` - Circuit breaker state changes
- **Health Events**: `health:*` - System health monitoring
- **System Events**: `system:*` - System-wide operations

## Component Event Matrix

### ExecutionEngine (`core/execution_engine.py`)

**Emits:**
- `engine:started` - When execution engine starts
- `engine:stopped` - When execution engine stops  
- `engine:paused` - When execution is paused
- `engine:resumed` - When execution resumes
- `task:started` - When a task begins execution
- `task:completed` - When a task completes successfully
- `task:failed` - When a task fails
- `task:timeout` - When a task times out
- `workflow:started` - When a workflow begins
- `workflow:completed` - When a workflow finishes
- `workflow:failed` - When a workflow fails

**Listens to:**
- `task:retry` - Scheduled retry events from EventScheduler
- `task:retry_executed` - Retry execution events
- Socket.IO events from central server coordination

**Event Flow:**
```
ExecutionEngine → emit_event() → EventHandlers → Socket.IO (if distributed)
     ↑                                              ↓
     └── scheduled events ← EventScheduler ← retry events
```

### EventScheduler (`core/scheduler.py`)

**Emits:**
- `task:retry` - When a scheduled retry is due
- `workflow:timeout` - When a workflow timeout occurs
- `health:check` - Scheduled health checks
- `cleanup` - Scheduled cleanup operations

**Listens to:**
- Schedule requests from ExecutionEngine
- Schedule requests from RetryManager
- Cancellation requests

**Event Flow:**
```
Components → schedule_event() → EventScheduler → emit_callback() → ExecutionEngine
                                      ↓
                               Internal timer loop
```

### RetryManager (`core/retry_manager.py`)

**Emits:**
- `task:retry_scheduled` - When a retry is scheduled
- `task:retry_executed` - When a retry is executed

**Listens to:**
- `task:failed` - To determine if retry is needed
- Retry events from EventScheduler

**Event Flow:**
```
ExecutionEngine → task:failed → RetryManager → schedule_retry() → EventScheduler
                                    ↓
                              task:retry_scheduled
```

### ProviderPool (`pooling/pool.py`)

**Emits:**
- `pool:scaled` - When pool size changes
- `pool:scaled_up` - When pool scales up
- `pool:scaled_down` - When pool scales down
- `pool:metrics` - Pool performance metrics
- `pool:scale_requested` - When scaling is requested

**Listens to:**
- `task:available` - To trigger scaling decisions
- `worker:*` - Worker state changes
- `backpressure:*` - Load pressure signals

**Event Flow:**
```
WorkerState → pool events → ProviderPool → scaling events → Central System
     ↑                           ↓
TaskQueue ← queue events ← BackpressureMonitor
```

### ProviderWorker (`pooling/worker.py`)

**Emits:**
- `worker:started` - When worker starts
- `worker:stopped` - When worker stops
- `worker:idle` - When worker becomes idle
- `worker:busy` - When worker starts processing
- `worker:failed` - When worker encounters error
- `worker:heartbeat` - Periodic health signals

**Listens to:**
- `task:available` - Tasks available for processing
- `task:claimed` - Task assignment confirmations

**Event Flow:**
```
TaskQueue → task:available → ProviderWorker → worker:busy → ProviderPool
              ↓                     ↓                         ↓
         task:claimed        worker:idle/failed        pool scaling decisions
```

### CircuitBreaker (`pooling/circuit_breaker.py`)

**Emits:**
- `circuit:opened` - When circuit opens due to failures
- `circuit:closed` - When circuit closes (recovery)
- `circuit:half_open` - When testing recovery

**Listens to:**
- `task:failed` - To track failure rates
- `task:completed` - To track success rates
- `provider:error` - Provider-level errors

**Event Flow:**
```
TaskResults → failure tracking → CircuitBreaker → circuit:* → ProviderPool/Router
                                      ↓
                               blocks task routing
```

### BackpressureMonitor (`pooling/backpressure.py`)

**Emits:**
- `backpressure:normal` - Normal load conditions
- `backpressure:high` - High load detected
- `backpressure:critical` - Critical load levels

**Listens to:**
- `queue:task_enqueued` - Queue depth changes
- `pool:metrics` - Pool utilization
- `worker:busy` / `worker:idle` - Worker state changes

**Event Flow:**
```
QueueManager → queue depth → BackpressureMonitor → backpressure:* → ProviderPool
WorkerStates → utilization ↗                                         ↓
                                                              scaling decisions
```

### QueueManager (`task_queue/task_queue.py`)

**Emits:**
- `queue:task_enqueued` - When task is added to queue
- `queue:task_dequeued` - When task is removed from queue
- `queue:full` - When queue reaches capacity
- `queue:empty` - When queue becomes empty
- `queue:priority_changed` - When task priority changes

**Listens to:**
- Task submission requests
- Priority update requests

**Event Flow:**
```
TaskSubmission → QueueManager → queue:task_enqueued → BackpressureMonitor
                      ↓                                       ↓
              queue:task_dequeued ← WorkerRequest    backpressure:* → ProviderPool
```

### DependencyResolver (`task_queue/dependency_resolver.py`)

**Emits:**
- Task resolution events (via QueueManager)
- Dependency validation events

**Listens to:**
- `task:completed` - To resolve dependent tasks
- `task:failed` - To handle dependency failures

**Event Flow:**
```
ExecutionEngine → task:completed → DependencyResolver → resolved tasks → QueueManager
                                          ↓
                                  parameter substitution
```

### HealthMonitor (hypothetical component)

**Emits:**
- `health:check_started` - Health check initiated
- `health:check_completed` - Health check finished
- `health:check_failed` - Health check failed
- `metrics:collected` - System metrics gathered
- `alert:triggered` - Alert conditions met

**Listens to:**
- `health:check` - Scheduled health checks
- All component events for monitoring

**Event Flow:**
```
EventScheduler → health:check → HealthMonitor → health:check_* → AlertSystem
AllComponents → all events ↗                        ↓
                                            metrics:collected → Monitoring
```

## Event Correlation and Tracing

### Correlation IDs

All events include correlation IDs for tracing related operations:

- **Workflow ID**: Links all events in a workflow execution
- **Task ID**: Links events for individual task execution  
- **Request ID**: Links events for external requests

### Event Tracing Flow

```
Workflow Submission (correlation_id: workflow-123)
├── workflow:started (workflow-123)
├── task:started (workflow-123, task-1)
├── task:completed (workflow-123, task-1)
├── task:started (workflow-123, task-2)
├── task:failed (workflow-123, task-2)
├── task:retry_scheduled (workflow-123, task-2)
├── task:retry_executed (workflow-123, task-2)
├── task:completed (workflow-123, task-2)
└── workflow:completed (workflow-123)
```

## Socket.IO Event Distribution

### Central Hub Communication

In distributed mode, events flow through the central Socket.IO hub:

```
Component A → emit_event() → Local Handler → Socket.IO emit → Central Hub
                                                                  ↓
Central Hub → Socket.IO broadcast → Component B → event_handler()
```

### Event Namespacing

Events are namespaced by component in Socket.IO:

- `/engine` - Execution engine events
- `/queue` - Queue management events
- `/pool` - Provider pool events
- `/health` - Health monitoring events

## Event Handler Registration

### Component Registration Pattern

```python
class MyComponent(SocketIOComponent):
    def __init__(self):
        super().__init__()
        self.register_event_handlers()
    
    def register_event_handlers(self):
        self.on_event('task:completed', self.handle_task_completion)
        self.on_event('pool:scaled', self.handle_pool_scaling)
    
    async def handle_task_completion(self, event_name, event_data):
        # Process task completion
        await self.emit_correlated('dependent:task:ready', result, event_data)
```

### Event Handler Chain

```
Event Source → emit_event() → Event Router → Handler Registry → Component Handlers
                                   ↓
                            correlation tracking → Event Store → Monitoring
```

## Error Event Propagation

### Error Escalation Chain

```
Provider Error → provider:error → ProviderPool → pool:scale_down
     ↓
CircuitBreaker → circuit:opened → Router → method:unavailable
     ↓
TaskExecution → task:failed → RetryManager → task:retry_scheduled
     ↓
WorkflowManager → workflow:failed → AlertSystem → alert:triggered
```

### Error Recovery Events

```
Provider Recovery → provider:started → ProviderPool → pool:scale_up
                                           ↓
CircuitBreaker → circuit:closed → Router → method:available
                        ↓
BackpressureMonitor → backpressure:normal → QueueManager
```

## Performance Monitoring Events

### Metrics Collection Flow

```
All Components → performance events → MetricsCollector → metrics:collected
                                           ↓
                                  MetricsStore → dashboard updates
                                           ↓
                                  AlertRules → alert:triggered
```

### Key Performance Events

- `pool:metrics` - Pool utilization and performance
- `queue:metrics` - Queue depth and throughput
- `task:duration` - Task execution timing
- `workflow:duration` - End-to-end workflow timing

## Event Filtering and Routing

### Severity-Based Routing

```python
# Route high-severity events to alerts
high_severity_events = get_events_by_severity(events, EventSeverity.ERROR)
for event in high_severity_events:
    await alert_system.process_event(event)

# Route component-specific events
pool_events = get_events_by_component(events, "pool")
await pool_monitor.process_events(pool_events)
```

### Event Filtering Pipeline

```
All Events → Severity Filter → Component Filter → Correlation Filter → Handlers
               ↓                    ↓                    ↓
        Alert System        Component Monitor      Workflow Tracker
```

## Best Practices for Event Handling

### 1. Event Emission

```python
# Always use structured events
event = create_task_completed_event(
    task_id="task-123",
    workflow_id="wf-456", 
    duration=5.2,
    source="execution_engine"
)
await self.emit_event(event)

# Include correlation IDs
await self.emit_correlated('task:started', task_data, original_event)
```

### 2. Event Handling

```python
@event_handler('task:completed')
async def handle_task_completion(self, event_name, event_data):
    try:
        # Process event
        result = await self.process_completion(event_data)
        
        # Emit follow-up events
        await self.emit_correlated('workflow:step_completed', result, event_data)
        
    except Exception as e:
        # Emit error event
        await self.emit_error_event(e, event_data)
```

### 3. Event Monitoring

```python
# Track event flow for debugging
correlation_events = get_events_by_correlation_id(events, workflow_id)
for event in correlation_events:
    logger.info(f"Event: {event.event_type} at {event.timestamp}")
```

## Event Debugging and Troubleshooting

### Event Tracing

Use the correlation ID to trace complete event flows:

```bash
# Filter events by workflow
events = get_events_by_correlation_id(all_events, "workflow-123")

# Check event sequence
event_timeline = sorted(events, key=lambda e: e.timestamp)
for event in event_timeline:
    print(f"{event.timestamp}: {event.event_type} - {event.source}")
```

### Common Event Patterns

1. **Task Execution Pattern**:
   ```
   task:submitted → task:queued → task:started → task:completed/failed
   ```

2. **Retry Pattern**:
   ```
   task:failed → task:retry_scheduled → task:retry_executed → task:started
   ```

3. **Scaling Pattern**:
   ```
   backpressure:high → pool:scale_requested → pool:scaled_up → worker:started
   ```

4. **Health Check Pattern**:
   ```
   health:check → health:check_started → health:check_completed/failed
   ```

This event routing architecture ensures loose coupling between components while maintaining clear communication patterns and full traceability of system operations.