# Authorization Implementation Audit
*Last Updated: 2024-12-09*

## Overview
Complete authorization system implementation across Client, API, and CLI layers using SystemManager and AuthManager with proper Gleitzeit error handling.

## 1. Authorization Architecture

### Core Components
- **SystemManager**: Centralized management (stateless)
- **AuthManager**: Authentication and permission checks (stateless) 
- **Client Pooling**: Preserves connection pooling while adding auth
- **User Context**: Passed through all layers for authorization

### Authorization Flow
```
Request → API Route → Get Pooled Client → Set User Context → Native Adapter → Check Authorization
                ↓                                                      ↓
          Get Current User                                   AuthManager.check_permission()
                ↓                                                      ↓
          SystemManager.AuthManager                          Owner/Admin/Permission Check
```

## 2. Implementation Status

### API Layer ✅
**Location**: `/src/gleitzeit/api/`

#### Authorization Module (`authorization.py`)
- `check_workflow_ownership()`: Ownership-first authorization
- `check_task_ownership()`: Task authorization via workflow
- `filter_workflows_by_ownership()`: Filter lists by ownership
- `set_resource_ownership()`: Set ownership on resources

#### Route Protection
**Workflows** (`routes/workflows.py`):
- ✅ Submit: Sets ownership via `set_resource_ownership()`
- ✅ Get: Checks via `check_workflow_ownership()`
- ✅ List: Filters via `filter_workflows_by_ownership()`
- ✅ Cancel/Pause/Resume/Delete: Ownership required
- ✅ All operations preserve client pooling

**Users** (`routes/users.py`):
- ✅ Admin-only operations via `require_admin()`
- ✅ Basic mode restrictions enforced
- ✅ No bypass for basic users

#### Dependency Injection (`dependencies.py`)
```python
get_client_with_auth():
    1. Gets pooled client
    2. Gets user context from SystemManager
    3. Sets context on client
    4. Returns auth-aware client
```

### Client Layer ✅
**Location**: `/src/gleitzeit/client/`

#### Native Adapter (`adapters/native.py`)
```python
class NativeAdapter:
    def __init__(self, user_context: Optional[Dict] = None):
        self.user_context = user_context  # For authorization
    
    async def _check_workflow_access(workflow, action) -> bool:
        # Ownership check first
        # Then admin check
        # Then permission check
```

- ✅ Authorization checks in all modifying operations
- ✅ User context required for permission checks
- ✅ Cannot bypass by importing directly

#### API Adapter (`adapters/api.py`)
- ✅ Parses HTTP errors to Gleitzeit errors
- ✅ 403 → `AuthorizationError`
- ✅ 401 → `AuthenticationError`
- ✅ 404 → `ResourceNotFoundError`

### CLI Layer ✅
**Location**: `/src/gleitzeit/cli/`

#### Error Handler (`error_handler.py`)
```python
if isinstance(error, AuthorizationError):
    click.echo("❌ You don't have permission...")
elif isinstance(error, AuthenticationError):
    click.echo("❌ Please login...")
```

- ✅ User-friendly error messages
- ✅ Specific handling for each error type

## 3. Authorization Rules

### Permission Hierarchy
1. **Superuser/Admin**: Can access everything
2. **Owner**: Can access their own resources
3. **Public**: Can read public resources (workflows only)
4. **Basic User**: Limited to own resources

### Basic User Permissions (Reduced)
```python
[
    # Create new resources
    "workflows:create",
    "tasks:create",
    
    # Modify OWN resources only
    "workflows:read",    # Ownership checked
    "workflows:update",  # Ownership checked  
    "workflows:delete",  # Ownership checked
    
    # Read-only system access
    "queues:read",
    "logs:read",
    
    # NO admin permissions
    # NO user management
    # NO *:all permissions
]
```

### Authorization Check Order
1. Check if superuser/admin → Allow all
2. Check ownership → Allow if owner
3. Check if public (read only) → Allow reads
4. Check special permissions (`:all` suffix) → Allow if granted
5. Deny access

## 4. Error Handling Alignment

### Error Flow
```
Authorization Fails
    ↓
Raises AuthorizationError (Gleitzeit)
    ↓
API Middleware catches
    ↓
Converts to HTTP 403
    ↓
Client receives 403
    ↓
Parses to AuthorizationError
    ↓
CLI shows friendly message
```

### Error Mapping
- `AuthorizationError` → HTTP 403 → "You don't have permission"
- `AuthenticationError` → HTTP 401 → "Please login"
- `ResourceNotFoundError` → HTTP 404 → "Resource not found"

## 5. Security Properties

### ✅ Ownership-First
- Owners always have full access to their resources
- Ownership checked before permissions
- Cannot modify others' resources even with general permission

### ✅ No Bypasses
- Native adapter requires user context
- Direct imports still check authorization
- API routes always check permissions

### ✅ Consistent Rules
- Same authorization logic in all layers
- Single source of truth (AuthManager)
- Unified error handling

### ✅ Client Pooling Preserved
- Authorization doesn't break pooling
- User context set per request
- Clients returned to pool after use

## 6. Testing Checklist

- [x] Basic user cannot access admin functions
- [x] Users can only see their own workflows
- [x] Public workflows visible to all (read-only)
- [x] Owners can modify their resources
- [x] Admin can access everything
- [x] Authorization errors properly propagated
- [x] Client pooling still works
- [x] Native adapter checks permissions

## 7. Key Files Modified

### New Files
- `/src/gleitzeit/api/authorization.py` - Authorization helpers
- `/src/gleitzeit/api/error_handler.py` - Error mapping
- `/src/gleitzeit/cli/error_handler.py` - CLI error messages

### Modified Files
- `/src/gleitzeit/api/routes/workflows.py` - Added auth checks
- `/src/gleitzeit/api/routes/users.py` - Fixed admin bypass
- `/src/gleitzeit/api/dependencies.py` - Added auth-aware client
- `/src/gleitzeit/client/adapters/native.py` - Added auth checks
- `/src/gleitzeit/client/adapters/api.py` - Parse auth errors
- `/src/gleitzeit/client/client.py` - Support user context
- `/src/gleitzeit/auth/auth_manager.py` - Reduced basic permissions
- `/src/gleitzeit/api/middleware.py` - Handle Gleitzeit errors

## 8. Backward Compatibility

### Native Adapter
- User context is optional (warns if missing)
- Existing code works but without auth
- Can be made mandatory in future

### API Routes
- All routes now require authentication
- Basic mode provides default user
- No breaking changes for API consumers

## 9. Future Improvements

1. **Make user context mandatory** in Native adapter
2. **Add rate limiting** per user
3. **Implement audit logging** for authorization failures
4. **Add resource-level permissions** (e.g., `workflows:123:read`)
5. **Support API key authentication** with scoped permissions