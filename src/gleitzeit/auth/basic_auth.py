"""
Basic authentication mode for Gleitzeit

Provides a simple, no-login-required authentication mode using a default "basic" user.
This allows data isolation between different auth modes while maintaining ease of use.
"""

import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import jwt
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# Configuration
BASIC_USER_ID = "basic-user"
BASIC_USER_EMAIL = "basic@localhost"
BASIC_USER_NAME = "Basic User"
BASIC_USER_ROLE = "user"

class BasicAuthMode:
    """
    Handles basic authentication mode where a default user is automatically used.
    No login required, but still provides user context for data isolation.
    """
    
    def __init__(self):
        self.auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
        self.secret_key = os.getenv("GLEITZEIT_SECRET_KEY", "basic-mode-default-secret-key")
        self.algorithm = "HS256"
        self.token_expiry_hours = 24 * 365  # 1 year for basic mode tokens
        
    def is_basic_mode(self) -> bool:
        """Check if running in basic auth mode"""
        return self.auth_mode == "basic"
    
    def is_admin_mode(self) -> bool:
        """Check if running in full/admin auth mode"""
        return self.auth_mode in ["admin", "full", "advanced"]
    
    def get_basic_user(self) -> Dict[str, Any]:
        """Get the basic user object"""
        return {
            "id": BASIC_USER_ID,
            "email": BASIC_USER_EMAIL,
            "name": BASIC_USER_NAME,
            "role": BASIC_USER_ROLE,
            "is_basic_user": True,
            "permissions": [
                # Core functionality permissions
                "workflows:create",
                "workflows:read", 
                "workflows:update",
                "workflows:delete",
                "tasks:create",
                "tasks:read",
                "tasks:update", 
                "tasks:delete",
                "queues:read",
                "queues:manage",
                "logs:read",
                "system:read",
                # Explicitly NO admin permissions like:
                # - users:create/delete/update
                # - roles:manage
                # - system:configure
                # - auth:manage
            ],
            "is_superuser": False,  # Not a superuser
            "created_at": datetime.utcnow().isoformat()
        }
    
    def create_basic_token(self) -> str:
        """Create a JWT token for the basic user"""
        user = self.get_basic_user()
        payload = {
            "sub": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "is_basic_user": True,
            "exp": datetime.utcnow() + timedelta(hours=self.token_expiry_hours),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def verify_basic_token(self, token: str) -> Dict[str, Any]:
        """Verify a basic mode token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            # In basic mode, always return the basic user regardless of token content
            if self.is_basic_mode():
                return self.get_basic_user()
            return payload
        except jwt.ExpiredSignatureError:
            # In basic mode, create a new token automatically
            if self.is_basic_mode():
                return self.get_basic_user()
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            # In basic mode, return basic user anyway
            if self.is_basic_mode():
                return self.get_basic_user()
            raise HTTPException(status_code=401, detail="Invalid token")
    
    async def get_current_user(self, request: Request) -> Dict[str, Any]:
        """
        Get the current user from request.
        In basic mode, always returns the basic user.
        In admin mode, requires valid authentication.
        """
        if self.is_basic_mode():
            # Always return basic user in basic mode
            return self.get_basic_user()
        
        # In admin mode, check for real authentication
        if hasattr(request.state, "user") and request.state.user:
            return request.state.user
        
        # Try to get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            return self.verify_basic_token(token)
        
        # No auth in admin mode
        raise HTTPException(status_code=401, detail="Authentication required")


# Global instance
basic_auth = BasicAuthMode()


def get_auth_mode() -> str:
    """Get current authentication mode"""
    return basic_auth.auth_mode


def is_basic_mode() -> bool:
    """Check if running in basic auth mode"""
    return basic_auth.is_basic_mode()


def is_admin_mode() -> bool:
    """Check if running in admin auth mode"""
    return basic_auth.is_admin_mode()


async def inject_basic_user(request: Request) -> None:
    """
    Middleware helper to inject basic user into request state.
    Called by the authentication middleware.
    """
    if is_basic_mode() and not hasattr(request.state, "user"):
        request.state.user = basic_auth.get_basic_user()


def create_basic_auth_response() -> Dict[str, Any]:
    """
    Create an auth response for basic mode.
    Used by login endpoints in basic mode.
    """
    if not is_basic_mode():
        raise HTTPException(
            status_code=400, 
            detail="Basic auth response only available in basic mode"
        )
    
    return {
        "access_token": basic_auth.create_basic_token(),
        "token_type": "bearer",
        "user": basic_auth.get_basic_user(),
        "mode": "basic",
        "message": "Automatic login as basic user"
    }


def check_admin_required(func):
    """
    Decorator to check if admin mode is required for certain operations.
    Used for user management, role assignment, etc.
    """
    async def wrapper(*args, **kwargs):
        if is_basic_mode():
            raise HTTPException(
                status_code=403,
                detail="This operation requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
            )
        return await func(*args, **kwargs)
    return wrapper