# Conditional Tasks - Implementation Fix Plan

**Date:** 2025-10-19
**Based on:** [CONDITIONAL_TASKS_AUDIT.md](./CONDITIONAL_TASKS_AUDIT.md)
**Status:** 📋 PLANNING

---

## Overview

This plan addresses the 6 critical issues found in the conditional tasks audit, organized by priority and implementation complexity.

---

## Phase 1: Critical Bug Fixes (Required for Basic Functionality)

**Timeline:** 1-2 days
**Risk:** Low (straightforward fixes)
**Testing:** Unit + Integration tests required

### 1.1 Add TASK_BLOCKED Event Type

**Priority:** 🔴 CRITICAL
**Complexity:** ⭐ TRIVIAL
**Files Modified:** 2

#### Implementation Steps:

1. **Add event type definition**
   - File: `src/gleitzeit/core/events.py`
   - Location: After line 41 (after TASK_SKIPPED)
   - Change:
   ```python
   TASK_SKIPPED = "task:skipped"  # Task skipped due to validation failure
   TASK_BLOCKED = "task:blocked"  # Task blocked by validation/dependency
   ```

2. **Update DependencyWorker to use new event**
   - File: `src/gleitzeit/workers/dependency_worker.py`
   - Location: Line 1210
   - Change:
   ```python
   # Before:
   event_type=EventType.TASK_CANCELLED,  # No TASK_BLOCKED yet

   # After:
   event_type=EventType.TASK_BLOCKED,
   ```

3. **Create test**
   - File: `tests/test_conditional_tasks.py` (new)
   - Test that blocked tasks emit TASK_BLOCKED event

#### Success Criteria:
- ✅ TASK_BLOCKED event type defined
- ✅ DependencyWorker uses TASK_BLOCKED instead of TASK_CANCELLED
- ✅ WebSocket receives TASK_BLOCKED events
- ✅ Test passes

---

### 1.2 Fix Duplicate Skip Logic

**Priority:** 🔴 CRITICAL
**Complexity:** ⭐⭐ EASY
**Files Modified:** 1

#### Implementation Steps:

1. **Analyze current flow**
   - `_check_validation_dependencies()` already:
     - Sets status to "skipped" (line 1166)
     - Adds to tasks:skipped set (line 1172)
     - Emits TASK_SKIPPED event (line 1150)
     - Returns True

2. **Update caller to only handle accounting**
   - File: `src/gleitzeit/workers/dependency_worker.py`
   - Location: Lines 552-575
   - Change:
   ```python
   if should_skip:
       # Status and event already handled by _check_validation_dependencies
       # Only update accounting here
       await self.redis.hincrby(
           default_sharding.get_workflow_key("state", workflow_id).encode(),
           b"skipped_tasks",
           1
       )
       await self.redis.hincrby(
           default_sharding.get_workflow_key("state", workflow_id).encode(),
           b"pending_tasks",
           -1
       )
       logger.info(f"Task {task_id} skipped due to validation failure (accounting updated)")
       continue
   ```

3. **Remove duplicate status setting**
   - Delete lines 554-560 (the duplicate hset call)

4. **Add verification logging**
   - Log in `_check_validation_dependencies()` when skip is applied
   - Log in caller when accounting is updated

#### Success Criteria:
- ✅ Status set only once
- ✅ Skipped count incremented only once
- ✅ Event emitted only once
- ✅ No duplicate Redis writes
- ✅ Test verifies single skip event per task

---

### 1.3 Fix Gate Control Task Name/ID Mismatch

**Priority:** 🔴 CRITICAL
**Complexity:** ⭐⭐⭐ MODERATE
**Files Modified:** 1

#### Root Cause Analysis:

The issue is in `dependency_worker.py:1249-1266`:
```python
skip_tasks = control.get('skip_tasks', [])
current_task = self.find_task_by_id(workflow, task_id)
task_name = current_task.get('name') if current_task else task_id
if task_name in skip_tasks:
```

The problem: Gate returns task **names** but we compare against task **IDs**.

#### Solution Options:

**Option A: Change ValidationHandler to return task IDs (RECOMMENDED)**
- Pros: More robust, IDs are unique
- Cons: Requires users to specify task IDs in gate rules

**Option B: Change DependencyWorker to build name→ID mapping**
- Pros: User-friendly, can use task names
- Cons: More complex, names may not be unique

