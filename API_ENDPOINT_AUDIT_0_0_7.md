# API Endpoint Audit – Gleitzeit 0.0.7

## Overview
This document captures the results of a focused review of the FastAPI endpoints under `src/gleitzeit/api/routes` in version 0.0.7. The goal was to identify correctness, reliability, and operational risks before the endpoints are exposed in production.

## Scope
- Workflow endpoints (`workflows.py`)
- Task endpoints (`tasks.py`)
- System monitoring endpoints (`system.py`)
- Health endpoints (`health.py`)
- Authentication endpoints (`auth.py`)
- Supporting auth dependencies and sharding helpers referenced by the routes

## Summary of Findings
| Severity   | Count | Themes |
|------------|-------|--------|
| Critical   | 2     | Incorrect sharding usage for task/workflow keys |
| High       | 3     | Ineffective filtering, blocking Redis commands, broken metrics |
| Medium     | 3     | Queue discovery gaps, blocking I/O in async path, worker visibility |

## Detailed Findings

### Critical

1. **Task endpoints address wrong Redis keys**  
   **Location:** `src/gleitzeit/api/routes/tasks.py:24,31,57,86,107,150`  
   **Issue:** Every handler calls `default_sharding.get_task_key("state"/"result"/...)`, but `ClusterShardingStrategy.get_task_key` expects `(task_id, workflow_id)`. The mistaken call signature generates hashes like `"{shard:<hash-of-\"state\"}>:task:status:<task_id>"`, so state, result, and log lookups all miss. Mutations (retry/cancel) also write to the wrong keys. Even after correcting the argument order the API still lacks the workflow id required for sharding, so the endpoints cannot reach the real task data.  
   **Impact:** Any client request for task details, retry, or cancel silently fails or operates on empty data, making the API unusable.  
   **Recommendation:** Redesign the task endpoints to resolve workflow ids (e.g., store `workflow_id` alongside task ids, or add a lookup table) and update every `get_task_key`/`get_stream_key` invocation to use the correct signature.

2. **Workflow endpoints use the same broken sharding pattern**  
   **Location:** `src/gleitzeit/api/routes/workflows.py:212,333`  
   **Issue:** Workflow helpers call `default_sharding.get_task_key("state", task_id)` and emit cancellation events to `default_sharding.get_stream_key("task:cancelled", task_id)`, both of which require a workflow id for correct hashing. The resulting keys reference non-existent hashes/streams, so task listings and cancellation fan-out never touch active data.  
   **Impact:** Workflow inspection always returns empty task lists, and cancellation requests never propagate to running workers.  
   **Recommendation:** Apply the same fix as above for all workflow task operations and validate event stream routing against the actual sharding contract.

### High

3. **Workflow list filtering breaks pagination and totals**  
   **Location:** `src/gleitzeit/api/routes/workflows.py:55-94`  
   **Issue:** Pagination is applied to the raw key list before the status filter and before metadata assembly. When `status` is provided, a page can be empty even if later records match. The `total` that is returned is the unfiltered key count, so clients cannot calculate accurate page numbers.  
   **Impact:** Clients receive inconsistent results and cannot rely on `total`/`offset` for paging.  
   **Recommendation:** Filter the decoded workflow objects before slicing, and return `total_filtered` alongside the raw total if both values are needed.

4. **System endpoints rely on `redis.keys`**  
   **Location:** `src/gleitzeit/api/routes/system.py:31-153`  
   **Issue:** Multiple handlers call `redis.keys(...)` while targeting cluster-formatted prefixes (`{shard:*}:...`). `KEYS` blocks the event loop, does not scale, and fails under Redis Cluster.  
   **Impact:** Monitoring endpoints can lock up the API or throw errors in any clustered deployment.  
   **Recommendation:** Replace `keys` with `scan_iter` or shard-aware fan-out that respects the deployed topology.

5. **Task metrics never find data**  
   **Location:** `src/gleitzeit/api/routes/system.py:111`, `src/gleitzeit/api/routes/system.py:217`  
   **Issue:** The code searches for `*:task:state:*`, but the sharding module stores task hashes under `task:status`. The counts therefore always read zero.  
   **Impact:** Operators lose visibility into live task throughput/failures.  
   **Recommendation:** Align the patterns with the actual key names (e.g., `*:task:status:*`) and consider reusing the sharding helper for clarity.

### Medium

6. **Queue discovery patterns miss all streams**  
   **Location:** `src/gleitzeit/api/routes/system.py:281-305`  
   **Issue:** The scan patterns `workflow:*`, `task:*`, `handler:*` ignore the `{shard:n}` hash tag prefix applied to every stream key, so the queue endpoint reports empty data.  
   **Impact:** Queue depth monitoring is non-functional.  
   **Recommendation:** Prefix patterns with the hash-tag format (e.g., `"{shard:*}:workflow:*"`) or maintain a curated list of known streams per shard.

7. **Blocking call in async health metrics**  
   **Location:** `src/gleitzeit/api/routes/system.py:377-389`  
   **Issue:** `psutil.cpu_percent(interval=1)` blocks the FastAPI event loop for one second on every request.  
   **Impact:** Health endpoint latency spikes and the service cannot scale under load.  
   **Recommendation:** Gather resource usage asynchronously (e.g., background task cache) or switch to non-blocking/stateless snapshots.

8. **Worker health checks target the wrong keys**  
   **Location:** `src/gleitzeit/api/routes/system.py:428`, `src/gleitzeit/api/routes/health.py:70`  
   **Issue:** Workers register under `{shard:0}:worker:registry:*`, but the endpoints scan for `worker:*:state`. The result set is always empty.  
   **Impact:** API reports zero workers even when the cluster is healthy.  
   **Recommendation:** Update the key pattern to the registry hash-tag format or centralize worker discovery through the orchestration layer.

## Recommendations & Next Steps
1. **Fix sharding contract in the API layer.** Provide a reliable way to recover `workflow_id` from any task operation, then correct every `get_task_key` / `get_stream_key` usage. Add regression tests that confirm task retries, cancellations, and workflow listings interact with real data.
2. **Harden system monitoring endpoints.** Replace blocking `KEYS` calls, fix stream/key patterns, and cache expensive resource metrics to keep the event loop responsive.
3. **Improve pagination and reporting accuracy.** Align workflow listing totals with filtered results and return consistent metadata for API consumers.
4. **Add integration coverage.** Expand `tests/test_new_endpoints.py` (or similar) to exercise the corrected Redis interactions and new monitoring behaviors under both single-node and cluster-like sharding scenarios.

## Appendix
- Sharding helpers: `src/gleitzeit/core/sharding.py`, `src/gleitzeit/core/sharding_cluster.py`
- Auth dependencies consulted: `src/gleitzeit/api/auth/dependencies.py`
