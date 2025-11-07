# Workflow and Task State Transition Audit - REVISED

**Date**: 2025-10-12
**Issue**: Workflow status not transitioning correctly from "running" to "waiting"/"scheduled"

---

## Critical Findings After Deep Investigation

### Finding 1: Task States ARE Stored in Redis ✓

**Location**: `{shard:X}:task:status:{task_id}`

**Fields stored**:
```
status: "completed" | "scheduled" | "waiting" | "failed"
workflow_id: "..."
execution_id: "..."
result: {...}
completed_at: "..."
handler_id: "..."
worker_id: "..."
```

**Example**:
```bash
redis-cli hgetall "{shard:8}:task:status:5e033b9c-0e86-46e9-ac2f-8d385ebf6bab"
# Timer task:
status: completed
timer_type: sleep
scheduled_at: 2025-10-12T20:13:24.514702
timer_fired_at: 2025-10-12T20:13:54.559288
...
```

### Finding 2: Task Status Lifecycle (ACTUAL vs EXPECTED)

**EXPECTED** (from TaskStatus enum):
```
PENDING → EXECUTING → COMPLETED
           ↓
        SCHEDULED (timers)
           ↓
        WAITING (signals)
```

**ACTUAL** (verified in Redis):
```
Regular tasks:  (no status stored) → COMPLETED
Timer tasks:    (no status stored) → SCHEDULED → (waits) → COMPLETED
Signal tasks:   (no status stored) → WAITING → (waits) → COMPLETED
```

**Key Discovery**: The `EXECUTING` status exists in the enum but **is never actually set**!

Tasks go straight from no status to:
- `completed` for regular tasks
- `scheduled` for timer tasks (then later `completed`)
- `waiting` for signal tasks (then later `completed`)

### Finding 3: Why Counters Are Fundamentally Flawed

**The Problem**: Maintaining counters (`running_tasks`, `scheduled_tasks`, `waiting_tasks`) is error-prone because:

1. **Redundant state**: Task states are already stored in Redis
2. **Sync issues**: Counters can get out of sync with actual task states
3. **Complex update logic**: Multiple workers updating counters creates race conditions
4. **No single source of truth**: Counters can say one thing, task states another

**Current counter issues**:
- Going negative (e.g., `running_tasks = -1`)
- Don't match actual task states
- Require careful increment/decrement pairing that's fragile

### Finding 4: Reconciliation Worker Already Does It Right