**Recommended: Option A**

#### Implementation Steps:

1. **Update ValidationHandler gate documentation**
   - File: `src/gleitzeit/handlers/validation.py`
   - Location: Lines 69-75
   - Change:
   ```python
   'validation/gate': {
       'description': 'Gate keeper for workflow branches',
       'params': {
           'rules': 'Gating rules with branch control (use task IDs)',
           'context': 'Additional context for evaluation',
           # Note: enable_tasks and disable_tasks should contain task IDs, not names
       }
   }
   ```

2. **Update gate result to clarify task IDs**
   - File: `src/gleitzeit/handlers/validation.py`
   - Location: Lines 348-351
   - Change result documentation:
   ```python
   'control': {
       'enable_tasks': list(tasks_to_enable),  # Task IDs
       'skip_tasks': list(tasks_to_skip)        # Task IDs
   },
   ```

3. **Update DependencyWorker to use task ID directly**
   - File: `src/gleitzeit/workers/dependency_worker.py`
   - Location: Lines 1249-1266
   - Change:
   ```python
   # Check for gate control directives
   control = result_data.get('control', {})
   if control:
       skip_tasks = control.get('skip_tasks', [])

       # Check if current task ID is in skip list
       if task_id in skip_tasks:
           logger.info(f"Task {task_id} in skip list from validation gate {dep_id}")

           # Emit TASK_SKIPPED event (not TASK_BLOCKED)
           await self.event_store.store_event(
               event_type=EventType.TASK_SKIPPED,
               workflow_id=workflow_id,
               task_id=task_id,
               level=EventLevel.IMPORTANT,
               data={
                   'reason': f"Skipped by validation gate {dep_id}",
                   'validation_task': dep_id,
                   'gate_control': True
               }
           )

           await self.redis.hset(
               default_sharding.get_task_key(task_id, workflow_id).encode(),
               mapping={
                   b"status": b"skipped",  # Changed from "blocked"
                   b"skipped_reason": f"Gated by validation {dep_id}".encode(),
                   b"skipped_at": datetime.utcnow().isoformat().encode()
               }
           )

           # Add to skipped set
           await self.redis.sadd(
               default_sharding.get_workflow_key("tasks:skipped", workflow_id).encode(),
               task_id.encode()
           )

           return True
   ```

4. **Update documentation with examples**
   - Add example showing task IDs in gate rules
   - Document the difference between name and ID

#### Success Criteria:
- ✅ Gate control uses task IDs consistently
- ✅ Gated tasks are marked as "skipped" not "blocked"
- ✅ TASK_SKIPPED event emitted for gated tasks
- ✅ Documentation clarifies task ID requirement
- ✅ Test validates gate control works end-to-end

---

## Phase 2: Feature Enhancements (Required for Production Use)

**Timeline:** 3-5 days
**Risk:** Medium (new features, careful design needed)
**Testing:** Extensive integration tests required

### 2.1 Add Context Injection from Task Results

**Priority:** 🟡 HIGH
**Complexity:** ⭐⭐⭐⭐ COMPLEX
**Files Modified:** 2-3

#### Design:

Allow validation tasks to extract data from dependency task results:

```yaml
tasks:
  - id: compute_threshold
    protocol: python/v1
    method: python/execute
    params:
      code: "result = {'threshold': 95, 'status': 'ok'}"

  - id: validate_threshold
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - "threshold > 90"
        - "status == 'ok'"
      context_from_tasks:
        threshold: "compute_threshold.result.threshold"
        status: "compute_threshold.result.status"
    dependencies:
      - compute_threshold

  - id: process_data
    protocol: python/v1
    method: python/execute
    params:
      code: "result = {'processed': True}"
    dependencies:
      - validate_threshold
```

#### Implementation Steps:

1. **Add context injection to ValidationHandler**
   - File: `src/gleitzeit/handlers/validation.py`
   - Location: `_evaluate_conditions()` method (line 104)
   - Before evaluation, fetch dependency results and merge into context

