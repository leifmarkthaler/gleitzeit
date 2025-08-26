"""
Permission checking and authorization decorators
"""

import logging
from functools import wraps
from typing import List, Optional, Union, Set
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)


def has_permission(user: dict, permission: str) -> bool:
    """
    Check if user has a specific permission
    
    Args:
        user: User dict with roles and permissions
        permission: Permission string (e.g., "workflows:create")
    
    Returns:
        True if user has permission, False otherwise
    """
    if not user:
        return False
    
    # Superuser has all permissions
    if user.get("is_superuser"):
        return True
    
    # Get all user permissions
    user_permissions = set(user.get("permissions", []))
    
    # Add permissions from API key scopes if present
    api_key_scopes = user.get("api_key_scopes", [])
    user_permissions.update(api_key_scopes)
    
    # Check exact match
    if permission in user_permissions:
        return True
    
    # Check wildcard permissions
    if "*" in user_permissions:
        return True
    
    # Check resource-level wildcards (e.g., "workflows:*")
    if ":" in permission:
        resource, action = permission.split(":", 1)
        if f"{resource}:*" in user_permissions:
            return True
    
    return False


def has_any_permission(user: dict, permissions: List[str]) -> bool:
    """
    Check if user has any of the specified permissions
    
    Args:
        user: User dict with roles and permissions
        permissions: List of permission strings
    
    Returns:
        True if user has any permission, False otherwise
    """
    return any(has_permission(user, perm) for perm in permissions)


def has_all_permissions(user: dict, permissions: List[str]) -> bool:
    """
    Check if user has all of the specified permissions
    
    Args:
        user: User dict with roles and permissions  
        permissions: List of permission strings
    
    Returns:
        True if user has all permissions, False otherwise
    """
    return all(has_permission(user, perm) for perm in permissions)


def has_role(user: dict, role: str) -> bool:
    """
    Check if user has a specific role
    
    Args:
        user: User dict with roles
        role: Role name
    
    Returns:
        True if user has role, False otherwise
    """
    if not user:
        return False
    
    return role in user.get("roles", [])


def has_any_role(user: dict, roles: List[str]) -> bool:
    """
    Check if user has any of the specified roles
    
    Args:
        user: User dict with roles
        roles: List of role names
    
    Returns:
        True if user has any role, False otherwise
    """
    if not user:
        return False
    
    user_roles = set(user.get("roles", []))
    return bool(user_roles.intersection(roles))


def require_permission(permission: Union[str, List[str]], any_permission: bool = False):
    """
    Decorator to require specific permission(s) for an endpoint
    
    Args:
        permission: Permission string or list of permissions
        any_permission: If True, user needs any permission; if False, needs all
    
    Example:
        @require_permission("workflows:create")
        async def create_workflow(request: Request):
            ...
            
        @require_permission(["workflows:read", "tasks:read"])
        async def get_workflow_details(request: Request):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Get user from request
            user = getattr(request.state, "user", None)
            
            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required"
                )
            
            # Check permissions
            if isinstance(permission, str):
                if not has_permission(user, permission):
                    logger.warning(
                        f"User {user.get('email')} denied access - missing permission: {permission}"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"Permission '{permission}' required"
                    )
            elif isinstance(permission, list):
                if any_permission:
                    if not has_any_permission(user, permission):
                        logger.warning(
                            f"User {user.get('email')} denied access - missing any of: {permission}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"One of these permissions required: {', '.join(permission)}"
                        )
                else:
                    if not has_all_permissions(user, permission):
                        logger.warning(
                            f"User {user.get('email')} denied access - missing all of: {permission}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"All permissions required: {', '.join(permission)}"
                        )
            
            # Call the actual function
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator


def require_role(role: Union[str, List[str]], any_role: bool = True):
    """
    Decorator to require specific role(s) for an endpoint
    
    Args:
        role: Role name or list of role names
        any_role: If True, user needs any role; if False, needs all
    
    Example:
        @require_role("admin")
        async def admin_action(request: Request):
            ...
            
        @require_role(["admin", "operator"])
        async def operator_action(request: Request):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Get user from request
            user = getattr(request.state, "user", None)
            
            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required"
                )
            
            # Check roles
            if isinstance(role, str):
                if not has_role(user, role):
                    logger.warning(
                        f"User {user.get('email')} denied access - missing role: {role}"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"Role '{role}' required"
                    )
            elif isinstance(role, list):
                if any_role:
                    if not has_any_role(user, role):
                        logger.warning(
                            f"User {user.get('email')} denied access - missing any role: {role}"
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
                            f"User {user.get('email')} denied access - missing all roles: {role}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"All roles required: {', '.join(role)}"
                        )
            
            # Call the actual function
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator


def require_superuser():
    """
    Decorator to require superuser status
    
    Example:
        @require_superuser()
        async def system_action(request: Request):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Get user from request
            user = getattr(request.state, "user", None)
            
            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required"
                )
            
            if not user.get("is_superuser"):
                logger.warning(
                    f"User {user.get('email')} denied access - superuser required"
                )
                raise HTTPException(
                    status_code=403,
                    detail="Superuser access required"
                )
            
            # Call the actual function
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator


def check_resource_permission(
    user: dict,
    resource_type: str,
    resource_id: str,
    action: str
) -> bool:
    """
    Check if user has permission for a specific resource
    
    Args:
        user: User dict
        resource_type: Type of resource (workflow, task, etc.)
        resource_id: Specific resource ID
        action: Action to perform (read, update, delete)
    
    Returns:
        True if user has permission, False otherwise
    """
    # Check general permission first
    general_permission = f"{resource_type}:{action}"
    if has_permission(user, general_permission):
        return True
    
    # Check resource-specific permission
    specific_permission = f"{resource_type}:{resource_id}:{action}"
    if has_permission(user, specific_permission):
        return True
    
    # Check if user owns the resource (would need to be implemented)
    # This would require database lookup to check resource ownership
    
    return False


# Common permission constants
class Permissions:
    """Common permission strings"""
    
    # Workflow permissions
    WORKFLOWS_CREATE = "workflows:create"
    WORKFLOWS_READ = "workflows:read"
    WORKFLOWS_UPDATE = "workflows:update"
    WORKFLOWS_DELETE = "workflows:delete"
    WORKFLOWS_PAUSE = "workflows:pause"
    WORKFLOWS_RESUME = "workflows:resume"
    WORKFLOWS_RETRY = "workflows:retry"
    
    # Task permissions
    TASKS_CREATE = "tasks:create"
    TASKS_READ = "tasks:read"
    TASKS_UPDATE = "tasks:update"
    TASKS_DELETE = "tasks:delete"
    TASKS_CANCEL = "tasks:cancel"
    TASKS_RETRY = "tasks:retry"
    
    # Queue permissions
    QUEUES_READ = "queues:read"
    QUEUES_MANAGE = "queues:manage"
    QUEUES_CLEAR = "queues:clear"
    
    # Provider permissions
    PROVIDERS_READ = "providers:read"
    PROVIDERS_MANAGE = "providers:manage"
    
    # System permissions
    SYSTEM_READ = "system:read"
    SYSTEM_MANAGE = "system:manage"
    STATISTICS_READ = "statistics:read"
    LOGS_READ = "logs:read"
    
    # User management
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_READ = "api_keys:read"
    API_KEYS_DELETE = "api_keys:delete"