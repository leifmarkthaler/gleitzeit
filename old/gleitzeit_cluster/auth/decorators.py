"""
Authentication and authorization decorators

Provides decorators for protecting functions and methods with authentication
and permission checks.
"""

import functools
from typing import Callable, Optional, Union, List

from .auth_manager import get_auth_manager, AuthenticationError, AuthorizationError
from .models import Role, Permission, AuthContext


def require_auth(func: Callable) -> Callable:
    """
    Decorator to require authentication
    
    The decorated function will receive an auth_context parameter
    with the authenticated user information.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        auth_manager = get_auth_manager()
        
        try:
            auth_context = auth_manager.require_authentication()
            # Inject auth context into function
            return await func(*args, auth_context=auth_context, **kwargs)
        except AuthenticationError as e:
            raise AuthenticationError(f"Authentication required: {e}")
    
    return wrapper


def require_permission(permission: Union[Permission, List[Permission]]) -> Callable:
    """
    Decorator to require specific permission(s)
    
    Args:
        permission: Single permission or list of permissions (ANY match)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            auth_manager = get_auth_manager()
            
            try:
                auth_context = auth_manager.require_authentication()
                
                # Check permissions
                permissions = [permission] if isinstance(permission, Permission) else permission
                
                has_permission = any(
                    auth_context.has_permission(perm) for perm in permissions
                )
                
                if not has_permission:
                    perm_names = [p.value for p in permissions]
                    raise AuthorizationError(
                        f"Insufficient permissions. Required: {' OR '.join(perm_names)}"
                    )
                
                # Inject auth context into function
                return await func(*args, auth_context=auth_context, **kwargs)
            
            except (AuthenticationError, AuthorizationError):
                raise
            except Exception as e:
                raise AuthenticationError(f"Authentication error: {e}")
        
        return wrapper
    return decorator


def require_role(role: Union[Role, List[Role]]) -> Callable:
    """
    Decorator to require specific role(s)
    
    Args:
        role: Single role or list of roles (ANY match)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            auth_manager = get_auth_manager()
            
            try:
                auth_context = auth_manager.require_authentication()
                
                # Check roles
                roles = [role] if isinstance(role, Role) else role
                
                has_role = any(
                    auth_context.has_role(r) for r in roles
                )
                
                if not has_role:
                    role_names = [r.value for r in roles]
                    raise AuthorizationError(
                        f"Insufficient role. Required: {' OR '.join(role_names)}"
                    )
                
                # Inject auth context into function
                return await func(*args, auth_context=auth_context, **kwargs)
            
            except (AuthenticationError, AuthorizationError):
                raise
            except Exception as e:
                raise AuthenticationError(f"Authentication error: {e}")
        
        return wrapper
    return decorator


def require_admin(func: Callable) -> Callable:
    """Decorator to require admin role - shortcut for require_role(Role.ADMIN)"""
    return require_role(Role.ADMIN)(func)


def optional_auth(func: Callable) -> Callable:
    """
    Decorator for optional authentication
    
    If authentication is available, auth_context will be provided.
    If not authenticated, auth_context will be None.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        auth_manager = get_auth_manager()
        
        try:
            auth_context = auth_manager.get_current_context()
        except Exception:
            auth_context = None
        
        # Always inject auth_context (may be None)
        return await func(*args, auth_context=auth_context, **kwargs)
    
    return wrapper


def require_self_or_admin(user_param: str = 'user_id') -> Callable:
    """
    Decorator to require user to access their own data OR be an admin
    
    Args:
        user_param: Parameter name that contains the target user_id
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            auth_manager = get_auth_manager()
            
            try:
                auth_context = auth_manager.require_authentication()
                
                # Get target user ID from parameters
                target_user_id = kwargs.get(user_param)
                if not target_user_id and args:
                    # Try to get from positional args (fragile, but fallback)
                    import inspect
                    sig = inspect.signature(func)
                    param_names = list(sig.parameters.keys())
                    if user_param in param_names:
                        param_index = param_names.index(user_param)
                        if param_index < len(args):
                            target_user_id = args[param_index]
                
                if not target_user_id:
                    raise AuthorizationError(f"Cannot determine target user from parameter: {user_param}")
                
                # Check if user is accessing their own data OR is admin
                is_self = auth_context.user.user_id == target_user_id
                is_admin = auth_context.has_role(Role.ADMIN)
                
                if not (is_self or is_admin):
                    raise AuthorizationError("Access denied. You can only access your own data or need admin role.")
                
                # Inject auth context into function
                return await func(*args, auth_context=auth_context, **kwargs)
            
            except (AuthenticationError, AuthorizationError):
                raise
            except Exception as e:
                raise AuthenticationError(f"Authentication error: {e}")
        
        return wrapper
    return decorator


# Convenience decorators for common permission combinations
def require_workflow_access(func: Callable) -> Callable:
    """Require workflow read/write permissions"""
    return require_permission([
        Permission.WORKFLOW_READ,
        Permission.WORKFLOW_CREATE,
        Permission.WORKFLOW_UPDATE,
        Permission.WORKFLOW_DELETE,
        Permission.WORKFLOW_EXECUTE
    ])(func)


def require_cluster_access(func: Callable) -> Callable:
    """Require cluster view/management permissions"""
    return require_permission([
        Permission.CLUSTER_VIEW,
        Permission.CLUSTER_MANAGE
    ])(func)


def require_system_access(func: Callable) -> Callable:
    """Require system-level permissions"""
    return require_permission([
        Permission.SYSTEM_STATS,
        Permission.SYSTEM_LOGS,
        Permission.SYSTEM_CONFIG
    ])(func)


# HTTP/API specific decorators (for future web UI integration)
def extract_api_key_from_request(request) -> Optional[str]:
    """
    Extract API key from HTTP request
    
    Checks:
    1. Authorization header: "Bearer <api_key>"
    2. X-API-Key header
    3. api_key query parameter
    """
    # Authorization header
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]  # Remove "Bearer " prefix
    
    # X-API-Key header
    api_key_header = request.headers.get('X-API-Key')
    if api_key_header:
        return api_key_header
    
    # Query parameter
    if hasattr(request, 'args'):  # Flask-style
        return request.args.get('api_key')
    elif hasattr(request, 'query'):  # FastAPI-style
        return request.query.get('api_key')
    
    return None


def api_require_auth(func: Callable) -> Callable:
    """
    Decorator for API endpoints that require authentication
    
    Extracts API key from HTTP request and authenticates.
    For use with Flask, FastAPI, or similar web frameworks.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Try to find request object in args/kwargs
        request = None
        for arg in args:
            if hasattr(arg, 'headers'):  # Likely a request object
                request = arg
                break
        
        if not request:
            request = kwargs.get('request')
        
        if not request:
            raise AuthenticationError("No request object found for API authentication")
        
        # Extract API key
        api_key = extract_api_key_from_request(request)
        if not api_key:
            raise AuthenticationError("API key required. Provide in Authorization header, X-API-Key header, or api_key parameter")
        
        # Authenticate
        auth_manager = get_auth_manager()
        
        try:
            # Get client IP if available
            client_ip = getattr(request, 'remote_addr', None)
            if not client_ip and hasattr(request, 'client'):
                client_ip = getattr(request.client, 'host', None)
            
            auth_context = auth_manager.authenticate_api_key(api_key, ip_address=client_ip)
            
            # Inject auth context into function
            return await func(*args, auth_context=auth_context, **kwargs)
        
        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Authentication error: {e}")
    
    return wrapper