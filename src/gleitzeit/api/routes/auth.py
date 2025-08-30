"""
Authentication API routes that delegate to client methods.
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from .base import APIRouteBase, get_shared_client

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


# Create a single instance to use for all routes
_auth_routes = None

def _get_routes() -> APIRouteBase:
    """Get the auth routes instance."""
    global _auth_routes
    if _auth_routes is None:
        _auth_routes = APIRouteBase(get_shared_client())
    return _auth_routes


@router.post("/login", response_model=Dict[str, Any])
async def login(request: LoginRequest, req: Request):
    """Login and get authentication token."""
    routes = _get_routes()
    return await routes.handle_client_call("login", request.username, request.password)

@router.post("/logout", response_model=Dict[str, Any])
async def logout(req: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Logout current user."""
    routes = _get_routes()
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await routes.handle_client_call("logout")

@router.get("/me", response_model=Dict[str, Any])
async def get_current_user(req: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current authenticated user."""
    routes = _get_routes()
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await routes.handle_client_call("get_current_user")

@router.post("/register", response_model=Dict[str, Any])
async def register(request: RegisterRequest, req: Request):
    """Register a new user."""
    routes = _get_routes()
    return await routes.handle_client_call(
        "register_user",
        request.username,
        request.email,
        request.password,
        request.full_name
    )

@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_token(req: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Refresh authentication token."""
    routes = _get_routes()
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await routes.handle_client_call("refresh_token")

@router.post("/change-password", response_model=Dict[str, Any])
async def change_password(
    old_password: str,
    new_password: str,
    req: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Change user password."""
    routes = _get_routes()
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await routes.handle_client_call("change_password", old_password, new_password)

@router.post("/reset-password", response_model=Dict[str, Any])
async def reset_password(email: str, req: Request):
    """Request password reset."""
    routes = _get_routes()
    return await routes.handle_client_call("reset_password", email)

@router.get("/permissions", response_model=Dict[str, Any])
async def get_user_permissions(req: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user's permissions."""
    routes = _get_routes()
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await routes.handle_client_call("get_user_permissions")

# Export router for inclusion in main API
__all__ = ["router"]