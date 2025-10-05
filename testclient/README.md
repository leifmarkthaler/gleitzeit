# GleitzeitClient Test Suite

Comprehensive tests for the Gleitzeit Python Client SDK.

## Test Files

### `test_client_authentication.py`
Tests authentication functionality:
- Session creation and management
- Session validation and destruction
- Auto-login functionality
- Manual authentication
- User information retrieval

### `test_client_workflows.py`
Tests workflow operations:
- Workflow submission (simple and with metadata)
- Workflow status queries
- Task listing from workflows
- Waiting for workflow completion
- **Result chaining between tasks**
- Workflow cancellation
- Batch workflow submission
- Workflow listing

### `test_client_tasks.py`
Tests task operations:
- Task status queries
- Task result retrieval
- Waiting for task completion
- Task dependencies and dependents
- Task listing and filtering
- Failed task handling
- Task logs retrieval

### `test_client_monitoring.py`
Tests monitoring and health functionality:
- Basic health checks
- Detailed system health
- Worker status monitoring
- System, workflow, and task metrics
- Queue depth monitoring
- Redis information
- Resource usage
- API version checks
- Configuration retrieval
- Rate limit status
- Audit and error logs
- Worker health checks

## Running Tests

### Prerequisites

1. **Start Gleitzeit server** (required for all tests):
   ```bash
   cd /Users/leifmarkthaler/github/gleitzeit\ 0.0.7
   export PYTHONPATH="$PWD/src:$PYTHONPATH"
   python -m gleitzeit.cli.main serve -c gleitzeit.yaml
   ```

2. **Ensure Redis is running**:
   ```bash
   redis-cli ping  # Should return PONG
   ```

### Run All Tests with Pytest

```bash
# From the project root
cd /Users/leifmarkthaler/github/gleitzeit\ 0.0.7

# Run all client tests
export PYTHONPATH="$PWD/src:$PYTHONPATH"
python -m pytest testclient/ -v

# Run specific test file
python -m pytest testclient/test_client_workflows.py -v

# Run specific test
python -m pytest testclient/test_client_workflows.py::test_result_chaining -v
```

### Run Individual Test Files

Each test file can also be run standalone:

```bash
cd /Users/leifmarkthaler/github/gleitzeit\ 0.0.7
export PYTHONPATH="$PWD/src:$PYTHONPATH"

# Authentication tests
python testclient/test_client_authentication.py

# Workflow tests
python testclient/test_client_workflows.py

# Task tests
python testclient/test_client_tasks.py

# Monitoring tests
python testclient/test_client_monitoring.py
```

## Test Coverage

### Authentication Tests (6 tests)
- ✓ Session creation
- ✓ Session validation
- ✓ Session destruction
- ✓ Auto-login
- ✓ Get current user
- ✓ Manual authentication

### Workflow Tests (9 tests)
- ✓ Submit simple workflow
- ✓ Submit workflow with metadata and priority
- ✓ Get workflow status
- ✓ Get workflow tasks
- ✓ Wait for workflow completion
- ✓ **Result chaining between tasks** (tests UUID-based input injection)
- ✓ Cancel workflow
- ✓ List workflows
- ✓ Batch workflow submission

### Task Tests (7 tests)
- ✓ Get task status
- ✓ Get task result
- ✓ Wait for task completion
- ✓ Get task dependencies
- ✓ List tasks
- ✓ Get failed tasks
- ✓ Get task logs

### Monitoring Tests (15 tests)
- ✓ Basic health check
- ✓ Detailed system health
- ✓ Worker status
- ✓ System metrics
- ✓ Workflow metrics
- ✓ Task metrics
- ✓ Queue depths
- ✓ Redis info
- ✓ Resource usage
- ✓ API version
- ✓ Configuration
- ✓ Rate limit status
- ✓ Audit logs
- ✓ Error logs
- ✓ Worker health checks

**Total: 37 tests covering 60+ client methods**

## Key Test: Result Chaining

The `test_result_chaining` test in `test_client_workflows.py` verifies that:

1. A "generate" task produces `{'number': 42, 'message': 'Generated data'}`
2. A "process" task receives this as input via the `inputs` dict (keyed by task UUID)
3. The "process" task correctly doubles the number: `42 * 2 = 84`
4. Result: `{'doubled': 84, 'processed': True}`

This demonstrates how the GleitzeitClient handles result chaining with the dependency worker's UUID-based injection mechanism.

## Test Output Examples

### Successful Workflow Test
```
✓ Submitted workflow: workflow-abc123
✓ Got workflow status: completed
  Created: 2025-09-30T10:30:00Z
  Updated: 2025-09-30T10:30:05Z
✓ Got 2 tasks from workflow
  - generate: completed
  - process: completed
✓ Workflow completed with status: completed
✓ Result chaining worked!
  Process task result: {'doubled': 84, 'processed': True}
  ✓ Verified: 42 * 2 = 84
```

### Successful Monitoring Test
```
✓ Got system health
  Status: healthy
  API Version: 0.0.7
  Uptime: 3600.5s
  Redis Connected: True
  Workers: 4
  Active Workflows: 2
  Active Tasks: 3

✓ Got 4 workers
  Worker: worker-task-execution-1
    Type: task_execution
    Status: running
    Last Heartbeat: 2025-09-30T10:29:55Z
    Tasks Processed: 127
```

## Troubleshooting

### Connection Errors
If tests fail with connection errors:
1. Ensure Gleitzeit server is running on `http://localhost:8000`
2. Check that Redis is running: `redis-cli ping`
3. Verify no firewall blocking localhost:8000

### Test Timeouts
If workflows don't complete:
1. Check worker status: `gleitzeit ps`
2. Check logs in `logs/` directory
3. Increase timeout values in tests

### Import Errors
Ensure `PYTHONPATH` is set:
```bash
export PYTHONPATH="/Users/leifmarkthaler/github/gleitzeit 0.0.7/src:$PYTHONPATH"
```

## Notes

- Tests use `auto_login=True` by default for convenience
- Some tests submit actual workflows to the server
- Tests are safe to run repeatedly (use unique workflow IDs)
- Monitoring tests are read-only and don't modify system state
- Result chaining tests verify the documented behavior in `GLEITZEIT_CLIENT_CAPABILITIES.md`

## Related Documentation

- **Client Capabilities**: `GLEITZEIT_CLIENT_CAPABILITIES.md` - Complete reference
- **Easy Client**: `src/gleitzeit/easy/` - High-level DSL for workflow building
- **Client Source**: `src/gleitzeit/client/` - Implementation details
