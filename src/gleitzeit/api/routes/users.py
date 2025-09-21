"""
User management API routes using SystemManager.

Provides CRUD operations for users through the AuthManager.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from gleitzeit.core.errors import SystemError, ErrorCode
from ..dependencies import get_system_manager
from ..auth_dependencies import get_current_user_required, security
from ..error_handler import gleitzeit_error_to_http
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


async def require_admin(
    current_user: Dict[str, Any] = Depends(get_current_user_required)
) -> Dict[str, Any]:
    """
    Helper to require admin role for protected endpoints.
    
    Returns:
        Current user if admin, raises HTTPException otherwise
    """
    # Check for admin role
    if current_user.get('role') != 'admin':
        raise HTTPException(
            status_code=403, 
            detail="Admin role required. User management is not available for basic users."
        )
    
    return current_user


class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "user"
    metadata: Optional[Dict[str, Any]] = None


class UpdateUserRequest(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


@router.get("/", response_model=List[Dict[str, Any]])
async def list_users(
    offset: int = 0,
    limit: int = 100,
    request: Request = None,
    admin_user: Dict[str, Any] = Depends(require_admin),
    system_manager = Depends(get_system_manager)
):
    """
    List all users (requires admin role).
    
    Args:
        offset: Pagination offset
        limit: Maximum users to return
        
    Returns:
        List of users without passwords
    """
    try:
        # Check if auth manager available
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Basic users can't list users
        # Admin check already performed by require_admin dependency
        
        # Admin check already performed by require_admin dependency
        
        users = await system_manager.auth_manager.list_users(offset, limit)
        return users
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/", response_model=Dict[str, Any])
async def create_user(
    user_request: CreateUserRequest,
    admin_user: Dict[str, Any] = Depends(require_admin),
    system_manager = Depends(get_system_manager)
):
    """
    Create a new user (requires admin role in production).
    
    Args:
        user_request: User creation details
        
    Returns:
        Created user without password
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Basic users can't create users
        # Admin check already performed by require_admin dependency
        
        # Admin check already performed by require_admin dependency
        
        # Create user
        user = await system_manager.auth_manager.create_user(
            username=user_request.username,
            email=user_request.email,
            password=user_request.password,
            role=user_request.role,
            metadata=user_request.metadata
        )
        
        return user
        
    except SystemError as e:
        raise gleitzeit_error_to_http(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise gleitzeit_error_to_http(e)


@router.get("/{user_id}", response_model=Dict[str, Any])
async def get_user(
    user_id: str,
    system_manager = Depends(get_system_manager)
):
    """
    Get user by ID.
    
    Args:
        user_id: User ID
        
    Returns:
        User data without password
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Get user
        user = await system_manager.auth_manager._get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Remove password
        user.pop("password_hash", None)
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{user_id}", response_model=Dict[str, Any])
async def update_user(
    user_id: str,
    updates: UpdateUserRequest,
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """
    Update user information.
    
    Args:
        user_id: User ID
        updates: Fields to update
        
    Returns:
        Updated user
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Check permissions (admin or self)
        current_user = await get_current_user(request, credentials, system_manager)
        if not current_user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Allow if admin or updating own profile
        if current_user.get('role') != 'admin' and current_user.get('id') != user_id:
            raise HTTPException(status_code=403, detail="Permission denied")
        
        # Update user
        update_dict = updates.dict(exclude_unset=True)
        user = await system_manager.auth_manager.update_user(user_id, update_dict)
        
        return user
        
    except SystemError as e:
        raise gleitzeit_error_to_http(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise gleitzeit_error_to_http(e)


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    admin_user: Dict[str, Any] = Depends(require_admin),
    system_manager = Depends(get_system_manager)
):
    """
    Delete a user (requires admin role).
    
    Args:
        user_id: User ID to delete
        
    Returns:
        Success status
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Admin check already performed by require_admin dependency
        # Prevent self-deletion
        if admin_user.get('id') == user_id:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        
        # Delete user
        success = await system_manager.auth_manager.delete_user(user_id)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"success": True, "message": "User deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: str,
    admin_user: Dict[str, Any] = Depends(require_admin),
    system_manager = Depends(get_system_manager)
):
    """
    Activate a deactivated user account.
    
    Args:
        user_id: User ID to activate
        
    Returns:
        Updated user
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Admin check already performed by require_admin dependency
        
        user = await system_manager.auth_manager.activate_user(user_id)
        return user
        
    except SystemError as e:
        raise gleitzeit_error_to_http(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating user: {e}")
        raise gleitzeit_error_to_http(e)


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    reason: Optional[str] = None,
    admin_user: Dict[str, Any] = Depends(require_admin),
    system_manager = Depends(get_system_manager)
):
    """
    Deactivate a user account.
    
    Args:
        user_id: User ID to deactivate
        reason: Optional reason for deactivation
        
    Returns:
        Updated user
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Admin check already performed by require_admin dependency
        
        user = await system_manager.auth_manager.deactivate_user(user_id, reason)
        return user
        
    except SystemError as e:
        raise gleitzeit_error_to_http(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating user: {e}")
        raise gleitzeit_error_to_http(e)


@router.post("/{user_id}/send-verification")
async def send_verification(
    user_id: str,
    system_manager = Depends(get_system_manager)
):
    """
    Send email verification to user.
    
    Args:
        user_id: User ID
        
    Returns:
        Verification status
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # TODO: Check if user can send verification (admin or self)
        
        result = await system_manager.auth_manager.send_verification_email(user_id)
        
        # Don't return token in production
        return {"message": result.get("message"), "expires_in": result.get("expires_in")}
        
    except SystemError as e:
        raise gleitzeit_error_to_http(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending verification: {e}")
        raise gleitzeit_error_to_http(e)


@router.get("/search/{query}")
async def search_users(
    query: str,
    field: str = "username",
    limit: int = 10,
    system_manager = Depends(get_system_manager)
):
    """
    Search for users by username or email.
    
    Args:
        query: Search query
        field: Field to search (username or email)
        limit: Maximum results
        
    Returns:
        List of matching users
    """
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # TODO: Add permission check
        
        if field not in ["username", "email"]:
            raise HTTPException(
                status_code=400,
                detail="Field must be 'username' or 'email'"
            )
        
        users = await system_manager.auth_manager.search_users(query, field, limit)
        return users
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")