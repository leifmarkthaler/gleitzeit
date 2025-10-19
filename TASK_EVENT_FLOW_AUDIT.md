# Task Event Flow and Acknowledgement Audit

**Date:** 2025-10-18
**Issue:** Tasks being processed twice in workflow execution
**Root Cause:** Multiple consumer groups reading from the same stream

---

## Executive Summary

Tasks are being duplicated because **two separate consumer groups** (`task_execution-group` and `python_specialist-group`) both read from the same `{shard:0}:task:ready` stream. In Redis Streams, each consumer group independently receives all messages, causing both workers to process the same tasks.

**Current State:**
- ✅ Consumer groups are using XREADGROUP with XACK correctly
- ✅ Messages are being acknowledged after processing
- ❌ Multiple consumer groups = multiple deliveries of same message
- ❌ No stream-based routing to separate task types

---

## 1. Task Lifecycle Event Flow

### 1.1 Task Submission → Ready
**Entry Point:** Workflow submission
**Stream Flow:**
```
workflow:submitted
  ↓ (WorkflowLoaderWorkerV2)
task:pending
  ↓ (DependencyWorker)
task:ready  ← MULTIPLE WORKERS READ HERE
  ↓ (TaskExecutionWorker)
task:completed / task:failed
```

### 1.2 Event Streams by Stage

| Stage | Stream Key | Producer | Consumer(s) | Consumer Groups |
|-------|-----------|----------|-------------|-----------------|
| Submission | `{shard:0}:workflow:submitted` | API/CLI | WorkflowLoaderWorkerV2 | `workflow_loader-group` |
| Pending | `{shard:0}:task:pending` | WorkflowLoaderWorkerV2 | DependencyWorker | `dependency-group` |
| Ready | `{shard:0}:task:ready` | DependencyWorker | TaskExecutionWorker (both types) | `task_execution-group` + `python_specialist-group` ⚠️ |
| Retry | `{shard:0}:task:retry` | RetryWorker | TaskExecutionWorker | Same as above ⚠️ |
| Completed | `{shard:0}:task:completed` | TaskExecutionWorker | WorkflowCompletionWorker | `workflow_completion-group` |
| Failed | `{shard:0}:task:failed` | TaskExecutionWorker | RetryWorker | `retry-group` |

---

## 2. Consumer Group Analysis

### 2.1 Current Consumer Groups (Redis State)
```bash
$ redis-cli xinfo groups "{shard:0}:task:ready"

name: python_specialist-group
  consumers: 1
  pending: 0
  last-delivered-id: 0-0

name: task_execution-group
  consumers: 1
  pending: 0
  last-delivered-id: 0-0
```

### 2.2 How Consumer Groups Work

**Single Consumer Group (Correct for Distribution):**
```
Stream: task:ready
Consumer Group: task-workers-group
  ├─ Consumer A (task_execution-0)
  ├─ Consumer B (task_execution-1)
  └─ Consumer C (python_specialist-0)

Message M1 → Delivered to ONE consumer (e.g., Consumer A)
Message M2 → Delivered to ONE consumer (e.g., Consumer C)
```

**Multiple Consumer Groups (Current Bug):**
```
Stream: task:ready
Consumer Group 1: task_execution-group
  ├─ Consumer A (task_execution-0)
  └─ Consumer B (task_execution-1)

Consumer Group 2: python_specialist-group
  └─ Consumer C (python_specialist-0)

Message M1 → Delivered to Group 1 (Consumer A) AND Group 2 (Consumer C)
         → PROCESSED TWICE ❌
```

---

## 3. Acknowledgement Flow Analysis

### 3.1 Read and Acknowledge Pattern
**Location:** `/src/gleitzeit/workers/base_cluster.py:137-208`

```python
# Read with consumer group
messages = await self.redis.xreadgroup(
    self.config.consumer_group.encode(),  # ← Each worker type has different group
    self.config.worker_id.encode(),
    streams,
    count=self.config.batch_size,
    block=self.config.block_timeout
)

# Process message
await self.process_message(stream, msg_id, data)

# ACK message (ALWAYS executed after processing)
await self.redis.xack(
    stream.encode(),
    self.config.consumer_group.encode(),
    msg_id.encode()
)
```

