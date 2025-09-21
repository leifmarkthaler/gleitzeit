# Race Condition Analysis - Stateless Solution

## 🔴 Critical Race Conditions Identified

### 1. Double Task Execution
**Location**: `get_ready_tasks()` → task assignment
```
Instance A: get_ready_tasks() → returns ["task-1"]
Instance B: get_ready_tasks() → returns ["task-1"]  # Same moment!
Instance A: starts executing task-1
Instance B: starts executing task-1  # DUPLICATE EXECUTION!
```

**Impact**: Task executed multiple times, potentially causing:
- Double charges in payment tasks
- Duplicate emails sent
- Data corruption
- Resource waste

### 2. Lost Updates in Workflow Completion
**Location**: `_check_workflow_completion()`
```python
# Current code:
statuses = await self._get_task_statuses(workflow_id)
all_complete = all(status == TaskStatus.COMPLETED for status in statuses.values())
if all_complete:
    await self.persistence.update_workflow_status(workflow_id, WorkflowStatus.COMPLETED)
```

**Race Condition**:
```
Instance A: checks all tasks complete → True
Instance B: marks new task as PENDING  # Workflow continues!
Instance A: marks workflow COMPLETED   # Wrong!
```

### 3. Task Status Transitions
**Location**: Task status updates
```
Instance A: checks task is PENDING
Instance B: checks task is PENDING
Instance A: marks task RUNNING
Instance B: marks task RUNNING  # Both think they own it!
```

### 4. Dependency Resolution Race
**Location**: `check_dependencies_met()`
```
Instance A: checks deps for task-3 → not ready (task-2 running)
Instance B: marks task-2 complete
Instance A: continues with stale decision
Instance C: checks deps for task-3 → ready
Instance C: starts task-3
Instance B: also starts task-3  # Race between B and C!
```

### 5. Template/Schedule Creation
**Location**: Creating templates or schedules
```
Instance A: checks template "foo" doesn't exist
Instance B: checks template "foo" doesn't exist
Instance A: creates template "foo"
Instance B: creates template "foo"  # Duplicate or overwrite!
```

### 6. Execution ID Generation
**Location**: `execute_workflow()`
```python
execution_id = f"{workflow.id}-exec-{uuid4().hex[:8]}"
```
While UUID collision is unlikely, the execution tracking has races:
```
Instance A: creates execution-123
Instance B: creates execution-456 for same workflow
Both: update same workflow status → conflict
```

## 🔧 Solutions Required

### Solution 1: Atomic Task Assignment (CAS Pattern)
```python
async def assign_task_atomic(self, task_id: str, worker_id: str) -> bool:
    """
    Atomically assign task to worker using Compare-And-Set.
    
    Returns True if successfully assigned, False if already taken.
    """
    # Use Redis SETNX or database row-level locking
    key = f"task_assignment:{task_id}"
    
    # Set only if not exists (atomic operation)
    success = await self.persistence.set_if_not_exists(
        key, 
        worker_id, 
        expire=300  # 5 min lease
    )
    
    if success:
        # We got it! Now mark as RUNNING
        await self.persistence.update_task_status(task_id, TaskStatus.RUNNING)
        return True
    return False
```

### Solution 2: Distributed Locking
```python
async def execute_with_lock(self, resource_id: str, operation):
    """Execute operation with distributed lock."""
    lock_key = f"lock:{resource_id}"
    lock_id = uuid4().hex
    
    # Try to acquire lock (Redis SET NX EX)
    acquired = await self.persistence.acquire_lock(lock_key, lock_id, ttl=10)
    
    if not acquired:
        return None  # Someone else has it
    
    try:
        return await operation()
    finally:
        # Release only if we still own it
        await self.persistence.release_lock(lock_key, lock_id)
```

### Solution 3: Optimistic Locking with Version
```python
async def update_task_status_safe(self, task_id: str, new_status: TaskStatus):
    """Update task status with optimistic locking."""
    max_retries = 3
    
    for attempt in range(max_retries):
        # Get current version
        task = await self.persistence.get_task(task_id)
        current_version = task.get('version', 0)
        
        # Try to update with version check
        success = await self.persistence.update_task_status_if_version(
            task_id,
            new_status,
            expected_version=current_version,
            new_version=current_version + 1
        )
        
        if success:
            return True
        
        # Retry with backoff
        await asyncio.sleep(0.1 * (attempt + 1))
    
    raise Exception(f"Failed to update task {task_id} after {max_retries} attempts")
```

