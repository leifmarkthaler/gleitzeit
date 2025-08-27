"""
Optional permission decorators for backward-compatible authentication.

These decorators only enforce permissions when authentication is enabled,
allowing the system to work without configuration for new users.
"""

import os
import logging
from functools import wraps
from typing import Union, List, Optional, Callable
from fastapi import Request, HTTPException

from .permissions import has_permission, has_any_permission, has_all_permissions, has_role, has_any_role

logger = logging.getLogger(__name__)


def optional_permission(permission: Union[str, List[str]], any_permission: bool = False):
    """
    Permission decorator that only enforces if auth is enabled.
    Otherwise, allows all requests (backward compatible).
    
    Args:
        permission: Permission string or list of permissions
        any_permission: If True with list, user needs any permission; if False, needs all
        
    Example:
        @app.post("/workflows")
        @optional_permission("workflows:create")
        async def submit_workflow(request: Request, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object in args or kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get('request')
            
            # Get auth mode
            auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
            
            # Even in basic mode, check if this is an admin-only permission
            admin_only_permissions = [
                "users:create", "users:update", "users:delete", "users:read",
                "roles:create", "roles:update", "roles:delete", "roles:manage",
                "auth:manage", "system:configure", "audit:read"
            ]
            
            # Check if requested permission is admin-only
            is_admin_only = False
            if isinstance(permission, str):
                is_admin_only = permission in admin_only_permissions
            elif isinstance(permission, list):
                is_admin_only = any(p in admin_only_permissions for p in permission)
            
            # In basic mode, deny admin operations
            if auth_mode == "basic" and is_admin_only:
                logger.warning(f"Basic mode user denied admin operation: {func.__name__}")
                raise HTTPException(
                    status_code=403,
                    detail="Admin operations require admin mode. Set GLEITZEIT_AUTH_MODE=admin"
                )
            
            # In basic mode, allow non-admin operations
            if auth_mode == "basic" and not is_admin_only:
                logger.debug(f"Basic auth mode, allowing non-admin access to {func.__name__}")
                return await func(*args, **kwargs)
            
            # If auth is enabled but no user (shouldn't happen with middleware)
            if not request or not hasattr(request.state, 'user'):
                logger.warning(f"Auth enabled but no user found for {func.__name__}")
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required"
                )
            
            user = request.state.user
            
            # Check permissions
            if isinstance(permission, str):
                if not has_permission(user, permission):
                    logger.warning(
                        f"User {user.get('email')} denied access to {func.__name__} - "
                        f"missing permission: {permission}"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"Permission denied: {permission}"
                    )
            elif isinstance(permission, list):
                if any_permission:
                    if not has_any_permission(user, permission):
                        logger.warning(
                            f"User {user.get('email')} denied access to {func.__name__} - "
                            f"missing any of: {permission}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"One of these permissions required: {', '.join(permission)}"
                        )
                else:
                    if not has_all_permissions(user, permission):
                        logger.warning(
                            f"User {user.get('email')} denied access to {func.__name__} - "
                            f"missing all of: {permission}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"All permissions required: {', '.join(permission)}"
                        )
            
            # Permission check passed
            logger.debug(f"User {user.get('email')} granted access to {func.__name__}")
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def optional_role(role: Union[str, List[str]], any_role: bool = True):
    """
    Role decorator that only enforces if auth is enabled.
    Otherwise, allows all requests (backward compatible).
    
    Args:
        role: Role name or list of role names
        any_role: If True with list, user needs any role; if False, needs all
        
    Example:
        @app.post("/admin/action")
        @optional_role("admin")
        async def admin_action(request: Request, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get('request')
            
            # In basic mode, allow everything
            auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
            if auth_mode == "basic":
                return await func(*args, **kwargs)
            
            # If auth is enabled, check role
            if not request or not hasattr(request.state, 'user'):
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required"
                )
            
            user = request.state.user
            
            # Check roles
            if isinstance(role, str):
                if not has_role(user, role):
                    logger.warning(
                        f"User {user.get('email')} denied access to {func.__name__} - "
                        f"missing role: {role}"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"Role '{role}' required"
                    )
            elif isinstance(role, list):
                if any_role:
                    if not has_any_role(user, role):
                        logger.warning(
                            f"User {user.get('email')} denied access to {func.__name__} - "
                            f"missing any role: {role}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"One of these roles required: {', '.join(role)}"
                        )
                else:
                    # Require all roles (unusual but possible)
                    user_roles = set(user.get("roles", []))
                    if not all(r in user_roles for r in role):
                        logger.warning(
                            f"User {user.get('email')} denied access to {func.__name__} - "
                            f"missing all roles: {role}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"All roles required: {', '.join(role)}"
                        )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def optional_superuser():
    """
    Superuser decorator that only enforces if auth is enabled.
    Otherwise, allows all requests (backward compatible).
    
    Example:
        @app.delete("/system/reset")
        @optional_superuser()
        async def system_reset(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get('request')
            
            # In basic mode, allow everything
            auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
            if auth_mode == "basic":
                return await func(*args, **kwargs)
            
            # If auth is enabled, check superuser
            if not request or not hasattr(request.state, 'user'):
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required"
                )
            
            user = request.state.user
            if not user.get("is_superuser"):
                logger.warning(
                    f"User {user.get('email')} denied access to {func.__name__} - "
                    f"superuser required"
                )
                raise HTTPException(
                    status_code=403,
                    detail="Superuser access required"
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def check_resource_ownership(resource_getter: Callable):
    """
    Decorator that checks if user owns the resource or is superuser.
    Only enforces if auth is enabled.
    
    Args:
        resource_getter: Function that takes the same args as the endpoint
                        and returns a dict with 'owner_id' field
        
    Example:
        async def get_workflow(workflow_id: str):
            return await get_workflow_by_id(workflow_id)
        
        @app.delete("/workflows/{workflow_id}")
        @optional_permission("workflows:delete")
        @check_resource_ownership(get_workflow)
        async def delete_workflow(request: Request, workflow_id: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get('request')
            
            # In basic mode, allow everything
            auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
            if auth_mode == "basic":
                return await func(*args, **kwargs)
            
            # If ownership filtering is disabled, allow
            if os.getenv("GLEITZEIT_AUTH_OWNERSHIP_FILTER", "true").lower() != "true":
                return await func(*args, **kwargs)
            
            # Check ownership
            if not request or not hasattr(request.state, 'user'):
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required"
                )
            
            user = request.state.user
            
            # Superusers can access any resource
            if user.get("is_superuser"):
                return await func(*args, **kwargs)
            
            # Get the resource and check ownership
            try:
                # Call resource_getter with the same kwargs
                resource = await resource_getter(**{
                    k: v for k, v in kwargs.items() 
                    if k != 'request'
                })
                
                if not resource:
                    # Resource not found, let the endpoint handle it
                    return await func(*args, **kwargs)
                
                # Check ownership - look in metadata first, then root level
                metadata = resource.get("metadata", {})
                owner_id = metadata.get("owner_id") or resource.get("owner_id")
                if owner_id and str(owner_id) != str(user.get("id")):
                    logger.warning(
                        f"User {user.get('email')} denied access to resource - "
                        f"not owner (owner: {owner_id}, user: {user.get('id')})"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail="You don't have permission to access this resource"
                    )
                
            except HTTPException:
                # Re-raise HTTP exceptions
                raise
            except Exception as e:
                # Log but don't block on ownership check failures
                logger.error(f"Failed to check resource ownership: {e}")
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def filter_by_ownership(check_ownership: bool = True):
    """
    Decorator that filters list results by ownership if auth is enabled.
    
    Args:
        check_ownership: If False, returns all items for superusers
        
    Example:
        @app.get("/workflows")
        @optional_permission("workflows:read")
        @filter_by_ownership()
        async def list_workflows(request: Request):
            workflows = await get_all_workflows()
            return workflows  # Will be filtered automatically
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get('request')
            
            # Call the original function
            result = await func(*args, **kwargs)
            
            # In basic mode, return filtered by basic user
            auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
            if auth_mode == "basic":
                # Still filter by user, but it's always the basic user
                # This keeps basic user's data separate from admin mode users
                pass  # Continue to filtering logic
            
            # If ownership filtering is disabled, return unfiltered
            if os.getenv("GLEITZEIT_AUTH_OWNERSHIP_FILTER", "true").lower() != "true":
                return result
            
            # If no user, return empty (shouldn't happen with middleware)
            if not request or not hasattr(request.state, 'user'):
                return []
            
            user = request.state.user
            
            # Superusers see everything if check_ownership is False
            if not check_ownership and user.get("is_superuser"):
                return result
            
            # Filter by ownership
            user_id = user.get("id")
            
            # Handle different return types
            if isinstance(result, list):
                filtered = []
                for item in result:
                    if isinstance(item, dict):
                        # Check for owner_id in metadata first, then at root level
                        metadata = item.get("metadata", {})
                        owner_id = metadata.get("owner_id") or item.get("owner_id")
                        # Include items without owner (legacy) or owned by user
                        if not owner_id or str(owner_id) == str(user_id) or user.get("is_superuser"):
                            filtered.append(item)
                return filtered
            
            elif isinstance(result, dict):
                # If result has 'items' or 'data' key with list
                for key in ['items', 'data', 'workflows', 'tasks', 'results']:
                    if key in result and isinstance(result[key], list):
                        filtered = []
                        for item in result[key]:
                            if isinstance(item, dict):
                                # Check for owner_id in metadata first, then at root level
                                metadata = item.get("metadata", {})
                                owner_id = metadata.get("owner_id") or item.get("owner_id")
                                if not owner_id or str(owner_id) == str(user_id) or user.get("is_superuser"):
                                    filtered.append(item)
                        result[key] = filtered
                        # Update count if present
                        if 'total' in result:
                            result['total'] = len(filtered)
                        break
            
            return result
        
        return wrapper
    return decorator