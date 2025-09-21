# Event Pathways Audit Report - Gleitzeit System

## Executive Summary

This audit analyzes the event flow pathways in the Gleitzeit system to understand how events flow from workflow submission to task execution, identify bottlenecks, and determine why tasks might be enqueued but not executed.

### Key Findings

1. **Complex Event Architecture**: System uses multiple event buses, consumers, and orchestrators
2. **Potential Missing TASK_READY Events**: Critical gap in task ready signal emission
3. **Disconnected Event Consumers**: Stream consumers may not be connected to event handlers
4. **Missing Stream Creation**: Event streams may not be properly initialized

## Event Flow Analysis

### 1. Workflow Submission to Task Execution Path

```
Workflow Submission → ExecutionEngineV2.submit_workflow()
                  ↓
          StatelessTaskOrchestrator.submit_workflow()
                  ↓
          EventBus.emit(WORKFLOW_SUBMITTED) → Redis Stream
                  ↓
          MultiplexedStreamConsumer.handle_message()
                  ↓
          StatelessTaskOrchestrator._handle_workflow_submitted()
                  ↓
          QueueManager.enqueue_task() (for initial tasks)
                  ↓
          EventBus.emit(TASK_READY) → Redis Stream
                  ↓
          [POTENTIAL GAP - Consumer may not pick up TASK_READY]
                  ↓
          StatelessTaskOrchestrator._handle_task_ready()
                  ↓
          TaskExecutor.execute_task()
```

### 2. Event Producers

**Primary Event Emission Points:**

1. **ExecutionEngineV2** (`/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/core/execution_engine_v2.py`)
   - Lines 350-358: `TASK_SUBMITTED` events
   - Lines 388-389: Workflow submission delegation

2. **StatelessTaskOrchestrator** (`/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/core/stateless_task_orchestrator.py`)
   - Lines 362-369: `workflow:submitted` events
   - Lines 294-298: `TASK_EXECUTING` events
   - Lines 312-320: `TASK_COMPLETED` events
   - Lines 335-344: `TASK_FAILED` events

3. **TaskQueue** (`/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/task_queue/task_queue.py`)
   - Lines 334-347: `TASK_READY` events when dependencies satisfied
   - Lines 414-434: `WORKFLOW_COMPLETED` events

4. **QueueManager** (`/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/task_queue/task_queue.py`)
   - Lines 774-786: `TASK_READY` events for ready tasks

### 3. Event Consumers

**Primary Event Consumption Points:**

1. **MultiplexedStreamConsumer** (`/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/events/multiplexed_stream_consumer.py`)
   - Lines 94-123: Stream discovery (`gleitzeit:events:stream:*`)
   - Lines 148-192: Main consumption loop using `XREADGROUP`
   - Lines 194-271: Message handling and event decoding

2. **StatelessEventConsumer** (`/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/events/stateless_event_consumer.py`)
   - Lines 183-255: Batch processing with idempotency checks
   - Lines 376-433: Idle message claiming

3. **StreamSystemManager** (`/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/system/stream_system_manager.py`)
   - Lines 191-220: MultiplexedStreamConsumer initialization
   - Lines 227-247: Event handler registration

### 4. Event Handlers

**StatelessTaskOrchestrator Event Handlers:**

1. **Workflow Submission** (Lines 373-417)
   - Event: `workflow:submitted`
   - Action: Enqueues initial tasks with no dependencies
   - **Critical**: Emits `TASK_READY` events

2. **Task Ready** (Lines 419-429)
   - Event: `task:ready`
   - Action: Processes ready tasks
   - **Gap**: May not be properly connected

3. **Task Completion** (Lines 431-463)
   - Event: `task:completed`
   - Action: Checks for newly ready dependent tasks
   - **Critical**: Emits new `TASK_READY` events

4. **Task Failure** (Lines 465-482)
   - Event: `task:failed`
   - Action: Emits workflow error events

## Critical Issues Identified

### 1. Event Stream Creation Gap

**Issue**: Redis streams may not be automatically created when events are emitted.

**Evidence**:
- MultiplexedStreamConsumer discovers streams using pattern `gleitzeit:events:stream:*`
- No explicit stream creation logic found in event emission code
- EventBus implementations may not create streams before publishing

**Impact**: Events could be lost if streams don't exist.

### 2. Handler Registration Disconnect

**Issue**: StatelessTaskOrchestrator handlers may not be properly registered with stream consumers.

**Evidence**:
- StatelessTaskOrchestrator has `register_with_stream_manager()` method (Lines 114-134)
- Method only gets called if ExecutionEngineV2 calls it (Lines 132-134)
- StreamSystemManager calls this (Lines 369-384) but standard SystemManager may not

**Impact**: Event handlers never receive events.