### Solution 4: State Machine Enforcement
```python
VALID_TRANSITIONS = {
    TaskStatus.PENDING: [TaskStatus.RUNNING, TaskStatus.CANCELLED],
    TaskStatus.RUNNING: [TaskStatus.COMPLETED, TaskStatus.FAILED],
    TaskStatus.COMPLETED: [],  # Terminal state
    TaskStatus.FAILED: [TaskStatus.PENDING],  # Can retry
}

async def transition_task_status(self, task_id: str, new_status: TaskStatus):
    """Transition task status with state machine validation."""
    async with self.distributed_lock(f"task:{task_id}"):
        current = await self.persistence.get_task_status(task_id)
        
        if new_status not in VALID_TRANSITIONS.get(current, []):
            raise ValueError(f"Invalid transition: {current} → {new_status}")
        
        await self.persistence.update_task_status(task_id, new_status)
```

### Solution 5: Idempotency Keys
```python
async def execute_task_idempotent(self, task_id: str, idempotency_key: str):
    """Execute task with idempotency guarantee."""
    # Check if already executed
    result_key = f"task_result:{task_id}:{idempotency_key}"
    existing = await self.persistence.get(result_key)
    
    if existing:
        return existing  # Already done, return cached result
    
    # Execute with lock
    async with self.distributed_lock(f"task_exec:{task_id}"):
        # Double-check after acquiring lock
        existing = await self.persistence.get(result_key)
        if existing:
            return existing
        
        # Execute and store result
        result = await self._execute_task_internal(task_id)
        await self.persistence.set(result_key, result, expire=86400)
        return result
```

## 🚨 Most Critical Fixes Needed

### Priority 1: Task Assignment
**Must fix**: Double execution of tasks
```python
# In StatelessDependencyManager.get_ready_tasks()
async def get_ready_tasks_and_assign(self, workflow_id: str, worker_id: str):
    """Get ready tasks and atomically assign one."""
    ready_task_ids = await self.get_ready_tasks(workflow_id, return_objects=False)
    
    for task_id in ready_task_ids:
        if await self.assign_task_atomic(task_id, worker_id):
            return task_id  # Successfully assigned
    
    return None  # No tasks available or all taken
```

### Priority 2: Workflow Completion
**Must fix**: Premature workflow completion
```python
async def mark_task_completed_safe(self, workflow_id: str, task_id: str):
    """Mark task complete and check workflow completion safely."""
    async with self.distributed_lock(f"workflow:{workflow_id}"):
        # Update task
        await self.persistence.update_task_status(task_id, TaskStatus.COMPLETED)
        
        # Check workflow completion within lock
        statuses = await self._get_task_statuses(workflow_id)
        all_complete = all(
            status == TaskStatus.COMPLETED 
            for status in statuses.values()
        )
        
        if all_complete:
            # Safe to mark complete - we have the lock
            await self.persistence.update_workflow_status(
                workflow_id, 
                WorkflowStatus.COMPLETED
            )
```

### Priority 3: Add Redis Atomic Operations
```python
# Add to persistence layer
class AtomicPersistenceOps:
    async def set_if_not_exists(self, key: str, value: Any, expire: int) -> bool:
        """Redis SETNX equivalent."""
        return await self.redis.set(key, value, nx=True, ex=expire)
    
    async def compare_and_set(self, key: str, old_value: Any, new_value: Any) -> bool:
        """Compare and set atomically using Lua script."""
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("set", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        return await self.redis.eval(lua_script, 1, key, old_value, new_value)
    
    async def increment_counter(self, key: str) -> int:
        """Atomic increment."""
        return await self.redis.incr(key)
```

## Recommended Implementation Order

1. **Immediate**: Add atomic task assignment to prevent double execution
2. **Next**: Add distributed locking for workflow state changes  
3. **Then**: Add optimistic locking with versions for updates
4. **Finally**: Add comprehensive state machine validation

## Testing Race Conditions

```python
async def test_concurrent_task_assignment():
    """Test that only one worker can claim a task."""
    task_id = "test-task-1"
    
    # Reset task to PENDING
    await persistence.update_task_status(task_id, TaskStatus.PENDING)
    
    # Try to assign from multiple workers concurrently
    results = await asyncio.gather(
        manager1.assign_task_atomic(task_id, "worker-1"),
        manager2.assign_task_atomic(task_id, "worker-2"),
        manager3.assign_task_atomic(task_id, "worker-3"),
    )
    
    # Only one should succeed
    assert sum(results) == 1
    
    # Task should be RUNNING
    status = await persistence.get_task_status(task_id)
    assert status == TaskStatus.RUNNING
```

## Conclusion

The stateless solution has **significant race conditions** that MUST be addressed:
1. Task double-execution (CRITICAL)
2. Workflow state conflicts (HIGH)  
3. Lost updates (MEDIUM)
4. Template/schedule conflicts (LOW)

Without atomic operations and distributed locking, the system is **NOT safe for production** in a distributed environment.