"""
Authentication middleware for FastAPI
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPBasic
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .utils import (
    parse_bearer_token,
    parse_basic_auth,
    decode_jwt_token,
    hash_api_key,
    verify_password
)
from .database import get_auth_db
from .basic_auth import basic_auth, is_basic_mode, is_admin_mode

logger = logging.getLogger(__name__)


class AuthConfig:
    """Authentication configuration"""
    def __init__(self):
        # Auth is ALWAYS enabled now, but mode determines behavior
        self.auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
        self.enabled = True  # Always enabled for data isolation
        self.jwt_secret = os.getenv("GLEITZEIT_AUTH_JWT_SECRET", "change-me-in-production")
        self.jwt_algorithm = os.getenv("GLEITZEIT_AUTH_JWT_ALGORITHM", "HS256")
        self.api_key_header = os.getenv("GLEITZEIT_AUTH_API_KEY_HEADER", "X-API-Key")
        self.require_auth_for_reads = os.getenv("GLEITZEIT_AUTH_REQUIRE_FOR_READS", "false").lower() == "true"
        self.allow_anonymous = os.getenv("GLEITZEIT_AUTH_ALLOW_ANONYMOUS", "true").lower() == "true"


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware that validates requests
    """
    
    def __init__(self, app, config: Optional[AuthConfig] = None):
        super().__init__(app)
        self.config = config or AuthConfig()
        self.auth_db = None
        
        # Paths that never require authentication
        self.public_paths = {
            "/health",
            "/",
            "/auth/login",
            "/auth/register",
            "/auth/forgot-password",
            "/docs",
            "/redoc",
            "/openapi.json"
        }
        
        # Read-only paths
        self.read_only_paths = {
            "GET": [
                "/status",
                "/statistics",
                "/providers",
                "/protocols"
            ]
        }
    
    async def dispatch(self, request: Request, call_next):
        """Process request through authentication"""
        
        # In basic mode, always use the basic user
        if is_basic_mode():
            request.state.user = basic_auth.get_basic_user()
            return await call_next(request)
        
        # Check if path requires authentication
        path = request.url.path
        method = request.method
        
        # Public paths don't require auth
        if path in self.public_paths:
            request.state.user = None
            return await call_next(request)
        
        # Try to authenticate the request
        user = await self.authenticate_request(request)
        
        # Check if authentication is required
        if not user:
            # Allow anonymous for read-only operations if configured
            if self.config.allow_anonymous and method == "GET":
                request.state.user = {
                    "id": "anonymous",
                    "email": "anonymous@localhost", 
                    "roles": ["viewer"],
                    "is_superuser": False,
                    "auth_method": "anonymous"
                }
                return await call_next(request)
            
            # Authentication required
            return self.unauthorized_response()
        
        # Set authenticated user
        request.state.user = user
        
        # Log authentication
        await self.log_access(request, user)
        
        # Continue with request
        response = await call_next(request)
        return response
    
    async def authenticate_request(self, request: Request) -> Optional[Dict[str, Any]]:
        """
        Try to authenticate the request using various methods
        
        Returns:
            User dict if authenticated, None otherwise
        """
        
        # 1. Check for API key in header
        api_key = request.headers.get(self.config.api_key_header)
        if api_key:
            user = await self.validate_api_key(api_key)
            if user:
                user["auth_method"] = "api_key"
                return user
        
        # 2. Check for Bearer token (JWT)
        auth_header = request.headers.get("Authorization", "")
        token = parse_bearer_token(auth_header)
        if token:
            user = await self.validate_jwt_token(token)
            if user:
                user["auth_method"] = "jwt"
                return user
        
        # 3. Check for Basic authentication
        basic_auth = parse_basic_auth(auth_header)
        if basic_auth:
            username, password = basic_auth
            user = await self.validate_basic_auth(username, password)
            if user:
                user["auth_method"] = "basic"
                return user
        
        # 4. Check for session cookie
        session_token = request.cookies.get("gleitzeit_session")
        if session_token:
            user = await self.validate_session(session_token)
            if user:
                user["auth_method"] = "session"
                return user
        
        return None
    
    async def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Validate API key and return user data"""
        try:
            # Get database connection
            if not self.auth_db:
                self.auth_db = get_auth_db()
            
            # Hash the API key
            key_hash = hash_api_key(api_key)
            
            # Look up in database
            api_key_record = await self.auth_db.get_api_key_by_hash(key_hash)
            if not api_key_record:
                return None
            
            # Check if key is valid
            if not api_key_record.is_valid:
                return None
            
            # Update last used timestamp
            await self.auth_db.update_api_key_last_used(api_key_record.id)
            
            # Get user
            user = await self.auth_db.get_user(api_key_record.user_id)
            if not user or not user.is_active:
                return None
            
            # Build user dict
            return {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "roles": [role.name for role in user.roles],
                "is_superuser": user.is_superuser,
                "permissions": user.permissions,
                "api_key_id": str(api_key_record.id),
                "api_key_scopes": api_key_record.scopes or []
            }
        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            return None
    
    async def validate_jwt_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate JWT token and return user data"""
        try:
            # Decode token
            payload = decode_jwt_token(
                token,
                self.config.jwt_secret,
                algorithms=[self.config.jwt_algorithm]
            )
            
            if not payload:
                return None
            
            # Check token type
            if payload.get("type") != "access":
                return None
            
            # Get fresh user data from database if needed
            if self.auth_db:
                user = await self.auth_db.get_user(payload.get("sub"))
                if user and user.is_active:
                    return {
                        "id": str(user.id),
                        "email": user.email,
                        "username": user.username,
                        "roles": [role.name for role in user.roles],
                        "is_superuser": user.is_superuser,
                        "permissions": user.permissions
                    }
            
            # Return token data if no database
            return {
                "id": payload.get("sub"),
                "email": payload.get("email"),
                "username": payload.get("username"),
                "roles": payload.get("roles", []),
                "is_superuser": payload.get("is_superuser", False)
            }
        except Exception as e:
            logger.error(f"Error validating JWT: {e}")
            return None
    
    async def validate_basic_auth(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Validate basic authentication"""
        try:
            if not self.auth_db:
                self.auth_db = get_auth_db()
            
            # Find user by email or username
            user = await self.auth_db.get_user_by_email(username)
            if not user:
                user = await self.auth_db.get_user_by_username(username)
            
            if not user or not user.is_active:
                return None
            
            # Verify password
            if not user.password_hash or not verify_password(password, user.password_hash):
                return None
            
            # Update last login
            await self.auth_db.update_user_last_login(user.id)
            
            return {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "roles": [role.name for role in user.roles],
                "is_superuser": user.is_superuser,
                "permissions": user.permissions
            }
        except Exception as e:
            logger.error(f"Error validating basic auth: {e}")
            return None
    
    async def validate_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """Validate session token"""
        try:
            if not self.auth_db:
                self.auth_db = get_auth_db()
            
            # Hash the session token
            token_hash = hash_api_key(session_token)  # Reuse same hash function
            
            # Look up session
            session = await self.auth_db.get_session_by_token_hash(token_hash)
            if not session or not session.is_valid:
                return None
            
            # Update last activity
            await self.auth_db.update_session_activity(session.id)
            
            # Get user
            user = await self.auth_db.get_user(session.user_id)
            if not user or not user.is_active:
                return None
            
            return {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "roles": [role.name for role in user.roles],
                "is_superuser": user.is_superuser,
                "permissions": user.permissions,
                "session_id": str(session.id)
            }
        except Exception as e:
            logger.error(f"Error validating session: {e}")
            return None
    
    async def log_access(self, request: Request, user: Dict[str, Any]):
        """Log access for audit trail"""
        try:
            if self.auth_db:
                await self.auth_db.create_audit_log(
                    user_id=user.get("id"),
                    action="api_access",
                    resource_type="endpoint",
                    resource_id=f"{request.method} {request.url.path}",
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("User-Agent"),
                    details={
                        "method": request.method,
                        "path": request.url.path,
                        "auth_method": user.get("auth_method")
                    }
                )
        except Exception as e:
            logger.error(f"Error logging access: {e}")
    
    def unauthorized_response(self) -> Response:
        """Return 401 Unauthorized response"""
        return Response(
            content='{"detail": "Authentication required"}',
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            media_type="application/json"
        )


# Security scheme for FastAPI docs
security = HTTPBearer(auto_error=False)