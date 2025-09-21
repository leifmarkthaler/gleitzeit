# Duplicate Stream Consumers Audit

## Executive Summary
**CRITICAL ISSUE**: The system has multiple independent stream consumers with different consumer groups, causing message duplication and competing stream processing pathways.

## Problems Identified

### 1. Multiple EventBus Implementations
Despite claiming to use only StreamlinedEventBus, we have:
- `StreamlinedEventBus` in `events/streamlined_event_bus.py` (✓ CORRECT)
- Old `EventBus` base class in `events/base.py` (✗ SHOULD BE REMOVED)
- `ClientEventBus` in `client/events/client_event_bus.py` (? NEEDS REVIEW)

### 2. Wrong Import Paths
Many core components import EventBus from the wrong location:

**Importing from `events.base` (WRONG):**
- `src/gleitzeit/core/execution_engine_v2.py`
- `src/gleitzeit/core/log_collector.py`
- `src/gleitzeit/core/log_stream.py`
- `src/gleitzeit/core/stateless_task_orchestrator.py`
- `src/gleitzeit/core/stream_execution_engine.py`
- `src/gleitzeit/timers/stream_timer_manager.py`
- `src/gleitzeit/signals/stream_signal_manager.py`
- `src/gleitzeit/scheduler/stream_event_scheduler.py`
- `src/gleitzeit/scheduler/hybrid_event_scheduler.py`
- `src/gleitzeit/scheduler/stream_monitor.py`
- `src/gleitzeit/scheduler/redis_event_scheduler.py`
- `src/gleitzeit/system/reconciliation_service.py`

**Should import from `events` (which aliases to StreamlinedEventBus):**
```python
from gleitzeit.events import EventBus  # This gets StreamlinedEventBus
```

### 3. Multiple Independent Stream Consumers

**THIS IS THE BIGGEST PROBLEM**: Different components read from Redis streams with DIFFERENT consumer groups:

| Component | Consumer Group | Location | Problem |
|-----------|---------------|----------|---------|
| StreamlinedEventBus | `gleitzeit-processors` | `events/streamlined_event_bus.py` | ✓ This is correct |
| TimerManager | `timer-processors` | `timers/stream_timer_manager.py` | ✗ Duplicate consumer! |
| SignalManager | `signal-processors` | `signals/stream_signal_manager.py` | ✗ Duplicate consumer! |
| EventScheduler | `event-processors` | `scheduler/stream_event_scheduler.py` | ✗ Duplicate consumer! |

**Why this is bad:**
- Each consumer group gets its OWN COPY of every message in the stream
- A single event could be processed 4 times (once by each consumer group)
- This causes race conditions, duplicate processing, and inconsistent state
- This is exactly the "multiple streams" problem identified earlier

### 4. Direct Stream Reading
Components that directly call Redis stream commands (`xreadgroup`):
- `src/gleitzeit/ui/api/routes/websocket_unified.py`
- `src/gleitzeit/timers/stream_timer_manager.py`
- `src/gleitzeit/signals/stream_signal_manager.py`
- `src/gleitzeit/scheduler/stream_event_scheduler.py`
- `src/gleitzeit/events/stateless_stream_consumer.py` (✓ This one is OK - used by StreamlinedEventBus)

## Components Using Wrong Implementations

### Loop-based Components Still in Use:
- `StreamTimerManager` - Has `_process_timers_loop()` with its own consumer group
- `StreamSignalManager` - Has `_process_signals_loop()` with its own consumer group
- `StreamEventScheduler` - Has `_process_events_loop()` with its own consumer group

### Stateless Components That Should Be Used:
- `StatelessTimerManager` - No loops, process_all_once() method
- `StatelessSignalManager` - No loops, process_all_once() method
- `StatelessScheduler` - No loops, process_all_once() method

### Files Exporting Wrong Components:
- `src/gleitzeit/timers/__init__.py` - Exports both, should only export Stateless
- `src/gleitzeit/signals/__init__.py` - Exports both, should only export Stateless
- `src/gleitzeit/scheduler/__init__.py` - Needs to export only Stateless

## Required Fixes

### Phase 1: Fix EventBus Imports
1. Update all imports from `events.base import EventBus` to `events import EventBus`
2. Remove the old `EventBus` class from `events/base.py`
3. Keep only `EventHandler` and `HandlerError` in base.py

### Phase 2: Consolidate Stream Consumers
1. Remove direct stream reading from TimerManager, SignalManager, EventScheduler
2. Make these components register handlers with StreamlinedEventBus instead
3. Ensure ONLY StreamlinedEventBus reads from Redis streams
4. Use a SINGLE consumer group: `gleitzeit-processors`

### Phase 3: Unified Event Flow
```
Redis Streams
    ↓
StreamlinedEventBus (ONLY consumer, group: gleitzeit-processors)
    ↓
Registered Handlers (Timer, Signal, Scheduler, etc.)
```

NOT this (current broken state):
```
Redis Streams
    ├→ StreamlinedEventBus (group: gleitzeit-processors)
    ├→ TimerManager (group: timer-processors)
    ├→ SignalManager (group: signal-processors)
    └→ EventScheduler (group: event-processors)
```

## Impact
- **Performance**: 4x message processing overhead
- **Correctness**: Race conditions between different consumers
- **Scalability**: Cannot properly horizontally scale with competing consumers
- **Reliability**: Messages could be processed multiple times or missed

## Verification Steps
After fixes:
1. Verify only ONE consumer group exists across all streams
2. Verify all components use StreamlinedEventBus
3. Verify no direct `xreadgroup` calls except in StatelessStreamConsumer
4. Test that events are processed exactly once