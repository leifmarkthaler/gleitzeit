"""
Middleware for authentication, error handling, and logging.
"""

import time
import logging
import traceback
import asyncio
from typing import Optional, Callable
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from gleitzeit.core.errors import SystemError, ErrorCode, GleitzeitError
from .error_handler import gleitzeit_error_to_http

logger = logging.getLogger(__name__)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware that validates tokens and sets user context.
    Uses SystemManager's stateless AuthManager for authentication.
    """
    
    def __init__(self, app: ASGIApp, auth_mode: str = "basic", system_manager=None):
        super().__init__(app)
        self.auth_mode = auth_mode
        self.system_manager = system_manager
        self.auth_manager = system_manager.auth_manager if system_manager else None
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process authentication for each request using stateless AuthManager."""
        
        # Skip middleware for WebSocket connections
        # WebSocket auth is handled in the WebSocket endpoints themselves
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        
        # Skip auth for public endpoints
        public_paths = ["/", "/health", "/docs", "/openapi.json", "/auth/login", "/auth/register"]
        if any(request.url.path.startswith(path) for path in public_paths):
            return await call_next(request)
        
        # Try to get user from session cookie or bearer token
        user = None
        
        # Check for session cookie first (stateless session)
        session_id = request.cookies.get("session_id")
        if session_id and self.auth_manager:
            try:
                # Get user from stateless session store
                user = await self.auth_manager.get_current_user(session_id)
            except SystemError:
                # Session invalid or expired
                pass
        
        # Check for Bearer token if no session
        if not user:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer ") and self.auth_manager:
                token = auth_header.replace("Bearer ", "")
                try:
                    # Validate token using stateless AuthManager
                    user = await self.auth_manager.validate_session(token)
                except SystemError:
                    # Token invalid or expired
                    pass
        
        # Handle based on auth mode
        if self.auth_mode == "basic":
            # In basic mode, use basic user if no auth provided
            if not user:
                if self.auth_manager:
                    user = self.auth_manager.basic_user
                else:
                    # Fallback basic user
                    user = {
                        "id": "basic-user",
                        "username": "basic",
                        "role": "user"
                    }
            
            # Set user context
            request.state.user = user
            request.state.user_id = user.get("id")
            request.state.user_role = user.get("role", "user")
            
        elif self.auth_mode in ["strict", "advanced", "admin"]:
            # In strict mode, require valid authentication
            if not user:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"}
                )
            
            # Set user context
            request.state.user = user
            request.state.user_id = user.get("id")
            request.state.user_role = user.get("role", "user")
        
        response = await call_next(request)
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Global error handling middleware that catches and formats exceptions.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Catch and handle errors."""
        # Skip for WebSocket connections
        if request.scope.get("type") == "websocket":
            return await call_next(request)
            
        try:
            response = await call_next(request)
            return response
            
        except GleitzeitError as exc:
            # Handle Gleitzeit errors with proper mapping
            http_exc = gleitzeit_error_to_http(exc)
            return JSONResponse(
                status_code=http_exc.status_code,
                content={"detail": http_exc.detail}
            )
            
        except HTTPException as exc:
            # Let HTTPExceptions pass through (they're already formatted)
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail}
            )
            
        except ValueError as exc:
            # Handle validation errors
            logger.warning(f"Validation error: {exc}")
            return JSONResponse(
                status_code=400,
                content={"detail": str(exc)}
            )
            
        except PermissionError as exc:
            # Handle permission errors
            logger.warning(f"Permission denied: {exc}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Permission denied"}
            )
            
        except FileNotFoundError as exc:
            # Handle not found errors
            logger.warning(f"Resource not found: {exc}")
            return JSONResponse(
                status_code=404,
                content={"detail": "Resource not found"}
            )
            
        except TimeoutError as exc:
            # Handle timeout errors
            logger.error(f"Request timeout: {exc}")
            return JSONResponse(
                status_code=504,
                content={"detail": "Request timeout"}
            )
            
        except Exception as exc:
            # Handle unexpected errors
            logger.error(f"Unexpected error: {exc}\n{traceback.format_exc()}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Request/response logging middleware.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response details."""
        
        # Skip for WebSocket connections
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        
        # Start timing
        start_time = time.time()
        
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Log response
        logger.info(
            f"Response: {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration:.3f}s"
        )
        
        # Add timing header
        response.headers["X-Process-Time"] = str(duration)
        
        return response


