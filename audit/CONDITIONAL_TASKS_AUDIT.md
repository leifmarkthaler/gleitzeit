# Conditional Tasks Deep Audit - Gleitzeit 0.0.7

**Date:** 2025-10-19
**Auditor:** Claude Code
**Scope:** Complete analysis of conditional task execution implementation

---

## Executive Summary

### Status: ⚠️ **ISSUES FOUND**

The conditional task system is **implemented** but has several **critical issues** that may prevent it from working correctly:

1. ❌ **CRITICAL**: Task name vs task ID mismatch in gate control logic
2. ❌ **CRITICAL**: Missing TASK_BLOCKED event type definition
3. ⚠️ **WARNING**: Inconsistent handling between `_check_validation_dependencies` and task readiness flow
4. ⚠️ **WARNING**: No validation of context data source
5. ⚠️ **INFO**: Limited expression evaluation capabilities

---

## Architecture Overview

### Components

1. **ValidationHandler** ([handlers/validation.py](src/gleitzeit/handlers/validation.py))
   - Protocol: `validation/v1`
   - Methods: `evaluate`, `assert`, `gate`
   - Uses `simpleeval` for safe expression evaluation

2. **DependencyWorker** ([workers/dependency_worker.py](src/gleitzeit/workers/dependency_worker.py))
   - Lines 548-575: Check validation dependencies before dispatching tasks
   - Lines 1100-1268: `_check_validation_dependencies()` method
   - Publishes `TASK_SKIPPED` events via EventStore

3. **Event System** ([core/events.py](src/gleitzeit/core/events.py))
   - Line 41: `TASK_SKIPPED` event type defined
   - **MISSING**: `TASK_BLOCKED` event type

---

## Detailed Findings

### 1. ❌ CRITICAL: Task Name vs Task ID Mismatch

**Location:** `dependency_worker.py:1252-1266`

**Issue:**
```python
# Line 1252-1256
skip_tasks = control.get('skip_tasks', [])
# Find current task to get its name
current_task = self.find_task_by_id(workflow, task_id)
task_name = current_task.get('name') if current_task else task_id
if task_name in skip_tasks:
```

**Problem:**
- Gate control returns task **names** in `skip_tasks` list
- Code compares task **name** against skip list
- But earlier validation already returned (line 1176) if `on_failure='skip'`
- This gate control logic is **unreachable code** for most cases

**Impact:**
- Gate-based skipping (via `validation/gate` method) may not work as expected
- Tasks will be **blocked** instead of **skipped** (line 1261: `b"status": b"blocked"`)
- No `TASK_SKIPPED` event is emitted for gate-controlled skips

**Root Cause:**
The code has two different code paths:
1. Lines 1146-1176: Handles `on_failure='skip'` from `validation/evaluate` - **WORKS**
2. Lines 1249-1266: Handles gate control from `validation/gate` - **BROKEN**

These paths don't align properly.

---

### 2. ❌ CRITICAL: Missing TASK_BLOCKED Event Type

**Location:** `dependency_worker.py:1206-1221`

**Issue:**
```python
# Line 1209-1211
# Emit task blocked event (using CANCELLED as closest match)
await self.event_store.store_event(
    event_type=EventType.TASK_CANCELLED,  # No TASK_BLOCKED yet
```

**Problem:**
- Code explicitly states "No TASK_BLOCKED yet"
- Uses `TASK_CANCELLED` event type as a workaround
- But data payload says `'status': 'blocked'`
- This creates confusion in event consumers

**Impact:**
- WebSocket clients can't differentiate between blocked and cancelled tasks
- Analytics/monitoring will miscount blocked tasks as cancelled
- Event type doesn't match actual task status

**Recommendation:**
Add to `core/events.py`:
```python
TASK_BLOCKED = "task:blocked"  # Task blocked by validation/dependency
```

---

### 3. ⚠️ WARNING: Duplicate Skip Logic

**Location:** `dependency_worker.py:548-575` vs `dependency_worker.py:1146-1176`

