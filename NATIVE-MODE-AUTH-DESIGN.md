# NATIVE Mode Authentication Design

## Current Problem
- NATIVE mode bypasses all authentication
- Stack inspection is fragile and can be bypassed
- Inconsistent security model

## Better Solution: Auth for NATIVE Mode

### Option 1: Service Account Token (Recommended)
```python
# API server gets a service token at startup
SERVICE_TOKEN = os.getenv("GLEITZEIT_SERVICE_TOKEN") or generate_secure_token()

# NativeAdapter requires this token
class NativeAdapter:
    def __init__(self, service_token: str = None):
        if not service_token or service_token != SERVICE_TOKEN:
            raise PermissionError("Invalid service token for NATIVE mode")
        self.authenticated = True
```

### Option 2: Certificate-Based Auth
```python
# API server has a certificate
class NativeAdapter:
    def __init__(self, cert_path: str = None):
        if not verify_api_certificate(cert_path):
            raise PermissionError("Invalid certificate for NATIVE mode")
```

### Option 3: Remove NATIVE Mode Entirely
Instead of NATIVE mode, the API could use a different pattern:

```python
# Direct service layer (not a client)
class WorkflowService:
    def __init__(self, persistence):
        self.persistence = persistence
    
    async def list_workflows(self, ...):
        # Direct persistence access
        return await self.persistence.list_workflows(...)

# API uses services, not clients
@router.get("/workflows")
async def list_workflows(
    service: WorkflowService = Depends(get_workflow_service)
):
    return await service.list_workflows()
```

## Recommended Approach

### 1. Short Term: Add Service Token to NATIVE Mode
```python
class GleitzeitClient:
    def __init__(self, mode, service_token=None, ...):
        if mode == ClientMode.NATIVE:
            if not service_token:
                raise ValueError("NATIVE mode requires service_token")
            # Validate token
            if not self._validate_service_token(service_token):
                raise PermissionError("Invalid service token")
```

### 2. Long Term: Replace with Service Layer
- Remove NATIVE mode entirely
- API uses service classes, not client classes
- Services have direct persistence access
- Clear separation of concerns

## Benefits of Auth for NATIVE Mode

1. **Consistent Security Model**
   - All modes require authentication
   - No special bypasses

2. **Defense in Depth**
   - Even if someone gets NATIVE mode, they need credentials
   - Service tokens can be rotated

3. **Audit Trail**
   - Can log who uses NATIVE mode
   - Track service account usage

4. **Testability**
   - Can test auth consistently
   - No stack inspection magic

## Implementation Plan

### Phase 1: Add Service Token (Quick Fix)
1. Generate service token at API startup
2. Pass token to SharedClientPool
3. NativeAdapter validates token
4. External code can't use without token

### Phase 2: Refactor to Service Layer (Proper Fix)
1. Create service classes for each domain
2. Services use persistence directly
3. API routes use services via DI
4. Remove NATIVE mode entirely

## Example Implementation

```python
# 1. Service token approach (quick fix)
import secrets
import os

class GleitzeitClient:
    # Class-level service token (set by API at startup)
    _SERVICE_TOKEN = None
    
    @classmethod
    def set_service_token(cls, token: str):
        """Set the service token (API startup only)."""
        cls._SERVICE_TOKEN = token
    
    def __init__(self, mode, service_token=None, ...):
        if mode == ClientMode.NATIVE:
            # Require and validate service token
            if not service_token or service_token != self._SERVICE_TOKEN:
                raise PermissionError(
                    "NATIVE mode requires valid service token. "
                    "This mode is only for internal API use."
                )

# 2. At API startup
async def lifespan(app: FastAPI):
    # Generate or load service token
    service_token = os.getenv("GLEITZEIT_SERVICE_TOKEN") or secrets.token_hex(32)
    GleitzeitClient.set_service_token(service_token)
    
    # Pass to dependencies
    app.state.service_token = service_token
    
    yield

# 3. In dependencies.py
async def get_pooled_client():
    service_token = current_app.state.service_token
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,
        service_token=service_token  # Required for NATIVE
    )
```

## Security Considerations

1. **Token Storage**
   - Never log tokens
   - Use environment variables
   - Rotate regularly

2. **Token Generation**
   - Use cryptographically secure random
   - Sufficient entropy (256 bits)
   - Unique per deployment

3. **Token Validation**
   - Constant-time comparison
   - Rate limit attempts
   - Log failures

## Conclusion

The current stack inspection approach is fragile. A service token requirement for NATIVE mode would be:
- More consistent (all modes need auth)
- More secure (can't bypass with tricks)
- More maintainable (explicit, not magic)
- More testable (can mock tokens)

The long-term solution is to remove NATIVE mode entirely and use a proper service layer pattern.