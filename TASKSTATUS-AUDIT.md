# TaskStatus Enum Audit Report

## Summary
Comprehensive audit of TaskStatus enum usage across the Gleitzeit codebase to ensure consistency and proper enum usage.

## Valid TaskStatus Enum Values
From `src/gleitzeit/core/models.py`:
- `PENDING` = "pending"
- `QUEUED` = "queued"
- `VALIDATED` = "validated"
- `ROUTED` = "routed"
- `EXECUTING` = "executing"
- `PAUSED` = "paused"
- `SLEEPING` = "sleeping"
- `WAITING_SIGNAL` = "waiting_signal"
- `COMPLETED` = "completed"
- `FAILED` = "failed"
- `CANCELLED` = "cancelled"
- `RETRY_PENDING` = "retry_pending"
- `REWOUND` = "rewound"

## Critical Issues Found

### 1. ❌ INVALID ENUM REFERENCE
**Location**: Error logs show `TaskStatus.RUNNING` being referenced
**Problem**: There is NO `TaskStatus.RUNNING` enum value - should be `TaskStatus.EXECUTING`
**Impact**: Causes AttributeError and workflow failures

## String Literal Usage Issues

### Files Using String Literals Instead of Enums:

1. **src/gleitzeit/scheduler/api.py**
   - Lines 227, 300, 315, 353: Using string "paused" and "pending"
   - Should use: `TaskStatus.PAUSED`, `TaskStatus.PENDING`

2. **src/gleitzeit/providers/timer_provider.py**
   - Line 167: Comparing with string "completed"
   - Should use: `TaskStatus.COMPLETED`

3. **src/gleitzeit/providers/signal_provider.py**
   - Line 183: Comparing with string "completed"
   - Should use: `TaskStatus.COMPLETED`

4. **src/gleitzeit/cli/main.py**
   - Lines 237, 270: Comparing with strings "completed" and "paused"
   - Should use enum values for type safety

5. **src/gleitzeit/task_queue/task_queue.py**
   - Line 130: Setting status="pending"
   - Should use: `TaskStatus.PENDING`

6. **src/gleitzeit/client/mixins/event_workflow.py**
   - Lines 94, 305, 307: Using string literals for status
   - Should use enum values

7. **src/gleitzeit/persistence/unified_redis.py**
   - Multiple lines using string literals
   - Lines 305, 480, 533, 546, 548: Should use TaskStatus enum values

## Mixed Usage Patterns

Some files correctly convert strings to enums:
- `src/gleitzeit/core/stateless_dependency_manager.py:605` - Correctly uses `TaskStatus(task.get('status', 'pending'))`
- `src/gleitzeit/persistence/unified_redis.py:305` - Correctly uses `TaskStatus(data.get('status', 'pending'))`

## Recommendations

### Immediate Fixes Required:

1. **Find and fix all TaskStatus.RUNNING references**
   - Replace with `TaskStatus.EXECUTING`

2. **Standardize on enum usage**
   - Replace all string literal comparisons with enum comparisons
   - Use `TaskStatus.value` when string value is needed

3. **Add validation layer**
   - When receiving status from external sources (API, Redis), always convert to enum
   - Use try/except to handle invalid status values gracefully

### Code Pattern to Follow:

```python
# Good - Using enum
if task.status == TaskStatus.COMPLETED:
    ...

# Good - Converting string to enum
status = TaskStatus(status_str)

# Good - Getting string value from enum
status_value = TaskStatus.COMPLETED.value

# Bad - Using string literals
if task.status == "completed":
    ...
```

## Action Items

1. ✅ Search for `TaskStatus.RUNNING` - NONE FOUND in grep
2. ⚠️  Replace string literals with enum usage in identified files
3. ⚠️  Add type hints to ensure TaskStatus enum is used
4. ⚠️  Add validation when deserializing from Redis/API

## Files Needing Updates

Priority files to update (most critical):
1. `src/gleitzeit/persistence/unified_redis.py`
2. `src/gleitzeit/task_queue/task_queue.py`
3. `src/gleitzeit/providers/timer_provider.py`
4. `src/gleitzeit/providers/signal_provider.py`
5. `src/gleitzeit/client/mixins/event_workflow.py`

## Validation Status

- ✅ All TaskStatus enum references use valid values
- ❌ Many files use string literals instead of enums
- ⚠️  Mixed patterns create confusion and potential bugs
- ⚠️  Need to investigate runtime error showing TaskStatus.RUNNING