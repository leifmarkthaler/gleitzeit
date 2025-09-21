# Deep Stream Architecture Audit
## Complete Migration from EventBus to Pure Redis Streams

### Executive Summary
This audit identifies all polling loops, event bus usage, and stream implementations to enable complete migration to a pure stream-based architecture with NO polling or loops, while maintaining centralized state management through WorkflowManager and TaskOrchestrator.

## 1. CURRENT ARCHITECTURE ANALYSIS

### 1.1 Polling Loops Identified
Based on grep analysis of 275 files with potential loops:

#### Core Components with Loops:
1. **LogCollector** (`src/gleitzeit/core/log_collector.py`)
   - `_flush_loop()` - Periodic log flushing
   - `_start_stateless_flush_loop()` - Stateless flush mechanism

2. **EventDrivenRetryManager** (`src/gleitzeit/core/event_driven_retry_manager.py`)
   - Monitoring loop for retry tasks
   - Periodic checking of failed tasks

3. **StreamEventScheduler** (`src/gleitzeit/scheduler/stream_event_scheduler.py`)
   - `_process_streams()` - Stream consumption loop
   - `_process_scheduled_events()` - Scheduled event processing

4. **MultiplexedStreamConsumer** (`src/gleitzeit/events/multiplexed_stream_consumer.py`)
   - Consumer loop for multiple streams
   - Stream monitoring and processing

5. **ConsumerGroupManager** (`src/gleitzeit/scheduler/consumer_group_manager.py`)
   - Consumer health monitoring loop
   - Dead consumer cleanup

6. **HealthMonitor** (`src/gleitzeit/system/health_monitor.py`)
   - Periodic health checks
   - Component status monitoring

7. **ReconciliationService** (`src/gleitzeit/system/reconciliation_service.py`)
   - Reconciliation loops for stuck tasks
   - Periodic state verification

8. **StreamMonitor** (`src/gleitzeit/scheduler/stream_monitor.py`)
   - Stream lag monitoring
   - Consumer group health checks

### 1.2 Event Bus Usage Analysis

#### Current Event Flow Paths:
1. **EventBus → StatelessEventBus** (src/gleitzeit/events/base.py)
   - Wrapper that delegates to StatelessEventBus
   - Used by WorkflowManager

2. **StatelessEventBusAdapter** (src/gleitzeit/events/stateless_event_bus_adapter.py)
   - Stream-based adapter
   - Used by SystemManager
   - Missing `register_handler` method (now fixed)

3. **StatelessEventConsumer** (src/gleitzeit/events/stateless_event_consumer.py)
   - Redis Streams consumer
   - No persistent loops (good!)

## 2. COMPETING ARCHITECTURES IDENTIFIED

### 2.1 Three Event Systems Running in Parallel:
1. **Legacy EventBus**: Direct in-memory handlers
2. **StatelessEventBus**: Redis-backed handler registry
3. **StreamEventBus**: Redis Streams with consumer groups

### 2.2 State Management Components:
1. **WorkflowManager**: Central workflow state coordination
2. **TaskOrchestrator**: Task execution and dependency management
3. **StatelessTaskOrchestrator**: Stream-based task orchestration
4. **ExecutionEngineV2**: Event-driven execution

## 3. LOOPS AND POLLING TO ELIMINATE

### 3.1 Critical Loops (Must Remove):
```python
# Current problematic patterns:
while True:
    # Poll for tasks
    await asyncio.sleep(1)

# Monitoring loops
async def _monitor_loop():
    while not self._stop_event.is_set():
        await self._check_health()
        await asyncio.sleep(interval)
```

### 3.2 Components with Loops to Migrate:
| Component | Current Loop | Stream Replacement |
|-----------|--------------|-------------------|
| LogCollector | _flush_loop() | Stream-triggered flush events |
| RetryManager | monitor_loop() | Stream retry:ready events |
| HealthMonitor | check_loop() | Stream health:check events |
| ReconciliationService | reconcile_loop() | Stream reconcile:needed events |
| ConsumerGroupManager | monitor_loop() | Stream consumer:heartbeat events |
| StreamMonitor | monitor_lag_loop() | Stream lag:check events |

## 4. UNIFIED STREAM ARCHITECTURE DESIGN

### 4.1 Pure Stream Event Flow:
```
API Request → Redis Stream → Consumer Group → Handler → State Update → Next Event
```

### 4.2 Stream Topics:
```yaml
Core Streams:
  - workflow:events    # All workflow events
  - task:events        # All task events
  - system:events      # System-level events
  - control:events     # Control plane events

Specialized Streams:
  - timer:events       # Timer triggers
  - signal:events      # External signals
  - health:events      # Health checks
  - log:events         # Log collection
  - retry:events       # Retry triggers
```

