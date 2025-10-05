# Gleitzeit 0.0.7 API Endpoint Audit

**Complete audit of all available API endpoints in the current implementation.**

---

## Authentication Endpoints (`/auth`)

### ✅ `/auth/session/create` - POST
- **Request**: `{username: str, password: str}`  (both required as strings, not null)
- **Response**: `{session_id: str, user: User}`
- **Notes**: Dev mode accepts any username without password validation

### ✅ `/auth/session/validate` - POST
- **Request**: `session_id: str` (query parameter, not body)
- **Response**: `{valid: bool, user: User}`

### ✅ `/auth/session/destroy` - POST
- **Request**: `session_id: str` (query parameter)
- **Response**: `{message: str}`

### ✅ `/auth/token` - POST
- **Request**: `{username: str, password: str}`
- **Response**: `Token` (JWT token object)

### ✅ `/auth/token/refresh` - POST
- **Request**: `refresh_token: str` (query parameter)
- **Response**: `Token` (new JWT token)

### ✅ `/auth/me` - GET
- **Response**: Current user information
- **Requires**: Authentication

### ✅ `/auth/rate-limit` - GET
- **Response**: `{limit: int, remaining: int, reset_in_seconds: int, current: int}`

---

## Workflow Endpoints (`/workflows`)

### ✅ `/workflows/submit` - POST
- **Request**: `{workflow: dict, workflow_id?: str, metadata?: dict}`
- **Response**: `{workflow_id: str, status: str, message: str, submitted_at: str}`

### ✅ `/workflows/list` - GET
- **Query Params**: `limit: int = 100, offset: int = 0, status?: str`
- **Response**: `{workflows: list, total: int, limit: int, offset: int}`
- **Returns**: Full workflow data with progress

### ✅ `/workflows/` - POST
- **Request**: `{workflow_ids: list[str]}`
- **Response**: `{workflows: list, requested: int, found: int}`
- **Notes**: Batch get multiple workflows

### ✅ `/workflows/{workflow_id}` - GET
- **Response**: `{workflow_id: str, state: dict, data?: dict}`

### ✅ `/workflows/{workflow_id}/tasks` - GET
- **Response**: `{workflow_id: str, task_count: int, tasks: list}`

### ✅ `/workflows/{workflow_id}/tasks/{task_id}/dependencies` - GET
- **Response**: `{task_id: str, workflow_id: str, dependencies: list[str]}`
- **Notes**: Returns task names, not UUIDs

### ✅ `/workflows/{workflow_id}/tasks/{task_id}/dependents` - GET
- **Response**: `{task_id: str, workflow_id: str, dependents: list[str]}`

### ✅ `/workflows/{workflow_id}/cancel` - POST
- **Response**: `{workflow_id: str, status: str, tasks_cancelled: int, message: str}`

---

## Task Endpoints (`/tasks`)

### ✅ `/tasks/list` - GET
- **Query Params**: `limit: int = 100, offset: int = 0, status?: str, workflow_id?: str`
- **Response**: `{task_ids: list[str], total: int, limit: int, offset: int}`
- **Notes**: Returns just task IDs for listing

### ✅ `/tasks/` - POST
- **Request**: `{task_ids: list[str]}`
- **Response**: `{tasks: list, requested: int, found: int}`
- **Notes**: Batch get multiple tasks

### ✅ `/tasks/{task_id}` - GET
- **Response**: `{task_id: str, workflow_id: str, state: dict}`

### ✅ `/tasks/{task_id}/logs` - GET
- **Response**: `{task_id: str, log_count: int, logs: list}`

### ✅ `/tasks/{task_id}/events` - GET
- **Response**: `{task_id: str, workflow_id: str, event_count: int, events: list}`
- **Notes**: Timeline of task execution events

### ✅ `/tasks/{task_id}/retry` - POST
- **Response**: `{task_id: str, status: str, message: str}`

### ✅ `/tasks/{task_id}/cancel` - POST
- **Response**: `{task_id: str, status: str, message: str}`

---

## Health Endpoints (`/health`)

### ✅ `/health/` - GET
- **Response**: `{status: str, components: dict}`
- **Notes**: Basic health check

### ✅ `/health/ready` - GET
- **Response**: `{ready: bool}`
- **Notes**: Kubernetes readiness probe

### ✅ `/health/live` - GET
- **Response**: `{alive: bool}`
- **Notes**: Kubernetes liveness probe

### ✅ `/health/detailed` - GET
- **Response**: `{status: str, version: str, redis_connected: bool, worker_count: int, active_workflows: int, redis_info: dict}`

### ✅ `/health/cluster` - GET
- **Response**: `{status: str, redis_connected: bool, cluster_info: dict, services: dict, deployment_modes: list, timestamp: str}`
- **Notes**: Stateless cluster health check with service discovery

---

## System Endpoints (`/system`)

### ✅ `/system/status` - GET
- **Response**: `{orchestrator: dict, workers: dict, queues: dict, shards: dict}`

### ✅ `/system/metrics` - GET
- **Response**: `{workflows: dict, tasks: dict}`

### ✅ `/system/workers` - GET
- **Response**: `{count: int, workers: list}`