2. **Implement result fetcher**
   ```python
   async def _build_context(self, task: Task) -> Dict[str, Any]:
       """Build context from static params and dependency results."""
       context = task.params.get('context', {}).copy()

       # Check for context_from_tasks
       context_from_tasks = task.params.get('context_from_tasks', {})

       if context_from_tasks:
           # Get Redis connection from handler config
           redis = self.config.get('redis')

           for var_name, path_spec in context_from_tasks.items():
               # Parse path: "task_id.result.field.subfield"
               parts = path_spec.split('.')
               dep_task_id = parts[0]

               # Fetch dependency task result
               task_key = default_sharding.get_task_key(dep_task_id, task.workflow_id)
               result_json = await redis.hget(task_key.encode(), b'result')

               if result_json:
                   result_data = json.loads(result_json.decode())

                   # Navigate the path
                   value = result_data
                   for part in parts[1:]:  # Skip task_id
                       if isinstance(value, dict):
                           value = value.get(part)
                       else:
                           value = None
                           break

                   if value is not None:
                       context[var_name] = value

       return context
   ```

3. **Update method signature**
   ```python
   async def _evaluate_conditions(self, task: Task) -> TaskResult:
       conditions = task.params.get('conditions', [])
       mode = task.params.get('mode', 'all')
       on_failure = task.params.get('on_failure', 'skip')

       # Build context from static params + dependency results
       context = await self._build_context(task)
   ```

4. **Handle errors gracefully**
   - If dependency task not found: log warning, skip that context var
   - If result path invalid: log warning, skip that context var
   - If result not yet available: treat as validation failure?

5. **Add to capabilities**
   ```python
   'validation/evaluate': {
       'description': 'Evaluate conditions and control flow',
       'params': {
           'conditions': 'List of conditions to evaluate',
           'mode': 'How to combine conditions (all/any/custom)',
           'context': 'Static context for evaluation',
           'context_from_tasks': 'Dynamic context from task results (dict: var -> task.path)',
           'on_failure': 'What to do when validation fails (skip/fail/continue)'
       }
   }
   ```

#### Success Criteria:
- ✅ Can extract simple values from task results
- ✅ Can extract nested values (e.g., `task.result.data.value`)
- ✅ Handles missing dependencies gracefully
- ✅ Handles invalid paths gracefully
- ✅ Works with all validation methods (evaluate, assert, gate)
- ✅ Test covers various path patterns
- ✅ Documentation includes examples

---

### 2.2 Expand Expression Evaluation Functions

**Priority:** 🟡 MEDIUM
**Complexity:** ⭐⭐ EASY
**Files Modified:** 1

#### Implementation Steps:

1. **Expand function library**
   - File: `src/gleitzeit/handlers/validation.py`
   - Location: Lines 34-44
   - Change:
   ```python
   self.evaluator.functions = {
       # Existing numeric functions
       'len': len,
       'abs': abs,
       'min': min,
       'max': max,
       'round': round,
       'sum': sum,

       # Type conversions
       'str': str,
       'int': int,
       'float': float,
       'bool': bool,

       # String operations (safe wrappers)
       'lower': lambda s: s.lower() if isinstance(s, str) else str(s).lower(),
       'upper': lambda s: s.upper() if isinstance(s, str) else str(s).upper(),
       'strip': lambda s: s.strip() if isinstance(s, str) else str(s).strip(),
       'startswith': lambda s, prefix: s.startswith(prefix) if isinstance(s, str) else False,
       'endswith': lambda s, suffix: s.endswith(suffix) if isinstance(s, str) else False,
       'contains': lambda s, sub: sub in s if isinstance(s, str) else False,
       'split': lambda s, sep=None: s.split(sep) if isinstance(s, str) else [],

       # List/collection operations
       'any': any,
       'all': all,
       'sorted': sorted,
       'reversed': lambda x: list(reversed(x)),

       # Type checking
       'isinstance': isinstance,
       'type': lambda x: type(x).__name__,

       # Safe None handling
       'is_none': lambda x: x is None,
       'is_not_none': lambda x: x is not None,
       'default': lambda x, default: default if x is None else x,
   }
   ```

2. **Add operators reference to docs**
   - Document available functions in ValidationHandler docstring
   - Add examples of common patterns

3. **Consider adding safe regex**
   ```python
   import re

   def safe_match(pattern, string):
       """Safe regex match with timeout protection."""
       try:
           return bool(re.match(pattern, str(string)))
       except Exception:
           return False

   self.evaluator.functions['matches'] = safe_match
   ```

#### Success Criteria:
- ✅ All new functions work correctly
- ✅ String operations handle non-string inputs gracefully
- ✅ Documentation updated with function reference
- ✅ Tests cover common use cases
- ✅ No security vulnerabilities introduced

