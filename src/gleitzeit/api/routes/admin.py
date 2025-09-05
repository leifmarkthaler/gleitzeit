"""
Admin API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from .base import APIRouteBase

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


# Create route handler instance (stateless - just contains logic)
admin_routes = APIRouteBase()


# User Management
@router.post("/users", response_model=Dict[str, Any])
async def create_user(
    request: UserCreateRequest,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Create a new user (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call(
        "create_user", 
        request.username, 
        request.email, 
        request.password,
        request.roles,
        client=client
    )


@router.get("/users", response_model=List[Dict[str, Any]])
async def list_users(
    req: Request,
    limit: int = 100,
    offset: int = 0,
    client: GleitzeitClient = Depends(get_client)
):
    """List all users (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("list_users", limit, offset, client=client)


@router.get("/users/{user_id}", response_model=Dict[str, Any])
async def get_user(
    user_id: str,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Get user by ID (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("get_user", user_id, client=client)


@router.put("/users/{user_id}", response_model=Dict[str, Any])
async def update_user(
    user_id: str,
    updates: Dict[str, Any],
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Update user (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("update_user", user_id, updates, client=client)


@router.delete("/users/{user_id}", response_model=bool)
async def delete_user(
    user_id: str,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Delete user (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("delete_user", user_id, client=client)


@router.post("/users/{user_id}/activate", response_model=Dict[str, Any])
async def activate_user(
    user_id: str,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Activate user account (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("activate_user", user_id, client=client)


@router.post("/users/{user_id}/deactivate", response_model=Dict[str, Any])
async def deactivate_user(
    user_id: str,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Deactivate user account (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("deactivate_user", user_id, client=client)


# API Key Management
@router.post("/api-keys", response_model=Dict[str, Any])
async def create_api_key(
    request: APIKeyCreateRequest,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Create API key (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call(
        "create_api_key",
        request.name,
        request.permissions,
        request.expires_in_days,
        client=client
    )


@router.get("/api-keys", response_model=List[Dict[str, Any]])
async def list_api_keys(
    req: Request,
    limit: int = 100,
    offset: int = 0,
    client: GleitzeitClient = Depends(get_client)
):
    """List API keys (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("list_api_keys", limit, offset, client=client)


@router.delete("/api-keys/{key_id}", response_model=bool)
async def revoke_api_key(
    key_id: str,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Revoke API key (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("revoke_api_key", key_id, client=client)


# Role Management
@router.post("/roles", response_model=Dict[str, Any])
async def create_role(
    request: RoleCreateRequest,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Create role (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call(
        "create_role",
        request.name,
        request.permissions,
        request.description,
        client=client
    )


@router.get("/roles", response_model=List[Dict[str, Any]])
async def list_roles(
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """List roles (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("list_roles", client=client)


@router.delete("/roles/{role_id}", response_model=bool)
async def delete_role(
    role_id: str,
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Delete role (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("delete_role", role_id, client=client)


# Audit and System
@router.get("/audit-logs", response_model=List[Dict[str, Any]])
async def get_audit_logs(
    req: Request,
    limit: int = 100,
    offset: int = 0,
    user_id: Optional[str] = None,
    action_type: Optional[str] = None,
    client: GleitzeitClient = Depends(get_client)
):
    """Get audit logs (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call(
        "get_audit_logs", 
        limit, 
        offset, 
        user_id, 
        action_type,
        client=client
    )


@router.get("/system-stats", response_model=Dict[str, Any])
async def get_system_statistics(
    req: Request,
    client: GleitzeitClient = Depends(get_client)
):
    """Get system statistics (admin only)."""
    admin_routes.require_admin(req)
    return await admin_routes.handle_client_call("get_system_statistics", client=client)