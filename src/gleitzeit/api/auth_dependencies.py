"""
Authentication dependencies for API routes.

Provides automatic basic user login and session management.
"""

from typing import Dict, Any, Optional
from fastapi import Request, Response, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from gleitzeit.core.errors import SystemError, ErrorCode
from .dependencies import get_system_manager
import logging

logger = logging.getLogger(__name__)

# Security scheme for JWT Bearer tokens
security = HTTPBearer(auto_error=False)


async def get_current_user_auto(
    request: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
) -> Dict[str, Any]:
    """
    Get current user with automatic basic user login.
    
    Behavior:
    1. If session/token provided -> validate and return user
    2. If no credentials -> auto-login as basic user
    3. If invalid credentials -> raise 401
    
    This ensures the system always has a user context while
    allowing switching to real users when credentials provided.
    
    Args:
        request: FastAPI request object
        response: FastAPI response object
        credentials: Optional bearer token
        system_manager: System manager instance
        
    Returns:
        User dictionary with id, username, role, permissions
        
    Raises:
        HTTPException: If authentication fails (not for missing auth)
    """
    # Try to get session from cookie first
    session_id = request.cookies.get("session_id")
    
    # Or from Bearer token
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    
    # Check if we have any credentials
    if session_id or token:
        # We have credentials - validate them
        try:
            if not system_manager or not system_manager.auth_manager:
                raise HTTPException(
                    status_code=503, 
                    detail="Authentication service unavailable"
                )
            
            # Use session ID if available, otherwise validate token
            if session_id:
                user = await system_manager.auth_manager.get_current_user(session_id)
            else:
                user = await system_manager.auth_manager.validate_session(token)
            
            return user
            
        except SystemError as e:
            # Invalid credentials - don't auto-login
            if e.code == ErrorCode.AUTHENTICATION_FAILED:
                raise HTTPException(status_code=401, detail="Invalid session or token")
            elif e.code == ErrorCode.AUTHENTICATION_REQUIRED:
                # This shouldn't happen with credentials provided
                raise HTTPException(status_code=401, detail="Authentication required")
            else:
                raise HTTPException(status_code=403, detail=str(e))
    
    # No credentials provided - auto-login as basic user
    if not system_manager or not system_manager.auth_manager:
        raise HTTPException(
            status_code=503, 
            detail="Authentication service unavailable"
        )
    
    try:
        # Get or create basic user session
        session_id, user = await system_manager.auth_manager.get_or_create_basic_session()
        
        # Set cookie for subsequent requests
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=False,  # Allow HTTP in development
            samesite="lax"
        )
        
        logger.debug(f"Auto-logged in as basic user: {user.get('username')}")
        return user
        
    except SystemError as e:
        # Could not create basic session (maybe limit reached)
        logger.warning(f"Failed to auto-login basic user: {e}")
        raise HTTPException(
            status_code=401, 
            detail="Authentication required - basic user session unavailable"
        )


async def get_current_user_required(
    request: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
) -> Dict[str, Any]:
    """
    Get current user - authentication required (no auto-login).
    
    Use this for endpoints that should not allow basic user access.
    
    Args:
        request: FastAPI request object
        response: FastAPI response object  
        credentials: Optional bearer token
        system_manager: System manager instance
        
    Returns:
        User dictionary (never basic user)
        
    Raises:
        HTTPException: 401 if not authenticated
    """
    # Try to get session from cookie first
    session_id = request.cookies.get("session_id")
    
    # Or from Bearer token
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    
    if not session_id and not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not system_manager or not system_manager.auth_manager:
        raise HTTPException(
            status_code=503, 
            detail="Authentication service unavailable"
        )
    
    try:
        # Use session ID if available, otherwise validate token
        if session_id:
            user = await system_manager.auth_manager.get_current_user(session_id)
        else:
            user = await system_manager.auth_manager.validate_session(token)
        
        # Don't allow basic user for secured endpoints
        if user.get("is_basic_user"):
            raise HTTPException(
                status_code=403, 
                detail="This operation requires a real user account"
            )
        
        return user
        
    except SystemError as e:
        if e.code == ErrorCode.AUTHENTICATION_FAILED:
            raise HTTPException(status_code=401, detail="Invalid session or token")
        else:
            raise HTTPException(status_code=403, detail=str(e))


async def require_permission(
    permission: str,
    user: Dict[str, Any] = Depends(get_current_user_auto)
) -> Dict[str, Any]:
    """
    Require a specific permission for the current user.
    
    Args:
        permission: Required permission string (e.g., "users:create")
        user: Current user from auto-login
        
    Returns:
        User if permission granted
        
    Raises:
        HTTPException: 403 if permission denied
    """
    permissions = user.get("permissions", [])
    if permission not in permissions:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {permission} required"
        )
    return user


# Convenience dependencies for common permissions
async def require_admin(
    user: Dict[str, Any] = Depends(get_current_user_required)
) -> Dict[str, Any]:
    """Require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_workflow_create(
    user: Dict[str, Any] = Depends(get_current_user_auto)
) -> Dict[str, Any]:
    """Require permission to create workflows."""
    return await require_permission("workflows:create", user)


async def require_task_create(
    user: Dict[str, Any] = Depends(get_current_user_auto)
) -> Dict[str, Any]:
    """Require permission to create tasks."""
    return await require_permission("tasks:create", user)