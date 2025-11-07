# Workflow State Reconciliation Worker - Design Document

## 1. Problem Statement

### Current Gap
Workflows can become stuck in incorrect states when workers crash before processing critical events:

**Scenario Example:**
1. Task fails and emits `task:failed` event
2. DependencyWorker should receive this event and mark workflow as "failed" (hard fail policy)
3. If DependencyWorker crashes before processing the event, workflow remains stuck as "running"
4. PendingRecoveryMixin will re-claim the stuck message, but by then the workflow state is already inconsistent

**What Exists:**
- **PendingRecoveryMixin**: Recovers stuck messages in Redis Streams using XCLAIM
- **WorkflowMonitorWorker**: Handles parent-child workflow notifications only

**What's Missing:**
- No periodic scanning of workflow states
- No reconciliation of inconsistent workflow data
- No enforcement of hard fail policy after the fact

## 2. Proposed Solution

### Workflow State Reconciliation Worker
A new worker that periodically scans workflows and ensures state consistency.

### Core Functions
1. **Scan Running Workflows**: Find all workflows with `status="running"`
2. **Validate State Consistency**: Check if task counts match reality
3. **Enforce Hard Fail Policy**: Mark workflows as "failed" if any task failed
4. **Detect Completions**: Mark workflows as "completed" when all tasks done
5. **Detect Stuck Workflows**: Identify workflows with no activity for extended periods

## 3. Architecture

### 3.1 Worker Type
- **Name**: `WorkflowReconciliationWorker`
- **Inheritance**: Extends `BaseWorker`
- **Pattern**: Periodic background task (not stream-based)

### 3.2 Execution Model
Unlike other workers that consume Redis Streams, this worker:
- Runs on a **timer-based loop** (e.g., every 60 seconds)
- Scans all 16 shards sequentially
- Processes workflows in batches to avoid overwhelming Redis

### 3.3 Shard Distribution
```
Shard 0-15: Each contains subset of workflows
Worker scans all shards in round-robin fashion
```

### 3.4 Worker Coordination
**Problem**: Multiple reconciliation workers could conflict
**Solution**:
- Use Redis distributed lock per shard
- Lock key: `{shard:N}:reconciliation:lock`
- TTL: 120 seconds (2x scan interval)
- Only one worker reconciles each shard at a time

## 4. Reconciliation Logic

### 4.1 Data Model

**Workflow State (Redis Hash)**:
```
{shard:N}:workflow:status:{workflow_id}
  - status: "submitted" | "running" | "completed" | "failed"
  - total_tasks: int
  - completed_tasks: int
  - failed_tasks: int
  - running_tasks: int
  - pending_tasks: int
  - created_at: timestamp
  - updated_at: timestamp
```

**Task State (Redis Hash)**:
```
{shard:N}:task:status:{task_id}
  - status: "pending" | "running" | "completed" | "failed" | "waiting"
  - workflow_id: str
  - completed_at: timestamp (if completed)
  - failed_at: timestamp (if failed)
```

### 4.2 Reconciliation Checks

**Check 1: Task Count Consistency**
```python
# Get workflow state
workflow = get_workflow(workflow_id)
total_accounted = (
    workflow.completed_tasks +
    workflow.failed_tasks +
    workflow.running_tasks +
    workflow.pending_tasks
)

if total_accounted != workflow.total_tasks:
    # Inconsistency detected - need to recalculate from actual task states
    await recalculate_task_counts(workflow_id)
```

**Check 2: Hard Fail Policy Enforcement**
```python
if workflow.status == "running" and workflow.failed_tasks > 0:
    # Workflow should have been marked as failed
    await mark_workflow_failed(workflow_id, reason="Task failure detected during reconciliation")
```

**Check 3: Completion Detection**
```python
if (workflow.status == "running" and
    workflow.completed_tasks == workflow.total_tasks and
    workflow.failed_tasks == 0):
    # All tasks completed successfully
    await mark_workflow_completed(workflow_id)
```

**Check 4: Zombie Workflow Detection**
```python
if workflow.status == "running" and workflow.running_tasks == 0:
    last_activity = get_last_task_activity(workflow_id)
    if time_since(last_activity) > ZOMBIE_THRESHOLD:
        # No running tasks but workflow stuck as running
        await mark_workflow_stalled(workflow_id)
```

### 4.3 Recalculation Algorithm

When inconsistency detected:
```python
async def recalculate_task_counts(workflow_id: str):
    """
    Recalculate workflow task counts from actual task states.
    """
    # Get all task IDs for workflow
    task_ids = await get_workflow_task_ids(workflow_id)

    counts = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "waiting": 0
    }

    # Fetch actual task states
    for task_id in task_ids:
        task = await get_task(task_id, workflow_id)
        if task:
            status = task.get("status", "pending")
            counts[status] += 1

    # Update workflow with corrected counts
    await update_workflow_counts(workflow_id, counts)

    return counts
```