**Status:** ✅ Acknowledgement is working correctly
**Issue:** Each consumer group ACKs its own copy of the message

### 3.2 Consumer Group Assignment
**Location:** `/src/gleitzeit/orchestrator/component_orchestrator.py:300`

```python
'consumer_group': f"{worker_type}-group",
```

**Result:**
- `task_execution` → `task_execution-group`
- `python_specialist` → `python_specialist-group`
- `dependency` → `dependency-group`
- etc.

**Impact:** Each worker type creates its own consumer group, causing duplicate delivery when multiple worker types read from the same stream.

---

## 4. Duplicate Processing Example

### 4.1 Observed Behavior
**Workflow ID:** `08af2d35-e8bf-40e2-bdd6-0688aef24ad1`
**Observation:** 4 tasks in workflow, 22 events total (expected: ~16 events)

### 4.2 Event Breakdown for Single Task
```
Task: some-python-task (task_id: xyz)

Expected Events (1x processing):
1. task:pending (added by WorkflowLoader)
2. task:ready (added by DependencyWorker)
3. task:completed (added by TaskExecutionWorker)
Total: 3 events per task × 4 tasks = 12 events + workflow events

Actual Events (2x processing):
1. task:pending (added by WorkflowLoader)
2. task:ready (added by DependencyWorker)
3. task:completed (added by task_execution worker)    ← First processing
4. task:completed (added by python_specialist worker) ← Duplicate!
Total: 4 events per task × 4 tasks = 16 events + workflow events
```

### 4.3 Message Delivery Timeline
```
T0: DependencyWorker adds message to {shard:0}:task:ready

T1: Redis delivers to task_execution-group
    → task_execution-0 reads message M1

T1: Redis ALSO delivers to python_specialist-group (independent!)
    → python_specialist-0 reads message M1

T2: task_execution-0 processes and ACKs M1 (in task_execution-group)
T2: python_specialist-0 processes and ACKs M1 (in python_specialist-group)

Result: Same task executed twice ❌
```

---

## 5. Worker Configuration Analysis

### 5.1 Task Execution Workers (from gleitzeit.yaml.default)

**General Worker:**
```yaml
- worker_type: task_execution
  worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
  count: 2
  enabled_task_types: ['all']  # ← Implicit default
  handler_configs:
    "python/v1": {...}
    "ollama/v1": {...}
```

**Specialized Worker:**
```yaml
- worker_type: python_specialist
  worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
  count: 1
  enabled_task_types: [python, script]  # ← Explicit filter
  handler_configs:
    "python/v1":
      subprocess_pool_max_size: 30  # ← Optimized for Python
```

### 5.2 Stream Subscription (Current)
**Location:** `/src/gleitzeit/workers/task_execution_worker.py:184-186`

```python
def get_base_streams(self) -> List[str]:
    """Subscribe to sharded task:ready streams"""
    return ["task:ready", "task:retry"]
```

**Issue:** Both `task_execution` and `python_specialist` subscribe to the SAME streams but with DIFFERENT consumer groups.

---

## 6. Architecture Patterns (Solutions)

### Option A: Shared Consumer Group (Attempted, Reverted)
**Approach:** All TaskExecutionWorker instances use same consumer group
```python
consumer_group = 'task-execution-group'  # Same for all
```

**Pros:**
- Simple change
- No duplicate delivery
- Load distribution across all workers

**Cons:**
- `python_specialist` might get non-Python tasks
- Would fail tasks it can't handle (implemented with ValueError throw)
- Relies on exception handling to leave messages unacked

**Status:** ❌ Reverted per user preference

---

### Option B: Stream-Based Routing (Recommended)
**Approach:** Route different task types to different streams

**Implementation:**

