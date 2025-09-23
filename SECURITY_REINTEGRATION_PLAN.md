# Security Reintegration Plan: 0.0.6 → 0.0.7

## Executive Summary
This document provides a step-by-step plan to reintegrate the proven 0.0.6 security model into 0.0.7, while preserving the worker-based architecture. The approach prioritizes minimal disruption with maximum security improvement.

## Phase 1: Enhanced Authentication Dependencies (Immediate)

### 1.1 Update `src/gleitzeit/api/auth/dependencies.py`

Add the missing auto-login functionality from 0.0.6:

```python
"""
Enhanced authentication dependencies with auto-login support.
Adapted from 0.0.6 for 0.0.7 architecture.
"""

import os
from typing import Dict, Any, Optional
from fastapi import Request, Response, HTTPException, Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import redis.asyncio as aioredis
import logging

from .models import User, UserRole
from .jwt_manager import JWTManager
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer(auto_error=False)

# Global instances
jwt_manager: Optional[JWTManager] = None
session_manager: Optional[SessionManager] = None


def init_auth(redis: aioredis.Redis):
    """Initialize authentication components"""
    global jwt_manager, session_manager

    jwt_manager = JWTManager()
    session_manager = SessionManager(redis)

    logger.info("Authentication components initialized")


async def get_redis() -> aioredis.Redis:
    """Get Redis connection from app state"""
    from ..main import app
    return app.state.redis


async def get_current_user_auto(
    request: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    api_key: Optional[str] = Header(None, alias="X-API-Key"),
    redis: aioredis.Redis = Depends(get_redis)
) -> User:
    """
    Get current user with automatic basic user login.

    Priority:
    1. JWT Bearer token
    2. Client session ID (from header)
    3. Cookie session
    4. API key
    5. Auto-create basic user (if enabled)
    """

    # Ensure auth is initialized
    if not session_manager:
        init_auth(redis)

    # Try JWT token
    if credentials and credentials.credentials:
        payload = jwt_manager.verify_token(credentials.credentials)
        if payload:
            return User(
                id=payload["sub"],
                username=payload.get("username", "unknown"),
                role=UserRole(payload.get("role", "user")),
                is_active=True
            )

    # Try client session ID from header
    if client_session_id:
        user = await session_manager.get_session(client_session_id)
        if user:
            return user

    # Try cookie session
    cookie_session_id = request.cookies.get("session_id")
    if cookie_session_id:
        user = await session_manager.get_session(cookie_session_id)
        if user:
            return user

    # Try API key
    if api_key:
        # Validate API key from Redis
        api_key_data = await redis.hget(f"api_keys:{api_key}", "user_data")
        if api_key_data:
            import json
            user_data = json.loads(api_key_data)
            return User(**user_data)

    # Auto-create basic user if enabled
    if os.getenv("GLEITZEIT_AUTO_LOGIN", "true").lower() == "true":
        # Create a basic session
        basic_user = User(
            id="basic-user",
            username="basic",
            role=UserRole.USER,
            is_active=True,
            metadata={"is_basic_user": True}
        )

        # Store session
        session_id = await session_manager.create_session(basic_user)

        # Set cookie
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=86400  # 24 hours
        )

        logger.debug(f"Auto-created basic user session: {session_id}")
        return basic_user

    # No authentication available
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_required(
    request: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    api_key: Optional[str] = Header(None, alias="X-API-Key"),
    redis: aioredis.Redis = Depends(get_redis)
) -> User:
    """
    Get current user - real authentication required (no auto-login).
    """

    # Get user but don't allow basic users
    user = await get_current_user_auto(
        request, response, credentials, client_session_id, api_key, redis
    )

    # Check if it's a basic user
    if user.metadata and user.metadata.get("is_basic_user"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires a real user account"
        )

    return user


async def require_admin(
    user: User = Depends(get_current_user_required)
) -> User:
    """Require admin role"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


async def require_permission(
    permission: str,
    user: User = Depends(get_current_user_auto)
) -> User:
    """Check for specific permission"""
    # In 0.0.7, we'll use role-based permissions
    role_permissions = {
        UserRole.ADMIN: ["*"],  # All permissions
        UserRole.USER: [
            "workflows:create", "workflows:read:own", "workflows:cancel:own",
            "tasks:read:own", "tasks:retry:own"
        ],
        UserRole.SERVICE: [
            "workflows:*", "tasks:*", "system:read"
        ]
    }

    user_perms = role_permissions.get(user.role, [])

    # Check wildcard or specific permission
    if "*" in user_perms or permission in user_perms:
        return user

    # Check owned resource permissions
    if ":own" in permission:
        base_perm = permission.replace(":own", "")
        if f"{base_perm}:own" in user_perms:
            return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Permission denied: {permission} required"
    )
```

