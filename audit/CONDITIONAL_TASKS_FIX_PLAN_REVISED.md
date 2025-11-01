# Conditional Tasks - Implementation Fix Plan (REVISED)

**Date:** 2025-10-19
**Revision:** After discovering existing dependency result injection
**Based on:** [CONDITIONAL_TASKS_AUDIT.md](./CONDITIONAL_TASKS_AUDIT.md)
**Status:** 📋 PLANNING

---

## IMPORTANT DISCOVERY

**Tasks already have access to dependency results via the `inputs` variable!**

From `/docs/api/QUICK_START.md` lines 254-269:
```python
{
    "id": "transform",
    "type": "python",
    "handler": "python",
    "depends_on": ["fetch"],
    "config": {
        "code": """
# Access previous task result
data = inputs.get("fetch", {}).get("data", [])
transformed = [x * 2 for x in data]
result = {"transformed": transformed}
"""
    }
}
```

**This means Phase 2.1 (Context Injection) is NOT needed!**

Validation tasks can already access dependency results - we just need to document it properly!

---

## Revised Plan Overview

### Phase 1: Critical Bug Fixes (UNCHANGED)
1. ✅ Add TASK_BLOCKED event type
2. ✅ Fix duplicate skip logic
3. ✅ Fix gate control task name/ID mismatch

### Phase 2: Feature Enhancements (SIMPLIFIED)
4. ~~Add context injection~~ **→ DOCUMENT existing `inputs` mechanism**
5. ✅ Expand expression evaluation functions

### Phase 3: Testing & Documentation (ENHANCED)
6. ✅ Comprehensive test suite
7. ✅ **Document `inputs` variable for ValidationHandler**

---

## Phase 1: Critical Bug Fixes (UNCHANGED)

[Same as original plan - no changes needed]

See original plan for detailed implementation steps for:
- 1.1: Add TASK_BLOCKED event type
- 1.2: Fix duplicate skip logic
- 1.3: Fix gate control task name/ID mismatch

---

## Phase 2: Feature Enhancements (REVISED)

### 2.1 ~~Add Context Injection~~ → Document Existing Input Mechanism

**Priority:** 🟡 HIGH
**Complexity:** ⭐ TRIVIAL (documentation only!)
**Files Modified:** 2-3 (docs only)

#### What We Discovered:

Tasks already receive dependency results automatically via an `inputs` dict:
```python
inputs = {
    "task_id_1": {"result": {...}, "status": "completed"},
    "task_id_2": {"result": {...}, "status": "completed"}
}
```

This works for **ALL handlers**, including ValidationHandler!

#### Validation Can Already Do This:

```yaml
tasks:
  - id: compute_threshold
    protocol: python/v1
    method: python/execute
    params:
      code: "result = {'threshold': 95}"

  - id: validate_threshold
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - "threshold > 90"
      context:
        # Just pass inputs directly!
        threshold: "{{inputs.compute_threshold.threshold}}"
    dependencies:
      - compute_threshold
```

**WAIT** - We need to verify if ValidationHandler actually receives `inputs`. Let me check...

#### Implementation Steps:

1. **Verify ValidationHandler receives inputs**
   - Check if Task model includes inputs
   - Check if handlers get inputs injected
   - Test with simple validation task

2. **If inputs ARE available (most likely):**
   - Document how to use `inputs` in validation context
   - Create examples showing validation based on previous results
   - Update ValidationHandler docstring

3. **If inputs are NOT available:**
   - Implement lightweight input injection for ValidationHandler only
   - Much simpler than originally planned
   - Just copy inputs from Task to context before evaluation

#### Success Criteria:
- ✅ Validation tasks can access dependency results
- ✅ Documentation shows how to use inputs
- ✅ Examples demonstrate real-world use cases
- ✅ Works with all 3 validation methods (evaluate, assert, gate)

---

### 2.2 Expand Expression Evaluation Functions (UNCHANGED)

[Same as original plan - no changes needed]

