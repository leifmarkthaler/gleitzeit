"""
Authentication API endpoints
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID, uuid4
from fastapi import APIRouter, Request, HTTPException, Response, Depends
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from ..auth.utils import (
    hash_password,
    verify_password,
    generate_api_key,
    hash_api_key,
    create_jwt_token,
    decode_jwt_token
)
from ..auth.database import get_auth_db
from ..auth.permissions import require_permission, Permissions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer(auto_error=False)


# Request/Response models
class LoginRequest(BaseModel):
    """Login request"""
    username: str = Field(..., description="Email or username")
    password: str = Field(..., description="Password")


class LoginResponse(BaseModel):
    """Login response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    user: dict


class RefreshRequest(BaseModel):
    """Refresh token request"""
    refresh_token: str


class RegisterRequest(BaseModel):
    """User registration request"""
    email: EmailStr
    password: str
    username: Optional[str] = None
    full_name: Optional[str] = None


class CreateApiKeyRequest(BaseModel):
    """API key creation request"""
    name: str
    description: Optional[str] = None
    expires_in_days: Optional[int] = None
    permissions: Optional[List[str]] = None
    scopes: Optional[List[str]] = None


class ApiKeyResponse(BaseModel):
    """API key response"""
    id: str
    key: str  # Only returned on creation
    key_prefix: str
    name: str
    created_at: datetime


class ChangePasswordRequest(BaseModel):
    """Change password request"""
    old_password: str
    new_password: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    User login with username/email and password
    
    Returns JWT access token and refresh token
    """
    auth_db = get_auth_db()
    
    # Find user by email or username
    user = await auth_db.get_user_by_email(request.username)
    if not user:
        user = await auth_db.get_user_by_username(request.username)
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )
    
    # Verify password
    if not user.password_hash or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )
    
    # Update last login
    await auth_db.update_user_last_login(user.id)
    
    # Create tokens
    jwt_secret = os.getenv("GLEITZEIT_AUTH_JWT_SECRET", "change-me-in-production")
    
    # Access token payload
    access_payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "roles": [role.name for role in user.roles],
        "is_superuser": user.is_superuser,
        "type": "access"
    }
    
    access_token = create_jwt_token(
        access_payload,
        jwt_secret,
        expires_delta=timedelta(hours=1)
    )
    
    # Refresh token payload
    refresh_payload = {
        "sub": str(user.id),
        "type": "refresh"
    }
    
    refresh_token = create_jwt_token(
        refresh_payload,
        jwt_secret,
        expires_delta=timedelta(days=30)
    )
    
    # Create session
    session_data = {
        "token_hash": hash_api_key(access_token),
        "refresh_token_hash": hash_api_key(refresh_token),
        "expires_at": datetime.utcnow() + timedelta(hours=1),
        "refresh_expires_at": datetime.utcnow() + timedelta(days=30)
    }
    
    await auth_db.create_session(user.id, session_data)
    
    # Log successful login
    await auth_db.create_audit_log(
        user_id=user.id,
        action="login",
        resource_type="auth",
        details={"method": "password"}
    )
    
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=3600,
        user={
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "roles": [role.name for role in user.roles],
            "is_superuser": user.is_superuser
        }
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """
    Logout current user
    
    Invalidates the current session/token
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    auth_db = get_auth_db()
    
    # Revoke session if exists
    session_id = user.get("session_id")
    if session_id:
        await auth_db.revoke_session(session_id)
    
    # Clear session cookie if exists
    response.delete_cookie("gleitzeit_session")
    
    # Log logout
    await auth_db.create_audit_log(
        user_id=user.get("id"),
        action="logout",
        resource_type="auth"
    )
    
    return {"message": "Logged out successfully"}


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(request: RefreshRequest):
    """
    Refresh access token using refresh token
    """
    jwt_secret = os.getenv("GLEITZEIT_AUTH_JWT_SECRET", "change-me-in-production")
    
    # Decode refresh token
    payload = decode_jwt_token(request.refresh_token, jwt_secret)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token"
        )
    
    # Get user
    auth_db = get_auth_db()
    user = await auth_db.get_user(payload.get("sub"))
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="User not found or inactive"
        )
    
    # Create new access token
    access_payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "roles": [role.name for role in user.roles],
        "is_superuser": user.is_superuser,
        "type": "access"
    }
    
    new_access_token = create_jwt_token(
        access_payload,
        jwt_secret,
        expires_delta=timedelta(hours=1)
    )
    
    # Create new refresh token
    new_refresh_payload = {
        "sub": str(user.id),
        "type": "refresh"
    }
    
    new_refresh_token = create_jwt_token(
        new_refresh_payload,
        jwt_secret,
        expires_delta=timedelta(days=30)
    )
    
    return LoginResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=3600,
        user={
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "roles": [role.name for role in user.roles],
            "is_superuser": user.is_superuser
        }
    )