## Phase 2: Secure Workflow Endpoints

### 2.1 Update `src/gleitzeit/api/routes/workflows.py`

```python
"""
Secured workflow submission and management endpoints.
Enhanced with 0.0.6 security model.
"""

import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, Response
from pydantic import BaseModel, Field, validator
import redis.asyncio as aioredis

from ...core.sharding import default_sharding
from ..auth.dependencies import (
    get_current_user_auto,
    get_current_user_required,
    require_permission,
    User
)

router = APIRouter()


class WorkflowSubmitRequest(BaseModel):
    """Enhanced workflow submission with validation"""
    workflow: Dict[str, Any] = Field(..., description="Workflow definition")
    workflow_id: Optional[str] = Field(None, description="Optional workflow ID")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional metadata")

    @validator('workflow')
    def validate_workflow_size(cls, v):
        """Validate workflow size and structure"""
        # Size check
        if len(json.dumps(v)) > 10_000_000:  # 10MB limit
            raise ValueError("Workflow exceeds maximum size of 10MB")

        # Basic structure validation
        if 'tasks' in v:
            if not isinstance(v['tasks'], list):
                raise ValueError("Tasks must be a list")
            if len(v['tasks']) > 1000:
                raise ValueError("Workflow cannot have more than 1000 tasks")

        return v

    @validator('workflow_id')
    def validate_workflow_id(cls, v):
        """Validate workflow ID format"""
        if v and not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError("Workflow ID must be alphanumeric with hyphens/underscores only")
        return v


class WorkflowSubmitResponse(BaseModel):
    """Workflow submission response"""
    workflow_id: str
    status: str
    message: str
    submitted_at: str
    submitted_by: str  # Added user tracking


@router.post("/submit", response_model=WorkflowSubmitResponse)
async def submit_workflow(
    request: WorkflowSubmitRequest,
    user: User = Depends(get_current_user_auto),  # Add authentication
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """
    Submit a workflow for execution with authentication and ownership tracking.
    """

    # Check permission
    await require_permission("workflows:create", user)

    # Generate workflow ID if not provided
    workflow_id = request.workflow_id or str(uuid.uuid4())

    # Add workflow metadata
    if "workflow_id" not in request.workflow:
        request.workflow["workflow_id"] = workflow_id

    # Add ownership information
    request.workflow["submitted_by"] = user.id
    request.workflow["submitted_by_username"] = user.username

    # Prepare submission data with user tracking
    submission_data = {
        b"workflow_id": workflow_id.encode(),
        b"workflow": json.dumps(request.workflow).encode(),
        b"metadata": json.dumps(request.metadata).encode(),
        b"submitted_at": datetime.utcnow().isoformat().encode(),
        b"submitted_by": user.id.encode(),
        b"submitted_by_username": user.username.encode(),
        b"source": b"api"
    }

    try:
        # Use Redis transaction for atomicity
        async with redis.pipeline() as pipe:
            # Submit to workflow:load stream
            stream_key = default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id)
            pipe.xadd(stream_key.encode(), submission_data)

            # Store initial workflow state with ownership
            workflow_key = default_sharding.get_workflow_key("state", workflow_id)
            pipe.hset(
                workflow_key.encode(),
                mapping={
                    b"workflow_id": workflow_id.encode(),
                    b"status": b"submitted",
                    b"submitted_at": datetime.utcnow().isoformat().encode(),
                    b"submitted_by": user.id.encode(),
                    b"submitted_by_username": user.username.encode()
                }
            )

            # Track user's workflows
            user_workflows_key = f"user:{user.id}:workflows"
            pipe.sadd(user_workflows_key.encode(), workflow_id.encode())

            # Execute transaction
            results = await pipe.execute()
            message_id = results[0]  # First result is from xadd

        # Log submission for audit
        import logging
        logging.info(f"Workflow {workflow_id} submitted by {user.username} ({user.id})")

        return WorkflowSubmitResponse(
            workflow_id=workflow_id,
            status="submitted",
            message=f"Workflow submitted successfully",
            submitted_at=datetime.utcnow().isoformat(),
            submitted_by=user.username
        )

    except Exception as e:
        # Log error securely
        import logging
        logging.error(f"Workflow submission failed for user {user.id}: {str(e)}")

        # Return sanitized error
        raise HTTPException(
            status_code=500,
            detail="Failed to submit workflow. Please try again later."
        )


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    user: User = Depends(get_current_user_auto),
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Get workflow with ownership check"""

    # Get workflow state
    state_key = default_sharding.get_workflow_key("state", workflow_id)
    state_data = await redis.hgetall(state_key.encode())

    if not state_data:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check ownership (admin can view all)
    submitted_by = state_data.get(b"submitted_by", b"").decode()
    if user.role != UserRole.ADMIN and submitted_by != user.id:
        # Check if user has explicit access
        access_key = f"workflow:{workflow_id}:access:{user.id}"
        has_access = await redis.exists(access_key.encode())
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view this workflow"
            )

    # Get workflow data
    data_key = default_sharding.get_workflow_key("data", workflow_id)
    workflow_data = await redis.hgetall(data_key.encode())

    # Combine and return
    result = {
        "workflow_id": workflow_id,
        "state": {k.decode(): v.decode() for k, v in state_data.items()},
    }

    if workflow_data:
        result["data"] = {
            k.decode(): json.loads(v.decode()) if k == b"workflow" else v.decode()
            for k, v in workflow_data.items()
        }

    return result


@router.get("/")
async def list_workflows(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user_auto),
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """List workflows - filtered by ownership for non-admins"""

    workflows = []

    if user.role == UserRole.ADMIN:
        # Admin can see all workflows
        # This would need proper implementation with Redis scanning
        pass  # Implementation needed
    else:
        # Get user's workflows
        user_workflows_key = f"user:{user.id}:workflows"
        workflow_ids = await redis.smembers(user_workflows_key.encode())

        for workflow_id_bytes in workflow_ids:
            workflow_id = workflow_id_bytes.decode()
            state_key = default_sharding.get_workflow_key("state", workflow_id)
            state_data = await redis.hgetall(state_key.encode())

            if state_data:
                workflow_info = {
                    "workflow_id": workflow_id,
                    **{k.decode(): v.decode() for k, v in state_data.items()}
                }

                # Filter by status if specified
                if not status or workflow_info.get("status") == status:
                    workflows.append(workflow_info)

    # Apply pagination
    paginated = workflows[offset:offset + limit]

    return {
        "workflows": paginated,
        "total": len(workflows),
        "limit": limit,
        "offset": offset
    }


@router.post("/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    user: User = Depends(get_current_user_auto),
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Cancel workflow with ownership check"""

    # Get workflow state to check ownership
    state_key = default_sharding.get_workflow_key("state", workflow_id)
    state_data = await redis.hgetall(state_key.encode())

    if not state_data:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check ownership
    submitted_by = state_data.get(b"submitted_by", b"").decode()
    if user.role != UserRole.ADMIN and submitted_by != user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only cancel your own workflows"
        )

    # Proceed with cancellation (existing logic)
    # ... rest of cancellation logic ...

    return {
        "workflow_id": workflow_id,
        "status": "cancelled",
        "cancelled_by": user.username,
        "message": "Workflow cancelled successfully"
    }


# Fix circular import
from ..main import app
from ..auth.models import UserRole
```