Add string, list, and type-checking functions to SimpleEval.

---

## Phase 3: Testing & Documentation (ENHANCED)

### 3.1 Create Comprehensive Test Suite (ENHANCED)

**Additional test scenarios to add:**

```python
@pytest.mark.asyncio
async def test_validation_with_dependency_inputs():
    """Test validation can access dependency task results via inputs"""
    workflow = {
        "name": "validation_with_inputs",
        "tasks": [
            {
                "id": "compute",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = {'value': 95}"}
            },
            {
                "id": "validate",
                "protocol": "validation/v1",
                "method": "validation/evaluate",
                "params": {
                    "conditions": ["value > 90"],
                    "context": {
                        # Access via inputs
                        "value": "{{inputs.compute.value}}"
                    }
                },
                "dependencies": ["compute"]
            }
        ]
    }
    # Test that validation passes and uses computed value
```

### 3.2 Update Documentation (ENHANCED)

**New documentation needed:**

1. **Create `docs/conditional-tasks-guide.md`**
   - How conditional execution works
   - **NEW:** How to access dependency results in validation
   - validation/evaluate examples
   - validation/assert examples
   - validation/gate examples
   - Available expression functions
   - Best practices

2. **Example workflows showing inputs usage:**
   ```yaml
   # Example 1: Simple threshold check
   tasks:
     - id: analyze
       protocol: python/v1
       method: python/execute
       params:
         code: "result = {'score': 85, 'passed': True}"

     - id: check_score
       protocol: validation/v1
       method: validation/evaluate
       params:
         conditions: ["score >= 80", "passed == True"]
         context:
           score: "{{inputs.analyze.score}}"
           passed: "{{inputs.analyze.passed}}"
       dependencies: [analyze]

   # Example 2: Gate control based on previous task
   tasks:
     - id: detect_environment
       protocol: python/v1
       method: python/execute
       params:
         code: "result = {'env': 'production', 'region': 'us-east-1'}"

     - id: gate_by_env
       protocol: validation/v1
       method: validation/gate
       params:
         rules:
           - name: production_path
             condition: "env == 'production'"
             enable_tasks: [deploy_prod, notify_ops]
             disable_tasks: [deploy_dev, skip_tests]
           - name: dev_path
             condition: "env == 'development'"
             enable_tasks: [deploy_dev, run_tests]
             disable_tasks: [deploy_prod]
         context:
           env: "{{inputs.detect_environment.env}}"
       dependencies: [detect_environment]
   ```

---

## Implementation Order (REVISED)

### Week 1: Critical Fixes + Verification

**Day 1:**
- ✅ Phase 1.1: Add TASK_BLOCKED event type (1-2 hours)
- ✅ Phase 1.2: Fix duplicate skip logic (2-3 hours)
- ✅ **Verify inputs mechanism works for ValidationHandler** (2-3 hours)

**Day 2:**
- ✅ Phase 1.3: Fix gate control task name/ID mismatch (4-6 hours)
- ✅ Write basic tests for Phase 1 fixes (2-3 hours)

**Day 3:**
- ✅ Phase 2.1: Document inputs usage (if it works) OR implement lightweight injection (if needed) (4-6 hours)
- ✅ Create example workflows using inputs (2-3 hours)

**Day 4:**
- ✅ Phase 2.2: Expand expression functions (3-4 hours)
- ✅ Write tests for expanded functions (2-3 hours)
- ✅ Buffer for issues

**Day 5:**
- ✅ Phase 3.1: Write comprehensive test suite (6-8 hours)

### Week 2: Testing & Documentation

**Day 1-2:**
- ✅ Continue test suite development
- ✅ Integration tests with inputs
- ✅ WebSocket event tests

**Day 3-4:**
- ✅ Phase 3.2: Complete documentation
- ✅ Conditional tasks guide
- ✅ Update existing docs

**Day 5:**
- ✅ Final testing
- ✅ Example validation
- ✅ Cleanup and review

