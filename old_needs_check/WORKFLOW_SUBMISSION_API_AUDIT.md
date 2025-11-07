# Workflow Submission API Audit Report

## Executive Summary
The workflow submission API in Gleitzeit 0.0.7 has significant security vulnerabilities including missing authentication, no rate limiting, inadequate input validation, and poor error handling that could lead to information disclosure and denial of service attacks.

## Critical Security Issues

### 1. **No Authentication Required (CRITICAL)**

**Location:** `src/gleitzeit/api/routes/workflows.py:34-38`

The submit_workflow endpoint has NO authentication requirements. Any unauthenticated user can submit workflows.

```python
@router.post("/submit", response_model=WorkflowSubmitResponse)
async def submit_workflow(
    request: WorkflowSubmitRequest,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    # Missing: user: User = Depends(get_current_user)
```

**Impact:**
- Anonymous workflow submission possible
- No audit trail of who submitted workflows
- No ability to enforce quotas or permissions
- Potential for abuse and resource exhaustion

**Fix Required:**
```python
async def submit_workflow(
    request: WorkflowSubmitRequest,
    user: User = Depends(get_current_user),  # ADD THIS
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
```

### 2. **No Rate Limiting (CRITICAL)**

**Location:** Entire API application

No rate limiting middleware or per-endpoint throttling exists. Users can submit unlimited workflows.

**Impact:**
- Denial of Service vulnerability
- Resource exhaustion attacks
- Redis stream overflow
- Worker starvation

**Required Implementation:**
- Add rate limiting middleware (e.g., slowapi)
- Implement per-user workflow submission quotas
- Add Redis stream size monitoring

### 3. **Insufficient Input Validation (HIGH)**

**Location:** `src/gleitzeit/api/routes/workflows.py:19-23`

The WorkflowSubmitRequest model accepts ANY dictionary as workflow without validation:

```python
class WorkflowSubmitRequest(BaseModel):
    workflow: Dict[str, Any] = Field(...)  # No size limit, no schema validation
    workflow_id: Optional[str] = Field(None)  # No format validation
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)  # Unbounded
```

**Issues:**
- No maximum size limit on workflow payload
- No validation of workflow structure
- workflow_id accepts any string (injection risk)
- Metadata field unbounded

**Required Validations:**
```python
from pydantic import validator, constr

class WorkflowSubmitRequest(BaseModel):
    workflow: Dict[str, Any] = Field(..., description="Workflow definition")
    workflow_id: Optional[constr(regex=r'^[a-zA-Z0-9-_]+$', max_length=100)] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator('workflow')
    def validate_workflow_size(cls, v):
        # Check size in bytes
        if len(json.dumps(v)) > 10_000_000:  # 10MB limit
            raise ValueError("Workflow too large")
        # Check task count
        if 'tasks' in v and len(v['tasks']) > 1000:
            raise ValueError("Too many tasks")
        return v

    @validator('metadata')
    def validate_metadata(cls, v):
        if len(json.dumps(v)) > 100_000:  # 100KB limit
            raise ValueError("Metadata too large")
        return v
```

### 4. **Information Disclosure in Error Messages (MEDIUM)**

**Location:** `src/gleitzeit/api/routes/workflows.py:93-94`

```python
except Exception as e:
    raise HTTPException(status_code=500, detail=f"Failed to submit workflow: {str(e)}")
```

**Issue:** Raw exception messages exposed to users, potentially revealing internal details.

**Fix:**
```python
except Exception as e:
    logger.error(f"Workflow submission failed for {workflow_id}: {str(e)}")
    raise HTTPException(
        status_code=500,
        detail="Failed to submit workflow. Please try again later."
    )
```

### 5. **Non-Atomic Operations (MEDIUM)**

**Location:** `src/gleitzeit/api/routes/workflows.py:69-84`

Two separate Redis operations without transaction:

```python
# Operation 1
message_id = await redis.xadd(stream_key.encode(), submission_data)

# Operation 2 - Can fail independently
await redis.hset(workflow_key.encode(), mapping={...})
```

**Issue:** If second operation fails, workflow is in stream but no state record exists.

**Fix:**
```python
# Use Redis pipeline for atomic operations
async with redis.pipeline() as pipe:
    pipe.xadd(stream_key.encode(), submission_data)
    pipe.hset(workflow_key.encode(), mapping={...})
    results = await pipe.execute()
```

### 6. **CORS Misconfiguration (MEDIUM)**

**Location:** `src/gleitzeit/api/main.py:61-67`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows ANY origin
    allow_credentials=True,  # Dangerous with wildcard origins
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Issue:** Allows requests from any origin with credentials, enabling CSRF attacks.

**Fix:**
```python
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Session-ID", "X-API-Key"],
)
```

### 7. **Missing Request ID Tracking (LOW)**

No request ID generation or correlation for debugging and audit trails.

**Recommendation:** Add request ID middleware:
```python
from fastapi import Request
import uuid

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
```

## Performance & Scalability Issues

### 1. **No Connection Pooling Limits**
The ClientPool has per-user limits but no global connection limit, risking resource exhaustion.

### 2. **Missing Stream Backpressure**
No checks for Redis stream size before adding messages. Streams could grow unbounded.

### 3. **Synchronous Circular Import**
Line 251: `from ..main import app` - Circular import could cause initialization issues.

## Security Recommendations Priority

### Immediate Actions (P0):
1. **Add authentication to submit_workflow endpoint**
2. **Implement rate limiting middleware**
3. **Fix CORS configuration for production**

### Short-term (P1):
1. **Add comprehensive input validation**
2. **Implement Redis transactions for atomicity**
3. **Sanitize error messages**
4. **Add request ID tracking**

### Medium-term (P2):
1. **Implement per-user quotas**
2. **Add stream size monitoring**
3. **Add audit logging**
4. **Implement workflow approval workflow for sensitive operations**

## Testing Gaps

Missing test coverage for:
- Authentication bypass attempts
- Large payload handling
- Malformed workflow structures
- Concurrent submission race conditions
- Rate limiting enforcement
- CORS policy validation

## Compliance Considerations

Current implementation may not meet:
- GDPR requirements (no audit trail)
- SOC 2 requirements (missing access controls)
- PCI DSS requirements (insufficient logging)

## Conclusion

The workflow submission API requires immediate security hardening before production deployment. The most critical issues are the complete lack of authentication and rate limiting, which could lead to immediate service disruption or abuse. The fixes are straightforward to implement but critical for system security.