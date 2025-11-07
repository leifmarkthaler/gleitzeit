# Client Implementation Audit – Gleitzeit 0.0.7

## Overview
Review focused on the modular Python client (`src/gleitzeit/client`) covering the base transport, mixin stack (auth, retry, workflows, tasks, monitoring), and the composed `GleitzeitClient`. Goal: validate that the client can authenticate, call the published API surface, and return usable data structures.

## Scope
- `BaseClient` connection/auth state management (`client/base.py`)
- Mixins under `client/mixins/*`
- Composite client (`client/client.py`)
- Interaction points against the 0.0.7 API endpoints

## Summary of Findings
| Severity | Count | Themes |
|----------|-------|--------|
| Critical | 1 | Authentication state wiped during initialization |
| High     | 4 | Task API mismatches, monitoring schema drift |
| Medium   | 2 | Workflow retry payload, rate-limit decoding |

## Detailed Findings

### Critical
1. **Authentication credentials are reset after AuthMixin initialization**  
   **Location:** `src/gleitzeit/client/base.py:55-59`, `src/gleitzeit/client/mixins/auth.py:35-47`  
   **Issue:** The MRO calls `AuthMixin.__init__` first (where `self.session_id`, `self.username`, etc. are set from kwargs), but `BaseClient.__init__` runs afterwards and unconditionally sets the same attributes back to `None`. As a result:  
   - User-supplied `session_id`, `api_key`, or `jwt_token` are discarded before the first request.  
   - `auto_login` defaults to `True`, yet `self.username` becomes `None`, so `auto_authenticate()` attempts `POST /auth/session/create` with a `null` username and fails.  
   **Impact:** Fresh `GleitzeitClient()` instances cannot authenticate (auto-login fails) and explicit credentials never reach the server.  
   **Recommendation:** Let `BaseClient` honor existing attributes (e.g., only set when missing) or move credential defaults into `AuthMixin` after the base class has run. Add a regression test that instantiates the client with a preset `session_id` and asserts subsequent requests send that header.

### High
2. **Task status parsing assumes a schema the API doesn’t provide**  
   **Location:** `src/gleitzeit/client/mixins/tasks.py:69-80`  
   **Issue:** `get_task_status` expects `/tasks/{task_id}` to return top-level fields such as `status`, `created_at`, and `workflow_id`. The 0.0.7 API actually returns `{ "task_id": ..., "state": {"status": ...}, ... }`. Accessing `task["status"]` raises `KeyError`, so every status poll or wait loop crashes.  
   **Recommendation:** Read from the `state` payload (e.g., `task['state']['status']`) and tolerate missing metadata. Cover with an integration test that submits a workflow and waits on `wait_for_task`.

3. **Workflow-scoped task endpoints don’t exist server-side**  
   **Location:** `src/gleitzeit/client/mixins/tasks.py:51-55`, `src/gleitzeit/client/mixins/tasks.py:108-131`, `src/gleitzeit/client/mixins/tasks.py:148-151`  
   **Issue:** When a `workflow_id` is provided, the client calls `/workflows/{workflow_id}/tasks/{task_id}[/(retry|cancel|logs)]`, but the API only exposes `/tasks/{task_id}` routes. The result is a FastAPI 404 whenever callers provide the optional `workflow_id`.  
   **Recommendation:** Drop the nonexistent workflow-scoped variants (always hit `/tasks/...`) or implement matching routes server-side. Update tests to cover both code paths.

4. **Worker monitoring expects fields that are never returned**  
   **Location:** `src/gleitzeit/client/mixins/monitoring.py:86-94`  
   **Issue:** The client constructs `WorkerStatus` using `worker["status"]`, `worker["tasks_processed"]`, etc., but `/system/workers` currently returns the raw Redis hash (`state`, `shards`, `started_at`). Accessing missing keys raises `KeyError`, so `get_workers_status()` crashes.  
   **Recommendation:** Use `.get` for optional data and map the actual fields (`state` → status, decode shard list). Add a smoke test calling `get_workers_status` against a running orchestrator stub.

5. **Workflow retry re-submits without a definition**  
   **Location:** `src/gleitzeit/client/mixins/workflows.py:229-237`  
   **Issue:** `retry_workflow` assumes `GET /workflows/{id}` returns a `definition` field, then tries to resubmit `workflow["definition"]`. The API only exposes `data["workflow"]`. Attempting a retry raises `KeyError`.  
   **Recommendation:** Pull the serialized workflow from the correct location (`response['data']['workflow']`) and guard against missing data. Add an end-to-end test that retries a workflow fixture.

### Medium
6. **Error log retrieval drops all entries**  
   **Location:** `src/gleitzeit/client/mixins/monitoring.py:190-199`  
   **Issue:** The client reads `response.get("logs", [])`, but `/system/logs/errors` returns an `errors` array. Callers always receive an empty list even when the API returns data.  
   **Recommendation:** Switch to `response.get("errors", [])` and include metadata like `total` if useful for pagination.

7. **Rate-limit metadata interpreted with wrong field names**  
   **Location:** `src/gleitzeit/client/mixins/monitoring.py:209-219`  
   **Issue:** `/auth/rate-limit` responds with `remaining`, `limit`, `reset_in_seconds`, and `current`; the client instead looks for `reset_at`/`window`, silently returning defaults.  
   **Recommendation:** Align the field names and expose `reset_in_seconds` verbatim so UI/CLI tooling can display accurate quota data.

## Recommendations & Next Steps
1. **Fix initialization order problems.** Update `BaseClient`/`AuthMixin` so credentials survive the constructor, then add regression tests for auto-login and explicit session usage.
2. **Realign task and workflow helpers with the live API.** Patch schema assumptions (`TaskStatus`) and remove nonexistent endpoints before release; backfill async tests that exercise retries, cancellation, and log retrieval.
3. **Audit monitoring helpers.** Bring `get_workers_status`, `get_error_logs`, and `get_rate_limit_status` in sync with the server responses, and consider snapshot tests against a mocked `/system` API to catch future drift.

## Appendix
- Server references: `src/gleitzeit/api/routes/tasks.py`, `src/gleitzeit/api/routes/workflows.py`, `src/gleitzeit/api/routes/system.py`, `src/gleitzeit/api/routes/auth.py`
- Legacy clients: `client_old.py`, `client_original.py` (not reviewed in detail; consider deprecating once modular client is fixed)
