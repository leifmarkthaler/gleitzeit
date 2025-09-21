"""
Authentication API routes that delegate to client methods.

Uses dependency injection for stateless operation.
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from gleitzeit.core.errors import SystemError, ErrorCode
from ..dependencies import get_system_manager
from ..error_handler import handle_auth_error, gleitzeit_error_to_http
import logging
import os

logger = logging.getLogger(__name__)

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




@router.post("/login", response_model=Dict[str, Any])
async def login(
    login_request: LoginRequest,
    request: Request,
    response: Response,
    system_manager = Depends(get_system_manager)
):
    """Login and get authentication token using stateless AuthManager."""
    try:
        if not system_manager or not system_manager.auth_manager:
            # Fallback to basic auth response
            logger.warning("AuthManager not available, using basic auth")
            return {
                "success": True,
                "user": {
                    "id": "basic-user",
                    "username": "basic",
                    "role": "user"
                },
                "token": "basic-token",
                "message": "Basic auth mode"
            }
        
        # Check if user is switching from basic user
        current_session_id = request.cookies.get("session_id")
        if current_session_id:
            # Logout current session (especially important for basic user)
            try:
                await system_manager.auth_manager.logout(current_session_id)
                logger.debug(f"Logged out previous session: {current_session_id}")
            except Exception as e:
                # Ignore logout errors - session might be expired
                logger.debug(f"Could not logout previous session: {e}")
        
        # Build request context for fingerprinting
        request_context = {
            "user_agent": request.headers.get("user-agent", ""),
            "accept_language": request.headers.get("accept-language", ""),
            "accept_encoding": request.headers.get("accept-encoding", ""),
            "ip_address": request.client.host if request.client else None
        }
        
        # Use SystemManager's AuthManager for stateless authentication
        result = await system_manager.auth_manager.login(
            login_request.username,
            login_request.password,
            request_context
        )
        
        # Set session cookie for stateless operation
        if "session_id" in result:
            response.set_cookie(
                key="session_id",
                value=result["session_id"],
                httponly=True,
                secure=True,
                samesite="lax"
            )
        
        return result
        
    except SystemError as e:
        raise handle_auth_error(e)
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise gleitzeit_error_to_http(e)


@router.post("/logout", response_model=Dict[str, Any])
async def logout(
    request: Request,
    response: Response,
    system_manager = Depends(get_system_manager)
):
    """Logout current user using stateless AuthManager."""
    try:
        # Get session from cookie
        session_id = request.cookies.get("session_id")
        if not session_id:
            return {"success": True, "message": "No active session"}
        
        if not system_manager or not system_manager.auth_manager:
            # Basic mode - just clear cookie
            response.delete_cookie("session_id")
            return {"success": True, "message": "Logged out"}
        
        # Use SystemManager's AuthManager
        result = await system_manager.auth_manager.logout(session_id)
        
        # Clear session cookie
        response.delete_cookie("session_id")
        
        return result
        
    except Exception as e:
        logger.error(f"Logout error: {e}")
        # Logout should always succeed
        response.delete_cookie("session_id")
        return {"success": True, "message": "Logged out"}


@router.get("/me", response_model=Dict[str, Any])
async def get_current_user(
    request: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Get current authenticated user using stateless AuthManager."""
    try:
        # Try to get session from cookie first
        session_id = request.cookies.get("session_id")
        
        # Or from Bearer token
        token = None
        if credentials and credentials.credentials:
            token = credentials.credentials
        
        # Debug logging
        logger.debug(f"Auth check - session_id: {session_id}, token: {token}, credentials: {credentials}")
        logger.debug(f"System manager: {system_manager is not None}")
        
        if not session_id and not token:
            # No credentials - try to get basic user session
            if not system_manager or not system_manager.auth_manager:
                # No auth system available - should not happen
                raise HTTPException(status_code=503, detail="Authentication service unavailable")
            
            # Try to create basic session for immediate access
            try:
                session_id, user = await system_manager.auth_manager.get_or_create_basic_session()
                # Set cookie for subsequent requests
                response.set_cookie(
                    key="session_id",
                    value=session_id,
                    httponly=True,
                    secure=False,  # Allow HTTP in development
                    samesite="lax"
                )
                return user
            except SystemError:
                # Basic user not available or session limit exceeded
                raise HTTPException(status_code=401, detail="Authentication required")
        
        if not system_manager or not system_manager.auth_manager:
            # Fallback to basic user
            return {
                "id": "basic-user",
                "username": "basic",
                "role": "user"
            }
        
        # Use session ID if available, otherwise validate token
        if session_id:
            user = await system_manager.auth_manager.get_current_user(session_id)
        else:
            user = await system_manager.auth_manager.validate_session(token)
        
        return user
        
    except SystemError as e:
        raise handle_auth_error(e)
    except Exception as e:
        logger.error(f"Get current user error: {e}")
        raise gleitzeit_error_to_http(e)