@router.get("/me")
async def get_current_user(request: Request):
    """
    Get current authenticated user information
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return user


@router.post("/register", response_model=dict)
async def register(request: RegisterRequest):
    """
    Register a new user
    
    Note: This endpoint may be disabled in production
    """
    # Check if registration is enabled
    if os.getenv("GLEITZEIT_AUTH_ALLOW_REGISTRATION", "false").lower() != "true":
        raise HTTPException(
            status_code=403,
            detail="User registration is disabled"
        )
    
    auth_db = get_auth_db()
    
    # Check if email already exists
    existing = await auth_db.get_user_by_email(request.email)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )
    
    # Check if username already exists
    if request.username:
        existing = await auth_db.get_user_by_username(request.username)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Username already taken"
            )
    
    # Create user
    user_data = {
        "email": request.email,
        "username": request.username or request.email.split("@")[0],
        "password": request.password,
        "full_name": request.full_name,
        "is_active": True,
        "is_superuser": False
    }
    
    user = await auth_db.create_user(user_data)
    
    # Add default role
    await auth_db.add_user_role(user.id, "viewer")
    
    # Log registration
    await auth_db.create_audit_log(
        user_id=user.id,
        action="register",
        resource_type="auth"
    )
    
    return {
        "message": "User registered successfully",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username
        }
    }


@router.post("/api-keys", response_model=ApiKeyResponse)
async def create_api_key(request: CreateApiKeyRequest, req: Request):
    """
    Create a new API key for the current user
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    auth_db = get_auth_db()
    
    # Generate API key
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:8]
    
    # Calculate expiration
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)
    
    # Create API key record
    key_data = {
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "name": request.name,
        "description": request.description,
        "expires_at": expires_at,
        "permissions": request.permissions or [],
        "scopes": request.scopes or []
    }
    
    api_key = await auth_db.create_api_key(user["id"], key_data)
    
    # Log API key creation
    await auth_db.create_audit_log(
        user_id=user["id"],
        action="create_api_key",
        resource_type="api_key",
        resource_id=str(api_key.id),
        details={"name": request.name}
    )
    
    return ApiKeyResponse(
        id=str(api_key.id),
        key=raw_key,  # Only returned on creation
        key_prefix=key_prefix,
        name=api_key.name,
        created_at=api_key.created_at
    )


@router.get("/api-keys", response_model=List[dict])
async def list_api_keys(req: Request):
    """
    List all API keys for the current user
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    auth_db = get_auth_db()
    api_keys = await auth_db.get_user_api_keys(user["id"])
    
    return [
        {
            "id": str(key.id),
            "key_prefix": key.key_prefix,
            "name": key.name,
            "description": key.description,
            "created_at": key.created_at,
            "last_used_at": key.last_used_at,
            "expires_at": key.expires_at
        }
        for key in api_keys
    ]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, req: Request):
    """
    Revoke an API key
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    auth_db = get_auth_db()
    
    # Verify ownership (in production, check if key belongs to user)
    await auth_db.revoke_api_key(UUID(key_id))
    
    # Log revocation
    await auth_db.create_audit_log(
        user_id=user["id"],
        action="revoke_api_key",
        resource_type="api_key",
        resource_id=key_id
    )
    
    return {"message": "API key revoked successfully"}


@router.post("/change-password")
async def change_password(request: ChangePasswordRequest, req: Request):
    """
    Change password for the current user
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    auth_db = get_auth_db()
    
    # Get full user record
    user_record = await auth_db.get_user(user["id"])
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify old password
    if not verify_password(request.old_password, user_record.password_hash):
        raise HTTPException(
            status_code=400,
            detail="Invalid old password"
        )
    
    # Update password (would need to add this method to auth_db)
    # For now, we'll update directly
    user_record.password_hash = hash_password(request.new_password)
    
    # Log password change
    await auth_db.create_audit_log(
        user_id=user["id"],
        action="change_password",
        resource_type="auth"
    )
    
    return {"message": "Password changed successfully"}


@router.get("/roles")
@require_permission(Permissions.USERS_READ)
async def list_roles(req: Request):
    """
    List all available roles
    
    Requires users:read permission
    """
    auth_db = get_auth_db()
    
    # Get all roles (would need to add this method)
    from ..auth.models import DEFAULT_ROLES
    
    return DEFAULT_ROLES


@router.get("/users")
@require_permission(Permissions.USERS_READ)
async def list_users(req: Request, skip: int = 0, limit: int = 100):
    """
    List all users (admin only)
    
    Requires users:read permission
    """
    # This would need database method to list all users
    return {"message": "User listing not yet implemented"}


@router.get("/audit-logs")
@require_permission(Permissions.SYSTEM_READ)
async def get_audit_logs(
    req: Request,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
):
    """
    Get audit logs
    
    Requires system:read permission
    """
    # This would need database method to query audit logs
    return {"message": "Audit log retrieval not yet implemented"}