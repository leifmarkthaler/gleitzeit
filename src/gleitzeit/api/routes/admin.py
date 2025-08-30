"""
Admin API routes that delegate to client methods.
"""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request
from pydantic import BaseModel
from .base import APIRouteBase, get_shared_client

router = APIRouter(prefix="/admin", tags=["admin"])


class UserCreateRequest(BaseModel):
    username: str
    email: str
    password: str
    roles: Optional[List[str]] = None


class APIKeyCreateRequest(BaseModel):
    name: str
    permissions: Optional[List[str]] = None
    expires_in_days: Optional[int] = 30


class RoleCreateRequest(BaseModel):
    name: str
    permissions: List[str]
    description: Optional[str] = None


# Create a single instance to use for all routes
_admin_routes = None

def _get_routes() -> APIRouteBase:
    """Get the admin routes instance."""
    global _admin_routes
    if _admin_routes is None:
        _admin_routes = APIRouteBase(get_shared_client())
    return _admin_routes


# User Management
@router.post("/users", response_model=Dict[str, Any])
async def create_user(request: UserCreateRequest, req: Request):
    """Create a new user (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call(
        "create_user", 
        request.username, 
        request.email, 
        request.password,
        request.roles
    )

@router.get("/users", response_model=List[Dict[str, Any]])
async def list_users(
    limit: int = 100,
    offset: int = 0,
    req: Request = None
):
    """List all users (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("list_users", limit, offset)

@router.get("/users/{user_id}", response_model=Dict[str, Any])
async def get_user(user_id: str, req: Request):
    """Get user by ID (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("get_user", user_id)

@router.put("/users/{user_id}", response_model=Dict[str, Any])
async def update_user(
    user_id: str,
    updates: Dict[str, Any],
    req: Request = None
):
    """Update user (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("update_user", user_id, updates)

@router.delete("/users/{user_id}", response_model=bool)
async def delete_user(user_id: str, req: Request):
    """Delete user (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("delete_user", user_id)

@router.post("/users/{user_id}/activate", response_model=Dict[str, Any])
async def activate_user(user_id: str, req: Request):
    """Activate user account (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("activate_user", user_id)

@router.post("/users/{user_id}/deactivate", response_model=Dict[str, Any])
async def deactivate_user(user_id: str, req: Request):
    """Deactivate user account (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("deactivate_user", user_id)

# API Key Management
@router.post("/api-keys", response_model=Dict[str, Any])
async def create_api_key(request: APIKeyCreateRequest, req: Request):
    """Create API key (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call(
        "create_api_key",
        request.name,
        request.permissions,
        request.expires_in_days
    )

@router.get("/api-keys", response_model=List[Dict[str, Any]])
async def list_api_keys(
    limit: int = 100,
    offset: int = 0,
    req: Request = None
):
    """List API keys (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("list_api_keys", limit, offset)

@router.delete("/api-keys/{key_id}", response_model=bool)
async def revoke_api_key(key_id: str, req: Request):
    """Revoke API key (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("revoke_api_key", key_id)

# Role Management
@router.post("/roles", response_model=Dict[str, Any])
async def create_role(request: RoleCreateRequest, req: Request):
    """Create role (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call(
        "create_role",
        request.name,
        request.permissions,
        request.description
    )

@router.get("/roles", response_model=List[Dict[str, Any]])
async def list_roles(req: Request):
    """List roles (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("list_roles")

@router.delete("/roles/{role_id}", response_model=bool)
async def delete_role(role_id: str, req: Request):
    """Delete role (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("delete_role", role_id)

# Audit and System
@router.get("/audit-logs", response_model=List[Dict[str, Any]])
async def get_audit_logs(
    limit: int = 100,
    offset: int = 0,
    user_id: Optional[str] = None,
    action_type: Optional[str] = None,
    req: Request = None
):
    """Get audit logs (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("get_audit_logs", limit, offset, user_id, action_type)

@router.get("/system-stats", response_model=Dict[str, Any])
async def get_system_statistics(req: Request):
    """Get system statistics (admin only)."""
    routes = _get_routes()
    routes.require_admin(req)
    return await routes.handle_client_call("get_system_statistics")

# Export router for inclusion in main API
__all__ = ["router"]