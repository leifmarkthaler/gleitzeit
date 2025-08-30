"""
Middleware for authentication, error handling, and logging.
"""

import time
import logging
import traceback
from typing import Optional, Callable
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware that validates tokens and sets user context.
    """
    
    def __init__(self, app: ASGIApp, auth_mode: str = "basic"):
        super().__init__(app)
        self.auth_mode = auth_mode
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process authentication for each request."""
        
        # Skip auth for public endpoints
        public_paths = ["/", "/health", "/docs", "/openapi.json", "/auth/login", "/auth/register"]
        if any(request.url.path.startswith(path) for path in public_paths):
            return await call_next(request)
        
        # In basic mode, assign default user if no headers
        if self.auth_mode == "basic":
            if not request.headers.get("X-User-ID"):
                # Add basic user headers
                request.state.user_id = "basic_user"
                request.state.user_role = "user"
                # Modify headers (create new scope for request)
                headers = dict(request.headers)
                headers["x-user-id"] = "basic_user"
                headers["x-user-role"] = "user"
                request._headers = headers
        
        # In strict mode, require authentication
        elif self.auth_mode == "strict":
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"}
                )
            
            # TODO: Validate JWT token and set user context
            # For now, just check if token exists
            token = auth_header.replace("Bearer ", "")
            if not token:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid authentication credentials"}
                )
            
            # Set user context (would normally decode JWT)
            request.state.user_id = "authenticated_user"
            request.state.user_role = "user"
        
        response = await call_next(request)
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Global error handling middleware that catches and formats exceptions.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Catch and handle errors."""
        try:
            response = await call_next(request)
            return response
            
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware to prevent abuse.
    """
    
    def __init__(self, app: ASGIApp, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts = {}  # Simple in-memory store (use Redis in production)
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limits."""
        
        # Get client identifier
        client_id = request.client.host if request.client else "unknown"
        if hasattr(request.state, "user_id"):
            client_id = request.state.user_id
        
        # Check rate limit
        current_minute = int(time.time() / 60)
        key = f"{client_id}:{current_minute}"
        
        # Get current count
        count = self.request_counts.get(key, 0)
        
        # Check if limit exceeded
        if count >= self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"}
            )
        
        # Increment count
        self.request_counts[key] = count + 1
        
        # Clean old entries (simple cleanup)
        if len(self.request_counts) > 1000:
            old_minute = current_minute - 2
            keys_to_delete = [k for k in self.request_counts if int(k.split(":")[1]) < old_minute]
            for k in keys_to_delete:
                del self.request_counts[k]
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(self.requests_per_minute - count - 1)
        response.headers["X-RateLimit-Reset"] = str((current_minute + 1) * 60)
        
        return response