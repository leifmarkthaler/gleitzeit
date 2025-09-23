# Core System Audit – Gleitzeit 0.0.7

## Overview
Focused review of the core execution path: Redis sharding helpers, worker implementations, orchestrator lifecycle management, and cross-cutting utilities (event monitoring, circuit breaker, retry). Objective: surface correctness and operability issues that would undermine production stability.

## Scope
- Sharding helpers & worker usage (`core/sharding.py`, `workers/*`)
- Dependency and task execution workers
- Component orchestrator (`src/gleitzeit/orchestrator/component_orchestrator.py`)
- Cluster-wide telemetry (`core/event_monitor.py`)
- Failure-handling primitives (`core/circuit_breaker.py`)

## Summary of Findings
| Severity | Count | Themes |
|----------|-------|--------|
| Critical | 1 | Sharding misuse in core workers breaks cancellation/skip flows |
| High     | 3 | Misrouted cancellation events, shard coverage gaps, circuit breaker regression |
| Medium   | 2 | Cross-platform orchestration issues, fragile shard assignment guard |

## Detailed Findings

### Critical
1. **Core workers call sharding helpers with the wrong signature**  
   **Locations:** `src/gleitzeit/workers/task_execution_worker.py:168`, `src/gleitzeit/workers/dependency_worker.py:310`  
   **Issue:** Both workers invoke `default_sharding.get_task_key("state", task_id)` / `get_task_key("status", workflow_id, task_id)`, but the helper signature is `(task_id, workflow_id)`. These calls produce hashes such as `{shard:<hash("state")>}:task:status:<task_id>`, so cancellation checks, skip markers, and dependency gating all consult empty hashes. Downstream logic (e.g., cancellation guard in TaskExecutionWorker) silently bypasses user initiated cancels, allowing tasks to execute anyway.  
   **Recommendation:** Refactor worker code to pass the actual `(task_id, workflow_id)` pair, and add integration tests that submit a task, cancel it, and ensure the worker respects the cancellation before execution.

### High
2. **Cancellation events hash by task id, not workflow id**  
   **Locations:** `src/gleitzeit/workers/task_execution_worker.py:177`, `src/gleitzeit/workers/dependency_worker.py:837`, `src/gleitzeit/workers/dependency_worker.py:889`  
   **Issue:** `default_sharding.get_stream_key()` expects a `workflow_id`, but each call passes the `task_id`. Streams therefore land on slots unrelated to the owning workflow, so the loaders/monitors that poll `{shard:<workflow>}:task:cancelled` never see the events.  
   **Recommendation:** Supply the workflow id when constructing all task-scoped streams and add stream-consumer tests to confirm cancelled tasks surface on the expected shard.

3. **Event monitor only scans 10 shards**  
   **Location:** `src/gleitzeit/core/event_monitor.py:334`  
   **Issue:** `_get_active_workflows` iterates `range(10)` while the cluster uses 16 logical shards. Any workflow sharded beyond index 9 is invisible to the event monitor, leaving dashboards blind to large portions of the fleet.  
   **Recommendation:** Drive shard iteration via `default_sharding.num_shards` (or config), and consider maintaining a lightweight workflow index to avoid full key scans.

4. **Circuit breaker crashes when no explicit config is provided**  
   **Location:** `src/gleitzeit/core/circuit_breaker.py:143`  
   **Issue:** The initializer logs `config.failure_threshold`; when `config` is `None`, this dereference raises `AttributeError`, aborting construction. Any component using default circuit breaker settings fails at import time instead of protecting calls.  
   **Recommendation:** Log against `self.config`, add coverage for the default-construction path, and audit existing usages for similar assumptions.

### Medium
5. **Orchestrator hardcodes POSIX path separators**  
   **Location:** `src/gleitzeit/orchestrator/component_orchestrator.py:266-268`  
   **Issue:** `PYTHONPATH` is extended with `':'`, which breaks on Windows (`os.pathsep` is `;`). Worker subprocesses launched by the orchestrator on Windows cannot import project modules.  
   **Recommendation:** Build the path with `os.pathsep` and add a smoke test (or CI job) that exercises orchestrator startup on Windows.

6. **Shard assignment assumes count ≥ 1**  
   **Location:** `src/gleitzeit/orchestrator/component_orchestrator.py:334-339`  
   **Issue:** `assign_shards_to_worker` divides by `self.worker_specs[worker_type].count`. If a config sets `count: 0` to disable a worker type, the orchestrator throws `ZeroDivisionError` during startup, halting all workers.  
   **Recommendation:** Guard against zero counts—either skip the worker entirely or enforce a minimum of one via validation before shard assignment.

## Recommendations & Next Steps
1. **Fix sharding contracts in workers.** Adjust task/cancellation lookups to always pass both IDs, then backfill regression tests covering cancel-before-execute and validation skip flows.
2. **Re-align cluster telemetry.** Correct cancellation stream hashing and replace the hard-coded shard loop in the event monitor. Verify that monitoring endpoints can now see workflows beyond shard 9.
3. **Stabilize platform primitives.** Patch the circuit breaker logging bug and make the orchestrator path/shard assignment logic configuration-safe. Add smoke tests around default circuit breaker creation and orchestrator startup on non-POSIX systems.

## Appendix
- Sharding reference: `src/gleitzeit/core/sharding.py`
- Worker base registration/heartbeat: `src/gleitzeit/workers/base.py`
- Retry & event utilities reviewed: `src/gleitzeit/core/stateless_retry_service.py`, `src/gleitzeit/core/event_store.py`