## Phase 3: Enhanced Client with Authentication

### 3.1 Update `src/gleitzeit/client/client.py`

```python
"""
Enhanced Gleitzeit client with authentication support.
Incorporates 0.0.6 session management and error handling.
"""

import json
import asyncio
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import aiohttp
import uuid

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResponse:
    """Workflow submission response"""
    workflow_id: str
    status: str
    message: str
    submitted_at: str
    submitted_by: Optional[str] = None


class AuthenticationError(Exception):
    """Authentication failed"""
    pass


class AuthorizationError(Exception):
    """Authorization failed"""
    pass


class GleitzeitClient:
    """
    Enhanced client with proper authentication and error handling.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        session_id: Optional[str] = None,
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
        pool_size: int = 5,
        auto_start_server: bool = False,
        auto_login: bool = True,
        username: Optional[str] = None,
        password: Optional[str] = None,
        retry_config: Optional[Dict[str, Any]] = None
    ):
        self.api_url = api_url.rstrip('/')
        self.session_id = session_id
        self.api_key = api_key
        self.jwt_token = jwt_token
        self.pool_size = pool_size
        self.auto_login = auto_login
        self.username = username or "default_user"
        self.password = password

        # Retry configuration
        self.retry_config = retry_config or {
            "max_retries": 3,
            "initial_delay": 1.0,
            "max_delay": 30.0,
            "exponential_base": 2,
            "jitter": True
        }

        # Connection pool
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None

        # Cookie jar for session management
        self._cookie_jar = aiohttp.CookieJar()

        if auto_start_server:
            self._ensure_server_running()

    def _ensure_server_running(self):
        """Check if server is running and start if needed"""
        import requests
        try:
            response = requests.get(f"{self.api_url}/health/", timeout=2)
            if response.status_code == 200:
                logger.info("API server is running")
            return
        except:
            logger.info("API server not running, attempting to start...")
            # TODO: Implement server startup
            pass

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def connect(self):
        """Initialize connection pool and authenticate if needed"""
        if not self._session:
            self._connector = aiohttp.TCPConnector(
                limit=self.pool_size,
                limit_per_host=self.pool_size,
                ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                cookie_jar=self._cookie_jar,
                timeout=aiohttp.ClientTimeout(total=30)
            )

            # Auto-login if enabled and no credentials provided
            if self.auto_login and not self.session_id and not self.jwt_token:
                try:
                    await self.create_session(self.username, self.password)
                except Exception as e:
                    logger.warning(f"Auto-login failed: {e}")

    async def close(self):
        """Close connection pool"""
        if self._session:
            await self._session.close()
            self._session = None
            self._connector = None

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication"""
        headers = {"Content-Type": "application/json"}

        if self.session_id:
            headers["X-Session-ID"] = self.session_id
        elif self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"

        return headers

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """Make HTTP request with retry logic"""
        last_exception = None

        for attempt in range(self.retry_config["max_retries"]):
            try:
                async with self._session.request(method, url, **kwargs) as resp:
                    # Check for auth errors (don't retry these)
                    if resp.status == 401:
                        raise AuthenticationError("Authentication failed")
                    elif resp.status == 403:
                        raise AuthorizationError("Authorization failed")

                    # Raise for other errors to trigger retry
                    if resp.status >= 500:
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status
                        )

                    # Success or client error (don't retry client errors)
                    return await resp.json()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e

                if attempt < self.retry_config["max_retries"] - 1:
                    # Calculate delay with exponential backoff
                    delay = min(
                        self.retry_config["initial_delay"] * (
                            self.retry_config["exponential_base"] ** attempt
                        ),
                        self.retry_config["max_delay"]
                    )

                    # Add jitter if enabled
                    if self.retry_config["jitter"]:
                        import random
                        delay *= (0.5 + random.random())

                    logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {delay:.2f}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Request failed after {self.retry_config['max_retries']} attempts")
                    raise

        raise last_exception

    # Authentication methods

    async def create_session(self, username: str, password: Optional[str] = None) -> str:
        """Create a new client session"""
        if not self._session:
            await self.connect()

        data = await self._request_with_retry(
            "POST",
            f"{self.api_url}/auth/session/create",
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"}
        )

        self.session_id = data["session_id"]
        logger.info(f"Created session for user {username}")
        return self.session_id

    async def destroy_session(self):
        """Destroy current session"""
        if not self.session_id:
            raise ValueError("No active session")

        if not self._session:
            await self.connect()

        data = await self._request_with_retry(
            "POST",
            f"{self.api_url}/auth/session/destroy",
            json={"session_id": self.session_id},
            headers=self._get_headers()
        )

        self.session_id = None
        logger.info("Session destroyed")
        return data

    async def create_token(self, username: str, password: Optional[str] = None) -> str:
        """Create JWT token"""
        if not self._session:
            await self.connect()

        data = await self._request_with_retry(
            "POST",
            f"{self.api_url}/auth/token",
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"}
        )

        self.jwt_token = data["access_token"]
        logger.info(f"Created token for user {username}")
        return self.jwt_token

    # Workflow operations with proper error handling

    async def submit_workflow(
        self,
        workflow: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> WorkflowResponse:
        """Submit a workflow for execution with authentication"""
        if not self._session:
            await self.connect()

        request_data = {
            "workflow": workflow,
            "workflow_id": workflow_id or str(uuid.uuid4())
        }

        try:
            data = await self._request_with_retry(
                "POST",
                f"{self.api_url}/workflows/submit",
                json=request_data,
                headers=self._get_headers()
            )

            return WorkflowResponse(**data)

        except AuthenticationError:
            # Try to re-authenticate once
            if self.auto_login:
                logger.info("Authentication failed, attempting to re-authenticate...")
                await self.create_session(self.username, self.password)

                # Retry the request
                data = await self._request_with_retry(
                    "POST",
                    f"{self.api_url}/workflows/submit",
                    json=request_data,
                    headers=self._get_headers()
                )

                return WorkflowResponse(**data)
            else:
                raise

        except Exception as e:
            logger.error(f"Failed to submit workflow: {e}")
            raise

    async def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status with authentication"""
        if not self._session:
            await self.connect()

        return await self._request_with_retry(
            "GET",
            f"{self.api_url}/workflows/{workflow_id}",
            headers=self._get_headers()
        )

    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a workflow"""
        if not self._session:
            await self.connect()

        return await self._request_with_retry(
            "POST",
            f"{self.api_url}/workflows/{workflow_id}/cancel",
            headers=self._get_headers()
        )

    # Synchronous wrappers

    def submit_workflow_sync(self, workflow: Dict[str, Any]) -> WorkflowResponse:
        """Synchronous wrapper for submit_workflow"""
        return asyncio.run(self.submit_workflow(workflow))

    def create_session_sync(self, username: str) -> str:
        """Synchronous wrapper for create_session"""
        return asyncio.run(self.create_session(username))
```

