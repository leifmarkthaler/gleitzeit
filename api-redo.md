# API Refactoring Documentation

## Overview

This document describes the complete refactoring of the Gleitzeit API from a monolithic 2,608-line file to a clean modular architecture that delegates all operations to the GleitzeitClient.

## Architecture Transformation

### Before: Monolithic API
- **Single File**: `src/gleitzeit/api/main.py` (2,608 lines)
- **89 Routes**: All defined inline in one file
- **Direct Access**: Routes directly accessed database, engine, and internal components
- **Testing Difficulty**: Hard to test individual routes
- **Maintenance Issues**: Difficult to maintain and extend

### After: Modular API
- **Modular Routes**: 4 route modules + base infrastructure
- **Client Delegation**: All routes delegate to GleitzeitClient methods
- **Clean Separation**: API is a thin layer over the client
- **Fully Tested**: 70 tests with 100% pass rate
- **Easy to Extend**: New routes simply delegate to client methods

## File Structure

### New Modular Files Created
```
src/gleitzeit/api/
├── routes/
│   ├── __init__.py        # Route module exports
│   ├── base.py            # Base infrastructure (APIRouteBase, shared client)
│   ├── workflows.py       # Workflow routes → WorkflowMixin
│   ├── tasks.py          # Task routes → TaskMixin
│   ├── admin.py          # Admin routes → AdminMixin
│   └── system.py         # System routes → SystemMixin
└── modular_main.py       # New modular FastAPI application
```

### Files to Remove
- `src/gleitzeit/api/main.py` - Old monolithic API (2,608 lines)
- `src/gleitzeit/api/client.py` - Old API client (no longer needed)

## Route Mapping

### Workflow Routes (15 endpoints)
| Route | Method | Client Method |
|-------|--------|---------------|
| `/workflows/` | POST | `submit_workflow()` |
| `/workflows/run` | POST | `run_workflow()` |
| `/workflows/{id}` | GET | `get_workflow()` |
| `/workflows/` | GET | `list_workflows()` |
| `/workflows/{id}/cancel` | POST | `cancel_workflow()` |
| `/workflows/{id}/pause` | POST | `pause_workflow()` |
| `/workflows/{id}/resume` | POST | `resume_workflow()` |
| `/workflows/{id}` | DELETE | `delete_workflow()` |
| `/workflows/{id}/tasks` | GET | `get_workflow_tasks()` |
| `/workflows/{id}/wait` | POST | `wait_for_workflow()` |
| `/workflows/{id}/clone` | POST | `clone_workflow()` |
| `/workflows/statistics/summary` | GET | `get_workflow_statistics()` |
| `/workflows/{id}/timeline` | GET | `get_workflow_timeline()` |
| `/workflows/{id}/dependencies` | GET | `get_workflow_dependencies()` |
| `/workflows/{id}/critical-path` | GET | `get_workflow_critical_path()` |

### Task Routes (8 endpoints)
| Route | Method | Client Method |
|-------|--------|---------------|
| `/tasks/` | POST | `submit_task()` |
| `/tasks/{id}` | GET | `get_task()` |
| `/tasks/` | GET | `list_tasks()` |
| `/tasks/{id}/cancel` | POST | `cancel_task()` |
| `/tasks/{id}/pause` | POST | `pause_task()` |
| `/tasks/{id}/resume` | POST | `resume_task()` |
| `/tasks/{id}` | PUT | `update_task()` |
| `/tasks/{id}/wait` | POST | `wait_for_task()` |

### Admin Routes (15 endpoints)
| Route | Method | Client Method |
|-------|--------|---------------|
| `/admin/users` | POST | `create_user()` |
| `/admin/users` | GET | `list_users()` |
| `/admin/users/{id}` | GET | `get_user()` |
| `/admin/users/{id}` | PUT | `update_user()` |
| `/admin/users/{id}` | DELETE | `delete_user()` |
| `/admin/users/{id}/activate` | POST | `activate_user()` |
| `/admin/users/{id}/deactivate` | POST | `deactivate_user()` |
| `/admin/api-keys` | POST | `create_api_key()` |
| `/admin/api-keys` | GET | `list_api_keys()` |
| `/admin/api-keys/{id}` | DELETE | `revoke_api_key()` |
| `/admin/roles` | POST | `create_role()` |
| `/admin/roles` | GET | `list_roles()` |
| `/admin/roles/{id}` | DELETE | `delete_role()` |
| `/admin/audit-logs` | GET | `get_audit_logs()` |
| `/admin/system-stats` | GET | `get_system_statistics()` |

### System Routes (8 endpoints)
| Route | Method | Client Method |
|-------|--------|---------------|
| `/system/health` | GET | `health_check()` |
| `/system/status` | GET | `get_system_status()` |
| `/system/info` | GET | `get_system_info()` |
| `/system/metrics` | GET | `get_system_metrics()` |
| `/system/config` | GET | `get_system_config()` |
| `/system/shutdown` | POST | `shutdown_system()` |
| `/system/maintenance/start` | POST | `start_maintenance_mode()` |
| `/system/maintenance/stop` | POST | `stop_maintenance_mode()` |