### 3. TASK_READY Event Emission Gaps

**Issue**: TASK_READY events critical for task execution may not be consistently emitted.

**Evidence**:
- TaskQueue emits TASK_READY when dependencies satisfied (Lines 334-347)
- QueueManager also emits TASK_READY (Lines 774-786)
- But StatelessTaskOrchestrator._handle_task_ready may not be called if handlers not registered

**Impact**: Tasks remain queued but never get executed.

### 4. Event Type Inconsistencies

**Issue**: Mixed event type naming conventions.

**Evidence**:
- Some events use EventType enum: `EventType.TASK_READY`
- Others use string literals: `"workflow:submitted"`, `"task:ready"`
- This may cause handler mismatches

## Event Stream Architecture

### Stream Keys Pattern
```
gleitzeit:events:stream:workflow:submitted
gleitzeit:events:stream:task:ready
gleitzeit:events:stream:task:completed
gleitzeit:events:stream:task:failed
```

### Consumer Groups
- Default: `"gleitzeit-processors"`
- Events: `"gleitzeit-processors-events"`
- Timers: `"gleitzeit-processors-timers"`
- Signals: `"gleitzeit-processors-signals"`

### Consumer Architecture
```
Redis Streams → MultiplexedStreamConsumer → Event Handlers
     ↓               ↓                         ↓
Stream Discovery → XREADGROUP Blocking → Handler Invocation
     ↓               ↓                         ↓
Auto Stream       Message Decode         StatelessTaskOrchestrator
Creation?         & Routing              Methods
```

## Recommendations

### 1. Ensure Stream Creation
**Priority**: High

**Action**: Implement automatic stream creation in EventBus.emit()
```python
async def emit(self, event):
    stream_key = f"gleitzeit:events:stream:{event.event_type}"
    # Ensure stream exists before publishing
    await self.redis.xadd(stream_key, event.to_dict(), maxlen=10000)
```

### 2. Fix Handler Registration
**Priority**: Critical

**Action**: Ensure StatelessTaskOrchestrator handlers are registered in all SystemManager types
```python
# In SystemManager._start_core_components()
if hasattr(self.execution_engine, 'task_orchestrator'):
    if hasattr(self, 'register_event_handler'):
        self.execution_engine.task_orchestrator.register_with_stream_manager(self)
```

### 3. Verify TASK_READY Flow
**Priority**: High

**Action**: Add explicit TASK_READY event emission verification
```python
# After enqueueing task
logger.info(f"Emitted TASK_READY event for {task.id}")
# Add tracking to verify handler receives it
```

### 4. Standardize Event Types
**Priority**: Medium

**Action**: Use EventType enum consistently across all components
```python
# Replace string literals with EventType enum
EventType.WORKFLOW_SUBMITTED instead of "workflow:submitted"
```

### 5. Add Event Flow Monitoring
**Priority**: Medium

**Action**: Implement event flow tracing
```python
# Add correlation IDs and flow tracking
event.correlation_id = workflow_id
event.tags["flow_step"] = "task_enqueued"
```

## Testing Recommendations

### 1. Event Flow Integration Test
Create test that verifies complete workflow submission to task execution flow:
```python
async def test_complete_event_flow():
    # Submit workflow
    # Verify WORKFLOW_SUBMITTED event emitted
    # Verify initial tasks enqueued
    # Verify TASK_READY events emitted
    # Verify handlers called
    # Verify tasks executed
```

### 2. Stream Consumer Health Check
Verify MultiplexedStreamConsumer is discovering and consuming from streams:
```python
async def test_stream_consumer_health():
    # Check stream discovery
    # Verify consumer group creation
    # Test event consumption
    # Verify handler invocation
```

### 3. Event Handler Registration Test
Verify all critical handlers are properly registered:
```python
async def test_handler_registration():
    # Check StatelessTaskOrchestrator handlers registered
    # Verify MultiplexedStreamConsumer has handlers
    # Test event routing to correct handlers
```

## Conclusion

The Gleitzeit event system has a well-designed architecture but suffers from potential connection gaps between event producers and consumers. The most critical issue is ensuring that:

1. Event streams are created when events are emitted
2. StatelessTaskOrchestrator handlers are registered with stream consumers
3. TASK_READY events flow properly from queue to execution

Addressing these issues should resolve the problem of tasks being enqueued but not executed.

## Files Analyzed

- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/events/multiplexed_stream_consumer.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/events/stateless_event_consumer.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/events/stateless_bus.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/core/stateless_task_orchestrator.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/task_queue/task_queue.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/core/task_executor.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/core/events.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/events/base.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/core/execution_engine_v2.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/system/system_manager.py`
- `/Users/leifmarkthaler/github/gleitzeit 0.0.6/src/gleitzeit/system/stream_system_manager.py`