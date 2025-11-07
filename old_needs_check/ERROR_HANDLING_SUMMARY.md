# Gleitzeit Error Handling Summary

## Workflow Validation Errors

### Successfully Detected and Handled ✅

1. **Missing Required Fields**
   - Missing handler field in task definition
   - Properly rejected with validation error

2. **Invalid Dependencies**
   - References to non-existent tasks
   - Caught during validation phase

3. **Invalid Methods**
   - Task methods not supported by handler protocol
   - Error: "method 'invalid/method' not supported by protocol"

4. **Duplicate Task IDs**
   - Multiple tasks with same ID
   - Detected and reported in validation

5. **Empty Workflows**
   - Workflows with no tasks defined
   - Error: "Workflow must have at least one task"

6. **Invalid Format**
   - Malformed JSON/YAML content
   - Error: "Invalid workflow format: not valid JSON or YAML"

## File Loading Errors

### Successfully Detected ✅

1. **Non-existent Files**
   - File path doesn't exist
   - Reported as runtime error

2. **Invalid JSON Files**
   - JSON syntax errors
   - Caught during parsing

3. **Invalid YAML Files**
   - YAML syntax errors
   - Caught during parsing

## Error Flow

### Validation Errors (Unretryable)
```
Workflow Submission
    ↓
WorkflowLoaderWorkerV2
    ↓
Validation Fails
    ↓
Mark as 'failed' in workflow:data
    ↓
Emit to global:workflow:load:failed
    ↓
ACK message (don't retry)
```

### Runtime Errors (Retryable)
```
Workflow Submission
    ↓
WorkflowLoaderWorkerV2
    ↓
File I/O or parsing error
    ↓
Log error
    ↓
Emit to global:workflow:load:failed
    ↓
Don't ACK (will retry)
```

## Error Message Locations

1. **Workflow Data Storage**
   - Key: `{shard:N}:workflow:data:{workflow_id}`
   - Fields: `status=failed`, `error=<message>`

2. **Failed Stream**
   - Key: `global:workflow:load:failed`
   - Contains: workflow_id, error, error_type, timestamp

3. **Dead Letter Queue**
   - Key: `{shard:N}:dlq:{stream_name}`
   - Messages that fail after retries

## Task Execution Errors

### Python Handler Behavior
- Exceptions caught and wrapped in TaskResult
- Status set to FAILED
- Error details included in result
- Task marked as failed in Redis

### Issue Found
- Workflow status tracking inconsistency
- Shows 2 completed, 3 running for 3-task workflow
- Task2 with division by zero has no status
- Task3 (depends on failed task2) still shows completed

## Recommendations

1. **Fix Status Tracking**
   - Ensure failed tasks properly update workflow status
   - Dependencies of failed tasks should be skipped/failed

2. **Add Retry Limits**
   - Configure max retries for runtime errors
   - Move to DLQ after exhausting retries

3. **Improve Error Messages**
   - Include stack traces for debugging
   - Add error codes for programmatic handling

4. **Add Monitoring**
   - Dashboard for failed workflows
   - Alerts for validation errors
   - Metrics on error types and frequencies