# Enum Inconsistencies Audit

## Summary
Comprehensive audit of enum usage inconsistencies across the Gleitzeit codebase.

## 1. TaskStatus Enum Issues (FIXED)
✅ **Already Fixed** - 9 incorrect `TaskStatus.RUNNING` references changed to `TaskStatus.EXECUTING`
- See TASKSTATUS-FIX.md for details

## 2. Duplicate Enum Definitions

### BackoffStrategy Duplication
**Issue**: `BackoffStrategy` enum is defined identically in two files:
- `/src/gleitzeit/core/retry_manager.py:24`
- `/src/gleitzeit/core/event_driven_retry_manager.py:24`

**Impact**: Code duplication, maintenance burden
**Recommendation**: Move to a shared location like `/src/gleitzeit/core/models.py` or create `/src/gleitzeit/core/retry_types.py`

## 3. Hardcoded Status Strings

### WorkflowStatus Strings (7 occurrences)
Files using hardcoded workflow status strings instead of `WorkflowStatus` enum:

1. **src/gleitzeit/client/adapters/native.py**
   - Line 145: `workflow.status = "cancelled"` → Should use `WorkflowStatus.CANCELLED`
   - Line 160: `workflow.status = "paused"` → Should use `WorkflowStatus.PAUSED`
   - Line 175: `workflow.status = "running"` → Should use `WorkflowStatus.RUNNING`

2. **Test Files** (Less critical but should be consistent):
   - `newtests/client/test_client_mixins.py:427`: "completed"
   - `tests/api/test_workflow_endpoints.py:156`: "completed"
   - `tests/api/test_workflow_endpoints.py:338`: "completed"
   - `tests/api/test_list_endpoints.py:109`: "completed"

### TaskStatus Strings (33 occurrences)
Files using hardcoded task status strings:

1. **Production Code Issues**:
   - **src/gleitzeit/replay/manager.py**
     - Lines 223, 328, 389, 432: `task.status = "pending"` → Should use `TaskStatus.PENDING`
     - Line 383: `task.status = "skipped"` → Note: "skipped" is not a valid TaskStatus enum value
   
   - **src/gleitzeit/persistence/unified_persistence.py**
     - Line 1239: `task.status = "executing"` → Should use `TaskStatus.EXECUTING`
   
   - **src/gleitzeit/persistence/unified_sqlalchemy.py**
     - Line 1233: `db_task.status = 'executing'` → Should use `TaskStatus.EXECUTING`
   
   - **src/gleitzeit/persistence/unified_redis.py**
     - Line 933: `task.status = 'executing'` → Should use `TaskStatus.EXECUTING`
   
   - **src/gleitzeit/persistence/atomic_operations.py** (Lua scripts - special case)
     - Line 101: `task.status = 'running'` → Invalid status! Should be 'executing'
     - Line 301: `task.status = 'pending'` → Should map to TaskStatus.PENDING

2. **Test Files** (Multiple occurrences in tests - less critical)

## 4. Invalid Status Values

### Critical Issues:
1. **"running" used for tasks** (should be "executing"):
   - `atomic_operations.py:101` (in Lua script)
   - Multiple test files using "running" for tasks

2. **"skipped" status**:
   - `replay/manager.py:383` uses "skipped" which is not in TaskStatus enum
   - Need to either add to enum or use different status

## 5. Recommendations

### Immediate Actions:
1. **Fix hardcoded strings in production code**:
   - Update `native.py` to use WorkflowStatus enum
   - Update `replay/manager.py` to use TaskStatus enum
   - Update persistence files to use TaskStatus enum

2. **Fix Lua scripts in atomic_operations.py**:
   - Change 'running' to 'executing' 
   - Consider using string constants that map to Python enums

3. **Resolve duplicate BackoffStrategy**:
   - Move to shared module
   - Import from single source

### Design Decisions Needed:
1. **"skipped" status**: Should this be added to TaskStatus enum or handled differently?
2. **Test consistency**: Should tests also use enums for better type safety?
3. **Lua script handling**: How to maintain consistency between Python enums and Lua string values?

## Files Requiring Updates

### Priority 1 (Production Code):
- [ ] `/src/gleitzeit/client/adapters/native.py` (3 fixes)
- [ ] `/src/gleitzeit/replay/manager.py` (5 fixes + "skipped" issue)
- [ ] `/src/gleitzeit/persistence/atomic_operations.py` (2 Lua script fixes)
- [ ] `/src/gleitzeit/persistence/unified_persistence.py` (1 fix)
- [ ] `/src/gleitzeit/persistence/unified_sqlalchemy.py` (1 fix)
- [ ] `/src/gleitzeit/persistence/unified_redis.py` (1 fix)

### Priority 2 (Code Organization):
- [ ] Consolidate BackoffStrategy enum definition
- [ ] Create constants for Lua scripts if needed

### Priority 3 (Tests - Optional):
- [ ] Update test files to use enums consistently

## Total Issues Found:
- **9 TaskStatus.RUNNING errors**: ✅ Already fixed
- **1 duplicate enum definition**: BackoffStrategy
- **13 hardcoded status strings in production code**
- **2 invalid status values**: "running" for tasks, "skipped" not in enum
- **20+ hardcoded strings in test files** (lower priority)