## Phase 4: Add Rate Limiting and Security Middleware

### 4.1 Create `src/gleitzeit/api/middleware/security.py`

```python
"""
Security middleware for rate limiting and request tracking.
"""

import time
import uuid
from typing import Dict, Any
from fastapi import Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as aioredis
import logging

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using Redis.
    """

    def __init__(self, app, redis: aioredis.Redis, default_limit: int = 100, window: int = 60):
        super().__init__(app)
        self.redis = redis
        self.default_limit = default_limit
        self.window = window

        # Endpoint-specific limits
        self.endpoint_limits = {
            "/workflows/submit": 10,  # 10 per minute
            "/auth/session/create": 5,  # 5 per minute
            "/auth/token": 5,  # 5 per minute
        }

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path.startswith("/health"):
            return await call_next(request)

        # Get client identifier (IP or user ID)
        client_id = request.client.host if request.client else "unknown"

        # Try to get user ID from headers if authenticated
        if "x-session-id" in request.headers:
            client_id = f"session:{request.headers['x-session-id']}"
        elif request.headers.get("authorization", "").startswith("Bearer "):
            client_id = f"token:{request.headers['authorization'][7:20]}"  # First 13 chars of token

        # Get rate limit for this endpoint
        limit = self.endpoint_limits.get(request.url.path, self.default_limit)

        # Rate limit key
        key = f"rate_limit:{client_id}:{request.url.path}"

        try:
            # Increment counter
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.window)
            results = await pipe.execute()

            request_count = results[0]

            # Check if limit exceeded
            if request_count > limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {limit} requests per {self.window} seconds."
                )

            # Add rate limit headers
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - request_count))
            response.headers["X-RateLimit-Reset"] = str(int(time.time()) + self.window)

            return response

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Don't block request if rate limiting fails
            return await call_next(request)


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """
    Add request ID and timing to all requests.
    """

    async def dispatch(self, request: Request, call_next):
        # Generate request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Track timing
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(time.time() - start_time)

        # Log request
        logger.info(
            f"Request {request_id}: {request.method} {request.url.path} "
            f"-> {response.status_code} ({time.time() - start_time:.3f}s)"
        )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Add CSP for API responses
        if request.url.path.startswith("/api"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none';"

        return response
```

