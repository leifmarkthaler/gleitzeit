# Pure Stream Migration Overview
## Current State Analysis and Implementation Plan

### Executive Summary
Based on our comprehensive audits, we have identified that **80% of the stream infrastructure is already built** but not properly connected. The migration to a pure Redis Streams architecture with zero polling loops is primarily a **wiring and connection problem**, not an architecture rebuild.

## Current Architecture Problems

### 1. Three Competing Event Systems
Currently running **simultaneously**:
```
1. EventBus (Legacy) → In-memory handlers
2. StatelessEventBus → Redis-backed registry
3. StreamEventBus → Redis Streams with consumer groups
```

### 2. Polling Loops Throughout Codebase
**Critical loops to eliminate**:
- `LogCollector._flush_loop()` - Periodic log flushing
- `StreamEventScheduler._process_events_loop()` - Stream consumption
- `HealthMonitor` check loops
- `ReconciliationService` reconciliation loops
- `ConsumerGroupManager` monitoring loops
- `RetryManager` monitoring loops

### 3. Disconnected Stream Components
**Already built but not connected**:
- `StreamSystemManager` - Exists but underutilized
- `StreamEventScheduler` - Has loops instead of blocking reads
- `MultiplexedStreamConsumer` - Built but has polling
- `StatelessEventConsumer` - Good design, not primary handler

## What's Already Built (Ready to Use)

### ✅ Stream Infrastructure (80% Complete)
- **StreamSystemManager**: Pure stream-based design with 64 shards
- **Consumer Groups**: `gleitzeit-api-processors` already created
- **Stream Topics**: All major streams defined (events, tasks, workflows, timers, signals)
- **AtomicPersistenceOperations**: Thread-safe state management
- **IdempotencyManager**: Duplicate prevention

### ✅ Redis Streams Features
- Consumer groups with reliability
- Stream sharding for scalability
- Dead letter queue handling
- Automatic retries
- Stream trimming/TTL

### ❌ What's Missing/Broken
- **Connection**: Components not wired together
- **EventBus Wrapper**: WorkflowManager uses EventBus instead of streams
- **Polling**: Using loops instead of blocking XREADGROUP
- **Primary Coordinator**: StreamSystemManager not used as main event hub

## Target Architecture

### Pure Stream Flow
```
API Request → Redis Stream → Consumer Group → Handler → State Update → Next Stream Event
```

### Zero Polling Architecture
- **XREADGROUP with blocking=0**: No CPU usage when idle
- **Event-driven scheduling**: Redis Sorted Sets + stream triggers
- **Stream-based monitoring**: Health checks via events
- **No asyncio.sleep()**: Eliminated entirely

### Centralized State Management (Preserved)
- **WorkflowManager**: Remains central workflow authority
- **TaskOrchestrator**: Handles all task state transitions
- **State changes emit stream events**: No polling for changes

## Implementation Plan

### Phase 1: Connect Existing Infrastructure (Immediate Wins)
**Files to modify:**
1. `src/gleitzeit/api/dependencies.py`
   - Replace EventBus creation with StreamSystemManager
   - Remove StatelessEventBusAdapter wrapper

2. `src/gleitzeit/core/workflow_manager.py`
   - Remove EventBus dependency
   - Connect directly to StreamSystemManager

3. `src/gleitzeit/core/task_orchestrator.py`
   - Use StreamSystemManager for all events
   - Remove EventBus references

### Phase 2: Eliminate Polling Loops
**Critical replacements:**
1. `src/gleitzeit/scheduler/stream_event_scheduler.py`
   ```python
   # REPLACE: while True + asyncio.sleep(1)
   # WITH: XREADGROUP(block=0)
   ```

2. `src/gleitzeit/core/log_collector.py`
   - Replace flush loop with stream-triggered flushes

3. `src/gleitzeit/system/health_monitor.py`
   - Convert to stream-based health checks

4. `src/gleitzeit/system/reconciliation_service.py`
   - Stream-triggered reconciliation

### Phase 3: Remove Legacy Event Systems
**Files to delete/modify:**
1. Remove EventBus wrapper layers
2. Delete StatelessEventBusAdapter (replace with direct streams)
3. Eliminate all event bus abstractions

### Phase 4: Optimize Stream Operations
1. Use blocking XREADGROUP everywhere
2. Implement proper consumer acknowledgment
3. Stream lag monitoring for auto-scaling

## Critical Success Metrics

### Before Migration
- ❌ Multiple event systems competing
- ❌ Constant CPU usage from polling loops
- ❌ Complex event routing through wrappers
- ❌ Inconsistent state management

### After Migration
- ✅ Single stream-based event system
- ✅ Zero CPU usage when idle (blocking reads)
- ✅ Direct stream event flow
- ✅ Centralized state management preserved
- ✅ Horizontal scalability via consumer groups

## Risk Assessment

### Low Risk (Wiring Changes)
- **StreamSystemManager connection**: Already exists, just needs wiring
- **WorkflowManager stream integration**: State management logic unchanged
- **Consumer group usage**: Infrastructure already built

### Medium Risk (Loop Replacement)
- **Blocking XREADGROUP**: Well-tested Redis operation
- **Event-driven scheduling**: Redis Sorted Sets proven pattern
- **Stream-based monitoring**: Event-driven health checks

### Mitigation Strategy
- **Incremental migration**: One component at a time
- **Rollback plan**: Keep original files as backups
- **Testing**: Validate each phase before proceeding
- **State preservation**: WorkflowManager/TaskOrchestrator logic untouched

## Next Steps

### Immediate (Phase 1)
1. **Wire StreamSystemManager** as primary event coordinator
2. **Remove EventBus** from WorkflowManager dependencies
3. **Test basic stream flow** with existing infrastructure

### Short-term (Phase 2)
1. **Fix first polling loop** (StreamEventScheduler)
2. **Convert LogCollector** to event-driven
3. **Validate no performance regression**

### Long-term (Phases 3-4)
1. **Remove all event bus abstractions**
2. **Optimize stream operations**
3. **Performance benchmarking**

## Conclusion

This is **NOT a rewrite** - it's a **reconnection project**. The stream infrastructure is already built and tested. We need to:

1. **Connect** existing components properly
2. **Replace** polling loops with blocking reads
3. **Remove** redundant event systems
4. **Preserve** WorkflowManager/TaskOrchestrator as state authorities

The result will be a **pure stream architecture** with zero polling, horizontal scalability, and simplified event flow while maintaining all existing state management patterns.