"""
Security middleware for rate limiting and request tracking.
"""

import time
import uuid
from typing import Dict, Any
from fastapi import Request, Response, HTTPException
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

        # Endpoint-specific limits (requests per minute)
        self.endpoint_limits = {
            "/workflows/submit": 10,  # 10 per minute
            "/auth/session/create": 5,  # 5 per minute
            "/auth/token": 5,  # 5 per minute
            "/tasks": 50,  # 50 per minute for task operations
            "/system": 20,  # 20 per minute for system operations
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
            # Use first part of token as identifier
            token = request.headers["authorization"][7:]
            client_id = f"token:{token[:20]}"  # First 20 chars of token
        elif "x-api-key" in request.headers:
            client_id = f"api:{request.headers['x-api-key']}"

        # Get rate limit for this endpoint
        path = request.url.path
        limit = self.default_limit

        # Find matching endpoint limit
        for endpoint_pattern, endpoint_limit in self.endpoint_limits.items():
            if path.startswith(endpoint_pattern):
                limit = endpoint_limit
                break

        # Rate limit key
        key = f"rate_limit:{client_id}:{path}".encode()

        try:
            # Use pipeline for atomic operations
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.window)
            results = await pipe.execute()

            request_count = results[0]

            # Check if limit exceeded
            if request_count > limit:
                # Get remaining time
                ttl = await self.redis.ttl(key)

                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {limit} requests per {self.window} seconds.",
                    headers={
                        "Retry-After": str(ttl if ttl > 0 else self.window),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time.time()) + ttl)
                    }
                )

            # Process request
            response = await call_next(request)

            # Add rate limit headers
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

        # Log incoming request
        logger.info(f"Request {request_id}: {request.method} {request.url.path}")

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration:.3f}"

        # Log completion
        logger.info(
            f"Request {request_id} completed: "
            f"{request.method} {request.url.path} -> {response.status_code} ({duration:.3f}s)"
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

        # Add Strict-Transport-Security for HTTPS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Add CSP for API responses
        if request.url.path.startswith("/api") or request.url.path.startswith("/workflows") or request.url.path.startswith("/tasks"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none';"

        return response


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Audit log for sensitive operations.
    """

    def __init__(self, app, redis: aioredis.Redis):
        super().__init__(app)
        self.redis = redis

        # Operations to audit
        self.audit_paths = {
            "/workflows/submit": "workflow_submit",
            "/workflows/{}/cancel": "workflow_cancel",
            "/tasks/{}/retry": "task_retry",
            "/auth/session/create": "session_create",
            "/auth/session/destroy": "session_destroy",
            "/auth/token": "token_create",
        }

    async def dispatch(self, request: Request, call_next):
        # Check if this path should be audited
        should_audit = False
        audit_action = None

        for path_pattern, action in self.audit_paths.items():
            if self._matches_pattern(request.url.path, path_pattern):
                should_audit = True
                audit_action = action
                break

        if not should_audit:
            return await call_next(request)

        # Extract user information
        user_id = "anonymous"
        if hasattr(request.state, "user"):
            user_id = request.state.user.id
        elif "x-session-id" in request.headers:
            user_id = f"session:{request.headers['x-session-id']}"

        # Process request
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        # Create audit log entry
        audit_entry = {
            "timestamp": time.time(),
            "request_id": getattr(request.state, "request_id", "unknown"),
            "action": audit_action,
            "user_id": user_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration": duration,
            "client_ip": request.client.host if request.client else "unknown",
        }

        # Store in Redis stream for audit log
        try:
            await self.redis.xadd(
                b"audit:log",
                {k.encode(): str(v).encode() for k, v in audit_entry.items()},
                maxlen=100000  # Keep last 100k entries
            )
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

        return response

    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern with {} placeholders"""
        # Simple pattern matching - replace {} with wildcard
        import re
        pattern_regex = pattern.replace("{}", r"[^/]+")
        return bool(re.match(f"^{pattern_regex}$", path))


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """
    IP whitelist middleware for admin endpoints.
    """

    def __init__(self, app, whitelist: list = None):
        super().__init__(app)
        self.whitelist = whitelist or []

        # Endpoints that require IP whitelist
        self.protected_paths = [
            "/admin",
            "/system/shutdown",
            "/system/config",
        ]

    async def dispatch(self, request: Request, call_next):
        # Check if path is protected
        is_protected = any(
            request.url.path.startswith(path)
            for path in self.protected_paths
        )

        if not is_protected:
            return await call_next(request)

        # Get client IP
        client_ip = request.client.host if request.client else None

        # Check whitelist
        if not client_ip or client_ip not in self.whitelist:
            logger.warning(f"Blocked access to {request.url.path} from {client_ip}")
            raise HTTPException(
                status_code=403,
                detail="Access denied from this IP address"
            )

        return await call_next(request)