class CORSMiddleware(BaseHTTPMiddleware):
    """
    CORS middleware for cross-origin requests.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        allow_origins: list = ["*"],
        allow_methods: list = ["*"],
        allow_headers: list = ["*"],
        allow_credentials: bool = True
    ):
        super().__init__(app)
        self.allow_origins = allow_origins
        self.allow_methods = allow_methods
        self.allow_headers = allow_headers
        self.allow_credentials = allow_credentials
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle CORS headers."""
        
        # Handle preflight requests
        if request.method == "OPTIONS":
            response = Response(content="", status_code=200)
        else:
            response = await call_next(request)
        
        # Add CORS headers
        origin = request.headers.get("origin", "*")
        if origin in self.allow_origins or "*" in self.allow_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = str(self.allow_credentials).lower()
            response.headers["Access-Control-Allow-Methods"] = ", ".join(self.allow_methods)
            response.headers["Access-Control-Allow-Headers"] = ", ".join(self.allow_headers)
        
        return response


class RequestCleanupMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures request cleanup tasks are executed.
    
    This handles cleanup for any per-request resources like clients
    that were created during request processing.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and ensure cleanup."""
        # Skip for WebSocket connections
        if request.scope.get("type") == "websocket":
            return await call_next(request)
            
        try:
            # Process the request
            response = await call_next(request)
            return response
        finally:
            # Run any cleanup tasks registered during the request
            if hasattr(request.state, 'cleanup_tasks'):
                for cleanup_task in request.state.cleanup_tasks:
                    try:
                        if asyncio.iscoroutinefunction(cleanup_task):
                            await cleanup_task()
                        else:
                            cleanup_task()
                    except Exception as e:
                        logger.error(f"Error during request cleanup: {e}")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware to prevent abuse.
    
    Uses persistence layer (Redis or InMemory) for stateless operation across instances.
    """
    
    def __init__(self, app: ASGIApp, requests_per_minute: int = 60, persistence=None):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.persistence = persistence
        self.rate_limit_prefix = "ratelimit"
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limits using persistence layer."""
        
        # Skip rate limiting if no persistence configured
        if not self.persistence:
            logger.warning("Rate limiting disabled - no persistence configured")
            return await call_next(request)
        
        # Get client identifier
        client_id = request.client.host if request.client else "unknown"
        if hasattr(request.state, "user_id"):
            client_id = request.state.user_id
        
        # Build rate limit key
        current_minute = int(time.time() / 60)
        key = f"{self.rate_limit_prefix}:{client_id}:{current_minute}"
        
        try:
            # Get current count from persistence
            current_count = await self._get_rate_limit_count(key)
            
            # Check if limit exceeded
            if current_count >= self.requests_per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"X-RateLimit-Limit": str(self.requests_per_minute),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str((current_minute + 1) * 60)}
                )
            
            # Increment count in persistence
            new_count = await self._increment_rate_limit(key)
            
            # Process request
            response = await call_next(request)
            
            # Add rate limit headers
            response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(max(0, self.requests_per_minute - new_count))
            response.headers["X-RateLimit-Reset"] = str((current_minute + 1) * 60)
            
            return response
            
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # On error, allow request but log the issue
            return await call_next(request)
    
    async def _get_rate_limit_count(self, key: str) -> int:
        """Get current rate limit count from persistence."""
        try:
            # Try to get from hash (Redis-like interface)
            if hasattr(self.persistence, 'hget'):
                value = await self.persistence.hget(key, "count")
                return int(value) if value else 0
            # Fallback to simple get
            elif hasattr(self.persistence, 'get'):
                value = await self.persistence.get(key)
                return int(value) if value else 0
            else:
                return 0
        except Exception:
            return 0
    
    async def _increment_rate_limit(self, key: str) -> int:
        """Increment rate limit count in persistence."""
        try:
            # Try to use atomic increment (Redis INCR)
            if hasattr(self.persistence, 'incr'):
                new_count = await self.persistence.incr(key)
                # Set expiry to 2 minutes (cleanup old entries)
                if hasattr(self.persistence, 'expire'):
                    await self.persistence.expire(key, 120)
                return new_count
            # Try hash increment
            elif hasattr(self.persistence, 'hincrby'):
                new_count = await self.persistence.hincrby(key, "count", 1)
                if hasattr(self.persistence, 'expire'):
                    await self.persistence.expire(key, 120)
                return new_count
            # Fallback to get/set
            else:
                current = await self._get_rate_limit_count(key)
                new_count = current + 1
                if hasattr(self.persistence, 'set'):
                    await self.persistence.set(key, str(new_count))
                return new_count
        except Exception as e:
            logger.error(f"Failed to increment rate limit: {e}")
            return 0