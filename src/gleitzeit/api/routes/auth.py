"""
Authentication API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from .base import APIRouteBase

router = APIRouter(prefix="/auth", tags=["authentication"])

# Security scheme for JWT Bearer tokens
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    email: str


# Create route handler instance (stateless - just contains logic)
auth_routes = APIRouteBase()


@router.post("/login", response_model=Dict[str, Any])
async def login(
    request: LoginRequest,
    client: GleitzeitClient = Depends(get_client)
):
    """Login and get authentication token."""
    return await auth_routes.handle_client_call(
        "login", 
        request.username, 
        request.password,
        client=client
    )


@router.post("/logout", response_model=Dict[str, Any])
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    client: GleitzeitClient = Depends(get_client)
):
    """Logout current user."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await auth_routes.handle_client_call("logout", client=client)


@router.get("/me", response_model=Dict[str, Any])
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    client: GleitzeitClient = Depends(get_client)
):
    """Get current authenticated user."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await auth_routes.handle_client_call("get_current_user", client=client)


@router.post("/register", response_model=Dict[str, Any])
async def register(
    request: RegisterRequest,
    client: GleitzeitClient = Depends(get_client)
):
    """Register a new user."""
    return await auth_routes.handle_client_call(
        "register_user",
        request.username,
        request.email,
        request.password,
        request.full_name,
        client=client
    )


@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    client: GleitzeitClient = Depends(get_client)
):
    """Refresh authentication token."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await auth_routes.handle_client_call("refresh_token", client=client)


@router.post("/change-password", response_model=Dict[str, Any])
async def change_password(
    request: ChangePasswordRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    client: GleitzeitClient = Depends(get_client)
):
    """Change user password."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await auth_routes.handle_client_call(
        "change_password", 
        request.old_password, 
        request.new_password,
        client=client
    )


@router.post("/reset-password", response_model=Dict[str, Any])
async def reset_password(
    request: ResetPasswordRequest,
    client: GleitzeitClient = Depends(get_client)
):
    """Request password reset."""
    return await auth_routes.handle_client_call("reset_password", request.email, client=client)


@router.get("/permissions", response_model=Dict[str, Any])
async def get_user_permissions(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    client: GleitzeitClient = Depends(get_client)
):
    """Get current user's permissions."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await auth_routes.handle_client_call("get_user_permissions", client=client)


@router.post("/verify-token", response_model=Dict[str, Any])
async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    client: GleitzeitClient = Depends(get_client)
):
    """Verify authentication token validity."""
    if not credentials:
        raise HTTPException(status_code=401, detail="No token provided")
    return await auth_routes.handle_client_call("verify_token", credentials.credentials, client=client)