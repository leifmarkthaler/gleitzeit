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

# Note: Most auth utilities now handled by GleitzeitClient for consistency
# from ..auth.utils import (
#     hash_password,
#     verify_password, 
#     generate_api_key,
#     hash_api_key,
#     create_jwt_token,
#     decode_jwt_token
# )
# from ..auth.database import get_auth_db
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
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.login(request.username, request.password)
        return LoginResponse(**result)
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/logout")
async def logout(request: Request, response: Response):
    """
    Logout current user
    
    Invalidates the current session/token
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.logout()
        
        # Clear session cookie if exists
        response.delete_cookie("gleitzeit_session")
        
        return result
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(request: RefreshRequest):
    """
    Refresh access token using refresh token
    """
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.refresh_token(request.refresh_token)
        return LoginResponse(**result)
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))


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
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.register_user(
            email=request.email,
            password=request.password,
            username=request.username,
            full_name=request.full_name
        )
        return result
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        if "already registered" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        elif "admin mode" in str(e).lower() or "disabled" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        else:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/api-keys", response_model=ApiKeyResponse)
async def create_api_key(request: CreateApiKeyRequest, req: Request):
    """
    Create a new API key for the current user
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.create_api_key(
            name=request.name,
            description=request.description,
            expires_in_days=request.expires_in_days
        )
        return ApiKeyResponse(**result)
    except Exception as e:
        logger.error(f"API key creation failed: {e}")
        if "admin mode" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        else:
            raise HTTPException(status_code=400, detail=str(e))


@router.get("/api-keys", response_model=List[dict])
async def list_api_keys(req: Request):
    """
    List all API keys for the current user
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.list_api_keys()
        return result
    except Exception as e:
        logger.error(f"API key listing failed: {e}")
        if "admin mode" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, req: Request):
    """
    Revoke an API key
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        success = await app_state.client.revoke_api_key(key_id)
        if success:
            return {"message": "API key revoked successfully"}
        else:
            raise HTTPException(status_code=404, detail="API key not found")
    except Exception as e:
        logger.error(f"API key revocation failed: {e}")
        if "admin mode" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/change-password")
async def change_password(request: ChangePasswordRequest, req: Request):
    """
    Change password for the current user
    """
    user = getattr(req.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.change_password(
            old_password=request.old_password,
            new_password=request.new_password,
            user_id=user["id"]
        )
        return result
    except Exception as e:
        logger.error(f"Password change failed: {e}")
        if "invalid old password" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        elif "admin mode" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/roles")
@require_permission(Permissions.USERS_READ)
async def list_roles(req: Request):
    """
    List all available roles
    
    Requires users:read permission
    """
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        roles = await app_state.client.list_roles()
        return roles
    except Exception as e:
        logger.error(f"Failed to list roles: {e}")
        if "admin mode" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
@require_permission(Permissions.USERS_READ)
async def list_users(req: Request, skip: int = 0, limit: int = 100):
    """
    List all users (admin only)
    
    Requires users:read permission
    """
    # Check auth mode - user management not available in basic mode
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    if auth_mode == "basic":
        raise HTTPException(
            status_code=403,
            detail="User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
        )
    
    # This would need database method to list all users
    return {"message": "User listing not yet implemented"}


@router.get("/audit-logs")
@require_permission(Permissions.SYSTEM_READ)
async def get_audit_logs(
    req: Request,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    since: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100
):
    """
    Get audit logs
    
    Requires system:read permission
    """
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        result = await app_state.client.get_audit_logs(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            since=since,
            skip=skip,
            limit=limit
        )
        return result
    except Exception as e:
        logger.error(f"Failed to get audit logs: {e}")
        if "admin mode" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Missing CRUD Endpoints
# ============================================================================

class CreateUserRequest(BaseModel):
    """Create user request"""
    email: EmailStr
    password: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    roles: Optional[List[str]] = None


class UpdateUserRequest(BaseModel):
    """Update user request"""
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None


class AssignRoleRequest(BaseModel):
    """Assign role request"""
    role: str


@router.post("/users", response_model=dict)
@require_permission(Permissions.USERS_CREATE)
async def create_user_admin(request: CreateUserRequest, req: Request):
    """
    Create a new user (admin only)
    
    Requires users:create permission
    """
    # Check auth mode
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    if auth_mode == "basic":
        raise HTTPException(
            status_code=403,
            detail="User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
        )
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        user = await app_state.client.create_user(
            email=request.email,
            password=request.password,
            username=request.username,
            full_name=request.full_name,
            roles=request.roles
        )
        return user
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users/{user_id}", response_model=dict)
@require_permission(Permissions.USERS_READ)
async def get_user_by_id(user_id: str, req: Request):
    """
    Get user by ID
    
    Requires users:read permission
    """
    # Check auth mode
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    if auth_mode == "basic":
        raise HTTPException(
            status_code=403,
            detail="User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
        )
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        user = await app_state.client.get_user(user_id)
        return user
    except RuntimeError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}", response_model=dict)
@require_permission(Permissions.USERS_UPDATE)
async def update_user_by_id(user_id: str, request: UpdateUserRequest, req: Request):
    """
    Update user by ID
    
    Requires users:update permission
    """
    # Check auth mode
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    if auth_mode == "basic":
        raise HTTPException(
            status_code=403,
            detail="User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
        )
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        # Convert to dict and filter None values
        updates = {k: v for k, v in request.dict().items() if v is not None}
        user = await app_state.client.update_user(user_id, **updates)
        return user
    except RuntimeError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}")
@require_permission(Permissions.USERS_DELETE)
async def delete_user_by_id(user_id: str, req: Request):
    """
    Delete user by ID
    
    Requires users:delete permission
    """
    # Check auth mode
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    if auth_mode == "basic":
        raise HTTPException(
            status_code=403,
            detail="User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
        )
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        success = await app_state.client.delete_user(user_id)
        if success:
            return {"message": "User deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        logger.error(f"Failed to delete user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/roles")
@require_permission(Permissions.USERS_UPDATE)
async def assign_user_role(user_id: str, request: AssignRoleRequest, req: Request):
    """
    Assign role to user
    
    Requires users:update permission
    """
    # Check auth mode
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    if auth_mode == "basic":
        raise HTTPException(
            status_code=403,
            detail="User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
        )
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        success = await app_state.client.assign_user_role(user_id, request.role)
        if success:
            return {"message": f"Role '{request.role}' assigned to user successfully"}
        else:
            raise HTTPException(status_code=404, detail="User or role not found")
    except Exception as e:
        logger.error(f"Failed to assign role to user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}/roles/{role_name}")
@require_permission(Permissions.USERS_UPDATE)
async def remove_user_role(user_id: str, role_name: str, req: Request):
    """
    Remove role from user
    
    Requires users:update permission
    """
    # Check auth mode
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    if auth_mode == "basic":
        raise HTTPException(
            status_code=403,
            detail="User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin"
        )
    
    # Use GleitzeitClient (thin layer)
    from ..api.main import app_state
    if not app_state.client:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    try:
        success = await app_state.client.remove_user_role(user_id, role_name)
        if success:
            return {"message": f"Role '{role_name}' removed from user successfully"}
        else:
            raise HTTPException(status_code=404, detail="User or role not found")
    except Exception as e:
        logger.error(f"Failed to remove role from user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))