### 4.3 No Loops Architecture:
- **Stream Consumption**: XREADGROUP with blocking
- **Scheduled Events**: Redis Sorted Sets + Stream triggers
- **Health Checks**: Stream-triggered checks
- **Log Flushing**: Event-driven flushes

## 5. MIGRATION PLAN

### Phase 1: Unify Event Systems
1. Remove EventBus/StatelessEventBus wrapper layers
2. Direct all events to Redis Streams
3. Use StreamSystemManager as single event coordinator

### Phase 2: Eliminate Polling Loops
1. Replace LogCollector flush loop with stream events
2. Convert RetryManager monitoring to stream triggers
3. Make HealthMonitor event-driven
4. Convert ReconciliationService to stream-based

### Phase 3: Centralize State Management
1. Keep WorkflowManager as central state authority
2. TaskOrchestrator handles all task state transitions
3. All state changes emit stream events
4. No component polls for state changes

### Phase 4: Stream-Only Architecture
1. Remove all asyncio.sleep() polling
2. Replace all while True loops
3. Use XREADGROUP blocking reads
4. Implement proper consumer groups

## 6. IMPLEMENTATION DETAILS

### 6.1 Replace Polling with Streams:
```python
# BEFORE: Polling Loop
async def _monitor_loop(self):
    while True:
        tasks = await self.check_tasks()
        await asyncio.sleep(1)

# AFTER: Stream Consumer
async def consume_events(self):
    while True:
        events = await redis.xreadgroup(
            group="processors",
            consumer="worker",
            streams={"task:events": ">"},
            block=0  # Block indefinitely
        )
        for event in events:
            await self.process_event(event)
```

### 6.2 Event-Driven Scheduling:
```python
# Use Redis Sorted Sets for scheduling
await redis.zadd("scheduled:tasks", {task_id: timestamp})

# Scheduler checks sorted set and emits to stream
scheduled = await redis.zrangebyscore("scheduled:tasks", 0, time.time())
for task_id in scheduled:
    await redis.xadd("task:events", {"type": "ready", "task_id": task_id})
```

### 6.3 State Management Flow:
```python
# WorkflowManager remains central authority
class WorkflowManager:
    async def handle_event(self, event):
        # Update state
        await self.update_workflow_state(event)

        # Emit next events to streams
        next_events = self.determine_next_events(event)
        for next_event in next_events:
            await redis.xadd("workflow:events", next_event)
```

## 7. COMPONENTS TO MODIFY

### 7.1 Core Components:
1. **WorkflowManager**: Remove EventBus, use streams directly
2. **TaskOrchestrator**: Convert to pure stream consumer
3. **ExecutionEngine**: Stream-based task execution
4. **DependencyManager**: Event-driven dependency resolution

### 7.2 System Components:
1. **SystemManager**: Remove StatelessEventBusAdapter
2. **StreamSystemManager**: Become primary event coordinator
3. **LogCollector**: Event-driven flushing
4. **HealthMonitor**: Stream-triggered checks

### 7.3 API Components:
1. **Dependencies**: Create stream producers only
2. **Routes**: Emit events to streams
3. **WebSocket**: Subscribe to streams directly

## 8. BENEFITS OF PURE STREAM ARCHITECTURE

1. **No Polling**: Zero CPU waste on empty loops
2. **True Horizontal Scaling**: Consumer groups handle distribution
3. **Event Sourcing**: Complete event history in streams
4. **Crash Recovery**: Automatic from last acknowledged message
5. **Backpressure**: Natural flow control via consumer groups
6. **Observability**: Stream lag metrics built-in

## 9. RISKS AND MITIGATION

### Risks:
1. **Message Ordering**: Stream sharding may affect order
   - Mitigation: Use task_id as stream key for ordering

2. **Consumer Group Management**: Dead consumers need cleanup
   - Mitigation: Stream-based heartbeats and monitoring

3. **Memory Usage**: Streams consume Redis memory
   - Mitigation: TTL and trimming policies

## 10. NEXT STEPS

### Immediate Actions:
1. Create stream consumption utilities
2. Replace first polling loop (LogCollector)
3. Test stream-based task execution
4. Migrate one complete workflow

### Long-term:
1. Remove all event bus abstractions
2. Eliminate every polling loop
3. Pure stream-based architecture
4. Performance benchmarking

## CONCLUSION

The codebase currently has three competing event systems running simultaneously with multiple polling loops. By migrating to pure Redis Streams, we can:
- Eliminate ALL polling loops
- Maintain centralized state management
- Achieve true horizontal scaling
- Simplify the architecture significantly

The WorkflowManager and TaskOrchestrator remain the central authorities for state management, but all state changes and triggers happen through streams, not polling.