### 4.2 Update `src/gleitzeit/api/main.py`

```python
"""
Enhanced Gleitzeit API with security middleware.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from ..core.sharding import default_sharding
from .pools.client_pool import ClientPool
from .middleware.security import (
    RateLimitMiddleware,
    RequestTrackingMiddleware,
    SecurityHeadersMiddleware
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    logger.info("Starting Gleitzeit API server")

    # Initialize Redis connection
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    app.state.redis = await aioredis.from_url(
        redis_url,
        decode_responses=False
    )

    # Initialize client connection pool
    app.state.client_pool = ClientPool()
    await app.state.client_pool.initialize()

    # Store sharding config
    app.state.sharding = default_sharding

    logger.info("API server initialized successfully")

    yield

    # Cleanup
    logger.info("Shutting down Gleitzeit API server")
    await app.state.client_pool.shutdown()
    await app.state.redis.close()


# Create FastAPI application
app = FastAPI(
    title="Gleitzeit API",
    version="0.0.7-secure",
    description="Secure workflow orchestration API with authentication and rate limiting",
    lifespan=lifespan
)

# Configure CORS properly
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Session-ID", "X-API-Key"],
)

# Add security middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTrackingMiddleware)

# Rate limiting will be added after Redis is initialized
@app.on_event("startup")
async def add_rate_limiting():
    """Add rate limiting middleware after Redis is available"""
    app.add_middleware(
        RateLimitMiddleware,
        redis=app.state.redis,
        default_limit=100,
        window=60
    )


# Import and include routers
from .routes import workflows, tasks, system, health, auth
from .auth.dependencies import init_auth

# Initialize authentication
@app.on_event("startup")
async def startup_event():
    """Initialize authentication on startup"""
    init_auth(app.state.redis)

app.include_router(auth.router, prefix="/auth", tags=["authentication"])
app.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(system.router, prefix="/system", tags=["system"])
app.include_router(health.router, prefix="/health", tags=["health"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Gleitzeit API",
        "version": "0.0.7-secure",
        "status": "operational",
        "features": [
            "authentication",
            "rate_limiting",
            "request_tracking",
            "ownership_management"
        ]
    }
```

