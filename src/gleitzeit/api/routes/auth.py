"""
Authentication routes
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import redis.asyncio as aioredis

from ..auth.models import User, UserRole, Token, LoginRequest
from ..auth.dependencies import ClientSessionAuth, jwt_manager, init_auth

router = APIRouter()


class SessionResponse(BaseModel):
    """Client session response"""
    session_id: str
    user: User


@router.post("/session/create", response_model=SessionResponse)
async def create_session(
    request: LoginRequest,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """
    Create a client session.

    For development, any username is accepted without password.
    In production, this would validate credentials.
    """

    # Initialize auth if needed
    if not jwt_manager:
        init_auth(redis)

    # Create user (in production, this would validate credentials)
    user = User(
        id=str(uuid.uuid4()),
        username=request.username,
        role=UserRole.USER
    )

    # Create client session
    client_auth = ClientSessionAuth(redis)
    session_id = await client_auth.create_client_session(user)

    return SessionResponse(
        session_id=session_id,
        user=user
    )


@router.post("/session/validate")
async def validate_session(
    session_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Validate a client session"""

    client_auth = ClientSessionAuth(redis)
    user = await client_auth.validate_client_session(session_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )

    return {"valid": True, "user": user}


@router.post("/session/destroy")
async def destroy_session(
    session_id: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Destroy a client session (logout)"""

    client_auth = ClientSessionAuth(redis)
    success = await client_auth.destroy_client_session(session_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    return {"message": "Session destroyed"}


@router.post("/token", response_model=Token)
async def create_token(
    request: LoginRequest,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """
    Create JWT token for user.

    Alternative to client sessions for stateless authentication.
    """

    # Initialize auth if needed
    if not jwt_manager:
        init_auth(redis)

    # Create user (in production, validate credentials)
    user = User(
        id=str(uuid.uuid4()),
        username=request.username,
        role=UserRole.USER
    )

    # Create JWT token
    return jwt_manager.create_access_token(user)


@router.post("/token/refresh")
async def refresh_token(
    refresh_token: str,
    redis: aioredis.Redis = Depends(lambda: app.state.redis)
):
    """Refresh access token using refresh token"""

    if not jwt_manager:
        init_auth(redis)

    new_token = jwt_manager.refresh_access_token(refresh_token)

    if not new_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    return new_token


# Fix circular import
from ..main import app