### ✅ `/system/metrics/workflows` - GET
- **Query Params**: `time_range: str = "1h"`
- **Response**: `{time_range: str, total_workflows: int, by_status: dict, active: int, completed: int, failed: int}`

### ✅ `/system/metrics/tasks` - GET
- **Query Params**: `time_range: str = "1h"`
- **Response**: `{time_range: str, total_tasks: int, by_status: dict, by_protocol: dict, executing: int, completed: int, failed: int}`

### ✅ `/system/redis/info` - GET
- **Response**: `{version: str, uptime_seconds: int, connected_clients: int, used_memory: str, total_connections_received: int, total_commands_processed: int, keyspace: dict}`

### ✅ `/system/queues` - GET
- **Response**: `{queues: dict, total_queues: int, total_messages: int}`

### ✅ `/system/audit/logs` - GET
- **Query Params**: `limit: int = 100, offset: int = 0, level?: str, workflow_id?: str`
- **Response**: `{logs: list, total: int, limit: int, offset: int, message: str}`
- **Notes**: Placeholder - not fully implemented

### ✅ `/system/logs/errors` - GET
- **Query Params**: `limit: int = 100, offset: int = 0, level: str = "ERROR"`
- **Response**: `{errors: list, total: int, limit: int, offset: int}`

### ✅ `/system/resources` - GET
- **Response**: `{cpu: dict, memory: dict, disk: dict}`
- **Requires**: `psutil` library

### ✅ `/system/config` - GET
- **Response**: Sanitized configuration (no sensitive data)

### ✅ `/system/workers/health-check` - POST
- **Response**: `{results: dict, healthy: int, unhealthy: int, total: int}`

### ✅ `/system/sessions` - GET
- **Response**: `{sessions: list, total: int, active: int}`

---

## Root Endpoint

### ✅ `/` - GET
- **Response**: `{name: str, version: str, status: str, description: str, features: list}`

---

## Endpoints NOT in Current Implementation

These methods were documented in the client but **do not exist** in the API:

### ❌ **Workflow Operations**
- `retry_workflow()` - NO `/workflows/{id}/retry` endpoint
  - **Alternative**: Use `submit_workflow()` with original workflow definition

### ❌ **Task Operations**
- `get_task_dependents()` - Endpoint EXISTS but path is under `/workflows/{workflow_id}/tasks/{task_id}/dependents`
  - Client implementation expects `/tasks/{task_id}/dependents`
- `get_task_dependencies()` - Same issue, path is under `/workflows/...`
- `get_failed_tasks()` - No dedicated endpoint
  - **Alternative**: Use `/workflows/{id}/tasks` and filter client-side
- `retry_failed_tasks()` - No batch retry endpoint
  - **Alternative**: Iterate and retry individually

---

## Key Findings

### 1. **Authentication Issues**
- `session_id` must be passed as **query parameter**, not in body
- `username` and `password` cannot be null - must be actual strings

### 2. **Task Dependency Endpoints**
- Dependencies/dependents endpoints are under `/workflows/{workflow_id}/tasks/{task_id}/...`
- NOT under `/tasks/{task_id}/...` as client expects

### 3. **Missing Batch Operations**
- No workflow retry endpoint
- No batch task retry
- Must implement client-side

### 4. **System Monitoring**
- Most monitoring endpoints exist and work
- Audit logging is placeholder only

### 5. **Rate Limiting**
- Rate limit info available at `/auth/rate-limit`
- Client method signature needs updating

---

## Recommendations

### Fix Client Implementation

1. **Fix auth methods**: Pass `session_id` as query param
2. **Fix dependency methods**: Use correct workflow-scoped paths
3. **Remove non-existent methods**: `retry_workflow`, `retry_failed_tasks`
4. **Add missing methods**: `get_task_events()`, `/health/cluster`
5. **Update method signatures**: Ensure params match API

### Update Documentation

1. **Mark unsupported operations** in `GLEITZEIT_CLIENT_CAPABILITIES.md`
2. **Add notes about workarounds** for missing endpoints
3. **Document correct endpoint paths**

### Test Strategy

1. **Test what exists first**: Focus on working endpoints
2. **Skip non-existent methods**: Remove tests for missing endpoints
3. **Add integration note**: Document which features require client-side logic

---

## Summary

**Total Endpoints Audited**: 40+

**Working Categories**:
- ✅ Authentication (7 endpoints)
- ✅ Workflows (8 endpoints)
- ✅ Tasks (7 endpoints)
- ✅ Health (4 endpoints)
- ✅ System Monitoring (12 endpoints)
- ✅ Root (1 endpoint)

**Issues Found**:
- 🔧 Parameter format mismatches (auth)
- 🔧 Path mismatches (task dependencies)
- ❌ Missing endpoints (retry_workflow, batch operations)
- ⚠️ Placeholder implementations (audit logs)

**Next Steps**:
1. Fix GleitzeitClient to match actual API
2. Update tests to only test existing endpoints
3. Update documentation with correct capabilities
4. Add client-side implementations for missing features

---

**Last Updated**: 2025-09-30
**API Version**: 0.0.7