---

## Phase 3: Testing & Documentation

**Timeline:** 2-3 days
**Risk:** Low
**Testing:** This IS the testing phase

### 3.1 Create Comprehensive Test Suite

**Priority:** 🔴 CRITICAL
**Complexity:** ⭐⭐⭐⭐ COMPLEX
**Files Created:** 3-4 test files

#### Test Files to Create:

1. **`tests/test_validation_handler.py`** - Unit tests
   ```python
   import pytest
   from gleitzeit.handlers.validation import ValidationHandler
   from gleitzeit.core.models import Task, TaskStatus

   @pytest.mark.asyncio
   async def test_evaluate_all_conditions_pass():
       """Test that all conditions must pass with mode='all'"""

   @pytest.mark.asyncio
   async def test_evaluate_any_conditions_pass():
       """Test that any condition can pass with mode='any'"""

   @pytest.mark.asyncio
   async def test_evaluate_none_conditions():
       """Test that no conditions pass with mode='none'"""

   @pytest.mark.asyncio
   async def test_assert_failure():
       """Test that assert fails task when condition is false"""

   @pytest.mark.asyncio
   async def test_gate_control_skip_tasks():
       """Test gate control returns correct skip lists"""

   @pytest.mark.asyncio
   async def test_context_injection():
       """Test context_from_tasks extracts dependency results"""

   @pytest.mark.asyncio
   async def test_expression_functions():
       """Test expanded function library"""
   ```

2. **`tests/test_conditional_execution.py`** - Integration tests
   ```python
   @pytest.mark.asyncio
   async def test_validation_skip_dependent_task():
       """Test that failed validation skips dependent tasks"""

   @pytest.mark.asyncio
   async def test_validation_fail_dependent_task():
       """Test that validation with on_failure='fail' fails dependent"""

   @pytest.mark.asyncio
   async def test_validation_block_dependent_task():
       """Test that validation with on_failure='block' blocks dependent"""

   @pytest.mark.asyncio
   async def test_gate_control_workflow():
       """Test full workflow with gate control"""

   @pytest.mark.asyncio
   async def test_context_from_previous_task():
       """Test validation uses data from previous task result"""
   ```

3. **`tests/test_conditional_websocket.py`** - WebSocket event tests
   ```python
   @pytest.mark.asyncio
   async def test_task_skipped_event():
       """Test TASK_SKIPPED event is published"""

   @pytest.mark.asyncio
   async def test_task_blocked_event():
       """Test TASK_BLOCKED event is published"""

   @pytest.mark.asyncio
   async def test_gate_control_skip_event():
       """Test gate control emits skip events"""
   ```

4. **`tests/workflows/conditional_examples.py`** - Example workflows
   - Simple validation with skip
   - Validation with fail
   - Gate control with multiple branches
   - Context injection from previous task
   - Complex multi-gate workflow

#### Success Criteria:
- ✅ 30+ test cases covering all scenarios
- ✅ All tests pass
- ✅ Code coverage > 90% for validation code
- ✅ Edge cases covered (missing deps, invalid context, etc.)

---

### 3.2 Update Documentation

**Priority:** 🟡 HIGH
**Complexity:** ⭐⭐ EASY
**Files Modified:** 2-3

#### Documentation Updates:

1. **Create conditional tasks guide**
   - File: `docs/conditional-tasks-guide.md` (new)
   - Sections:
     - Introduction to conditional execution
     - validation/evaluate examples
     - validation/assert examples
     - validation/gate examples
     - Context injection from task results
     - Available expression functions
     - Best practices
     - Common patterns

2. **Update WebSocket examples**
   - File: `docs/python-client-websocket-examples.md`
   - Add section on monitoring conditional workflows
   - Show TASK_SKIPPED and TASK_BLOCKED events

3. **Update main README**
   - Add conditional tasks to feature list
   - Link to conditional tasks guide

#### Success Criteria:
- ✅ Complete guide with examples
- ✅ All examples are tested and work
- ✅ WebSocket monitoring documented
- ✅ README updated

---

## Implementation Order

### Week 1: Critical Fixes

**Day 1-2:**
- ✅ Phase 1.1: Add TASK_BLOCKED event type
- ✅ Phase 1.2: Fix duplicate skip logic
- ✅ Create basic test structure