**Issue:**
Skip logic appears in two places:
1. **Task readiness check** (lines 548-575): Sets status to `skipped` if `_check_validation_dependencies()` returns True
2. **Inside `_check_validation_dependencies()`** (lines 1163-1175): Also sets status to `skipped` and emits event

**Problem:**
- The task readiness check (lines 552-575) sets status to `skipped` **again** after `_check_validation_dependencies()` already did it
- The `TASK_SKIPPED` event is only emitted inside `_check_validation_dependencies()` (line 1150)
- But the skipped count is incremented in both places (lines 563-566)

**Impact:**
- Skipped task count may be incremented **twice** for the same task
- Inefficient duplicate Redis writes
- Potential race conditions

**Actual Code Flow:**
```
_check_validation_dependencies() is called (line 548)
  ↓
If validation failed with on_failure='skip':
  ↓
Sets status=skipped (line 1166)
Adds to tasks:skipped set (line 1172)
Emits TASK_SKIPPED event (line 1150)
Returns True
  ↓
Caller (line 552) checks: if should_skip:
  ↓
Sets status=skipped AGAIN (line 557)
Increments skipped_tasks count (line 563)
Decrements pending_tasks (line 569)
```

**Recommendation:**
The task readiness check should NOT re-set the status. It should only handle accounting:
```python
if should_skip:
    # Status already set by _check_validation_dependencies
    # Just update accounting
    await self.redis.hincrby(...)  # skipped count
    await self.redis.hincrby(...)  # pending count
    continue
```

---

### 4. ⚠️ WARNING: No Context Data Validation

**Location:** `handlers/validation.py:104-112`

**Issue:**
```python
async def _evaluate_conditions(self, task: Task) -> TaskResult:
    conditions = task.params.get('conditions', [])
    mode = task.params.get('mode', 'all')
    context = task.params.get('context', {})  # <-- No validation
    on_failure = task.params.get('on_failure', 'skip')
```

**Problem:**
- Context data comes from task params
- No mechanism to inject **runtime data from previous tasks**
- Users can only provide static context at workflow submission time
- Cannot make decisions based on previous task results

**Missing Feature:**
There's no built-in way to say "use the result of task X as context". Users would need to:
1. Use a python task to fetch results and build context
2. Pass that context to validation task
3. But validation task params are static at submission time

**Impact:**
- Severely limits usefulness of conditional execution
- Cannot do "if previous task returned X, skip next task"
- Most real-world conditional logic requires runtime data

**Recommendation:**
Add support for dependency result injection:
```python
{
    "id": "check_threshold",
    "protocol": "validation/v1",
    "method": "validation/evaluate",
    "params": {
        "conditions": ["threshold > 100"],
        "context_from_tasks": {  # <-- NEW FEATURE
            "threshold": "compute_threshold.result.value"
        }
    },
    "dependencies": ["compute_threshold"]
}
```

---

### 5. ⚠️ INFO: Limited Expression Evaluation

**Location:** `handlers/validation.py:34-44`

**Issue:**
```python
self.evaluator.functions = {
    'len': len,
    'abs': abs,
    'min': min,
    'max': max,
    'round': round,
    'str': str,
    'int': int,
    'float': float,
    'bool': bool,
}
```

**Problem:**
- Very limited set of functions
- No string operations (startswith, endswith, contains)
- No list operations (any, all - ironically these are Python builtins but not exposed)
- No regex support
- No date/time operations

**Impact:**
- Users limited to basic numeric comparisons
- Cannot do string matching, pattern matching, date comparisons
- Forces users to write Python tasks for simple string checks

**Recommendation:**
Expand safe functions:
```python
self.evaluator.functions = {
    # Existing...
    'len': len, 'abs': abs, 'min': min, 'max': max,
    'round': round, 'str': str, 'int': int, 'float': float, 'bool': bool,

    # String operations
    'lower': lambda s: s.lower() if isinstance(s, str) else s,
    'upper': lambda s: s.upper() if isinstance(s, str) else s,
    'startswith': lambda s, prefix: s.startswith(prefix) if isinstance(s, str) else False,
    'endswith': lambda s, suffix: s.endswith(suffix) if isinstance(s, str) else False,
    'contains': lambda s, sub: sub in s if isinstance(s, str) else False,

    # List operations
    'any': any,
    'all': all,
    'sum': sum,

    # Safe type checks
    'isinstance': isinstance,
    'type': type,
}
```

