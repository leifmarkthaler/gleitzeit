# Multi-Stream Architecture Not Working
Generated: 2025-09-16

## Executive Summary

The multi-stream architecture designed to eliminate polling loops is completely disconnected. **No events are being emitted to Redis Streams** because the workflow system is initialized with `event_bus=None`.

## The Core Issue

### Discovery Path
1. StatelessTaskOrchestrator calls non-existent `dependency_manager.get_dependent_tasks()` (line 501)
2. This breaks task progression after first task completes
3. Investigation revealed events should trigger task progression through streams
4. Found multi-stream architecture components exist (StatelessEventBusAdapter, StreamEventScheduler, etc.)
5. **Critical Finding**: WorkflowManager is created with `event_bus=None` in dependencies.py:331

## The Broken Chain

### What Was Supposed to Happen (Multi-Stream Design)
```
Task Completes →
  TaskExecutor emits TASK_COMPLETED →
    Event goes to Redis Stream (XADD) →
      Stream Consumer processes event →
        Handler triggers next task
```

### What Actually Happens
```
Task Completes →
  TaskExecutor tries to emit TASK_COMPLETED →
    event_bus is None →
      No event emitted →
        No stream entry →
          No consumer processing →
            No task progression
```

## Components That Exist But Are Unused

### 1. StatelessEventBusAdapter (stream_event_bus.py)
- Has XADD functionality at line 263
- Properly emits events to Redis streams
- Never instantiated because event_bus is None

### 2. StreamEventScheduler
- Pure stream-based event scheduling
- Consumer groups for distributed processing
- Never receives events because none are emitted

### 3. StatelessEventConsumer
- Designed to consume from streams
- Would handle task progression
- Never processes anything because streams are empty

## The Immediate Fix

In `/src/gleitzeit/api/dependencies.py` line 331, change:
```python
workflow_manager = await WorkflowManagerFactory.create(
    persistence=persistence,
    event_bus=None,  # THIS IS THE PROBLEM
    execution_engine=None,
    dependency_resolver=None
)
```

To:
```python
# Create the stream-based event bus
event_bus = StatelessEventBusAdapter(
    redis=persistence.redis,  # Assuming redis client is available
    instance_id=f"api-{uuid.uuid4().hex[:8]}"
)
await event_bus.start()

workflow_manager = await WorkflowManagerFactory.create(
    persistence=persistence,
    event_bus=event_bus,  # Now events will be emitted!
    execution_engine=None,
    dependency_resolver=None
)
```

## Additional Required Fixes

### 1. Implement Missing Method
Add `get_dependent_tasks()` to UnifiedDependencyManager or fix StatelessTaskOrchestrator to not call it

### 2. Start Stream Consumers
Ensure stream consumers are running to process events from the streams

### 3. Fix Status Transitions
Ensure EXECUTING status is set before task execution (as per STATUS-FIX-DESIGN.md)

## Why Multi-Stream Was Designed

The multi-stream architecture was implemented to:
1. **Eliminate polling loops** - No more checking for ready tasks
2. **Enable horizontal scaling** - Multiple workers via consumer groups
3. **Provide event-driven processing** - Pure reactive system
4. **Ensure exactly-once processing** - Redis Streams guarantees

## Current State

The entire multi-stream infrastructure exists but is completely bypassed because:
- No EventBus is instantiated in the API layer
- TaskExecutor has no event_bus to emit to
- All stream-related code is essentially dead code

## Impact

Without the event bus connection:
1. **No task progression** after first task
2. **No event monitoring** possible
3. **No distributed processing** capability
4. **Polling loops can't be eliminated** (the original goal)

## Recommendation

1. **Immediate**: Wire up the EventBus in dependencies.py
2. **Short-term**: Fix the missing method issue
3. **Medium-term**: Verify stream consumers are properly started
4. **Long-term**: Consider if event-driven is the right architecture

## Key Insight

The system has two parallel architectures:
1. **Direct execution path** (partially working)
2. **Stream-based event path** (completely disconnected)

The stream-based path was meant to replace polling but was never connected. This explains why task progression is broken - the system is trying to use an event-driven approach without any events being emitted.