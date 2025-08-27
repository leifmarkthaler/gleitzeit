# Gleitzeit API Endpoints Documentation

## Overview

The Gleitzeit API provides comprehensive REST endpoints for workflow orchestration, task management, monitoring, and system administration. All endpoints follow RESTful conventions and return JSON responses.

## Base URL

```
http://localhost:8000
```

## Authentication

Gleitzeit supports two authentication modes:

### Basic Mode (Default)
No authentication required. All requests are automatically authenticated as a basic user with core permissions.

### Admin Mode
When enabled via `GLEITZEIT_AUTH_MODE=admin`, requires authentication using:
- JWT tokens (via login endpoint)
- API keys (Bearer tokens)
- Session cookies

See the authentication endpoints section for login and token management.

## Core Endpoints

### System Status

#### Health Check
```http
GET /health
```
Returns the health status of the API server.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-08-26T17:37:52.122317"
}
```

#### System Status
```http
GET /status
```
Returns comprehensive system status information.

#### System Statistics
```http
GET /statistics/system
```
Returns overall system statistics including uptime, task stats, and queue information.

**Response:**
```json
{
  "tasks": {
    "queued": 3,
    "completed": 6,
    "failed": 1
  },
  "queues": {
    "total_queues": 1,
    "queues": {
      "default": {
        "size": 0,
        "processing": 0
      }
    }
  },
  "uptime_seconds": 123.45
}
```

### Task Management

#### Submit Task
```http
POST /tasks
```
Submit a new task for execution.

**Request Body:**
```json
{
  "id": "optional-task-id",
  "name": "Task Name",
  "protocol": "python/v1",
  "method": "python/execute",
  "params": {
    "file": "/path/to/script.py"
  },
  "priority": "normal",
  "retry": {
    "max_attempts": 3,
    "initial_delay": 1.0
  }
}
```

#### Get Task
```http
GET /tasks/{task_id}
```
Retrieve details of a specific task.

#### List Tasks
```http
GET /tasks
```
List all tasks with optional filtering.

**Query Parameters:**
- `status`: Filter by status (pending, running, completed, failed)
- `workflow_id`: Filter by workflow
- `limit`: Maximum number of results (default: 100)
- `offset`: Pagination offset

#### Delete Task
```http
DELETE /tasks/{task_id}
```
Delete a task (only if completed or failed).

#### Get Task Logs
```http
GET /tasks/{task_id}/logs
```
Retrieve execution logs for a task.

**Query Parameters:**
- `tail`: Number of lines to return (default: 50)
- `level`: Minimum log level (debug, info, warning, error)

#### Get Task Result
```http
GET /tasks/{task_id}/result
```
Retrieve the result of a completed task.

### Task Control (New)

#### Cancel Task
```http
POST /tasks/{task_id}/cancel
```
Cancel a queued or pending task. Returns an error if the task is already executing or completed.

**Response:**
```json
{
  "message": "Task {task_id} cancelled successfully"
}
```

#### Retry Task
```http
POST /tasks/{task_id}/retry
```
Retry a failed or cancelled task with the same parameters.

**Response:**
```json
{
  "message": "Task {task_id} retried",
  "new_task_id": "new-task-id",
  "status": "submitted"
}
```

### Workflow Management

#### Submit Workflow
```http
POST /workflows
```
Submit a new workflow from YAML/JSON definition.

**Request Body:**
```json
{
  "id": "optional-workflow-id",
  "name": "Workflow Name",
  "description": "Workflow description",
  "tasks": [
    {
      "id": "task1",
      "name": "First Task",
      "protocol": "python/v1",
      "method": "python/execute",
      "params": {...}
    }
  ]
}
```

#### Upload Workflow File
```http
POST /workflows/upload
```
Upload a workflow YAML file.

**Form Data:**
- `file`: YAML file containing workflow definition

#### Get Workflow
```http
GET /workflows/{workflow_id}
```
Retrieve workflow details.

#### List Workflows
```http
GET /workflows
```
List all workflows.

#### Delete Workflow
```http
DELETE /workflows/{workflow_id}
```
Delete a workflow and its tasks.

#### Get Workflow Tasks
```http
GET /workflows/{workflow_id}/tasks
```
List all tasks in a workflow.

#### Get Workflow Timeline
```http
GET /workflows/{workflow_id}/timeline
```
Get execution timeline for workflow visualization.

#### Get Workflow Results
```http
GET /workflows/{workflow_id}/results
```
Get aggregated results from all workflow tasks.

### Workflow Control (New)

#### Pause Workflow
```http
POST /workflows/{workflow_id}/pause
```
Pause a running workflow. Cancels all pending tasks.

**Response:**
```json
{
  "message": "Workflow {workflow_id} paused",
  "cancelled_tasks": 5
}
```

#### Resume Workflow
```http
POST /workflows/{workflow_id}/resume
```
Resume a paused workflow. Resubmits cancelled tasks.

**Response:**
```json
{
  "message": "Workflow {workflow_id} resumed",
  "resubmitted_tasks": 5
}
```

#### Retry Workflow
```http
POST /workflows/{workflow_id}/retry
```
Retry all failed tasks in a workflow.

**Response:**
```json
{
  "message": "Retried 3 failed tasks in workflow {workflow_id}",
  "retried_tasks": [
    {
      "old_task_id": "task-1",
      "new_task_id": "task-1-retry"
    }
  ]
}
```

### Queue Management (New)

#### List Queues
```http
GET /queues
```
List all task queues and their statistics.

**Response:**
```json
{
  "total_queues": 1,
  "queues": {
    "default": {
      "size": 10,
      "processing": 2,
      "pending": 8,
      "priority_distribution": {
        "high": 1,
        "normal": 7,
        "low": 2
      }
    }
  }
}
```

#### Get Queue Details
```http
GET /queues/{queue_name}
```
Get detailed statistics for a specific queue.

### Statistics (New)

#### Task Statistics
```http
GET /statistics/tasks
```
Get task execution statistics.

**Response:**
```json
{
  "total": 100,
  "pending": 5,
  "running": 2,
  "completed": 90,
  "failed": 3,
  "cancelled": 0
}
```

### Data Management (New)

#### Cleanup Old Data
```http
DELETE /cleanup?days=30
```
Clean up data older than specified days.

**Query Parameters:**
- `days`: Number of days to retain (default: 30)

**Response:**
```json
{
  "message": "Cleaned up data older than 30 days",
  "items_deleted": 150
}
```

### Real-time Streaming

#### Stream Task Logs
```websocket
WS /ws/logs/task/{task_id}
```
WebSocket endpoint for real-time log streaming for a specific task.

**Message Types:**
- `log:subscribed` - Subscription confirmation
- `log:history` - Historical log entries
- `log:message` - Real-time log entry
- `log:stream_start` - Stream started
- `log:stream_end` - Stream ended

#### Stream Workflow Logs
```websocket
WS /ws/logs/workflow/{workflow_id}
```
WebSocket endpoint for real-time log streaming for all tasks in a workflow.

#### Stream Global Logs
```websocket
WS /ws/logs
```
WebSocket endpoint for global log streaming (all tasks and workflows).

### Advanced Features

#### Batch Processing
```http
POST /batch
```
Submit multiple tasks for batch processing.

**Request Body:**
```json
{
  "batch_id": "optional-batch-id",
  "tasks": [
    {
      "name": "Task 1",
      "protocol": "python/v1",
      "method": "python/execute",
      "params": {...}
    }
  ],
  "parallel": true,
  "max_concurrent": 5
}
```

#### Chat Interface
```http
POST /chat
```
LLM chat interface for natural language task creation.

**Request Body:**
```json
{
  "message": "Run a Python script that prints hello world",
  "model": "llama2",
  "temperature": 0.7
}
```

### Provider Management

#### List Providers
```http
GET /providers
```
List all registered protocol providers.

#### List Protocols
```http
GET /protocols
```
List all available protocols.

### Log Management

#### Query System Logs
```http
GET /logs
```
Query all system logs with filtering and pagination support.

**Query Parameters:**
- `level` (string): Filter by log level
- `source` (string): Filter by source
- `task_id` (string): Filter by task ID
- `workflow_id` (string): Filter by workflow ID
- `since` (datetime): Logs since timestamp
- `until` (datetime): Logs until timestamp
- `limit` (integer, default: 100): Maximum logs to return
- `offset` (integer, default: 0): Pagination offset

#### Search Logs
```http
GET /logs/search
```
Search logs by text content across all tasks and workflows.

**Query Parameters:**
- `query` (string, required): Search query text
- `task_id` (string): Filter by task ID
- `workflow_id` (string): Filter by workflow ID
- `level` (string): Minimum log level
- `limit` (integer, default: 50): Maximum results

#### Get Log Statistics
```http
GET /logs/stats
```
Get aggregated statistics about system logs.

#### Clean Up Old Logs
```http
DELETE /logs/cleanup
```
Remove logs older than specified retention period.

**Query Parameters:**
- `days` (integer, default: 30): Delete logs older than N days
- `level` (string): Only delete logs of this level or lower

#### Get/Update Retention Settings
```http
GET /logs/retention
PUT /logs/retention
```
Manage log retention configuration.

#### Tail Task Logs
```http
GET /logs/tail/{task_id}
```
Get the most recent logs for a specific task.

### Audit Logs

#### Get Audit Logs
```http
GET /audit-logs
```
Retrieve audit logs for user actions and system events. Requires `system:read` permission.

**Query Parameters:**
- `user_id` (string): Filter by user ID
- `action` (string): Filter by action type
- `resource_type` (string): Filter by resource type
- `since` (datetime): Actions since timestamp
- `skip` (integer): Pagination offset
- `limit` (integer): Maximum results

### Event Error Management

#### List Event Errors
```http
GET /event-errors
```
Retrieve persisted event handler errors for debugging and monitoring.

**Query Parameters:**
- `limit` (integer, 1-1000, default: 100): Maximum errors to return
- `event_type` (string): Filter by event type
- `handler_name` (string): Filter by handler name  
- `since` (datetime): Return errors since timestamp

**Response:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "handler_name": "TaskCompletedHandler",
    "event_type": "TASK_COMPLETED",
    "event_id": "evt-123",
    "error_type": "ValueError",
    "error_message": "Task status invalid for completion",
    "error_traceback": "Traceback (most recent call last)...",
    "timestamp": "2024-01-15T10:30:00Z",
    "metadata": {"task_id": "task-456"}
  }
]
```

