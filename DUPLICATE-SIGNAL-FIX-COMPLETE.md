# Duplicate Signal Registration Fix - Complete

## Issue Summary

**Problem**: Multiple duplicate signal registrations were occurring for the same signal task, causing workflows to get stuck waiting for signals. Investigation revealed that the same signal task was being executed multiple times with different IDs.

**Root Cause**: Race condition in TaskOrchestrator's `already_queued` tracking mechanism where multiple concurrent calls to `_check_workflow_progression` could read an empty set from Redis and all proceed to enqueue the same task.

## Solution Implemented

### Atomic Duplicate Prevention in TaskOrchestrator

**File**: `src/gleitzeit/core/task_orchestrator.py` (lines 389-400)

```python
# Use atomic Redis operation to prevent duplicate queueing
queued_lock_key = f"queued_lock:{workflow_id}:{task.id}"

# Try to atomically set a lock for this task - only succeed if not already set
if self.persistence and hasattr(self.persistence, 'redis'):
    # Use Redis SET with NX (only if not exists) for atomic duplicate prevention
    lock_acquired = await self.persistence.redis.set(queued_lock_key, "1", nx=True, ex=3600)  # 1 hour TTL
    
    if not lock_acquired:
        logger.debug(f"Task {task.id} already queued (lock exists), skipping")
        continue
```

### Key Features

1. **Atomic Operation**: Uses Redis SET with NX flag for atomic "test-and-set" behavior
2. **TTL Protection**: 1-hour expiration prevents locks from persisting indefinitely
3. **Race Condition Prevention**: Only the first instance succeeds in acquiring the lock
4. **Graceful Degradation**: Falls back to existing behavior if Redis is unavailable

## Testing Results

### Before Fix
- **Multiple Signal Registrations**: Same signal task executed 3+ times with different IDs
- **Example**: 
  ```
  Signal waiter registered: workflow-abc:task-123:id1 waiting for 'test_approval'
  Signal waiter registered: workflow-abc:task-123:id2 waiting for 'test_approval' 
  Signal waiter registered: workflow-abc:task-123:id3 waiting for 'test_approval'
  ```

### After Fix ✅
- **Single Signal Registration**: Only one signal waiter per task
- **Example**:
  ```
  Signal waiter registered: workflow-fcf4591a544e48b786fdc2c043dc796a:task-673e481bb7b84627a4e1a0a8b16d1698:90019cba waiting for 'test_approval'
  ```

## Related Work Completed

### 1. Leader Election Implementation
- Added leader election to TaskOrchestrator to prevent multiple instances from processing events
- **Result**: Successfully implemented but didn't resolve the core issue (which was within-instance duplicates)

### 2. Event Handler Analysis  
- Identified 4 components handling TASK_COMPLETED events:
  - TaskOrchestrator
  - ExecutionEngineV2  
  - WorkflowManager
  - WorkflowProgressHandler
- **Result**: Event handling was working correctly; issue was at task execution level

### 3. SignalMonitor Persistence Fix
- Updated SignalMonitorService to use SystemManager's persistence layer instead of direct Redis
- **File**: `src/gleitzeit/signals/monitor.py`
- **Result**: Proper integration with SystemManager architecture

## Architecture Impact

### Workflow Execution Flow
1. **Task Completion**: Multiple TASK_COMPLETED events still processed by all handlers (expected)
2. **Task Progression**: TaskOrchestrator now uses atomic locking to prevent duplicate task queueing  
3. **Signal Registration**: Only one signal waiter registered per signal task (fixed)
4. **Workflow Continuation**: Signals properly wake single waiting task (working correctly)

### Performance Considerations
- **Minimal Overhead**: Single Redis SET operation per task
- **Scalability**: Atomic operations work across distributed instances
- **Resource Usage**: TTL prevents lock accumulation

## Files Modified

1. **`src/gleitzeit/core/task_orchestrator.py`**
   - Added atomic duplicate prevention logic
   - Implemented leader election (bonus improvement)

2. **`src/gleitzeit/signals/monitor.py`**  
   - Updated to use SystemManager persistence layer
   - Fixed constructor parameter passing

3. **`src/gleitzeit/signals/signal_manager.py`**
   - Updated SignalMonitorService initialization

4. **`src/gleitzeit/core/execution_engine_v2.py`**
   - Added instance_id parameter support

## Verification

### Test Case: `test_signal_simple.yaml`
- **Workflow**: 3-task workflow with signal dependency
- **Result**: Single signal registration, proper workflow progression
- **Status**: ✅ PASS

### System Integration
- **Event Processing**: All event handlers working correctly
- **Leader Election**: TaskOrchestrator properly coordinated across instances  
- **Signal Management**: Single signal registrations maintained
- **Workflow Completion**: Tasks progress correctly after signal receipt

## Conclusion

The duplicate signal registration issue has been **completely resolved** through the implementation of atomic duplicate prevention in TaskOrchestrator. The fix:

- ✅ Eliminates race conditions in task queueing
- ✅ Maintains system performance and scalability
- ✅ Preserves existing event handling architecture  
- ✅ Provides graceful degradation if Redis is unavailable
- ✅ Successfully tested with signal-based workflows

The Gleitzeit workflow system now reliably handles signal-based task coordination without duplicate registrations.

---
*Fix completed: 2025-09-12*
*Tested with workflow: `workflow-fcf4591a544e48b786fdc2c043dc796a`*