@router.post("/register", response_model=Dict[str, Any])
async def register(
    request: RegisterRequest,
    system_manager = Depends(get_system_manager)
):
    """Register a new user (only in advanced auth mode)."""
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Check if user has permission to create users
        # For now, only allow if explicitly enabled
        allow_registration = os.getenv("GLEITZEIT_ALLOW_REGISTRATION", "false").lower() == "true"
        if not allow_registration:
            raise HTTPException(
                status_code=403,
                detail="User registration is disabled"
            )
        
        # In advanced mode, would implement user registration
        # For now, return not implemented
        raise HTTPException(
            status_code=501,
            detail="User registration not yet implemented"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_token(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Refresh authentication token using stateless AuthManager."""
    try:
        if not credentials:
            raise HTTPException(status_code=401, detail="No token provided")
        
        if not system_manager or not system_manager.auth_manager:
            # Basic mode - return same token
            return {
                "success": True,
                "token": credentials.credentials,
                "message": "Basic auth mode"
            }
        
        # Use SystemManager's AuthManager
        result = await system_manager.auth_manager.refresh_token(
            credentials.credentials
        )
        
        # Update session cookie if new session created
        if "session_id" in result:
            response.set_cookie(
                key="session_id",
                value=result["session_id"],
                httponly=True,
                secure=True,
                samesite="lax"
            )
        
        return result
        
    except SystemError as e:
        raise handle_auth_error(e)
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise gleitzeit_error_to_http(e)


@router.post("/change-password", response_model=Dict[str, Any])
async def change_password(
    request: ChangePasswordRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Change user password (only in advanced auth mode)."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if not system_manager or not system_manager.auth_manager:
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable"
        )
    
    # Get current user to check permissions
    try:
        session = await system_manager.auth_manager.validate_session(credentials.credentials)
        user = session.get("user", {})
        if user.get("is_basic_user"):
            raise HTTPException(
                status_code=403,
                detail="Basic user cannot change password"
            )
    except SystemError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Would implement password change in advanced mode
    raise HTTPException(
        status_code=501,
        detail="Password change not yet implemented"
    )


@router.post("/reset-password", response_model=Dict[str, Any])
async def reset_password(
    request: ResetPasswordRequest,
    system_manager = Depends(get_system_manager)
):
    """Request password reset (only in advanced auth mode)."""
    if not system_manager or not system_manager.auth_manager:
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable"
        )
    
    # Password reset only for non-basic users
    # Would check if user exists and is not basic user
    user = await system_manager.auth_manager._get_user_by_username(request.email)
    if user and user.get("is_basic_user"):
        raise HTTPException(
            status_code=403,
            detail="Password reset not available for basic user"
        )
    
    # Would implement password reset in advanced mode
    raise HTTPException(
        status_code=501,
        detail="Password reset not yet implemented"
    )


@router.get("/permissions", response_model=Dict[str, Any])
async def get_user_permissions(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Get current user's permissions using stateless AuthManager."""
    try:
        # Get current user first
        user_response = await get_current_user(request, credentials, system_manager)
        
        if not system_manager or not system_manager.auth_manager:
            # Return basic permissions
            return {
                "permissions": [
                    "workflows:create", "workflows:read",
                    "tasks:create", "tasks:read"
                ]
            }
        
        # Get user permissions
        user_id = user_response.get("id")
        permissions = user_response.get("permissions", [])
        
        return {
            "user_id": user_id,
            "permissions": permissions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get permissions error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/verify-token", response_model=Dict[str, Any])
async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Verify authentication token validity using stateless AuthManager."""
    try:
        if not credentials:
            raise HTTPException(status_code=401, detail="No token provided")
        
        if not system_manager or not system_manager.auth_manager:
            # Basic mode - always valid
            return {
                "valid": True,
                "message": "Basic auth mode"
            }
        
        # Validate token
        try:
            user = await system_manager.auth_manager.validate_session(
                credentials.credentials
            )
            return {
                "valid": True,
                "user": user
            }
        except SystemError:
            return {
                "valid": False,
                "message": "Invalid or expired token"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Helper function for use in other routes
async def get_or_create_session_id(
    request: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials],
    system_manager
) -> str:
    """
    Get or create a session ID for the current request.
    
    In basic mode, automatically creates a basic session if none exists.
    This ensures authentication is always enforced.
    
    Returns:
        Session ID
    """
    # Try to get session from cookie first
    session_id = request.cookies.get("session_id") if request else None
    
    # Or from Bearer token
    token = None
    if credentials:
        token = credentials.credentials
    
    # If we have a session or token, return it
    if session_id:
        return session_id
    if token:
        # Token acts as session ID
        return token
    
    # No session - create one based on mode
    if not system_manager or not system_manager.auth_manager:
        # No auth system - use default
        return "basic-user-default"
    
    # Try to get basic session if no credentials
    try:
        session_id, _ = await system_manager.auth_manager.get_or_create_basic_session()
        
        # Set cookie for subsequent requests if we have response
        if response:
            response.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                secure=False,  # Allow HTTP in development
                samesite="lax"
            )
        
        return session_id
    except SystemError:
        # Basic user not available or session limit exceeded
        raise SystemError(
            message="Authentication required",
            code=ErrorCode.AUTHENTICATION_REQUIRED
        )

async def get_current_user_helper(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
    system_manager
) -> Dict[str, Any]:
    """
    Helper function to get current user in route handlers.
    
    This is used by other routes to get the authenticated user.
    Returns basic user in basic mode, authenticated user otherwise.
    """
    try:
        # Try to get session from cookie first
        session_id = request.cookies.get("session_id") if request else None
        
        # Or from Bearer token
        token = None
        if credentials:
            token = credentials.credentials
        
        # In basic mode or no auth, get/create basic session
        if not system_manager or not system_manager.auth_manager:
            # No auth system - return basic user
            return {
                "id": "basic-user",
                "username": "basic",
                "email": "basic@localhost",
                "role": "user",
                "permissions": ["workflows:create", "workflows:read", "tasks:create", "tasks:read"]
            }
        
        # If no credentials provided
        if not session_id and not token:
            # Try to get basic session
            try:
                session_id, user = await system_manager.auth_manager.get_or_create_basic_session()
                return user
            except SystemError:
                # Return unauthenticated user (no permissions)
                return system_manager.auth_manager.get_unauthenticated_user()
        
        # Validate session/token
        if session_id:
            user = await system_manager.auth_manager.get_current_user(session_id)
        else:
            user = await system_manager.auth_manager.validate_session(token)
        
        return user
        
    except SystemError as e:
        # In case of auth errors, return appropriate unauthenticated user
        logger.debug(f"Auth validation failed: {e}")
        if system_manager and system_manager.auth_manager:
            return system_manager.auth_manager.get_unauthenticated_user()
        else:
            # No auth system - return minimal user
            return {
                "id": "no-auth",
                "username": "no-auth",
                "role": "none",
                "permissions": []
            }
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        # Return appropriate unauthenticated user as fallback
        if system_manager and system_manager.auth_manager:
            return system_manager.auth_manager.get_unauthenticated_user()
        else:
            # Critical error - no auth system
            return {
                "id": "error",
                "username": "error",
                "role": "none",
                "permissions": []
            }


# Export the helper with the original name for compatibility
get_current_user = get_current_user_helper