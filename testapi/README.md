# Gleitzeit API Endpoint Tests

**Direct HTTP tests for all API endpoints** - tests the actual API without using the client library.

## Test Files

### `test_api_auth.py` - Authentication Endpoints (7 tests)
- ✓ `POST /auth/session/create` - Create session
- ✓ `POST /auth/session/validate` - Validate session
- ✓ `POST /auth/session/destroy` - Destroy session
- ✓ `POST /auth/token` - Create JWT token
- ✓ `GET /auth/me` - Get current user
- ✓ `GET /auth/rate-limit` - Get rate limit status

### `test_api_workflows.py` - Workflow Endpoints (7 tests)
- ✓ `POST /workflows/submit` - Submit workflow
- ✓ `GET /workflows/{id}` - Get workflow details
- ✓ `GET /workflows/{id}/tasks` - Get workflow tasks
- ✓ `GET /workflows/list` - List workflows
- ✓ `POST /workflows/` - Batch get workflows
- ✓ `POST /workflows/{id}/cancel` - Cancel workflow
- ✓ Result chaining test - Verify task dependency data flow

### `test_api_tasks.py` - Task Endpoints (7 tests)
- ✓ `GET /tasks/list` - List tasks
- ✓ `GET /tasks/{id}` - Get task details
- ✓ `POST /tasks/` - Batch get tasks
- ✓ `GET /tasks/{id}/logs` - Get task logs
- ✓ `GET /tasks/{id}/events` - Get task events
- ✓ `POST /tasks/{id}/retry` - Retry failed task
- ✓ `POST /tasks/{id}/cancel` - Cancel task

### `test_api_health.py` - Health Endpoints (6 tests)
- ✓ `GET /` - Root endpoint
- ✓ `GET /health/` - Basic health check
- ✓ `GET /health/ready` - Readiness probe
- ✓ `GET /health/live` - Liveness probe
- ✓ `GET /health/detailed` - Detailed health info
- ✓ `GET /health/cluster` - Cluster health & service discovery

### `test_api_system.py` - System Endpoints (11 tests)
- ✓ `GET /system/status` - System status
- ✓ `GET /system/metrics` - Overall metrics
- ✓ `GET /system/workers` - List workers
- ✓ `GET /system/metrics/workflows` - Workflow metrics
- ✓ `GET /system/metrics/tasks` - Task metrics
- ✓ `GET /system/redis/info` - Redis information
- ✓ `GET /system/queues` - Queue depths
- ✓ `GET /system/config` - System configuration
- ✓ `GET /system/resources` - Resource usage (CPU, memory, disk)
- ✓ `POST /system/workers/health-check` - Trigger worker health checks
- ✓ `GET /system/sessions` - Active sessions

**Total: 38 API tests covering 40+ endpoints**

## Running Tests

### Prerequisites

1. **Start Gleitzeit server**:
   ```bash
   cd /Users/leifmarkthaler/github/gleitzeit\ 0.0.7
   export PYTHONPATH="$PWD/src:$PYTHONPATH"
   python -m gleitzeit.cli.main serve -c gleitzeit.yaml
   ```

2. **Install httpx** (for async HTTP requests):
   ```bash
   pip install httpx
   ```

### Run All Tests with Pytest

```bash
# From the project root
cd /Users/leifmarkthaler/github/gleitzeit\ 0.0.7

# Run all API tests
python -m pytest testapi/ -v

# Run specific test file
python -m pytest testapi/test_api_auth.py -v

# Run specific test
python -m pytest testapi/test_api_auth.py::test_create_session -v
```

### Run Individual Test Files

Each test file can be run standalone:

```bash
cd /Users/leifmarkthaler/github/gleitzeit\ 0.0.7

# Auth tests
python testapi/test_api_auth.py

# Workflow tests
python testapi/test_api_workflows.py

# Task tests
python testapi/test_api_tasks.py

# Health tests
python testapi/test_api_health.py

# System tests
python testapi/test_api_system.py
```

## Test Features

### Direct HTTP Testing
- Uses `httpx.AsyncClient` for direct HTTP requests
- No dependency on GleitzeitClient library
- Tests the actual API contract

### Authentication
- Tests all auth methods (session, JWT, API key)
- Tests parameter formats (query params vs body)
- Verifies response structures

### Result Chaining
- Comprehensive test for task dependency data flow
- Verifies UUID-based input injection
- Checks actual computation results (42 * 2 = 84)

### Error Handling
- Tests terminal state transitions
- Verifies retry logic
- Tests cancellation scenarios

### Monitoring & Health
- System metrics and statistics
- Worker registration and health
- Queue depths and Redis info
- Resource usage tracking

## Test Output Examples

### Successful Auth Test
```
✓ Created session: 7109af9f-d4fb-4f2e-855d-84080b0e054a
✓ Session 7109af9f-d4fb-4f2e-855d-84080b0e054a is valid
✓ Destroyed session 7109af9f-d4fb-4f2e-855d-84080b0e054a
✓ Created JWT token
✓ Got current user: {'id': '...', 'username': 'me_user'}
✓ Rate limit: 95/100 remaining
```

### Successful Result Chaining Test
```
Submitted chaining workflow: workflow-abc123
✓ Result chaining worked: {'doubled': 84}
```

### Successful System Monitoring Test
```
✓ System metrics:
  Workflows: 15 total, 2 running
  Tasks: 47 total, 5 running
✓ Workers: 4 registered
  - worker-task-execution-1: task_execution
  - worker-workflow-loader-1: workflow_loader
  - worker-dependency-1: dependency
```

## Key Differences from Client Tests

| Aspect | API Tests (`testapi/`) | Client Tests (`testclient/`) |
|--------|------------------------|------------------------------|
| **Method** | Direct HTTP with `httpx` | Uses `GleitzeitClient` library |
| **Purpose** | Test API contract | Test client library |
| **Scope** | Endpoint behavior | Client abstraction layer |
| **Auth** | Manual header management | Automatic via client |
| **Errors** | HTTP status codes | Python exceptions |
| **Focus** | API correctness | Client usability |

## Troubleshooting

### Connection Errors
Ensure server is running:
```bash
curl http://localhost:8000/health/
```

### Authentication Errors
Check that auto-login is enabled in `gleitzeit.yaml`:
```yaml
auth:
  enabled: true
  auto_login: true
```

### Import Errors
Install required dependencies:
```bash
pip install httpx pytest pytest-asyncio
```

### Timeout Issues
Some tests wait for workflow completion - adjust timeouts if needed:
```python
for _ in range(30):  # Increase if workflows take longer
    await asyncio.sleep(2)
```

## Notes

- Tests create actual workflows and tasks on the server
- Tests use unique usernames to avoid conflicts
- Some tests may skip if conditions aren't met (e.g., no failed tasks)
- Tests are safe to run repeatedly
- System monitoring tests are read-only

## Related Documentation

- **API Audit**: `API_ENDPOINT_AUDIT.md` - Complete endpoint reference
- **Client Tests**: `testclient/README.md` - Client library tests
- **Client Capabilities**: `GLEITZEIT_CLIENT_CAPABILITIES.md` - Full client API

---

**Last Updated**: 2025-09-30
**API Version**: 0.0.7