---

## Key Changes from Original Plan

### Removed:
- ❌ **Context injection implementation** - Already exists!
- ❌ Complex `context_from_tasks` parameter design
- ❌ Redis fetching logic
- ❌ Path parsing (task.result.field.subfield)

### Added:
- ✅ **Verification step** - Confirm inputs work for ValidationHandler
- ✅ **Documentation focus** - Show users how to use existing feature
- ✅ **Template/interpolation** - May need `{{inputs.task.field}}` syntax

### Simplified:
- **Phase 2.1** reduced from 3-5 days to <1 day (mostly docs)
- **Overall timeline** reduced from 2 weeks to **1 week** (or less)
- **Risk** reduced significantly (less new code)

---

## Verification Checklist (NEW)

Before implementing Phase 2.1, we need to verify:

### ✅ Check 1: Task Model Has Inputs
```python
# Check if Task model has inputs field
task = Task(...)
if hasattr(task, 'inputs'):
    print("✅ Task has inputs")
```

### ✅ Check 2: Handler Receives Inputs
```python
# In ValidationHandler.execute()
async def execute(self, task: Task) -> TaskResult:
    print(f"Task inputs: {task.inputs if hasattr(task, 'inputs') else 'NO INPUTS'}")
```

### ✅ Check 3: Inputs Are Populated
```python
# Run test workflow with dependencies
# Check if inputs contains dependency results
```

### ✅ Check 4: Template Interpolation
- Does Gleitzeit support `{{inputs.task.field}}` syntax?
- Or do we need to manually extract inputs in ValidationHandler?
- Or is it raw dict access: `task.params.get('context', {})`?

---

## Updated Risk Assessment

| Phase | Risk Level | Original | Revised |
|-------|-----------|----------|---------|
| 1.1 TASK_BLOCKED | 🟢 LOW | LOW | **Same** |
| 1.2 Duplicate skip | 🟢 LOW | LOW | **Same** |
| 1.3 Gate control | 🟡 MEDIUM | MEDIUM | **Same** |
| 2.1 Context/Inputs | 🟢 **LOW** | MEDIUM | **REDUCED** ⬇️ |
| 2.2 Expression functions | 🟢 LOW | LOW | **Same** |
| 3.1 Testing | 🟢 LOW | LOW | **Same** |
| 3.2 Documentation | 🟢 LOW | LOW | **Same** |

**Overall Risk:** 🟢 **LOW** (was MEDIUM)

---

## Timeline Comparison

| Metric | Original Plan | Revised Plan | Savings |
|--------|---------------|--------------|---------|
| **Total Time** | 10-12 days | **5-7 days** | ~5 days |
| **Phase 2.1** | 3-5 days | **0.5-1 day** | 3-4 days |
| **New Code** | ~300 lines | **~50 lines** | 250 lines |
| **Risk Level** | MEDIUM | **LOW** | ⬇️⬇️ |

---

## Next Steps

1. **VERIFY inputs mechanism** ← START HERE
   - Create simple test workflow
   - Add validation task with dependency
   - Check if inputs are available
   - Test if context can reference inputs

2. **Based on verification results:**
   - **If inputs work:** Skip to documentation
   - **If need interpolation:** Implement template support
   - **If inputs missing:** Implement injection (but likely won't need to)

3. **Proceed with Phase 1** (bug fixes)

4. **Document and test** inputs usage

---

## Conclusion

**Major Discovery:** Gleitzeit already has a dependency result mechanism via `inputs`!

This dramatically simplifies our implementation plan:
- ✅ Less code to write
- ✅ Less testing needed
- ✅ Lower risk
- ✅ Faster delivery
- ✅ Uses existing, proven mechanism

The original audit was correct about the issues, but we can now fix them much more efficiently!

**Revised Estimate:**
- **1 week** (was 2 weeks)
- **Low risk** (was medium)
- **Minimal new code** (mostly docs and bug fixes)
