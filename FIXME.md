# FIXME - Known Issues and Bugs

## 1. Python Provider Context Variable Issue
**Status:** 🔴 Open  
**Severity:** High  
**Discovered:** 2024-08-24  

### Description
Python scripts that expect a `context` variable are failing because the Python provider doesn't properly inject the context from task parameters.

### Symptoms
- Python tasks fail with `NameError: name 'context' is not defined`
- Tasks get stuck in "executing" state with "retry_pending" result
- Affects workflows with parameter substitution like `${task_name.response}`

### Example Error
```
ERROR:gleitzeit.providers.base:Provider python-provider failed python/execute after 0.022s: [TASK_EXECUTION_FAILED] Python script failed with exit code 1: Traceback (most recent call last):
  File "/Users/leifmarkthaler/github/gleitzeit 0.0.6/examples/scripts/calculate_stats.py", line 10, in <module>
    numbers_str = context.get('numbers_str', '')
NameError: name 'context' is not defined
```

### Affected Files
- `/examples/scripts/calculate_stats.py` - Expects `context` variable
- `/src/gleitzeit/providers/python_provider.py` - Needs to inject context
- `/examples/mixed_workflow.yaml` - Uses context parameter

### Reproduction Steps
1. Start server with SQL persistence: `GLEITZEIT_PERSISTENCE_TYPE=sql python -m gleitzeit.cli.gleitzeit_cli serve`
2. Submit the mixed_workflow.yaml which has:
   - Task 1: LLM generates numbers
   - Task 2: Python script processes numbers from context
   - Task 3: LLM summarizes results
3. Task 2 fails with context undefined error

### Proposed Fix
The Python provider needs to:
1. Extract the `context` parameter from task params
2. Inject it as a global variable before executing the script
3. Or modify scripts to read from environment/args instead of global context

---

## 2. Task Status Update Issues - Architectural Problem
**Status:** 🔴 Root Cause Identified  
**Severity:** High  
**Discovered:** 2024-08-24  

### Root Cause Analysis
The architecture has a fundamental conflict between Redis and SQL persistence approaches:

#### Redis Adapter Approach:
- **Emits events from within persistence operations** (save_task, save_task_result)
- Creates circular event flow: Event → Handler → Save → Emit Event → Handler...
- Works because Redis operations are atomic and fast
- Built-in event emission in UnifiedRedisEventsAdapter

#### SQL Adapter Approach:
- **Relies on external event handlers** to update status
- No built-in event emission (originally)
- Depends on execution engine emitting correct events
- Transaction isolation causes race conditions

#### The Conflict:
1. Execution engine emits TASK_COMPLETED event
2. PersistenceTaskHandler receives event and calls save_task
3. If persistence adapter ALSO emits events → circular dependency
4. If persistence adapter DOESN'T emit events → SQL doesn't work like Redis

### Current State
- Redis works because it has complete event-driven architecture built-in
- SQL fails because of incomplete event handling and race conditions
- Both approaches have issues with event storms when both emit events

### Attempted Fixes
- ✅ Event bus passed to persistence adapter during initialization
- ✅ Pooling adapter path emits completion events
- ❌ Created SQL event adapter → causes validation errors and event storms
- ❌ Duplicate event removal → breaks some flows

### The Real Solution Needed
Choose ONE approach:
1. **Option A: Events ONLY from Execution Engine**
   - Remove all event emission from persistence adapters
   - Execution engine is sole source of events
   - Persistence just saves data
   
2. **Option B: Events ONLY from Persistence Adapters**
   - Execution engine just calls save operations
   - Persistence adapters emit all events
   - Need event-driven adapters for all backends

3. **Option C: Hybrid with Clear Boundaries**
   - Execution events: TASK_STARTED, TASK_FAILED (immediate)
   - Persistence events: TASK_COMPLETED (after save)
   - Clear rules about who emits what

### Affected Files
- `/src/gleitzeit/client.py` - Initialization order
- `/src/gleitzeit/core/execution_engine.py` - Event emission logic
- `/src/gleitzeit/persistence/unified_redis_events.py` - Has event emission
- `/src/gleitzeit/persistence/unified_sqlalchemy.py` - No event emission
- `/src/gleitzeit/persistence/unified_sqlalchemy_events.py` - Attempted fix

---

## 3. Event Storm and Race Conditions
**Status:** ✅ Fixed  
**Severity:** Medium  
**Discovered:** 2024-08-24  
**Fixed:** 2024-08-24  

### Description
Multiple duplicate events were being fired for the same task, causing excessive database updates and potential race conditions.

### Root Cause
The execution engine was emitting TASK_COMPLETED event twice:
1. First via `event_bus.emit(completion_event)` (line 522)
2. Second via `emit_structured_event(task_completed_event)` (line 567)

### Symptoms (Before Fix)
- Log showed multiple TASK_COMPLETED events for same task
- Task status bounced between different states
- Database showed many redundant UPDATE operations

### Fix Applied
Removed the duplicate event emission in `/src/gleitzeit/core/execution_engine.py`:
- Kept the first emission via event_bus
- Removed the second emission via emit_structured_event
- Added comment explaining why second emission was removed

### Files Modified
- `/src/gleitzeit/core/execution_engine.py` - Removed duplicate event emission

---

## 4. Task Execution Hanging Issue
**Status:** ✅ Fixed  
**Severity:** Critical  
**Discovered:** 2024-08-25  
**Fixed:** 2024-08-25  

### Description
Tasks can get stuck in "executing" status indefinitely while the execution engine shows as "idle" with 0 active workers. This is a critical reliability issue that affects production workflows.

### Symptoms
- Task status shows "executing" but never completes or fails
- Execution engine status shows "idle" 
- No active workers reported despite tasks showing as executing
- No timeout or automatic cleanup mechanism
- Tasks never complete, blocking dependent tasks
- Workflows get stuck indefinitely

### Root Causes
1. **Task lifecycle management** - Tasks can get stuck in executing state without proper cleanup
2. **Execution engine monitoring** - Engine doesn't detect or recover hung tasks  
3. **Timeout handling** - No automatic cleanup of long-running tasks
4. **Error recovery** - Silent failures leave tasks in inconsistent state
5. **State synchronization** - Disconnect between task status and execution engine state

### Example Case
Task `task_efca202e` (combine_results) from parallel_workflow.yaml stuck executing for >5 minutes:
- Task API shows: `"status": "executing"`  
- Queue API shows: `"engine_status": "idle", "active_workers": 0`
- No error logs or completion events

### Impact
- **Production Critical**: Workflows can hang indefinitely
- **No Recovery**: Manual intervention required to unstick tasks  
- **Resource Waste**: Tasks consume execution slots without progress
- **Cascading Failures**: Dependent tasks never start

### Fix Applied
- ✅ Task timeouts with automatic cleanup (configurable, default 5 minutes)
- ✅ Proper error handling and state transitions
- ✅ Comprehensive task execution error handling with callbacks
- ✅ TASK_READY event emission in dependency resolution
- ✅ Asyncio task lifecycle management
- ✅ Timeout protection at both execution engine and provider levels

### Affected Files
- `/src/gleitzeit/core/execution_engine.py` - Task execution lifecycle
- `/src/gleitzeit/task_queue/task_queue.py` - Task status management
- `/src/gleitzeit/persistence/` - Task state persistence
- `/examples/parallel_workflow.yaml` - Reproduces the issue

---

## Contributing
When fixing these issues:
1. Add tests to prevent regression
2. Update this file with fix status
3. Document any new issues discovered during fixing