## 5. Implementation Details

### 5.1 Worker Structure

```python
class WorkflowReconciliationWorker(BaseWorker):
    """
    Periodically scans workflows and fixes inconsistent states.
    """

    # Configuration
    SCAN_INTERVAL = 60  # seconds
    BATCH_SIZE = 100  # workflows per batch
    LOCK_TTL = 120  # seconds
    ZOMBIE_THRESHOLD = 600  # 10 minutes

    async def run(self):
        """Main reconciliation loop"""
        while self._running:
            await asyncio.sleep(self.SCAN_INTERVAL)
            await self.reconcile_all_shards()

    async def reconcile_all_shards(self):
        """Scan all assigned shards"""
        for shard in self.assigned_shards:
            try:
                async with self.acquire_shard_lock(shard):
                    await self.reconcile_shard(shard)
            except LockAcquisitionError:
                # Another worker is handling this shard
                continue

    async def reconcile_shard(self, shard: int):
        """Reconcile all running workflows on a shard"""
        offset = 0
        while True:
            workflows = await self.scan_running_workflows(
                shard, offset, self.BATCH_SIZE
            )
            if not workflows:
                break

            for workflow_id in workflows:
                await self.reconcile_workflow(workflow_id, shard)

            offset += self.BATCH_SIZE

    async def reconcile_workflow(self, workflow_id: str, shard: int):
        """Reconcile a single workflow"""
        # Implementation of checks from 4.2
        pass
```

### 5.2 Distributed Locking

```python
async def acquire_shard_lock(self, shard: int):
    """
    Acquire distributed lock for shard reconciliation.

    Uses Redis SET NX EX pattern.
    """
    lock_key = f"{{shard:{shard}}}:reconciliation:lock"
    lock_value = f"{self.config.worker_id}:{uuid.uuid4()}"

    acquired = await self.redis.set(
        lock_key.encode(),
        lock_value.encode(),
        nx=True,
        ex=self.LOCK_TTL
    )

    if not acquired:
        raise LockAcquisitionError(f"Could not acquire lock for shard {shard}")

    return ReconciliationLock(self.redis, lock_key, lock_value)
```

### 5.3 Scanning Running Workflows

```python
async def scan_running_workflows(
    self, shard: int, offset: int, limit: int
) -> List[str]:
    """
    Scan for workflows with status='running' on a shard.

    Uses sorted set for efficient scanning:
    {shard:N}:workflows:by_status:running
    """
    key = f"{{shard:{shard}}}:workflows:by_status:running"

    workflow_ids = await self.redis.zrange(
        key.encode(),
        offset,
        offset + limit - 1
    )

    return [wf_id.decode() for wf_id in workflow_ids]
```

### 5.4 Logging and Metrics

```python
async def reconcile_workflow(self, workflow_id: str, shard: int):
    """Reconcile workflow with detailed logging"""
    try:
        # Check consistency
        inconsistencies = await self.check_workflow_consistency(workflow_id)

        if inconsistencies:
            await self.log_worker_warning(
                "workflow_inconsistency_detected",
                f"Workflow {workflow_id} has inconsistencies: {inconsistencies}",
                workflow_id=workflow_id,
                shard=shard,
                inconsistencies=inconsistencies
            )

            # Fix inconsistencies
            await self.fix_workflow_state(workflow_id, inconsistencies)

            await self.log_worker_info(
                "workflow_reconciled",
                f"Workflow {workflow_id} reconciled successfully",
                workflow_id=workflow_id,
                shard=shard
            )
    except Exception as e:
        await self.log_worker_error(
            "reconciliation_failed",
            e,
            workflow_id=workflow_id,
            shard=shard
        )
```

## 6. Configuration

### 6.1 Worker Configuration

```yaml
# gleitzeit.yaml
workers:
  - type: workflow_reconciliation
    enabled: true
    instances: 1  # Only need 1 instance (handles all shards with locking)
    config:
      scan_interval: 60  # seconds
      batch_size: 100
      lock_ttl: 120
      zombie_threshold: 600
      max_concurrent: 5  # Max workflows to reconcile concurrently
```

### 6.2 Environment Variables

```bash
RECONCILIATION_SCAN_INTERVAL=60
RECONCILIATION_BATCH_SIZE=100
RECONCILIATION_LOCK_TTL=120
RECONCILIATION_ZOMBIE_THRESHOLD=600
```

## 7. Testing Strategy

### 7.1 Unit Tests

**Test 1: Task Count Recalculation**
```python
async def test_recalculate_task_counts():
    # Create workflow with incorrect counts
    workflow_id = await create_workflow(total_tasks=5)
    await set_workflow_counts(workflow_id, completed=2, failed=0)

    # Create actual tasks with different counts
    await create_tasks(workflow_id, completed=3, failed=1)

    # Reconcile
    worker = WorkflowReconciliationWorker(config)
    await worker.reconcile_workflow(workflow_id, shard=0)

    # Verify counts corrected
    workflow = await get_workflow(workflow_id)
    assert workflow.completed_tasks == 3
    assert workflow.failed_tasks == 1
```