## Implementation Timeline

### Phase 1: Core Security (Day 1)
1. Update authentication dependencies ✓
2. Add auto-login functionality ✓
3. Implement session management ✓

### Phase 2: Endpoint Security (Day 2)
1. Secure workflow endpoints ✓
2. Add ownership tracking ✓
3. Implement permission checks ✓

### Phase 3: Client Enhancement (Day 3)
1. Add authentication to client ✓
2. Implement retry logic ✓
3. Add error handling ✓

### Phase 4: Infrastructure (Day 4)
1. Add rate limiting ✓
2. Implement request tracking ✓
3. Add security headers ✓

### Phase 5: Testing & Documentation (Day 5)
1. Write security tests
2. Update API documentation
3. Create migration guide

## Testing Strategy

### Unit Tests
```python
# test_auth.py
async def test_auto_login():
    """Test automatic basic user creation"""
    pass

async def test_session_management():
    """Test session creation and validation"""
    pass

async def test_permission_checks():
    """Test permission enforcement"""
    pass
```

### Integration Tests
```python
# test_workflow_security.py
async def test_workflow_ownership():
    """Test that users can only access their own workflows"""
    pass

async def test_admin_override():
    """Test that admins can access all workflows"""
    pass

async def test_rate_limiting():
    """Test rate limit enforcement"""
    pass
```

## Migration Checklist

- [ ] Backup existing data
- [ ] Update environment variables
- [ ] Deploy authentication dependencies
- [ ] Deploy secured endpoints
- [ ] Update client libraries
- [ ] Test authentication flow
- [ ] Test rate limiting
- [ ] Monitor for issues
- [ ] Update documentation

## Environment Variables

```bash
# Authentication
GLEITZEIT_AUTO_LOGIN=true  # Enable auto-login for development
JWT_SECRET=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_EXPIRATION=3600

# CORS
CORS_ORIGINS=http://localhost:3000,https://app.example.com

# Rate Limiting
RATE_LIMIT_DEFAULT=100
RATE_LIMIT_WINDOW=60

# Redis
REDIS_URL=redis://localhost:6379
```

## Rollback Plan

If issues arise:
1. Revert to previous version
2. Restore environment variables
3. Clear Redis session data
4. Notify users of temporary disruption

## Conclusion

This plan provides a comprehensive approach to reintegrating 0.0.6's proven security model into 0.0.7, while preserving the worker-based architecture. The phased approach ensures minimal disruption while maximizing security improvements.