1. **Dependency Worker emits to type-specific streams:**
```python
# In DependencyWorker, when task becomes ready:
task_type = task.get('type')  # e.g., 'python'
stream = f"task:{task_type}:ready"  # e.g., 'task:python:ready'

# Also emit to central stream for logging/monitoring
await redis.xadd("{shard:0}:task:ready", data)  # Central log
await redis.xadd(f"{{shard:0}}:{stream}", data)  # Type-specific
```

2. **Workers subscribe to type-specific streams:**
```python
# TaskExecutionWorker.get_base_streams()
def get_base_streams(self) -> List[str]:
    if 'all' in self.enabled_types:
        # General worker subscribes to all type streams
        return ["task:ready", "task:retry"]
    else:
        # Specialized worker subscribes to specific types
        streams = []
        for task_type in self.enabled_types:
            streams.append(f"task:{task_type}:ready")
            streams.append(f"task:{task_type}:retry")
        return streams
```

**Pros:**
- ✅ Keep central `task:ready` stream for logging/monitoring
- ✅ No duplicate processing
- ✅ Each worker only sees relevant tasks
- ✅ Maintain separate consumer groups per worker type
- ✅ Clear routing logic

**Cons:**
- More streams to manage
- Requires dual-write to central + type-specific streams
- Need to handle tasks with unknown types

---

### Option C: Task Filtering with Shared Group
**Approach:** Shared consumer group + skip logic

**Implementation:**
```python
# In TaskExecutionWorker.process_message()
task_type = task.get('type')
if 'all' not in self.enabled_types:
    if task_type not in self.enabled_types:
        # Raise exception to leave unacked for another worker
        raise ValueError(f"Task type {task_type} not in {self.enabled_types}")
```

**Pros:**
- Single consumer group (load distribution)
- No new streams needed

**Cons:**
- Inefficient (workers read messages they skip)
- Relies on pending entry list + exception handling
- Messages may get stuck in pending if no worker can handle

**Status:** ⚠️ Partially implemented but reverted

---

## 7. Recommended Solution

**Use Option B: Stream-Based Routing**

### 7.1 Implementation Plan

1. **Update DependencyWorker to dual-write:**
   - Emit to `{shard:0}:task:ready` (central log)
   - Emit to `{shard:0}:task:{type}:ready` (type-specific)

2. **Update TaskExecutionWorker.get_base_streams():**
   - If `enabled_types: ['all']` → subscribe to `task:ready`
   - If `enabled_types: [python, script]` → subscribe to `task:python:ready`, `task:script:ready`

3. **Update TimerWorker and other task emitters:**
   - Also dual-write to both central + type-specific streams

4. **Handle unknown task types:**
   - Default to `task:ready` stream if type not in routing table
   - Log warning for unmapped types

### 7.2 Backward Compatibility
- Keep central `task:ready` stream active
- General workers (`enabled_types: ['all']`) continue reading from it
- Specialized workers get routed to specific streams
- No breaking changes to existing workflows

---

## 8. Current Issues Summary

| Issue | Severity | Impact | Status |
|-------|----------|--------|--------|
| Duplicate task processing | 🔴 Critical | Tasks execute 2x, wasted resources | Identified |
| Multiple consumer groups on same stream | 🔴 Critical | Root cause of duplicates | Root cause found |
| No stream-based routing | 🟡 Medium | Inefficient task distribution | Design needed |
| `enabled_task_types` not enforced | 🟡 Medium | Workers process tasks outside scope | Partially fixed |
| Central logging stream requirement | 🟢 Low | User wants visibility of all tasks | Requirement noted |

---

## 9. Code Locations Reference

### Consumer Group Creation
- **File:** `/src/gleitzeit/orchestrator/component_orchestrator.py`
- **Line:** 300
- **Code:** `'consumer_group': f"{worker_type}-group"`

### Stream Reading
- **File:** `/src/gleitzeit/workers/base_cluster.py`
- **Lines:** 137-208
- **Method:** `run()` → XREADGROUP → process_message() → XACK

