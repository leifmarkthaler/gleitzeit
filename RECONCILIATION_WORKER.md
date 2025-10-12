# Workflow State Reconciliation Worker

## Overview

The Workflow State Reconciliation Worker is a background service that periodically scans all workflows and ensures state consistency. It automatically detects and fixes workflows stuck in incorrect states due to worker crashes, network failures, or other unexpected errors.

## Purpose

In distributed systems, workflows can enter inconsistent states when:
- Worker processes crash mid-execution
- Network failures interrupt task processing
- Race conditions occur during state transitions
- Hard fail policies aren't properly enforced

The reconciliation worker acts as a safety net, ensuring eventual consistency across all workflow states.

## Architecture

### Timer-Based Execution
Unlike stream-based workers that process Redis Streams, the reconciliation worker runs on a periodic timer (default: 60 seconds). This design allows it to:
- Scan all workflows systematically
- Operate independently of workflow events
- Catch edge cases that event-driven workers might miss

### Distributed Locking
When multiple reconciliation workers run (for high availability), they coordinate using Redis distributed locks:
- **Lock Key Pattern**: `{shard:{N}}:reconciliation:lock`
- **Lock TTL**: 120 seconds (configurable)
- **Lock Value**: `{worker_id}:{uuid}` for safe release
- **Lock Algorithm**: Redis SET NX EX (atomic test-and-set)

Only one worker can reconcile a given shard at a time, preventing duplicate work and race conditions.

### Shard-Based Processing
Workflows are distributed across 16 shards. The reconciliation worker:
1. Iterates through all assigned shards
2. Acquires a distributed lock for each shard
3. Scans workflows in that shard
4. Releases the lock
5. Moves to the next shard

## Reconciliation Checks

The worker performs four critical state consistency checks:

### 1. Task Count Consistency
**Problem**: Workflow shows `tasks_pending > 0` but status is COMPLETED or FAILED
**Fix**: Recalculate task counts from actual task states

```python
# Check if task counts match reality
if workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
    if workflow.tasks_pending > 0:
        await self.reconcile_task_counts(workflow)
```

### 2. Hard Fail Policy Enforcement
**Problem**: Workflow has `hard_fail_policy=true` and failed tasks, but status isn't FAILED
**Fix**: Mark workflow as FAILED immediately

```python
# Enforce hard fail policy
if workflow.hard_fail_policy and workflow.tasks_failed > 0:
    if workflow.status != WorkflowStatus.FAILED:
        await self.mark_workflow_failed(workflow)
```

### 3. Completion Detection
**Problem**: All tasks completed but workflow status is still RUNNING
**Fix**: Mark workflow as COMPLETED or FAILED based on task outcomes

```python
# Detect completion
if workflow.tasks_pending == 0 and workflow.status == WorkflowStatus.RUNNING:
    if workflow.tasks_failed > 0:
        await self.mark_workflow_failed(workflow)
    else:
        await self.mark_workflow_completed(workflow)
```

### 4. Zombie Workflow Detection
**Problem**: Workflow running for longer than timeout threshold with no progress
**Fix**: Mark as FAILED with timeout error

```python
# Detect zombies (default: 10 minutes)
if workflow.status == WorkflowStatus.RUNNING:
    runtime = datetime.utcnow() - workflow.started_at
    if runtime.total_seconds() > self.zombie_threshold:
        await self.mark_workflow_failed(workflow, reason="timeout")
```

## Configuration

### Worker Definition
Add to `gleitzeit.yaml`:

```yaml
workers:
  - type: reconciliation
    worker_id: reconciliation-async
    mode: async
    replicas: 1  # Can scale up for HA
    shards: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
```

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `scan_interval` | 60 | Seconds between reconciliation scans |
| `batch_size` | 100 | Max workflows to process per shard per scan |
| `lock_ttl` | 120 | Distributed lock TTL in seconds |
| `zombie_threshold` | 600 | Workflow timeout threshold in seconds (10 min) |

### Custom Configuration Example

```yaml
workers:
  - type: reconciliation
    worker_id: reconciliation-async
    mode: async
    scan_interval: 30  # Scan every 30 seconds
    batch_size: 200    # Process up to 200 workflows per shard
    zombie_threshold: 1800  # 30-minute timeout
```

## High Availability

### Multiple Workers
Run multiple reconciliation workers for fault tolerance:

```yaml
workers:
  - type: reconciliation
    worker_id: reconciliation-1
    mode: async
    replicas: 1
    shards: [0, 1, 2, 3, 4, 5, 6, 7]

  - type: reconciliation
    worker_id: reconciliation-2
    mode: async
    replicas: 1
    shards: [8, 9, 10, 11, 12, 13, 14, 15]
```

### Shard Assignment
- Each worker handles a subset of shards
- Workers coordinate via distributed locks
- If a worker crashes, its shards will be processed by other workers on the next scan

## Monitoring

### Metrics
The worker emits these metrics to Redis:

- `workflows_scanned`: Total workflows examined
- `workflows_reconciled`: Workflows that needed fixes
- `scan_duration`: Time taken to scan all shards
- `scan_errors`: Number of errors encountered

### Logs
Key log events:

```
INFO - WorkflowReconciliationWorker initialized: scan_interval=60s, batch_size=100
INFO - Scanned 245 workflows, reconciled 3, took 1.2s
ERROR - Error reconciling shard 5: <error details>
```

### Health Checks
Monitor worker health via:
- Redis heartbeat key: `worker:heartbeat:{worker_id}`
- Service registry: Check worker status with `gleitzeit ps`

## Performance

### Scan Timing
With default settings (60s interval, 100 batch size):
- **Empty system**: <10ms per shard (16 shards = ~160ms total)
- **1000 workflows**: ~1-2 seconds per scan
- **10000 workflows**: ~10-15 seconds per scan

### Resource Usage
- **CPU**: Minimal (mostly I/O bound)
- **Memory**: ~50MB base + ~100KB per 1000 workflows
- **Redis**: ~100 commands per scan for 1000 workflows

### Scaling
If scans take longer than the scan interval:
1. Increase `batch_size` to process more workflows per scan
2. Decrease `scan_interval` to scan more frequently
3. Add more workers with shard partitioning

## Implementation Details

### File Location
`src/gleitzeit/workers/reconciliation_worker.py`

### Key Classes

**WorkflowReconciliationWorker**
- Inherits from `BaseWorker`
- Overrides `run()` for timer-based loop
- Implements shard-based scanning with distributed locking

**ReconciliationLock**
- Context manager for distributed locks
- Uses Lua script for safe lock release
- Prevents lock stealing across workers

**LockAcquisitionError**
- Exception raised when lock cannot be acquired
- Caught and logged, then worker skips to next shard

### Redis Keys Used

```
{shard:{N}}:workflows              # Workflow hash keys per shard
{shard:{N}}:reconciliation:lock    # Distributed lock per shard
worker:heartbeat:{worker_id}       # Worker liveness indicator
worker:metrics:{worker_id}         # Worker performance metrics
```

## Troubleshooting

### Worker Not Starting
**Check**: Worker appears in `gleitzeit ps` output
**Fix**: Verify worker configuration in `gleitzeit.yaml`

### No Reconciliations Happening
**Check**: Logs show "reconcile_all_shards() completed" but workflows_reconciled=0
**Diagnosis**: This is normal if all workflows are in consistent states

### Lock Acquisition Failures
**Check**: Logs show "Could not acquire lock for shard X"
**Diagnosis**: Another worker is processing that shard (expected behavior)

### Slow Scans
**Check**: `scan_duration` metric > 60 seconds
**Fix**: Increase `batch_size` or partition shards across more workers

## Testing

### Verify Worker is Running
```bash
gleitzeit ps
```

Look for `worker-reconciliation` with status `✅ healthy`

### Check Logs
```bash
gleitzeit logs reconciliation-async
```

Should show periodic scans:
```
2025-10-05 22:02:23 - INFO - Starting reconciliation scan for 16 shards
2025-10-05 22:02:23 - INFO - Reconciliation scan completed
```

### Test Reconciliation
1. Create a workflow with hard_fail_policy
2. Manually corrupt workflow state in Redis
3. Wait 60 seconds for reconciliation scan
4. Verify workflow state is corrected

## Future Enhancements

Potential improvements:
- **Adaptive Scanning**: Scan active shards more frequently
- **Metrics Dashboard**: Grafana dashboard for reconciliation metrics
- **State Snapshots**: Track reconciliation actions for debugging
- **Custom Reconcilers**: Plugin system for domain-specific checks
- **Alerting**: Notifications when reconciliation rate exceeds threshold
