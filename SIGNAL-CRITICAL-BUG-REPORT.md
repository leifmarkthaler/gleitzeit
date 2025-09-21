# 🚨 CRITICAL BUG REPORT: Signal Task Completion Failure

## Executive Summary
**Critical bug discovered in SignalTaskHandler causing all signal tasks to remain in "pending" status even after workflow completion.**

## Bug Details

### Symptoms
- Workflow shows `Status: COMPLETED` ✅
- Task count shows `Tasks: 0/3 completed` ❌
- All task statuses remain "pending" in persistence
- Signal workflows appear to complete but task tracking is broken

### Root Cause
**Registration/Lookup Key Pattern Mismatch in SignalTaskHandler**

The SignalTaskHandler has a fundamental mismatch between how it registers signal waiters and how it looks them up:

#### Registration Pattern (in `handle_wait`)
```python
# Creates individual waiter metadata keys:
signal_id = f"{workflow_id}:{task_id}:{uuid.uuid4().hex[:8]}"
waiter_key = self._get_signal_waiter_key(signal_id)
# Result: signal:waiter:workflow-id:task-id:random
```

#### Lookup Pattern (in `send_signal`)
```python
# Looks for workflow-scoped signal sets:
scoped_signal_key = self._get_scoped_signal_key(workflow_id, signal_name)
# Expected: signal:workflow-id:signal-name:waiters
waiter_keys = await self.persistence.redis.smembers(scoped_signal_key)
```

### Impact
1. **All signal workflows affected** - 100% failure rate for signal task completion
2. **Task counts incorrect** - Misleading progress reporting
3. **Events work but persistence broken** - WorkflowProgressHandler tracks correctly via events, but task statuses never update
4. **Signal security features non-functional** - Workflow-scoped signals not actually working

## Evidence

### Redis Key Analysis
```bash
# Expected key for workflow-scoped signals:
signal:workflow-ee73347f0c954e169fb3c8c659459dd1:test_approval:waiters

# Actual keys created:
signal:waiter:workflow-ee73347f0c954e169fb3c8c659459dd1:task-70a71d8220124221b98042a316a7093c:89f95b7a
signal:waiter:workflow-ee73347f0c954e169fb3c8c659459dd1:task-70a71d8220124221b98042a316a7093c:c8639e9f
```

### Log Evidence
```
# Signal waiter registered (individual key):
2025-09-12 18:14:02,262 - Signal waiter registered: workflow-ee73347f0c954e169fb3c8c659459dd1:task-70a71d8220124221b98042a316a7093c:c8639e9f waiting for 'test_approval'

# Signal sent but no waiters found (looking for set key):
2025-09-12 18:16:21,795 - Signal 'test_approval' woke 0 tasks in workflow workflow-ee73347f0c954e169fb3c8c659459dd1
```

### API Response Showing Issue
```json
{
  "id": "workflow-ee73347f0c954e169fb3c8c659459dd1",
  "status": "completed",
  "tasks": [
    {"name": "start_workflow", "status": "pending"},
    {"name": "wait_for_approval", "status": "pending"},
    {"name": "process_after_signal", "status": "pending"}
  ]
}
```

## Technical Analysis

### Why Events Still Work
- WorkflowProgressHandler listens to `TASK_COMPLETED` events
- Events are emitted correctly even though task status updates fail
- Workflow status updates via event aggregation (working)
- Task status updates via persistence layer (broken)

### Code Flow Analysis
1. **Task Execution** → SignalProvider executes → Returns SLEEPING status ✅
2. **Signal Registration** → Creates individual waiter keys ✅
3. **Signal Send** → Looks for waiter sets ❌ (KEY MISMATCH)
4. **Task Completion** → Never happens because no waiters found ❌
5. **Event Emission** → Never happens because task not completed ❌

## Fix Required

The SignalTaskHandler needs to be updated to use consistent key patterns:

### Option 1: Fix Registration (Recommended)
Update `handle_wait` to register waiters in sets:
```python
# Register in workflow-scoped signal set
scoped_signal_key = self._get_scoped_signal_key(workflow_id, signal_name)
waiter_id = f"{workflow_id}:{task_id}"
await self.persistence.redis.sadd(scoped_signal_key, waiter_id)
```

### Option 2: Fix Lookup
Update `send_signal` to scan for individual waiter keys (less efficient)

## Severity Assessment
- **Severity**: CRITICAL
- **Scope**: All signal workflows
- **User Impact**: High - Progress tracking completely broken
- **Security Impact**: Medium - Workflow isolation not functioning as designed

## Immediate Actions Required
1. Fix key pattern mismatch in SignalTaskHandler
2. Test signal workflow completion end-to-end
3. Verify task status updates in persistence
4. Confirm workflow-scoped signal isolation works

## Related Files
- `/src/gleitzeit/signals/handler.py` - Primary bug location
- `/src/gleitzeit/providers/signal_provider.py` - Affected provider
- `/src/gleitzeit/api/routes/signals.py` - API endpoints affected

---
*Bug discovered: 2025-09-12*
*Investigation completed by analyzing task progression event logging discrepancies*