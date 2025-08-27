# Log Management API

## Overview

The Log Management API provides comprehensive endpoints for querying, searching, and managing system logs collected by the LogCollector service. These endpoints enable monitoring, debugging, and operational control of the logging system.

## Base URL

All log endpoints are prefixed with `/logs`

## Authentication

These endpoints follow the same authentication rules as other Gleitzeit API endpoints. Some endpoints may require elevated permissions.

## Endpoints

### Query System Logs

Retrieve system logs with filtering and pagination support.

**Endpoint:** `GET /logs`

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `level` | string | No | Filter by log level (DEBUG, INFO, WARNING, ERROR) | None |
| `source` | string | No | Filter by source (TASK, WORKFLOW, SYSTEM, API) | None |
| `task_id` | string | No | Filter by specific task ID | None |
| `workflow_id` | string | No | Filter by specific workflow ID | None |
| `since` | datetime | No | Logs since timestamp | None |
| `until` | datetime | No | Logs until timestamp | None |
| `limit` | integer | No | Maximum logs to return (1-1000) | 100 |
| `offset` | integer | No | Pagination offset | 0 |

**Response:** `200 OK`

```json
{
  "logs": [
    {
      "id": "log-123",
      "timestamp": "2024-01-15T10:30:00Z",
      "level": "INFO",
      "source": "TASK",
      "message": "Task execution started",
      "task_id": "task-456",
      "workflow_id": "wf-789",
      "metadata": {
        "provider": "ollama",
        "model": "llama2"
      }
    }
  ],
  "total": 500,
  "offset": 0,
  "limit": 100
}
```

**Example Requests:**

```bash
# Get all INFO and above logs
curl http://localhost:8000/logs?level=INFO

# Get logs for a specific task
curl http://localhost:8000/logs?task_id=task-456

# Get logs from the last hour
curl "http://localhost:8000/logs?since=2024-01-15T09:00:00Z"

# Paginate through logs
curl http://localhost:8000/logs?limit=50&offset=100
```

### Search Logs

Search logs by text content across all tasks and workflows.

**Endpoint:** `GET /logs/search`

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `query` | string | Yes | Search query text | - |
| `task_id` | string | No | Filter by task ID | None |
| `workflow_id` | string | No | Filter by workflow ID | None |
| `level` | string | No | Minimum log level | None |
| `limit` | integer | No | Maximum results (1-500) | 50 |

**Response:** `200 OK`

```json
{
  "logs": [
    {
      "id": "log-789",
      "timestamp": "2024-01-15T10:35:00Z",
      "level": "ERROR",
      "source": "TASK",
      "message": "Connection timeout to provider",
      "task_id": "task-123",
      "metadata": {}
    }
  ],
  "total": 15,
  "offset": 0,
  "limit": 50
}
```

**Example Requests:**

```bash
# Search for error messages
curl http://localhost:8000/logs/search?query=error

# Search within a specific workflow
curl "http://localhost:8000/logs/search?query=timeout&workflow_id=wf-123"

# Search for warnings and above
curl "http://localhost:8000/logs/search?query=connection&level=WARNING"
```

### Get Log Statistics

Get aggregated statistics about system logs.

**Endpoint:** `GET /logs/stats`

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `since` | datetime | No | Statistics since timestamp | None |
| `until` | datetime | No | Statistics until timestamp | None |

**Response:** `200 OK`

```json
{
  "total_logs": 10000,
  "by_level": {
    "DEBUG": 3000,
    "INFO": 5000,
    "WARNING": 1500,
    "ERROR": 500
  },
  "by_source": {
    "TASK": 7000,
    "WORKFLOW": 2000,
    "SYSTEM": 800,
    "API": 200
  },
  "oldest_log": "2024-01-01T00:00:00Z",
  "newest_log": "2024-01-15T15:30:00Z",
  "storage_backend": "redis",
  "retention_days": 30
}
```

**Use Cases:**
- Monitor log volume trends
- Identify error rates
- Track system activity levels
- Capacity planning

**Example Request:**

```bash
# Get overall statistics
curl http://localhost:8000/logs/stats

# Get statistics for today
curl "http://localhost:8000/logs/stats?since=2024-01-15T00:00:00Z"
```

### Clean Up Old Logs

Remove logs older than specified retention period.

**Endpoint:** `DELETE /logs/cleanup`

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `days` | integer | No | Delete logs older than N days (1-365) | 30 |
| `level` | string | No | Only delete logs of this level or lower | None |

**Response:** `200 OK`

```json
{
  "success": true,
  "deleted": 5000,
  "message": "Deleted 5000 logs older than 30 days"
}
```

**Use Cases:**
- Regular maintenance to control storage
- Compliance with retention policies
- Free up Redis memory

**Example Requests:**

```bash
# Clean up logs older than 7 days
curl -X DELETE http://localhost:8000/logs/cleanup?days=7

# Clean up only DEBUG logs older than 1 day
curl -X DELETE "http://localhost:8000/logs/cleanup?days=1&level=DEBUG"
```

### Get Retention Settings

Get current log retention configuration.

**Endpoint:** `GET /logs/retention`

**Response:** `200 OK`

```json
{
  "retention_days": 30,
  "auto_cleanup": false,
  "cleanup_schedule": "daily",
  "max_logs_per_task": 10000
}
```

### Update Retention Settings

Update log retention configuration.

**Endpoint:** `PUT /logs/retention`

**Request Body:**