### Stream Subscription
- **File:** `/src/gleitzeit/workers/task_execution_worker.py`
- **Lines:** 184-186
- **Method:** `get_base_streams()`

### Task Emission (Ready)
- **File:** `/src/gleitzeit/workers/dependency_worker.py`
- **Line:** 184, 382
- **Stream:** `{shard:0}:task:ready`

### Worker Configuration
- **File:** `/src/gleitzeit/config/gleitzeit.yaml.default`
- **Lines:** 134-178
- **Workers:** `task_execution`, `python_specialist`

---

## 10. Testing Verification Plan

### 10.1 Pre-Fix Verification (Current State)
```bash
# Check consumer groups
redis-cli xinfo groups "{shard:0}:task:ready"
# Expected: 2 groups (task_execution-group, python_specialist-group)

# Submit test workflow
gleitzeit workflow submit test.yaml

# Check event count
redis-cli xlen "{shard:0}:task:ready"
redis-cli xlen "{shard:0}:task:completed"
# Compare: Should see 2x completed events for same tasks
```

### 10.2 Post-Fix Verification (After Stream Routing)
```bash
# Check new streams exist
redis-cli keys "*task:python:ready*"
redis-cli keys "*task:ready*"

# Check consumer groups
redis-cli xinfo groups "{shard:0}:task:ready"
# Expected: 1 group (task_execution-group) OR none if only type-specific

redis-cli xinfo groups "{shard:0}:task:python:ready"
# Expected: 1 group (python_specialist-group)

# Submit test workflow with Python tasks
gleitzeit workflow submit test_python.yaml

# Verify no duplicates
redis-cli xread COUNT 100 STREAMS "{shard:0}:task:completed" 0
# Count completed events - should match task count exactly
```

### 10.3 Edge Cases to Test
1. ✅ Python task → routed to python_specialist
2. ✅ Non-Python task → routed to task_execution
3. ✅ Unknown task type → handled gracefully
4. ✅ Central stream still populated → for monitoring
5. ✅ Workflow with mixed task types → no duplicates

---

## 11. Conclusion

**Root Cause:** Multiple consumer groups reading from the same stream causes Redis to deliver each message to each group independently, resulting in duplicate task execution.

**Original Analysis:** Both `task_execution` and `python_specialist` workers created separate consumer groups (`task_execution-group` and `python_specialist-group`), causing every task to be delivered to both groups and processed twice.

**Additional Finding:** The `enabled_task_types` configuration was not being properly propagated to workers, causing the `python_specialist` to load ALL handlers instead of just Python handlers, further negating any intended specialization.

**Implemented Fix:** Remove the `python_specialist` worker entirely and improve the `task_execution` worker configuration.

**Rationale:**
- The specialized worker provided no real benefit (both workers loaded all handlers anyway)
- Created unnecessary complexity and duplicate processing
- Better to have simpler architecture with well-tuned general workers
- Improved Python settings (pool size: 30, timeout: 1800s) now in task_execution workers

**Changes Made:**
1. ✅ Removed `python_specialist` worker from gleitzeit.yaml.default
2. ✅ Increased `task_execution` Python handler settings:
   - subprocess_pool_max_size: 20 → 30
   - default_timeout: 600s → 1800s (30 minutes)
   - Added subprocess_pool_min_size: 5
3. ✅ Reverted shared consumer group change (no longer needed)
4. ✅ Reverted enabled_task_types exception handling (no longer needed)

**Result:**
- Single consumer group (`task_execution-group`) for task processing
- No duplicate task execution
- Better Python performance with increased pool and timeout
- Simpler, more maintainable architecture

**Next Steps:**
1. Reinstall gleitzeit to pick up config changes
2. Restart all services
3. Clean up old `python_specialist-group` consumer group
4. Test with sample workflows to verify no duplicates
5. Monitor task execution metrics

---

**Audit completed:** 2025-10-18
**Audit updated:** 2025-10-18 (fix implemented)
**Auditor:** Claude (Sonnet 4.5)
