# Event Error Management API

## Overview

The Event Error Management API provides endpoints for monitoring, debugging, and managing event handler failures in the Gleitzeit system. All event handler errors are automatically persisted for traceability ("Nachvollziehbarkeit") and can be queried through these endpoints.

## Base URL

All event error endpoints are prefixed with `/event-errors`

## Authentication

These endpoints follow the same authentication rules as other Gleitzeit API endpoints. If authentication is enabled (`GLEITZEIT_AUTH_ENABLED=true`), appropriate credentials are required.

## Endpoints

### List Event Errors

Retrieve a list of recent event handler errors for debugging and monitoring.

**Endpoint:** `GET /event-errors`

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `limit` | integer | No | Maximum number of errors to return (1-1000) | 100 |
| `event_type` | string | No | Filter by event type (e.g., "TASK_COMPLETED") | None |
| `handler_name` | string | No | Filter by handler name | None |
| `since` | datetime | No | Return only errors since this timestamp | None |

**Response:** `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "handler_name": "TaskCompletedHandler",
    "event_type": "TASK_COMPLETED",
    "event_id": "evt-123",
    "error_type": "ValueError",
    "error_message": "Task status invalid for completion",
    "error_traceback": "Traceback (most recent call last):\n  File...",
    "timestamp": "2024-01-15T10:30:00Z",
    "metadata": {
      "task_id": "task-456",
      "workflow_id": "wf-789",
      "handler_class": "TaskCompletedHandler"
    }
  }
]
```

**Example Request:**

```bash
# Get last 10 errors
curl http://localhost:8000/event-errors?limit=10

# Get errors for specific event type
curl http://localhost:8000/event-errors?event_type=TASK_FAILED

# Get errors from a specific handler since yesterday
curl "http://localhost:8000/event-errors?handler_name=WorkflowHandler&since=2024-01-14T00:00:00Z"
```

### Get Error Statistics

Retrieve aggregated statistics about event handler errors.

**Endpoint:** `GET /event-errors/stats`

**Response:** `200 OK`

```json
{
  "total_errors": 42,
  "handlers_with_errors": [
    ["TaskCompletedHandler", 25],
    ["WorkflowHandler", 10],
    ["DependencyHandler", 7]
  ],
  "event_types_with_errors": [
    ["TASK_COMPLETED", 20],
    ["TASK_FAILED", 15],
    ["WORKFLOW_COMPLETED", 7]
  ],
  "oldest_error": "2024-01-01T00:00:00Z",
  "newest_error": "2024-01-15T14:30:00Z"
}
```

**Use Cases:**
- Monitor which handlers are failing most frequently
- Identify problematic event types
- Track error trends over time

**Example Request:**

```bash
curl http://localhost:8000/event-errors/stats
```

### Get Specific Error

Retrieve detailed information about a specific event error, including full traceback.

**Endpoint:** `GET /event-errors/{error_id}`

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `error_id` | string | Yes | Unique error identifier |

**Response:** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "handler_name": "TaskCompletedHandler",
  "event_type": "TASK_COMPLETED",
  "event_id": "evt-123",
  "error_type": "ValueError",
  "error_message": "Task status invalid for completion",
  "error_traceback": "Traceback (most recent call last):\n  File \"/app/handlers.py\", line 45, in handle\n    self.process_task(task)\n  File \"/app/handlers.py\", line 78, in process_task\n    raise ValueError('Task status invalid')\nValueError: Task status invalid for completion",
  "timestamp": "2024-01-15T10:30:00Z",
  "metadata": {
    "task_id": "task-456",
    "workflow_id": "wf-789",
    "handler_class": "TaskCompletedHandler",
    "event_data": {
      "task_name": "Process Data",
      "duration": 5.2
    }
  }
}
```

**Error Responses:**

- `404 Not Found` - Error with specified ID not found
- `503 Service Unavailable` - Event error persistence not available

**Example Request:**

```bash
curl http://localhost:8000/event-errors/550e8400-e29b-41d4-a716-446655440000
```

### Clean Up Old Errors

Remove event errors older than a specified retention period.

**Endpoint:** `DELETE /event-errors/cleanup`

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `days` | integer | No | Delete errors older than this many days (1-365) | 30 |

**Response:** `200 OK`

```json
{
  "success": true,
  "removed": 150,
  "message": "Removed 150 errors older than 30 days"
}
```

**Use Cases:**
- Regular maintenance to control storage usage
- Compliance with data retention policies
- Manual cleanup after resolving issues

**Example Request:**

```bash
# Remove errors older than 7 days
curl -X DELETE http://localhost:8000/event-errors/cleanup?days=7