#### Get Error Statistics
```http
GET /event-errors/stats
```
Returns aggregated statistics about event handler errors.

**Response:**
```json
{
  "total_errors": 42,
  "handlers_with_errors": [
    ["TaskCompletedHandler", 25],
    ["WorkflowHandler", 10]
  ],
  "event_types_with_errors": [
    ["TASK_COMPLETED", 20],
    ["TASK_FAILED", 15]
  ],
  "oldest_error": "2024-01-01T00:00:00Z",
  "newest_error": "2024-01-15T14:30:00Z"
}
```

#### Get Specific Error
```http
GET /event-errors/{error_id}
```
Retrieve detailed information about a specific event error.

**Path Parameters:**
- `error_id` (string): Event error identifier

#### Clean Up Old Errors
```http
DELETE /event-errors/cleanup
```
Remove event errors older than specified retention period.

**Query Parameters:**
- `days` (integer, 1-365, default: 30): Delete errors older than this many days

**Response:**
```json
{
  "success": true,
  "removed": 150,
  "message": "Removed 150 errors older than 30 days"
}
```

## Response Codes

| Code | Description |
|------|-------------|
| 200  | Success |
| 201  | Created |
| 400  | Bad Request - Invalid parameters |
| 404  | Not Found - Resource doesn't exist |
| 409  | Conflict - Resource already exists |
| 500  | Internal Server Error |
| 503  | Service Unavailable - System not initialized |