**The reconciliation worker** ([reconciliation_worker.py:513-544](src/gleitzeit/workers/reconciliation_worker.py#L513-L544)) **already computes workflow status correctly**:

```python
# Get all task IDs
task_ids = await self.get_workflow_task_ids(workflow_id, shard)

# Query each task's actual status
counts = {'pending': 0, 'running': 0, 'completed': 0, ...}
for task_id in task_ids:
    task = await self.get_task(task_id, workflow_id, shard)
    status = task.get(b'status', b'pending').decode()

    # Count by status
    if status == 'pending':
        counts['pending'] += 1
    elif status in ['scheduled', 'sleeping']:
        counts['scheduled'] += 1
    # ... etc
```

**It computes from actual task states - no counters needed!**

---

## Root Cause Analysis - The Real Problem

### The Flawed Architecture

**Current approach**:
1. Dependency worker tries to maintain counters
2. Increments counter when task becomes ready (based on protocol)
3. Decrements counter when task completes (based on... what?)
4. Counters get out of sync → negative values

**The flaw**: Trying to maintain derived state (counters) separately from source state (task statuses)

### Why We Thought Counters Were Needed

**Assumption**: "Computing workflow status from task states is expensive"

**Reality**:
- Workflows typically have 10-100 tasks
- Querying task states is fast (Redis hash operations)
- Reconciliation worker already does this every 60 seconds
- The "performance optimization" of counters creates consistency bugs

### The Counter Increment/Decrement Mismatch

**When task becomes ready** ([dependency_worker.py:567-596](src/gleitzeit/workers/dependency_worker.py#L567-L596)):
```python
# Increment counter based on PROTOCOL
if protocol.startswith('timer/'):
    counter_field = b"scheduled_tasks"
elif protocol.startswith('signal/'):
    counter_field = b"waiting_tasks"
else:
    counter_field = b"running_tasks"

await redis.hincrby(workflow_state, counter_field, 1)
```

**When task completes** ([dependency_worker.py:285-290](src/gleitzeit/workers/dependency_worker.py#L285-L290)):
```python
# ALWAYS decrements running_tasks - WRONG!
await redis.hincrby(workflow_state, b"running_tasks", -1)
```

**Result**:
- Timer task: `scheduled_tasks++` on ready, `running_tasks--` on complete
- `scheduled_tasks = 1`, `running_tasks = -1` ❌

**Why we can't fix with status lookup**:
- Regular tasks never get intermediate status
- Can't tell if completed task was running/scheduled/waiting

**Why we can't fix with protocol lookup**:
- Would need workflow data on every completion
- Still fragile and hacky

---

## The Correct Solution: Stateless Workflow Status

### Principle: Single Source of Truth

**Task states in Redis are the source of truth**. Workflow status should be **computed** from task states, not maintained separately.

### The Clean Architecture

```
Task States (Redis)
       ↓ (query when needed)
   Compute Counts
       ↓
Determine Workflow Status
```

**No counters to maintain = no sync issues**

### Implementation Strategy

**Option A: Query on Every Status Check** ⭐ **RECOMMENDED**
```python
async def get_workflow_status(workflow_id: str) -> str:
    """Compute workflow status from actual task states"""
    # Get all task IDs
    task_ids = await get_workflow_task_ids(workflow_id)

    # Query task states and count by type
    counts = {'running': 0, 'scheduled': 0, 'waiting': 0, 'completed': 0, ...}
    for task_id in task_ids:
        task_state = await redis.hget(f"task:status:{task_id}", "status")
        status = task_state or "pending"

        # Count by protocol for tasks without status
        if not status or status == "pending":
            task_data = await get_task_data(task_id)
            protocol = task_data['protocol']
            if protocol.startswith('timer/'):
                counts['scheduled'] += 1
            elif protocol.startswith('signal/'):
                counts['waiting'] += 1
            else:
                counts['running'] += 1
        else:
            # Map status to counter
            if status in ['scheduled', 'sleeping']:
                counts['scheduled'] += 1
            elif status in ['waiting', 'waiting_signal']:
                counts['waiting'] += 1
            elif status == 'completed':
                counts['completed'] += 1
            # ... etc

    # Determine workflow status
    total = len(task_ids)
    if counts['completed'] == total:
        return 'completed'
    elif counts['running'] > 0:
        return 'running'
    elif counts['scheduled'] > 0:
        return 'scheduled'
    elif counts['waiting'] > 0:
        return 'waiting'

    return 'running'  # default
```

**Pros**:
- Always accurate
- No counters to maintain
- No sync issues
- Simple logic

**Cons**:
- N+1 Redis queries (1 for task IDs, N for task states)
- But: N is typically small (10-100 tasks)
- And: Redis is fast (microseconds per query)

**Option B: Cache Computed Status**
- Compute status as in Option A
- Cache result for 1-5 seconds
- Invalidate on task completion events
- Balances accuracy vs performance

**Option C: Keep Reconciliation Worker Only**
- Remove all counter updates from dependency worker
- Reconciliation worker recalculates periodically (every 10-30 seconds)
- Accept slight delay in status transitions

---

## Recommended Implementation

### Phase 1: Remove Counter Updates from Dependency Worker

**Remove/Comment out**:
1. All `hincrby` calls for task counters in `handle_task_completion`
2. All `hincrby` calls for task counters in `find_ready_tasks`
3. All `hincrby` calls for task counters in `handle_task_failure`

**Keep**:
- Initial counter setup in `handle_workflow_submission` (for backward compatibility)
- Reconciliation worker's counter recalculation

### Phase 2: Make Status Computation Function

Create `compute_workflow_status()` function that:
1. Queries all task states
2. Counts by status/protocol
3. Returns workflow status

Use this in:
- Dependency worker after task completion
- API endpoints when returning workflow info
- Reconciliation worker (replace existing logic)

### Phase 3: Add Status Transition Logic

After computing workflow status:
```python
current_status = await redis.hget(workflow_state_key, "status")
new_status = await compute_workflow_status(workflow_id)

if new_status != current_status:
    await transition_workflow_status(workflow_id, new_status)
```

---

## Migration Path

### Step 1: Add Computed Status (Non-Breaking)
- Add `compute_workflow_status()` function
- Log computed vs counter-based status for comparison
- Don't change behavior yet

### Step 2: Validate (Monitoring)
- Run for 24-48 hours
- Compare computed status with counter-based status
- Verify computed status is accurate

### Step 3: Switch to Computed (Breaking Change)
- Remove counter updates from dependency worker
- Use computed status everywhere
- Keep counters in workflow state for observability

### Step 4: Clean Up (Optional)
- Remove unused counter fields from workflow state
- Simplify reconciliation worker

---

## Testing Strategy

### Test Cases

1. **Regular Python workflow**:
   - All tasks should show workflow as "running"
   - On completion → "completed"

2. **Timer-only workflow**:
   - Should start as "scheduled"
   - Remain "scheduled" until timer fires
   - Then → "completed"

3. **Signal-only workflow**:
   - Should start as "waiting"
   - Remain "waiting" until signal received
   - Then → "completed"

4. **Mixed workflow** (python → timer → python):
   - Start: "running" (python task)
   - After first python: "scheduled" (timer waiting)
   - After timer: "running" (second python)
   - End: "completed"

5. **Counter verification**:
   - After every operation, verify counters match computed counts
   - No negative values ever

---

## Files to Modify

### 1. Create new file: `src/gleitzeit/core/workflow_status.py`
```python
async def compute_workflow_status(
    redis, workflow_id: str, shard: int
) -> Tuple[str, Dict[str, int]]:
    """
    Compute workflow status from actual task states.

    Returns:
        (status, counts) tuple
    """
    # Implementation here
```

### 2. Modify: `src/gleitzeit/workers/dependency_worker.py`
- Import `compute_workflow_status`
- Replace counter updates with status computation
- Call `compute_workflow_status` after task completion

### 3. Modify: `src/gleitzeit/workers/reconciliation_worker.py`
- Use shared `compute_workflow_status` function
- Remove duplicate counting logic

### 4. Add tests: `tests/test_workflow_status.py`
- Test all workflow status scenarios
- Verify no negative counters
- Test status transitions

---

## Success Criteria

1. ✅ No negative counters ever
2. ✅ Workflow status matches actual task states
3. ✅ Status transitions happen immediately after task completion
4. ✅ "scheduled" status shows when only timer tasks remain
5. ✅ "waiting" status shows when only signal tasks remain
6. ✅ All tests pass
7. ✅ No performance regression (status computation < 10ms for 100-task workflow)

---

## Conclusion

**The fundamental issue**: Trying to maintain derived state (counters) separately from source state (task statuses).

**The solution**: Compute workflow status from task states on-demand. No counters = no sync issues.

**Why this is better**:
- Simpler code
- Always accurate
- No consistency bugs
- Easier to reason about
- Follows "single source of truth" principle

**Performance is not a concern**:
- Typical workflow: 10-100 tasks
- Redis queries: microseconds each
- Total computation: < 10ms
- Worth it for correctness and simplicity