## Key Architecture Components

### APIRouteBase Class
```python
class APIRouteBase:
    """Base class for API route modules that delegate to client methods."""
    
    async def handle_client_call(self, client_method_name: str, *args, **kwargs):
        """Generic handler for client method calls with proper error handling."""
        # Get client method and call it
        # Handle errors and convert to HTTP exceptions
```

### Route Pattern
```python
@router.post("/", response_model=Dict[str, Any])
async def submit_workflow(request: WorkflowSubmissionRequest, req: Request):
    """Submit a workflow for execution."""
    workflow = Workflow(**request.workflow)
    routes = _get_routes()
    return await routes.handle_client_call("submit_workflow", workflow)
```

### Shared Client Management
```python
_shared_client: Optional[GleitzeitClient] = None

def get_shared_client() -> GleitzeitClient:
    """Get or create the shared client instance for API routes."""
    global _shared_client
    if _shared_client is None:
        _shared_client = GleitzeitClient(mode=ClientMode.NATIVE)
    return _shared_client
```

## Migration Steps

### 1. Update Startup Scripts

**CLI main.py:**
```python
# OLD
from gleitzeit.api.main import app

# NEW
from gleitzeit.api.modular_main import app
```

**run_server.py:**
```python
# OLD
from gleitzeit.api.main import app

# NEW
from gleitzeit.api.modular_main import app
```

### 2. Remove Old Files
- Delete `src/gleitzeit/api/main.py` (monolithic API)
- Delete `src/gleitzeit/api/client.py` (old API client)

### 3. Rename New Main
- Rename `modular_main.py` → `main.py`

## Testing Coverage

### Test Results
- **70 Total Tests**: All passing (100%)
- **46 Endpoints**: Fully tested
- **Error Handling**: Comprehensive coverage
- **Authentication**: Admin privilege enforcement tested

### Test Files
```
newtests/api/
├── conftest.py           # Test fixtures and mocks
├── test_workflows.py     # 21 workflow tests
├── test_tasks.py        # 15 task tests
├── test_admin.py        # 18 admin tests
└── test_system.py       # 16 system tests
```

## Benefits of New Architecture

### 1. **Maintainability**
- Clean separation of concerns
- Easy to add new routes
- Simple to modify existing routes

### 2. **Testability**
- Each route module can be tested independently
- Mock client for unit testing
- Integration tests against real client

### 3. **Consistency**
- All routes follow same pattern
- Centralized error handling
- Uniform authentication checks

### 4. **Scalability**
- Easy to add new route modules
- Can split large modules if needed
- Client handles all business logic

### 5. **Documentation**
- Routes clearly map to client methods
- Self-documenting code structure
- Easy to generate OpenAPI docs

## Error Handling

### HTTP Status Codes
- **200**: Success
- **401**: Authentication required
- **403**: Insufficient privileges
- **500**: Internal server error
- **501**: Not implemented
- **503**: Service unavailable

### Exception Mapping
```python
RuntimeError("not initialized") → 503 Service Unavailable
NotImplementedError → 501 Not Implemented  
Exception → 500 Internal Server Error
```

## Authentication

### Current Implementation
- Header-based: `X-User-ID`, `X-User-Role`
- Admin check: `require_admin()` method
- Basic mode: Default user assigned by middleware

### Future Enhancements
- JWT token support
- OAuth2 integration
- API key authentication

## Performance Considerations

### Shared Client
- Single client instance for all requests
- Initialized once at startup
- Native mode for direct engine access

### Async Operations
- All routes are async
- Client methods are async
- Proper connection pooling

## Deployment

### Docker
```dockerfile
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["uvicorn", "gleitzeit.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment Variables
- `GLEITZEIT_API_HOST`: API host (default: localhost)
- `GLEITZEIT_API_PORT`: API port (default: 8000)
- `GLEITZEIT_MODE`: Client mode (AUTO, API, NATIVE)

## Rollback Plan

If issues arise with the new modular API:

1. **Quick Rollback**: 
   - Restore `main_old.py` → `main.py`
   - Update imports in startup scripts

2. **Gradual Migration**:
   - Run both APIs on different ports
   - Migrate routes incrementally
   - Test thoroughly before switching

## Future Enhancements

1. **Additional Route Modules**:
   - `monitoring.py` - Metrics and monitoring
   - `batch.py` - Batch processing operations
   - `streaming.py` - WebSocket/SSE endpoints

2. **OpenAPI Generation**:
   - Auto-generate from route definitions
   - Include in API responses

3. **Rate Limiting**:
   - Add rate limiting middleware
   - Per-user/per-route limits

4. **Caching**:
   - Response caching for read operations
   - Redis integration for distributed cache

## Conclusion

The modular API architecture provides a clean, maintainable, and testable foundation for the Gleitzeit API. By delegating all operations to the GleitzeitClient, the API becomes a thin layer that's easy to understand, extend, and maintain. The successful test coverage (100% pass rate) gives confidence in the reliability of the new architecture.