## Error Response Format

All errors follow a consistent format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

## Rate Limiting

Currently no rate limiting is implemented.

## Versioning

The API is currently at version 1.0 (implicit, no version in URL).

## Examples

### Submit and Monitor a Task

```bash
# Submit a task
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Example Task",
    "protocol": "python/v1",
    "method": "python/execute",
    "params": {
      "code": "print(\"Hello, World!\")"
    }
  }'

# Response: {"task_id": "abc-123", "status": "submitted"}

# Check task status
curl http://localhost:8000/tasks/abc-123

# Get task logs
curl http://localhost:8000/tasks/abc-123/logs

# If task fails, retry it
curl -X POST http://localhost:8000/tasks/abc-123/retry
```

### Stream Logs via WebSocket

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/logs/task/abc-123');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'log:message') {
    console.log(`[${data.data.level}] ${data.data.message}`);
  }
};
```

## Migration from Previous Version

The following endpoints are new in this version:
- Task control: `/tasks/{id}/cancel`, `/tasks/{id}/retry`
- Workflow control: `/workflows/{id}/pause`, `/workflows/{id}/resume`, `/workflows/{id}/retry`
- Queue management: `/queues`, `/queues/{name}`
- Statistics: `/statistics/tasks`, `/statistics/system`
- Data management: `/cleanup`
- Log streaming: WebSocket endpoints for real-time logs
- Log management: `/logs`, `/logs/search`, `/logs/stats`, `/logs/cleanup`, `/logs/retention`, `/logs/tail/{id}`
- Event error management: `/event-errors`, `/event-errors/stats`, `/event-errors/{id}`, `/event-errors/cleanup`
- Audit logs: `/audit-logs` (now functional)

All existing endpoints remain backward compatible.