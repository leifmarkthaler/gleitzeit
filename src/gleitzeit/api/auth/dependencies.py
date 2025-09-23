"""
Authentication dependencies for FastAPI
"""

import os
from typing import Optional
from fastapi import Depends, HTTPException, Header, status
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