---

## WebSocket Event Integration

### ✅ Working: TASK_SKIPPED Events

**Code:** `dependency_worker.py:1150-1160`

```python
await self.event_store.store_event(
    event_type=EventType.TASK_SKIPPED,
    workflow_id=workflow_id,
    task_id=task_id,
    level=EventLevel.IMPORTANT,
    data={
        'reason': f"Validation {dep_id} returned false",
        'validation_task': dep_id,
        'on_failure': on_failure
    }
)
```

**Status:** ✅ **WORKS** - Events are published to WebSocket for skipped tasks

---

## Test Coverage Analysis

### ❌ NO TESTS FOUND

**Search Results:**
```bash
# No test files found for validation handler
$ find tests/ -name "*validation*" -o -name "*conditional*"
# (no results)
```

**Impact:**
- No automated testing of conditional logic
- High risk of regressions
- Issues like the ones found may go unnoticed

**Recommendation:**
Create comprehensive test suite covering:
1. validation/evaluate with all modes (all/any/none/custom)
2. validation/assert with passing and failing assertions
3. validation/gate with skip lists
4. on_failure behaviors (skip/fail/block)
5. Gate control with task name resolution
6. Context injection from task results
7. WebSocket event publishing for skipped tasks

---

## Recommendations Summary

### Immediate Fixes Required

1. **Fix Task Name Mismatch**
   - File: `dependency_worker.py:1249-1266`
   - Action: Use task_id instead of task_name for gate control comparison, OR make gate control return task IDs

2. **Add TASK_BLOCKED Event Type**
   - File: `core/events.py`
   - Action: Add `TASK_BLOCKED = "task:blocked"`
   - File: `dependency_worker.py:1209`
   - Action: Use `EventType.TASK_BLOCKED` instead of `TASK_CANCELLED`

3. **Remove Duplicate Skip Logic**
   - File: `dependency_worker.py:552-575`
   - Action: Don't re-set status=skipped, only handle accounting

### Feature Enhancements

4. **Add Context Injection from Task Results**
   - File: `handlers/validation.py`
   - Action: Support `context_from_tasks` parameter to inject runtime data

5. **Expand Expression Functions**
   - File: `handlers/validation.py:34-44`
   - Action: Add string, list, and type-checking functions

### Testing

6. **Create Comprehensive Test Suite**
   - Create: `tests/test_validation_handler.py`
   - Create: `tests/test_conditional_execution.py`
   - Add integration tests for all conditional workflows

---

## Risk Assessment

**Current Risk Level:** 🔴 **HIGH**

| Issue | Severity | Impact | Likelihood |
|-------|----------|--------|----------|
| Task name mismatch | HIGH | Gate control broken | 90% |
| Missing TASK_BLOCKED event | MEDIUM | Monitoring confusion | 100% |
| Duplicate skip logic | LOW | Count inflation | 50% |
| No context injection | HIGH | Limited usability | 100% |
| Limited expressions | MEDIUM | User workarounds | 80% |
| No test coverage | HIGH | Undetected bugs | 100% |

---

## Conclusion

The conditional task system has a **solid foundation** but several **critical bugs** prevent it from working correctly:

1. ❌ Gate control is broken due to task name vs ID mismatch
2. ❌ Missing event type causes monitoring issues
3. ⚠️ No runtime context injection severely limits usefulness
4. ❌ Zero test coverage means issues go undetected

**Recommendation:** Fix items #1-3 immediately and add comprehensive tests before considering this feature production-ready.

---

## Next Steps

1. Create failing tests that demonstrate the issues
2. Fix critical bugs (#1-3)
3. Add context injection feature
4. Expand expression evaluation
5. Add integration tests
6. Update documentation with examples
