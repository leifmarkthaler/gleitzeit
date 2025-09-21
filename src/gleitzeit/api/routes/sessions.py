"""
Session management API routes using SystemManager.

Provides session listing, revocation, and device management.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from gleitzeit.core.errors import SystemError, ErrorCode
from ..dependencies import get_system_manager
from ..auth_dependencies import get_current_user_auto, security
from ..error_handler import gleitzeit_error_to_http
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/", response_model=List[Dict[str, Any]])
async def get_sessions(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager = Depends(get_system_manager)
):
    """Get current user's active sessions."""
    try:
        if not system_manager or not system_manager.auth_manager:
            return []
        
        sessions = await system_manager.auth_manager.get_active_sessions(current_user["id"])
        return sessions
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get sessions error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{session_id}", response_model=Dict[str, Any])
async def revoke_session(
    session_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager = Depends(get_system_manager)
):
    """Revoke a specific session."""
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        success = await system_manager.auth_manager.revoke_session(current_user["id"], session_id)
        if success:
            return {"success": True, "message": "Session revoked"}
        else:
            raise HTTPException(status_code=404, detail="Session not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Revoke session error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/", response_model=Dict[str, Any])
async def revoke_all_sessions(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager = Depends(get_system_manager)
):
    """Revoke all sessions (logout everywhere)."""
    try:
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        count = await system_manager.auth_manager.revoke_all_user_sessions(current_user["id"])
        return {"success": True, "revoked": count, "message": f"Revoked {count} sessions"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Revoke all sessions error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/devices", response_model=List[Dict[str, Any]])
async def get_devices(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager = Depends(get_system_manager)
):
    """Get user's devices/browsers."""
    try:
        if not system_manager or not system_manager.auth_manager:
            return []
        
        devices = await system_manager.auth_manager.get_user_devices(current_user["id"])
        return devices
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get devices error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/devices/trust", response_model=Dict[str, Any])
async def trust_device(
    request: Request,
    trust_days: int = 30,
    current_user: Dict[str, Any] = Depends(get_current_user_auto),
    system_manager = Depends(get_system_manager)
):
    """Trust current device for specified duration."""
    try:
        
        if not system_manager or not system_manager.auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable"
            )
        
        # Get device fingerprint from request
        request_data = {
            "user_agent": request.headers.get("user-agent", ""),
            "accept_language": request.headers.get("accept-language", ""),
            "accept_encoding": request.headers.get("accept-encoding", ""),
            "ip_address": request.client.host if request.client else None
        }
        
        fingerprint = await system_manager.auth_manager.get_session_fingerprint(request_data)
        trust_info = await system_manager.auth_manager.trust_device(
            user["id"], 
            fingerprint, 
            trust_days
        )
        
        return {
            "success": True,
            "trust_id": trust_info["trust_id"],
            "expires_at": trust_info["expires_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trust device error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/history", response_model=List[Dict[str, Any]])
async def get_auth_history(
    request: Request,
    limit: int = 50,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    """Get user's authentication history."""
    try:
        # Get current user
        user = await get_current_user(request, credentials, system_manager)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        if not system_manager or not system_manager.auth_manager:
            return []
        
        history = await system_manager.auth_manager.get_auth_history(user["id"], limit)
        return history
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get auth history error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")