**Test 2: Hard Fail Policy Enforcement**
```python
async def test_enforce_hard_fail_policy():
    # Create running workflow with failed task
    workflow_id = await create_workflow(status="running")
    await create_tasks(workflow_id, completed=2, failed=1)

    # Reconcile
    worker = WorkflowReconciliationWorker(config)
    await worker.reconcile_workflow(workflow_id, shard=0)

    # Verify workflow marked as failed
    workflow = await get_workflow(workflow_id)
    assert workflow.status == "failed"
```

### 7.2 Integration Tests

**Test 3: Worker Crash Recovery**
```python
async def test_worker_crash_recovery():
    # Submit workflow
    workflow_id = await submit_workflow(tasks=5)

    # Start processing
    await process_tasks(workflow_id, count=3)

    # Fail one task
    await fail_task(workflow_id, task_id=task_ids[3])

    # Simulate dependency_worker crash before processing fail event
    await crash_dependency_worker()

    # Workflow should still be "running" (inconsistent)
    workflow = await get_workflow(workflow_id)
    assert workflow.status == "running"
    assert workflow.failed_tasks == 0  # Not yet updated

    # Start reconciliation worker
    worker = WorkflowReconciliationWorker(config)
    await worker.reconcile_all_shards()

    # Verify workflow now marked as failed
    workflow = await get_workflow(workflow_id)
    assert workflow.status == "failed"
    assert workflow.failed_tasks == 1
```

### 7.3 Performance Tests

**Test 4: Large Scale Scanning**
```python
async def test_large_scale_scan():
    # Create 10,000 workflows
    workflow_ids = await create_workflows(count=10000)

    # Introduce inconsistencies in 10%
    for wf_id in random.sample(workflow_ids, 1000):
        await introduce_inconsistency(wf_id)

    # Time full reconciliation
    start = time.time()
    worker = WorkflowReconciliationWorker(config)
    await worker.reconcile_all_shards()
    duration = time.time() - start

    # Should complete in under 60 seconds
    assert duration < 60

    # Verify all inconsistencies fixed
    for wf_id in workflow_ids:
        assert await is_consistent(wf_id)
```

## 8. Deployment Strategy

### 8.1 Rollout Plan

**Phase 1: Monitoring Only**
- Deploy worker in read-only mode
- Log detected inconsistencies without fixing
- Collect metrics on inconsistency frequency

**Phase 2: Partial Fix**
- Enable fixing for low-risk scenarios (completion detection)
- Keep hard fail policy enforcement disabled

**Phase 3: Full Deployment**
- Enable all reconciliation logic
- Monitor error rates and performance

### 8.2 Monitoring

**Metrics to Track:**
- `reconciliation.workflows_scanned`: Total workflows scanned per cycle
- `reconciliation.inconsistencies_found`: Count of inconsistencies detected
- `reconciliation.workflows_fixed`: Count of workflows reconciled
- `reconciliation.scan_duration`: Time to scan all shards
- `reconciliation.errors`: Reconciliation failures

**Alerts:**
- High inconsistency rate (> 5%)
- Scan duration exceeds interval
- Reconciliation failures

## 9. Future Enhancements

### 9.1 Smart Scheduling
- Skip recently updated workflows
- Prioritize older workflows
- Adaptive scan intervals based on inconsistency rate

### 9.2 Workflow-Level Locking
- Fine-grained locks per workflow
- Prevent conflicts with other workers

### 9.3 Manual Reconciliation
- API endpoint to trigger reconciliation for specific workflow
- CLI command: `gleitzeit reconcile <workflow_id>`

### 9.4 Reconciliation Reports
- Generate periodic reports of inconsistencies
- Track trends over time
- Alert on anomalies

## 10. Security Considerations

- **Resource Limits**: Prevent runaway reconciliation from overwhelming Redis
- **Rate Limiting**: Max workflows reconciled per second
- **Circuit Breaker**: Stop reconciliation if error rate exceeds threshold
- **Audit Logging**: Log all state changes made during reconciliation

## 11. Summary

The Workflow State Reconciliation Worker fills a critical gap in Gleitzeit's reliability:

1. **Complements PendingRecoveryMixin**: While pending recovery re-claims stuck messages, reconciliation fixes already-incorrect state
2. **Enforces Hard Fail Policy**: Ensures workflows are marked failed even if dependency_worker crashes
3. **Detects Completions**: Marks workflows as completed when all tasks done
4. **Finds Zombies**: Identifies workflows stuck with no activity
5. **Periodic Scanning**: Runs continuously to catch any inconsistencies

This makes Gleitzeit more resilient to worker crashes and ensures eventual consistency of workflow states.