**Day 3-4:**
- ✅ Phase 1.3: Fix gate control task name/ID mismatch
- ✅ Write tests for Phase 1 fixes
- ✅ Verify all Phase 1 tests pass

**Day 5:**
- ✅ Phase 3.1 (partial): Write integration tests for existing functionality
- ✅ Buffer for fixing any issues found

### Week 2: Feature Enhancements

**Day 1-3:**
- ✅ Phase 2.1: Implement context injection from task results
- ✅ Write comprehensive tests
- ✅ Debug and refine

**Day 4:**
- ✅ Phase 2.2: Expand expression evaluation functions
- ✅ Write function tests
- ✅ Update capabilities documentation

**Day 5:**
- ✅ Phase 3.2: Documentation
- ✅ Create examples
- ✅ Final testing and validation

---

## Testing Strategy

### Test Pyramid:

```
        /\
       /  \      E2E Tests (5-10 tests)
      /    \     - Full workflows with validation
     /------\
    /        \   Integration Tests (20-30 tests)
   /          \  - DependencyWorker + ValidationHandler
  /            \ - WebSocket event publishing
 /--------------\
/                \ Unit Tests (40-50 tests)
                   - ValidationHandler methods
                   - Context injection logic
                   - Expression evaluation
```

### Test Coverage Goals:

- **Unit Tests:** 95%+ coverage of ValidationHandler
- **Integration Tests:** All conditional workflows scenarios
- **E2E Tests:** Full workflows with Python client monitoring

---

## Rollback Plan

If issues are discovered after deployment:

1. **Phase 1 rollback:**
   - Revert event type changes
   - Keep TASK_CANCELLED for blocked tasks
   - Low risk

2. **Phase 2 rollback:**
   - Disable context injection feature via feature flag
   - Fall back to static context only
   - Medium risk

3. **Complete rollback:**
   - Revert all changes to dependency_worker.py
   - Keep validation handler as-is (it's already working)
   - High impact but always possible

---

## Success Metrics

### Functional Metrics:
- ✅ All 6 issues from audit resolved
- ✅ 80+ tests passing
- ✅ Zero known bugs

### Quality Metrics:
- ✅ Code coverage > 90%
- ✅ Documentation complete
- ✅ All examples working

### Performance Metrics:
- ⏱️ Validation execution < 100ms
- ⏱️ Context injection < 50ms overhead
- ⏱️ No memory leaks in expression evaluation

---

## Risk Assessment

| Phase | Risk Level | Mitigation |
|-------|-----------|------------|
| 1.1 TASK_BLOCKED | 🟢 LOW | Simple addition, well-tested |
| 1.2 Duplicate skip | 🟢 LOW | Logic simplification, tests verify |
| 1.3 Gate control | 🟡 MEDIUM | Breaking change for gate users (if any) |
| 2.1 Context injection | 🟡 MEDIUM | New feature, needs extensive testing |
| 2.2 Expression functions | 🟢 LOW | Additive, backward compatible |
| 3.1 Testing | 🟢 LOW | Only improves quality |
| 3.2 Documentation | 🟢 LOW | No code changes |

**Overall Risk:** 🟡 MEDIUM

---

## Open Questions

1. **Context injection timing:**
   - What if dependency task result not yet available?
   - Should we wait or fail validation?

2. **Gate control breaking change:**
   - Are there existing users of validation/gate?
   - Can we support both task names AND IDs?

3. **Performance:**
   - How many task results can we reasonably inject?
   - Should we cache fetched results?

4. **Security:**
   - Any concerns with expanded expression functions?
   - Rate limiting for validation tasks?

---

## Next Steps

1. **Review this plan** with team/stakeholders
2. **Prioritize** which phases are must-have vs nice-to-have
3. **Assign** tasks if working with team
4. **Start with Phase 1.1** (easiest win)
5. **Create feature branch** for all changes
6. **Run tests continuously** as changes are made

---

## Conclusion

This plan systematically addresses all issues found in the audit:
- ✅ Fixes 3 critical bugs (Phase 1)
- ✅ Adds 2 major features (Phase 2)
- ✅ Creates comprehensive tests (Phase 3)
- ✅ Updates documentation (Phase 3)

**Estimated Total Time:** 2 weeks (1 developer)
**Risk Level:** Medium (manageable with proper testing)
**Impact:** High (enables production use of conditional tasks)