# Remove errors older than 90 days
curl -X DELETE http://localhost:8000/event-errors/cleanup?days=90
```

## Error Response Format

All error responses follow the standardized Gleitzeit error format:

```json
{
  "error": {
    "code": -29001,
    "message": "Event error persistence not available",
    "data": {
      "suggestion": "Event error persistence may be disabled or not initialized"
    }
  },
  "request_id": "req-abc123"
}
```

## Integration with System Status

The main `/status` endpoint now includes event error information:

```json
{
  "status": "running",
  "version": "0.0.5",
  "providers": {...},
  "persistence_backend": "UnifiedRedisAdapter",
  "task_statistics": {...},
  "uptime_seconds": 3600,
  "event_errors_enabled": true,
  "event_error_count": 42
}
```

Fields:
- `event_errors_enabled`: Whether event error persistence is active
- `event_error_count`: Number of errors in current session (up to last 1000)

## Configuration

Event error persistence is configured during client initialization:

```python
client = await GleitzeitClient.create(
    config={
        'persist_event_errors': True,  # Enable error persistence (default: True)
        'enable_distributed_events': True,  # Enable distributed events
        'retention_days': 30  # How long to keep errors
    }
)
```

Environment variables:
```bash
# Enable distributed events (uses Redis pub/sub)
export GLEITZEIT_ENABLE_DISTRIBUTED_EVENTS=true

# Configure persistence type
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0
```

## Use Cases

### Debugging Handler Failures

When a handler fails, use these endpoints to:

1. Check statistics to see if it's a pattern
2. List recent errors to identify the failing handler
3. Get specific error details including traceback
4. Fix the issue and clean up old errors

```bash
# 1. Check overall statistics
curl http://localhost:8000/event-errors/stats

# 2. List errors from the problematic handler
curl "http://localhost:8000/event-errors?handler_name=TaskCompletedHandler&limit=5"

# 3. Get full details of a specific error
curl http://localhost:8000/event-errors/550e8400-e29b-41d4-a716-446655440000

# 4. After fixing, clean up old errors
curl -X DELETE http://localhost:8000/event-errors/cleanup?days=1
```

### Monitoring in Production

Set up monitoring by periodically checking:

```bash
# Check if errors are increasing
curl http://localhost:8000/event-errors/stats

# Alert if error count exceeds threshold
ERROR_COUNT=$(curl -s http://localhost:8000/status | jq .event_error_count)
if [ $ERROR_COUNT -gt 100 ]; then
  echo "ALERT: High error count: $ERROR_COUNT"
fi
```

### Compliance and Audit

For compliance requirements:

1. Errors are automatically persisted with full context
2. Retention period is configurable
3. Cleanup endpoint ensures data doesn't persist beyond retention
4. All errors include timestamps and tracebacks for audit trails

## Performance Considerations

- **Listing errors**: Limited to 1000 results maximum
- **Statistics**: Calculated from last 1000 errors
- **Storage**: Errors use the same persistence backend as tasks
- **Cleanup**: Runs asynchronously, may take time for large datasets

## Security Notes

- Error tracebacks may contain sensitive information
- Consider authentication requirements for production
- Filter results carefully when exposing to end users
- Traceback information should only be available to administrators

## Related Documentation

- [Event-Aware Architecture](../EVENT_AWARE_ARCHITECTURE.md)
- [Error Handling](../error-handling-fix.md)
- [API Error Responses](./error_responses.md)