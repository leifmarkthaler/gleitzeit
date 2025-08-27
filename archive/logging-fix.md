# Logging System Fix Implementation Plan

## Overview
Address the misalignments in the logging system by exposing existing LogCollector functionality through comprehensive API endpoints.

## Issues to Fix

### Priority 1: Global Log Query Endpoints ✅
- [x] Implement `GET /logs` - Query all system logs with filtering
- [x] Implement `GET /logs/search` - Search logs across tasks/workflows
- [x] Implement `GET /logs/stats` - Get log statistics

### Priority 2: Log Management Endpoints ✅
- [x] Implement `DELETE /logs/cleanup` - Clean up old logs
- [x] Implement `GET /logs/retention` - Get retention settings
- [x] Implement `PUT /logs/retention` - Update retention settings

### Priority 3: Complete Audit Logs ✅
- [x] Complete `GET /audit-logs` implementation
- [x] Add audit log filtering and pagination

### Priority 4: Documentation ✅
- [x] Update API documentation with new endpoints
- [x] Document log retention policies
- [x] Add usage examples

## Implementation Details

### 1. Global Log Query Endpoint
**Endpoint**: `GET /logs`

**Query Parameters**:
- `level` (string): Filter by log level (DEBUG, INFO, WARNING, ERROR)
- `source` (string): Filter by log source (TASK, WORKFLOW, SYSTEM, API)
- `task_id` (string): Filter by specific task
- `workflow_id` (string): Filter by specific workflow
- `since` (datetime): Logs since timestamp
- `until` (datetime): Logs until timestamp
- `limit` (int): Maximum logs to return (default: 100, max: 1000)
- `offset` (int): Pagination offset

**Response**:
```json
{
  "logs": [
    {
      "id": "log-123",
      "timestamp": "2024-01-15T10:30:00Z",
      "level": "INFO",
      "source": "TASK",
      "message": "Task started",
      "task_id": "task-456",
      "workflow_id": "wf-789",
      "metadata": {}
    }
  ],
  "total": 500,
  "offset": 0,
  "limit": 100
}
```

### 2. Log Search Endpoint
**Endpoint**: `GET /logs/search`

**Query Parameters**:
- `query` (string): Text search in log messages
- `task_id` (string): Filter by task
- `workflow_id` (string): Filter by workflow
- `level` (string): Minimum log level
- `limit` (int): Max results (default: 50)

**Response**: Same as log query

### 3. Log Statistics Endpoint
**Endpoint**: `GET /logs/stats`

**Query Parameters**:
- `since` (datetime): Statistics since timestamp
- `until` (datetime): Statistics until timestamp
- `group_by` (string): Group by hour/day/week

**Response**:
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

### 4. Log Cleanup Endpoint
**Endpoint**: `DELETE /logs/cleanup`

**Query Parameters**:
- `days` (int): Delete logs older than N days (default: 30)
- `level` (string): Only delete logs of this level or lower

**Response**:
```json
{
  "success": true,
  "deleted": 5000,
  "message": "Deleted 5000 logs older than 30 days"
}
```

### 5. Log Retention Settings
**Endpoint**: `GET /logs/retention`

**Response**:
```json
{
  "retention_days": 30,
  "auto_cleanup": true,
  "cleanup_schedule": "daily",
  "max_logs_per_task": 10000
}
```

**Endpoint**: `PUT /logs/retention`

**Request Body**:
```json
{
  "retention_days": 60,
  "auto_cleanup": true
}
```

### 6. Complete Audit Logs
**Endpoint**: `GET /audit-logs`

**Query Parameters**:
- `user_id` (string): Filter by user
- `action` (string): Filter by action type
- `resource_type` (string): Filter by resource type
- `since` (datetime): Actions since timestamp
- `limit` (int): Max results
- `offset` (int): Pagination

**Response**:
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
      "metadata": {
        "ip_address": "192.168.1.1",
        "user_agent": "Mozilla/5.0"
      }
    }
  ],
  "total": 100,
  "offset": 0,
  "limit": 50
}
```

## Implementation Steps

1. **Create log routes module** (`api/routes/logs.py`)
   - Implement all log query and management endpoints
   - Use existing LogCollector and LogRedisAdapter

2. **Enhance LogRedisAdapter** if needed
   - Add search capability
   - Add statistics aggregation
   - Add cleanup methods

3. **Complete audit log retrieval**
   - Implement database query methods
   - Add proper filtering and pagination

4. **Add log retention configuration**
   - Store settings in persistence layer
   - Implement auto-cleanup task

5. **Update API documentation**
   - Add new endpoints to api-endpoints.md
   - Create logs.md documentation

6. **Add tests**
   - Test log querying with various filters
   - Test cleanup functionality
   - Test retention settings

## Success Criteria

- [x] All log query endpoints return correct data
- [x] Log search works across all tasks
- [x] Statistics accurately reflect log volumes
- [x] Cleanup removes old logs successfully
- [x] Audit logs are fully retrievable
- [x] Documentation is complete and accurate
- [x] System maintains backward compatibility

## Implementation Complete

All logging system fixes have been successfully implemented:

1. **Created `api/routes/logs.py`** with all planned endpoints
2. **Enhanced `LogRedisAdapter`** with:
   - `count_logs()` - Count logs matching criteria
   - `search_logs()` - Search by text content
   - `get_stats()` - Aggregate statistics
   - `cleanup_old_logs()` - Delete old logs with level filtering
3. **Completed audit logs** in `auth.py` and `auth/database.py`
4. **Registered routes** in `main.py`
5. **Created comprehensive documentation** in `docs/api/logs.md`
6. **Updated main API docs** with all new endpoints

The logging system now has full API exposure matching its robust collection capabilities.

## Timeline

1. Hour 1: Implement core log query endpoints
2. Hour 2: Add search and statistics
3. Hour 3: Implement management endpoints
4. Hour 4: Complete audit logs and documentation

## Notes

- Use existing LogCollector and persistence infrastructure
- Maintain consistency with event error endpoints pattern
- Ensure proper error handling and validation
- Consider performance implications for large log volumes
- Add appropriate authentication/authorization checks