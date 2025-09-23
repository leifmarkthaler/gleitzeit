"""
Authentication dependencies for FastAPI
"""

import os
from typing import Optional
from fastapi import Depends, HTTPException, Header, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import redis.asyncio as aioredis
import logging

from .models import User, UserRole
from .jwt_manager import JWTManager
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

# Security scheme for OpenAPI docs
security = HTTPBearer(auto_error=False)

# Global instances (initialized in main.py)
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


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> User:
    """
    Get current user from request.

    Priority order:
    1. JWT Bearer token
    2. Client session ID (from header)
    3. API key
    4. Auto-create basic user for development
    """

    # Try JWT token
    if credentials and credentials.credentials:
        payload = jwt_manager.verify_token(credentials.credentials)
        if payload:
            return User(
                id=payload["sub"],
                username=payload.get("username", "unknown"),
                role=payload.get("role", UserRole.USER)
            )

    # Try client session ID
    if client_session_id and session_manager:
        user = await session_manager.get_session(client_session_id)
        if user:
            return user

    # Try API key
    if api_key:
        # TODO: Implement API key validation
        # For now, accept any API key and create service user
        return User(
            id=f"api-{api_key[:8]}",
            username="api-user",
            role=UserRole.SERVICE
        )

    # Auto-create basic user for development
    if os.getenv("GLEITZEIT_AUTO_LOGIN", "true").lower() == "true":
        return User(
            id="dev-user",
            username="developer",
            role=UserRole.USER
        )

    # No valid authentication
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Ensure user is active"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Require admin role"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


async def require_service_account(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Require service account"""
    if current_user.role != UserRole.SERVICE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service account required"
        )
    return current_user


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

    Behavior:
    1. If session/token provided -> validate and return user
    2. If no credentials -> auto-login as basic user
    3. If invalid credentials -> raise 401

    This ensures the system always has a user context while
    allowing switching to real users when credentials provided.
    """

    # Ensure auth is initialized
    if not session_manager:
        init_auth(redis)

    # Try to get session from cookie first
    session_id = request.cookies.get("session_id")

    # Check if we have any credentials
    if session_id or credentials or client_session_id or api_key:
        try:
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
            if session_id:
                user = await session_manager.get_session(session_id)
                if user:
                    return user

            # Try API key
            if api_key:
                # Validate API key from Redis
                api_key_data = await redis.hget(f"api_keys:{api_key}".encode(), b"user_data")
                if api_key_data:
                    import json
                    user_data = json.loads(api_key_data.decode())
                    return User(**user_data)
                else:
                    # For now, accept any API key and create service user
                    return User(
                        id=f"api-{api_key[:8]}",
                        username="api-user",
                        role=UserRole.SERVICE,
                        is_active=True
                    )

            # If we got here, credentials were invalid
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # No credentials provided - auto-create basic user if enabled
    if os.getenv("GLEITZEIT_AUTO_LOGIN", "true").lower() == "true":
        # Create a basic session
        basic_user = User(
            id="basic-user",
            username="basic",
            role=UserRole.USER,
            is_active=True
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


async def require_permission(
    permission: str,
    user: User = Depends(get_current_user_auto)
) -> User:
    """
    Check for specific permission.
    """
    # Define role-based permissions
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


class ClientSessionAuth:
    """
    Client session authentication for SDK clients.

    This is what 0.0.6 was planning - clients maintain their own session ID
    and send it with each request in a header.
    """

    def __init__(self, redis: aioredis.Redis):
        self.session_manager = SessionManager(redis)

    async def create_client_session(self, user: User) -> str:
        """Create a new client session and return session ID"""
        session = await self.session_manager.create_session(user)
        return session.session_id

    async def validate_client_session(self, session_id: str) -> Optional[User]:
        """Validate client session ID"""
        return await self.session_manager.get_session(session_id)

    async def destroy_client_session(self, session_id: str) -> bool:
        """Destroy client session"""
        return await self.session_manager.delete_session(session_id)