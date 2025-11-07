# API and Client Alignment Audit

## Summary
This audit compares the API endpoints exposed by the FastAPI application with the client methods that consume them.

## ✅ Aligned Endpoints

### Workflows API
| API Endpoint | Method | Client Method | Status |
|-------------|--------|---------------|--------|
| `/workflows/submit` | POST | `submit_workflow()` | ✅ Aligned |
| `/workflows/{workflow_id}` | GET | `get_workflow()` | ✅ Aligned |
| `/workflows/{workflow_id}/tasks` | GET | `get_workflow_tasks()` | ✅ Aligned |
| `/workflows/{workflow_id}/cancel` | POST | `cancel_workflow()` | ✅ Aligned |

### Tasks API
| API Endpoint | Method | Client Method | Status |
|-------------|--------|---------------|--------|
| `/tasks/{task_id}` | GET | `get_task()` | ✅ Aligned |
| `/tasks/{task_id}/logs` | GET | `get_task_logs()` | ✅ Aligned |
| `/tasks/{task_id}/retry` | POST | `retry_task()` | ✅ Aligned |
| `/tasks/{task_id}/cancel` | POST | `cancel_task()` | ✅ Aligned |

### Auth API
| API Endpoint | Method | Client Method | Status |
|-------------|--------|---------------|--------|
| `/auth/session/create` | POST | `create_session()` | ✅ Aligned |
| `/auth/session/validate` | POST | `validate_session()` | ⚠️ Client uses GET |
| `/auth/session/destroy` | POST | `destroy_session()` | ✅ Aligned |
| `/auth/token` | POST | `create_token()` | ✅ Aligned |
| `/auth/token/refresh` | POST | `refresh_token()` | ✅ Aligned |

### Health API
| API Endpoint | Method | Client Method | Status |
|-------------|--------|---------------|--------|
| `/health` | GET | `health_check()` | ✅ Aligned |
| `/health/ready` | GET | - | ❌ Not used by client |
| `/health/live` | GET | - | ❌ Not used by client |

### System API
| API Endpoint | Method | Client Method | Status |
|-------------|--------|---------------|--------|
| `/system/status` | GET | - | ❌ Not used by client |
| `/system/metrics` | GET | `get_system_metrics()` | ✅ Aligned |
| `/system/workers` | GET | `get_workers_status()` | ✅ Aligned |

## ❌ Client Methods Without API Endpoints

These client methods call endpoints that don't exist in the API:

1. **`list_workflows()`** - Calls `GET /workflows` (doesn't exist)
2. **`get_system_health()`** - Calls `GET /health/detailed` (doesn't exist)
3. **`get_workflow_metrics()`** - Calls `GET /system/metrics/workflows` (doesn't exist)
4. **`get_task_metrics()`** - Calls `GET /system/metrics/tasks` (doesn't exist)
5. **`get_redis_info()`** - Calls `GET /system/redis/info` (doesn't exist)
6. **`get_queue_depths()`** - Calls `GET /system/queues` (doesn't exist)
7. **`get_audit_logs()`** - Calls `GET /system/audit/logs` (doesn't exist)
8. **`get_error_logs()`** - Calls `GET /system/logs/errors` (doesn't exist)
9. **`get_resource_usage()`** - Calls `GET /system/resources` (doesn't exist)
10. **`check_api_version()`** - Calls `GET /` (doesn't exist)
11. **`get_configuration()`** - Calls `GET /system/config` (doesn't exist)
12. **`trigger_health_check_all_workers()`** - Calls `POST /system/workers/health-check` (doesn't exist)
13. **`get_active_sessions()`** - Calls `GET /system/sessions` (doesn't exist)
14. **`get_rate_limit_status()`** - Calls `GET /auth/rate-limit` (doesn't exist)
15. **`get_current_user()`** - Calls `GET /auth/me` (doesn't exist)
16. **`get_task_dependencies()`** - Calls `GET /workflows/{workflow_id}/tasks/{task_id}/dependencies` (doesn't exist)
17. **`get_task_dependents()`** - Calls `GET /workflows/{workflow_id}/tasks/{task_id}/dependents` (doesn't exist)

## ⚠️ Issues Found

### 1. Authentication Issue
The `validate_session()` method in the client uses GET but the API expects POST for `/auth/session/validate`.

### 2. Cancel Workflow Issue
The `cancel_workflow` endpoint references `user.username` but doesn't have user context (line 246 in workflows.py).

### 3. Missing Root Endpoint
Client's `check_api_version()` tries to call `GET /` but there's no root endpoint defined.

## 📋 Recommendations

### Priority 1: Fix Breaking Issues
1. **Fix validate_session method** - Change client to use POST instead of GET
2. **Fix cancel_workflow endpoint** - Remove `user.username` reference or add proper auth dependency
3. **Add root endpoint** - Add a simple GET / endpoint that returns API info

### Priority 2: Remove or Implement Missing Endpoints
Either:
- Remove the client methods that call non-existent endpoints, OR
- Implement the missing API endpoints

### Priority 3: Documentation
- Document which client methods are actually functional
- Add integration tests to ensure alignment stays intact

## Client Methods That Work Out of the Box

✅ **Fully Functional:**
- `submit_workflow()`
- `get_workflow()`
- `get_workflow_tasks()`
- `cancel_workflow()` (after fixing user reference)
- `get_task()`
- `get_task_logs()`
- `retry_task()`
- `cancel_task()`
- `create_session()`
- `destroy_session()`
- `create_token()`
- `refresh_token()`
- `health_check()`
- `get_system_metrics()`
- `get_workers_status()`

❌ **Non-Functional (Missing API endpoints):**
- All monitoring methods except basic ones
- Task dependency/dependent queries
- Workflow listing
- Session management beyond basic CRUD
- Rate limiting status