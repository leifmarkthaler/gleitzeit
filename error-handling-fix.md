# Error Handling Improvements for Gleitzeit v0.0.6

## Executive Summary

This document outlines critical error handling improvements needed in Gleitzeit to enhance stability, debuggability, and user experience. Based on extensive testing and implementation work, these fixes would significantly improve the library's production readiness.

**Update (2025-08-27)**: Priority 1 and 2 issues have been completed. See [Implementation Status](#implementation-status) section for details on how each issue was resolved.

## Priority 1: Critical Issues (Blocking Production)

### 1. Circular Import Issues ✅ COMPLETED

**Problem**: Authentication modules cause circular imports when imported at module level.

**Status**: ✅ Already fixed in codebase

**How it was fixed**:
- Authentication imports are now conditional based on `GLEITZEIT_AUTH_ENABLED` environment variable
- Located in `src/gleitzeit/api/main.py` lines 160-175
- Auth imports only happen when authentication is explicitly enabled
- Graceful fallback if auth modules fail to import

**Current Implementation**:
```python
# src/gleitzeit/api/main.py
if os.getenv("GLEITZEIT_AUTH_ENABLED", "false").lower() == "true":
    try:
        from gleitzeit.auth.middleware import AuthMiddleware
        from gleitzeit.auth.permissions import require_permission, require_role, Permissions
        app.add_middleware(AuthMiddleware)
    except ImportError as e:
        logger.warning(f"Auth module import failed: {e}")
```

**Impact**: Application starts successfully regardless of auth module availability

### 2. Database Column Name Conflicts ✅ COMPLETED

**Problem**: SQLAlchemy reserves 'metadata' as an attribute name.

**Status**: ✅ Already fixed in codebase

**How it was fixed**:
- All SQLAlchemy models now use different attribute names while keeping 'metadata' as the column name
- Pattern: `attribute_name = Column('metadata', Text)`
- Fixed in both `unified_sqlalchemy.py` and `unified_sql_backend.py`

**Current Implementation**:
```python
# src/gleitzeit/persistence/unified_sqlalchemy.py
task_metadata = Column('metadata', Text)  # Line 63
workflow_metadata = Column('metadata', Text)  # Line 99
log_metadata = Column('metadata', Text)  # Line 220
```

**Impact**: SQL persistence works correctly without attribute conflicts

### 3. Missing Error Context in Task Failures ✅ COMPLETED

**Problem**: When tasks fail, the error message lacks context about which task and why.

**Status**: ✅ Fixed on 2025-08-27

**How it was fixed**:
- Enhanced `GleitzeitError` base class with new methods:
  - `to_context_dict()`: Returns comprehensive error context including traceback
  - `to_json_string()`: Serializes error context as JSON for storage
- Updated `execution_engine.py` to use enriched error context:
  - Lines 834-874: Captures full error context in metadata
  - Lines 537-554: Creates structured TaskError for unhandled exceptions
- Integrated with existing log collector for rich error logging

**Implementation Details**:
```python
# src/gleitzeit/core/errors.py (lines 160-206)
def to_context_dict(self) -> Dict[str, Any]:
    """Get comprehensive error context for logging and debugging."""
    context = {
        "code": self.code.value,
        "code_name": self.code.name,
        "message": self.message,
        "type": type(self).__name__,
        "data": self.data,
        "traceback": traceback.format_exc() if available
    }
    return context

# src/gleitzeit/core/execution_engine.py
task.error_message = task_error.to_json_string()  # Full context as JSON
```

**Impact**: Task failures now include full stack traces, error codes, and contextual information

## Priority 2: High-Impact Issues

### 4. Race Conditions in Task Queue ✅ COMPLETED

**Problem**: Multiple workers can pick up the same task.

**Status**: ✅ Fixed on 2025-08-27

**How it was fixed**:
- Added `acquire_next_queued_task()` method to `UnifiedPersistenceAdapter` interface
- Implemented atomic task acquisition for each backend:
  - **Redis**: Lua script for atomic find-check-update (lines 844-968 in `unified_redis.py`)
  - **SQL**: SELECT FOR UPDATE with row locking (lines 1178-1250 in `unified_sqlalchemy.py`)
  - **Memory**: AsyncIO locks for thread safety
- Updated `TaskQueue.dequeue()` to use atomic acquisition when available

**Implementation Details**:
```python
# src/gleitzeit/persistence/unified_persistence.py (lines 145-164)
async def acquire_next_queued_task(self, check_dependencies: bool = True) -> Optional[Task]:
    """Atomically acquire the next queued task and mark it as EXECUTING."""
    
# Redis implementation uses Lua script for atomicity
# SQL implementation uses SELECT FOR UPDATE:
query = (
    select(DBTask)
    .where(DBTask.status == 'queued')
    .order_by(priority_order, DBTask.created_at)
    .with_for_update(skip_locked=True)  # Skip locked rows
)

# src/gleitzeit/task_queue/task_queue.py (lines 131-136)
if hasattr(self.persistence, 'acquire_next_queued_task'):
    task = await self.persistence.acquire_next_queued_task(check_dependencies)
```

**Impact**: Eliminates race conditions in multi-worker environments

### 5. WebSocket Store Reference Bugs ✅ COMPLETED

**Problem**: WebSocket code references non-existent stores.

**Status**: ✅ Already fixed in codebase

**How it was fixed**:
- WebSocket routes properly import stores from their respective modules
- `_ui_tasks` defined in `src/gleitzeit/ui/api/routes/tasks.py` (line 17)
- `_ui_workflows` defined in `src/gleitzeit/ui/api/routes/workflows.py` (line 22)
- WebSocket imports these correctly in `websocket.py` (lines 173-174)

**Current Implementation**:
```python
# src/gleitzeit/ui/api/routes/websocket.py
from .tasks import _ui_tasks
from .workflows import _ui_workflows
```

**Impact**: WebSocket functionality works correctly without import errors

### 6. Missing Dependency Installation Checks ✅ COMPLETED

**Problem**: Optional dependencies (JWT, bcrypt) fail silently.

**Status**: ✅ Fixed on 2025-08-27

**How it was fixed**:
- Created comprehensive dependency checking module: `src/gleitzeit/core/dependency_check.py`
- Added checks for auth (PyJWT, bcrypt, passlib), Redis, and UI dependencies
- Integrated checks into API startup (`api/main.py` lines 160-167)
- Integrated checks into CLI serve command (`cli/gleitzeit_cli.py` lines 1087-1107)
- Provides clear error messages with installation instructions

**Implementation Details**:
```python
# src/gleitzeit/core/dependency_check.py
def check_auth_dependencies() -> Tuple[bool, Optional[str]]:
    """Check if authentication dependencies are installed."""
    missing = []
    for package in ['jwt', 'bcrypt', 'passlib']:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        error_msg = f"Missing packages: {missing}\nInstall with: pip install gleitzeit[auth]"
        return False, error_msg
    return True, None

# src/gleitzeit/api/main.py
if os.getenv("GLEITZEIT_AUTH_ENABLED", "false").lower() == "true":
    auth_deps_ok, auth_error_msg = check_auth_dependencies()
    if not auth_deps_ok:
        logger.error(f"Authentication dependencies check failed: {auth_error_msg}")
        raise ImportError(auth_error_msg)
```

**Impact**: Clear error messages when dependencies are missing, preventing silent failures

## Priority 3: User Experience Issues

### 7. Unclear Error Messages

**Current**:
```
Internal Server Error
```

**Improved**:
```python
class DetailedHTTPException(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str = None, context: dict = None):
        super().__init__(status_code, detail)
        self.error_code = error_code
        self.context = context or {}
    
    def to_dict(self):
        return {
            "error": {
                "message": self.detail,
                "code": self.error_code,
                "context": self.context,
                "timestamp": datetime.utcnow().isoformat()
            }
        }

# Usage
raise DetailedHTTPException(
    status_code=400,
    detail="Workflow submission failed",
    error_code="WORKFLOW_INVALID",
    context={"missing_fields": ["tasks"], "workflow_id": workflow_id}
)
```

### 8. Persistence Connection Failures ✅ COMPLETED

**Problem**: No graceful fallback when Redis/SQL unavailable.

**Status**: ✅ Already implemented in codebase

**How it was implemented**:
- Full automatic fallback chain in `src/gleitzeit/persistence/factory.py`
- Fallback sequence: Redis → SQL → In-Memory
- Connection testing before selecting backend (lines 164-167)
- Configurable via `GLEITZEIT_PERSISTENCE_TYPE=auto` environment variable
- Graceful warnings logged during fallback

**Current Implementation**:
```python
# src/gleitzeit/persistence/factory.py (lines 118-131)
elif persistence_type == PersistenceType.AUTO:
    # Try Redis first
    adapter = await cls._try_redis(redis_url, final_config, event_bus)
    if adapter:
        return adapter
    
    # Fall back to SQL
    adapter = await cls._try_sql(sql_connection, sql_db_path, final_config, event_bus)
    if adapter:
        return adapter
    
    # Final fallback to in-memory
    logger.warning("Redis and SQL both failed, using in-memory persistence")
    return await cls._create_memory(final_config, event_bus)
```

**Impact**: System remains operational even when primary persistence backends fail

### 9. Task Timeout Handling ✅ COMPLETED

**Problem**: Tasks can hang indefinitely.

**Status**: ✅ Already implemented in codebase

**How it was implemented**:
- Task model includes optional timeout field (1-3600 seconds)
- ExecutionEngine has configurable default timeout (300 seconds)
- Applied via `asyncio.wait_for` in task execution
- Proper TaskTimeoutError handling with error codes

**Current Implementation**:
```python
# src/gleitzeit/core/models.py (line 84-85)
timeout: Optional[int] = Field(None, ge=1, le=3600,
                              description="Execution timeout in seconds")

# src/gleitzeit/core/execution_engine.py (lines 1151-1160)
try:
    task_result = await asyncio.wait_for(
        self.pooling_adapter.execute_task(task),
        timeout=float(self.task_timeout)  # Configurable task timeout
    )
except asyncio.TimeoutError:
    raise TaskError(
        message=f"Task execution timed out after {self.task_timeout} seconds",
        code=ErrorCode.TASK_EXECUTION_FAILED,
        task_id=task.id
    )
```

**Features**:
- Per-task configurable timeout
- Default timeout of 300 seconds (5 minutes)
- Maximum timeout of 3600 seconds (1 hour) for tasks
- Proper error handling and reporting

**Impact**: Tasks cannot hang indefinitely, improving system reliability

## Priority 4: Debugging Improvements

### 10. Insufficient Logging

**Problem**: Critical operations lack logging.

**Proposed Enhancement**:
```python
class LoggingMixin:
    """Mixin to add structured logging to any class"""
    
    def log_operation(self, operation: str, **context):
        logger.info(
            f"{self.__class__.__name__}.{operation}",
            extra={
                "component": self.__class__.__name__,
                "operation": operation,
                **context
            }
        )
    
    def log_error(self, operation: str, error: Exception, **context):
        logger.error(
            f"{self.__class__.__name__}.{operation} failed: {error}",
            extra={
                "component": self.__class__.__name__,
                "operation": operation,
                "error_type": type(error).__name__,
                "error_message": str(error),
                **context
            },
            exc_info=True
        )

# Usage
class TaskQueue(LoggingMixin):
    async def enqueue(self, task: Task):
        self.log_operation("enqueue", task_id=task.id, priority=task.priority)
        try:
            # ... enqueue logic ...
        except Exception as e:
            self.log_error("enqueue", e, task_id=task.id)
            raise
```

### 11. Event Bus Error Handling

**Problem**: Event handler exceptions can crash the system.

**Proposed Fix**:
```python
class EventBus:
    async def emit(self, event: Event):
        handlers = self._handlers.get(event.type, [])
        
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"Event handler failed for {event.type}",
                    extra={
                        "event_type": event.type,
                        "handler": handler.__name__,
                        "error": str(e)
                    },
                    exc_info=True
                )
                # Continue processing other handlers
                # Optionally emit an error event
                if event.type != EventType.HANDLER_ERROR:
                    await self.emit(Event(
                        type=EventType.HANDLER_ERROR,
                        data={
                            "original_event": event.type,
                            "handler": handler.__name__,
                            "error": str(e)
                        }
                    ))
```

## Implementation Plan

### Phase 1: Critical Fixes (Week 1) ✅ COMPLETED
- [x] Fix circular imports - Already fixed with conditional imports
- [x] Resolve database column conflicts - Already fixed with attribute renaming
- [x] Add proper error context to task failures - Enhanced error classes with full context

### Phase 2: Stability Improvements (Week 2) ✅ COMPLETED
- [x] Implement atomic queue operations - Added atomic task acquisition for all backends
- [x] Add dependency checks - Comprehensive dependency checking system
- [x] Fix WebSocket store references - Already fixed with proper imports

### Phase 3: Resilience (Week 3) - PARTIALLY COMPLETED
- [x] Add persistence fallback mechanisms - Already implemented with auto fallback
- [x] Implement task timeouts - Already implemented with configurable timeouts
- [ ] Enhance event bus error handling

### Phase 4: Observability (Week 4)
- [ ] Add structured logging
- [ ] Implement error tracking
- [ ] Add debugging utilities

## Testing Strategy

### Unit Tests
```python
# test_error_handling.py
import pytest
from gleitzeit.core.errors import DetailedHTTPException

def test_detailed_exception():
    exc = DetailedHTTPException(
        status_code=400,
        detail="Test error",
        error_code="TEST_001",
        context={"field": "value"}
    )
    
    assert exc.status_code == 400
    assert exc.error_code == "TEST_001"
    assert "field" in exc.context
```

### Integration Tests
```python
# test_persistence_fallback.py
def test_persistence_fallback_chain():
    # Mock Redis connection failure
    with patch('redis.Redis.ping', side_effect=ConnectionError):
        # Mock SQL connection failure
        with patch('sqlalchemy.create_engine', side_effect=Exception):
            persistence = PersistenceFactory.create_with_fallback()
            assert isinstance(persistence, InMemoryPersistence)
```

### Chaos Testing
```python
# chaos_test.py
async def test_random_failures():
    """Inject random failures to test resilience"""
    
    chaos_config = {
        "network_failure_rate": 0.1,
        "task_timeout_rate": 0.05,
        "memory_pressure": True
    }
    
    system = GleitzeitSystem(chaos_mode=chaos_config)
    
    # Submit 100 workflows
    workflows = [create_test_workflow() for _ in range(100)]
    results = await system.execute_all(workflows)
    
    # System should handle at least 90% successfully
    success_rate = sum(1 for r in results if r.success) / len(results)
    assert success_rate >= 0.9
```

## Monitoring & Alerts

### Key Metrics to Track

```python
# metrics.py
class ErrorMetrics:
    def __init__(self):
        self.counters = {
            "task_failures": 0,
            "timeout_errors": 0,
            "connection_errors": 0,
            "validation_errors": 0
        }
        
    def record_error(self, error_type: str):
        self.counters[error_type] += 1
        
        # Alert if error rate is too high
        if self.get_error_rate(error_type) > 0.1:  # 10% error rate
            self.send_alert(
                f"High {error_type} rate: {self.get_error_rate(error_type):.2%}"
            )
```

### Alert Conditions

1. **Task failure rate > 10%**
2. **Queue depth > 1000 tasks**
3. **Persistence connection failures**
4. **Memory usage > 80%**
5. **Event bus handler errors**

## Expected Outcomes

### Before
- Cryptic error messages
- System crashes on edge cases
- Difficult debugging
- Silent failures

### After
- Clear, actionable error messages
- Graceful degradation
- Comprehensive logging
- Self-healing capabilities
- Better observability

## Success Metrics

- **50% reduction** in production incidents
- **75% faster** issue diagnosis
- **90% uptime** even with component failures
- **100% error traceability** with context

## Implementation Status

### Completed Fixes (Updated 2025-08-27)

Priority 1, 2, and partial Priority 3 issues have been successfully resolved:

**Priority 1 - Critical Issues:**
1. **Circular Import Issues** ✅
   - Already fixed with conditional imports
   - Auth modules only loaded when explicitly enabled
   
2. **Database Column Conflicts** ✅
   - Already resolved with attribute renaming pattern
   - Uses `attribute_name = Column('metadata', Text)`
   
3. **Enhanced Error Context** ✅
   - Added `to_context_dict()` and `to_json_string()` methods to GleitzeitError
   - Integrated with log collector for rich error logging
   - Task failures now include full stack traces and context

**Priority 2 - High-Impact Issues:**
4. **Race Condition Fix** ✅
   - Implemented atomic task acquisition across all backends
   - Redis: Lua scripts for atomicity
   - SQL: SELECT FOR UPDATE row locking
   - Backwards compatible with existing code
   
5. **WebSocket Store References** ✅
   - Already fixed with proper module imports
   - Stores correctly defined and imported
   
6. **Dependency Checks** ✅
   - Created comprehensive dependency checking system
   - Clear error messages with installation instructions
   - Integrated into both API and CLI entry points

**Priority 3 - User Experience Issues:**
7. **Unclear Error Messages** ❌ - Still using basic HTTPException in API

8. **Persistence Connection Failures** ✅
   - Already implemented with automatic fallback chain
   - Redis → SQL → In-Memory fallback sequence
   - Connection testing and graceful degradation
   
9. **Task Timeout Handling** ✅
   - Already implemented with configurable timeouts
   - Per-task timeout configuration
   - Default 300 seconds, max 3600 seconds

### Files Modified/Created

- `src/gleitzeit/core/errors.py` - Enhanced with context methods
- `src/gleitzeit/core/execution_engine.py` - Updated error handling
- `src/gleitzeit/persistence/unified_persistence.py` - Added atomic interface
- `src/gleitzeit/persistence/unified_redis.py` - Implemented atomic acquisition
- `src/gleitzeit/persistence/unified_sqlalchemy.py` - Implemented atomic acquisition
- `src/gleitzeit/task_queue/task_queue.py` - Updated to use atomic methods
- `src/gleitzeit/core/dependency_check.py` - New dependency checking module
- `src/gleitzeit/api/main.py` - Added dependency checks
- `src/gleitzeit/cli/gleitzeit_cli.py` - Added dependency checks

### Remaining Work

The following issues remain for future implementation:

**Priority 3:**
- **Unclear Error Messages** (#7) - API needs structured error responses with codes and context

**Priority 4:**
- **Insufficient Logging** (#10) - Could benefit from structured logging mixin
- **Event Bus Error Handling** (#11) - Event handlers need error isolation

## Conclusion

The error handling audit revealed that Gleitzeit already has robust error handling in many areas. Out of 11 identified issues:

**Already Implemented (8/11):**
- ✅ All Priority 1 issues (3/3)
- ✅ All Priority 2 issues (3/3) 
- ✅ Most Priority 3 issues (2/3)
- ❌ Priority 4 issues remain (0/2)

**Key Findings:**
- The codebase already includes sophisticated features like automatic persistence fallback and task timeout handling
- Atomic operations prevent race conditions across all backend types
- Rich error context is captured and logged throughout the system
- The unified backend architecture provides excellent resilience

**Remaining Improvements:**
Only 3 enhancements remain, all non-critical:
1. Structured HTTP error responses for better API UX
2. Enhanced structured logging for easier debugging
3. Isolated error handling in event bus handlers

The system demonstrates production-ready error handling with comprehensive fallback mechanisms, timeout protection, and detailed error tracking. The remaining improvements would enhance developer experience but are not blocking production use.