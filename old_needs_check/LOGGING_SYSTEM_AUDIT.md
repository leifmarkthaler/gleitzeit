# Gleitzeit Logging System Audit

**Date:** 2025-09-30
**Version:** 0.0.7

## Executive Summary

The Gleitzeit logging system has **partially implemented** structured logging infrastructure but lacks **centralized error/audit log collection** and **persistent storage** to Redis. The API endpoints exist but return empty results because no logs are being stored in Redis.

---

## Current State

### 1. Logging Infrastructure

#### Structured Logging Mixin (`logging_mixin.py`)
- ✅ **Exists**: Comprehensive LoggingMixin class with async/sync variants
- ✅ **Features**:
  - Structured logging with context (task_id, workflow_id, etc.)
  - Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
  - OpenTelemetry integration support
  - Fallback to Python's standard logging
- ❌ **Issue**: References `gleitzeit.core.logs.LogCollector` which was **removed** (line 14)
  - Line 16: `get_log_collector = lambda: None` - hardcoded to return None
  - This means **all logging falls back to standard Python logging**

#### File-based Logging
- ✅ **Active**: Logs directory contains ~220 log files
- ✅ **Components**: API, workers (dependency, task_execution, workflow_loader, workflow_submission)
- ❌ **No centralized aggregation**: Each component logs to separate files
- ❌ **No Redis storage**: File logs are not indexed or stored in Redis

### 2. API Endpoints

#### `/system/audit/logs` (system.py:271-288)
- ✅ **Endpoint exists** and returns 200 OK
- ❌ **Placeholder implementation**: Always returns empty array
- Returns: `{"logs": [], "total": 0, "message": "Audit logging not yet implemented"}`
- **No actual audit log storage or retrieval**

#### `/system/logs/errors` (system.py:291-318)
- ✅ **Endpoint exists** and returns 200 OK
- ✅ **Fixed**: Now uses `scan_iter()` instead of manual cursor loop
- ❌ **No error data**: Searches for Redis keys matching `*:error:*`
- ❌ **Returns empty**: No errors are being written to Redis with this pattern
- Redis check confirms: 0 keys match `*:error:*` pattern

### 3. Error Logging in Workers

Found 51 `logger.error()` / `logger.exception()` calls across 15 worker files:
- `workflow_loader_worker_v2.py`: 3 calls
- `base.py`: 4 calls
- `retry_worker.py`: 3 calls
- `task_execution_worker.py`: 4 calls
- Others: 2-7 calls each

**Issue**: These all use standard Python logging - **NOT stored to Redis**

### 4. Missing Components

#### LogCollector Service
- **Status**: Removed/disabled
- **Impact**: No centralized log collection
- **Evidence**: Line 16 in `logging_mixin.py` returns None

#### Redis Log Storage
- **No keys found** for:
  - Error logs: `*:error:*` → 0 results
  - Audit logs: `*:audit:*` → 0 results
  - Structured logs: `*:log:*` → 0 results

---

## Issues Identified

### Critical Issues

1. **No Centralized Error Logging**
   - Workers log errors via Python's logging module
   - Errors are written to individual log files only
   - No structured error data in Redis
   - API `/system/logs/errors` returns empty results

2. **Audit Logging Not Implemented**
   - Endpoint is a placeholder
   - No audit trail of user/system actions
   - No compliance/security logging

3. **Log Collector Removed**
   - `LogCollector` was removed but mixin still references it
   - All structured logging falls back to standard Python logging
   - Loses structured context (task_id, workflow_id, etc.)

### Medium Issues

4. **File-based Logs Not Searchable**
   - 220+ log files in `/logs` directory
   - No indexing or aggregation
   - Cannot query by workflow_id, task_id, error_type, etc.

5. **No Log Retention Policy**
   - Log files accumulate indefinitely
   - No rotation, archival, or cleanup

6. **Inconsistent Log Levels**
   - Workers use different logging patterns
   - No centralized log level configuration

---

## Architecture Analysis

### What Works
- ✅ File-based logging operational
- ✅ LoggingMixin provides good API for structured logging
- ✅ Workers actively logging errors/warnings
- ✅ API endpoints functional (but return no data)

### What's Missing

```
┌─────────────┐
│   Workers   │
└─────┬───────┘
      │ logger.error()
      ↓
┌─────────────────┐      ┌────────────┐
│  Python Logging │ ───→ │  Log Files │
└─────────────────┘      └────────────┘
                         (220+ files)

❌ Missing:
┌─────────────┐      ┌──────────────┐      ┌───────┐
│   Workers   │ ───→ │ LogCollector │ ───→ │ Redis │
└─────────────┘      └──────────────┘      └───────┘
                           ↑
                           │
                    ┌──────┴──────┐
                    │ API Queries │
                    └─────────────┘
```

---

## Test Results

**Client Tests**: 37/37 passed ✅

The logging endpoints **pass tests** because they return valid empty responses:
- `test_get_audit_logs`: Returns `{"logs": [], ...}` - Test passes ✅
- `test_get_error_logs`: Returns `{"errors": [], ...}` - Test passes ✅

However, they provide **no actual logging data**.

---

## Recommendations

### Immediate Fixes (Priority 1)

1. **Implement Redis Error Logging**
   - Create error handler that writes to Redis: `error:<timestamp>:<error_id>`
   - Store: error_type, message, stack_trace, workflow_id, task_id, timestamp
   - Pattern: `{shard}:error:{timestamp}:{uuid}`

2. **Implement Audit Logging**
   - Log user actions: workflow submissions, task retries, cancellations
   - Store: user, action, resource_id, timestamp, metadata
   - Pattern: `{shard}:audit:{timestamp}:{uuid}`

3. **Fix LogCollector Integration**
   - Either re-implement LogCollector service
   - OR update LoggingMixin to write directly to Redis
   - Remove placeholder `get_log_collector = lambda: None`

### Medium Priority

4. **Centralized Log Aggregation**
   - Implement log streaming from files to Redis
   - Index by workflow_id, task_id, level, component
   - TTL-based retention (e.g., 7 days)

5. **Log Querying API**
   - Enhance `/system/logs/errors` to support filtering:
     - By workflow_id, task_id, time_range
     - By error_type, severity level
   - Add `/system/logs` for general log queries

6. **Log Rotation**
   - Implement file rotation policy
   - Archive old logs (S3, etc.)
   - Clean up after upload

### Low Priority

7. **Structured Logging Enhancement**
   - Standardize log format across all workers
   - Add correlation IDs for request tracing
   - OpenTelemetry full integration

8. **Monitoring & Alerting**
   - Error rate metrics
   - Critical error notifications
   - Log volume monitoring

---

## Code Locations

### Key Files
- `src/gleitzeit/core/logging_mixin.py` - Logging infrastructure
- `src/gleitzeit/api/routes/system.py:271-318` - Log API endpoints
- `src/gleitzeit/core/logs.py` - LogCollector (removed/missing)

### Workers Using Logging
- All workers in `src/gleitzeit/workers/` (15 files, 51 error log calls)

### Log Output
- `/logs/` - 220+ log files (api, workers)

---

## Conclusion

The logging system has a **solid foundation** but is **incomplete**:

1. ✅ **API structure exists** - endpoints defined and functional
2. ✅ **Logging mixin works** - provides good abstraction
3. ❌ **No data storage** - logs go to files only, not Redis
4. ❌ **No centralized collection** - LogCollector was removed
5. ❌ **Audit logging not implemented** - placeholder only

**Impact**: Cannot query logs programmatically, no structured error tracking, no audit trail.

**Next Step**: Implement Redis-based error logging as Priority 1 fix.