```json
{
  "retention_days": 60,
  "auto_cleanup": true,
  "cleanup_schedule": "daily",
  "max_logs_per_task": 5000
}
```

**Response:** `200 OK`

Returns the updated settings.

**Note:** This endpoint is not fully implemented and currently only returns the requested settings without persisting them.

### Tail Task Logs

Get the most recent logs for a specific task.

**Endpoint:** `GET /logs/tail/{task_id}`

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_id` | string | Yes | Task identifier |

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `lines` | integer | No | Number of recent lines (1-500) | 50 |

**Response:** `200 OK`

```json
[
  {
    "id": "log-999",
    "timestamp": "2024-01-15T15:30:00Z",
    "level": "INFO",
    "source": "TASK",
    "message": "Task completed successfully",
    "task_id": "task-456",
    "metadata": {}
  }
]
```

**Example Request:**

```bash
# Get last 100 lines for a task
curl http://localhost:8000/logs/tail/task-456?lines=100
```

## Audit Logs

### Get Audit Logs

Retrieve audit logs for user actions and system events.

**Endpoint:** `GET /audit-logs`

**Query Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `user_id` | string | No | Filter by user ID | None |
| `action` | string | No | Filter by action type | None |
| `resource_type` | string | No | Filter by resource type | None |
| `since` | datetime | No | Actions since timestamp | None |
| `skip` | integer | No | Pagination offset | 0 |
| `limit` | integer | No | Maximum results | 100 |

**Response:** `200 OK`

```json
{
  "audit_logs": [
    {
      "id": "audit-123",
      "timestamp": "2024-01-15T10:30:00Z",
      "user_id": "user-456",
      "action": "login",
      "resource_type": "session",
      "resource_id": "session-789",
      "details": null,
      "ip_address": "192.168.1.1",
      "user_agent": "Mozilla/5.0..."
    }
  ],
  "total": 42,
  "offset": 0,
  "limit": 100
}
```

**Actions Tracked:**
- `login` - User login
- `logout` - User logout
- `register` - New user registration
- `create_api_key` - API key creation
- `revoke_api_key` - API key revocation
- `change_password` - Password change

**Example Requests:**

```bash
# Get all audit logs
curl http://localhost:8000/audit-logs

# Get login/logout events
curl "http://localhost:8000/audit-logs?action=login"

# Get user-specific audit trail
curl "http://localhost:8000/audit-logs?user_id=user-456"
```

## Error Response Format

All error responses follow the standardized Gleitzeit error format:

```json
{
  "error": {
    "code": -29001,
    "message": "Log collector not available",
    "data": {
      "suggestion": "Log collection may be disabled or not initialized"
    }
  },
  "request_id": "req-abc123"
}
```

## Configuration

Log collection is configured during client initialization:

```python
client = await GleitzeitClient.create(
    config={
        'enable_logging': True,
        'log_backend': 'redis',  # or 'sql', 'memory'
        'log_retention_days': 30,
        'log_buffer_size': 100,
        'log_flush_interval': 1.0
    }
)
```

Environment variables:
```bash
# Enable Redis log backend
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0

# Configure retention
export GLEITZEIT_LOG_RETENTION_DAYS=30
```

## Storage Backends

### Redis Backend (Recommended)
- Uses Redis Streams for time-series storage
- Automatic expiration with TTL
- High performance for writes and queries
- Supports real-time streaming

### SQL Backend
- Uses relational database tables
- Better for long-term storage
- Supports complex queries
- Lower write performance

### Memory Backend
- In-memory buffer only
- No persistence
- Suitable for development/testing
- Limited by available RAM

## Use Cases

### Debugging Task Failures

When a task fails, use the log endpoints to investigate:

```bash
# 1. Get task logs
curl http://localhost:8000/logs?task_id=task-failed-123

# 2. Search for error messages
curl "http://localhost:8000/logs/search?query=error&task_id=task-failed-123"

# 3. Get the last 100 lines
curl http://localhost:8000/logs/tail/task-failed-123?lines=100
```

### Monitoring System Health

Set up monitoring by checking log statistics:

```bash
# Check error rates
STATS=$(curl -s http://localhost:8000/logs/stats)
ERROR_COUNT=$(echo $STATS | jq .by_level.ERROR)

if [ $ERROR_COUNT -gt 100 ]; then
  echo "ALERT: High error count in logs: $ERROR_COUNT"
fi
```

### Compliance and Retention

Manage log retention for compliance:

```bash
# Clean up old logs monthly
curl -X DELETE http://localhost:8000/logs/cleanup?days=90

# Verify retention settings
curl http://localhost:8000/logs/retention
```

## Performance Considerations

- **Query Performance**: Queries are optimized for Redis Streams
- **Search Performance**: Full-text search loads logs into memory
- **Storage Growth**: Logs are automatically trimmed per stream
- **Network Traffic**: Use pagination for large result sets

## Security Notes

- Log content may include sensitive information
- Consider authentication requirements for production
- Filter logs carefully when exposing to end users
- Audit logs track all authentication events

## WebSocket Streaming

For real-time log streaming, use the WebSocket endpoints:

- `/ws/logs` - Stream all logs
- `/ws/logs/task/{task_id}` - Stream task logs
- `/ws/logs/workflow/{workflow_id}` - Stream workflow logs

See the main API documentation for WebSocket details.

## Related Documentation

- [API Endpoints Overview](../api-endpoints.md)
- [Event Errors API](./event_errors.md)
- [System Architecture](../architecture.md)
- [LogCollector Design](../log-system.md)