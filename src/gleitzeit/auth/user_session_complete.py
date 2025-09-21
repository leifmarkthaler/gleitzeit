"""
Complete user and session management functions for AuthManager.

Provides user activation/deactivation, email verification,
session limits, activity tracking, and device fingerprinting.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set

from gleitzeit.core.errors import (
    SystemError,
    TaskValidationError,
    ErrorCode
)


class UserSessionComplete:
    """Mix-in class providing complete user and session management."""
    
    # User Management Completion
    
    async def activate_user(self, user_id: str) -> Dict[str, Any]:
        """
        Activate a user account.
        
        Args:
            user_id: User ID to activate
            
        Returns:
            Updated user info
        """
        user = await self._get_user_by_id(user_id)
        if not user:
            raise SystemError(
                message="User not found",
                code=ErrorCode.NOT_FOUND
            )
        
        if user.get("is_active"):
            return user  # Already active
        
        # Activate user
        user["is_active"] = True
        user["activated_at"] = datetime.utcnow().isoformat()
        user["updated_at"] = datetime.utcnow().isoformat()
        
        # Save user
        user_key = f"user:{user_id}"
        await self.persistence.set(user_key, user)
        
        # Log activation
        await self._log_auth_event(
            user_id=user_id,
            event_type="user_activated",
            success=True,
            metadata={}
        )
        
        # Remove sensitive data
        user.pop("password_hash", None)
        return user
    
    async def deactivate_user(self, user_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Deactivate a user account.
        
        Args:
            user_id: User ID to deactivate
            reason: Optional reason for deactivation
            
        Returns:
            Updated user info
        """
        user = await self._get_user_by_id(user_id)
        if not user:
            raise SystemError(
                message="User not found",
                code=ErrorCode.NOT_FOUND
            )
        
        if not user.get("is_active"):
            return user  # Already inactive
        
        # Deactivate user
        user["is_active"] = False
        user["deactivated_at"] = datetime.utcnow().isoformat()
        user["deactivation_reason"] = reason
        user["updated_at"] = datetime.utcnow().isoformat()
        
        # Save user
        user_key = f"user:{user_id}"
        await self.persistence.set(user_key, user)
        
        # Revoke all sessions
        await self.revoke_all_user_sessions(user_id)
        
        # Log deactivation
        await self._log_auth_event(
            user_id=user_id,
            event_type="user_deactivated",
            success=True,
            metadata={"reason": reason}
        )
        
        # Remove sensitive data
        user.pop("password_hash", None)
        return user
    
    async def send_verification_email(self, user_id: str) -> Dict[str, Any]:
        """
        Send email verification token.
        
        Args:
            user_id: User ID
            
        Returns:
            Verification token info
        """
        user = await self._get_user_by_id(user_id)
        if not user:
            raise SystemError(
                message="User not found",
                code=ErrorCode.NOT_FOUND
            )
        
        if user.get("email_verified"):
            return {"message": "Email already verified"}
        
        # Generate verification token
        token = secrets.token_urlsafe(32)
        verification_data = {
            "user_id": user_id,
            "email": user.get("email"),
            "token": token,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat()
        }
        
        # Store verification token
        token_key = f"email_verification:{token}"
        await self.persistence.set(token_key, verification_data)
        
        # Set expiry
        if hasattr(self.persistence, 'expire'):
            await self.persistence.expire(token_key, 86400)  # 24 hours
        
        # Log event
        await self._log_auth_event(
            user_id=user_id,
            event_type="verification_email_sent",
            success=True,
            metadata={"email": user.get("email")}
        )
        
        # In production, would send actual email
        return {
            "message": "Verification email sent",
            "token": token,  # Don't return in production!
            "expires_in": 86400
        }
    
    async def verify_email(self, token: str) -> Dict[str, Any]:
        """
        Verify email with token.
        
        Args:
            token: Verification token
            
        Returns:
            Verification result
        """
        # Get verification data
        token_key = f"email_verification:{token}"
        verification_data = await self.persistence.get(token_key)
        
        if not verification_data:
            raise SystemError(
                message="Invalid verification token",
                code=ErrorCode.INVALID_PARAMS
            )
        
        # Check expiry
        expires_at = datetime.fromisoformat(verification_data["expires_at"])
        if datetime.utcnow() > expires_at:
            await self.persistence.delete(token_key)
            raise SystemError(
                message="Verification token expired",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
        
        # Get user
        user_id = verification_data["user_id"]
        user = await self._get_user_by_id(user_id)
        if not user:
            raise SystemError(
                message="User not found",
                code=ErrorCode.NOT_FOUND
            )
        
        # Verify email
        user["email_verified"] = True
        user["email_verified_at"] = datetime.utcnow().isoformat()
        user["updated_at"] = datetime.utcnow().isoformat()
        
        # Save user
        user_key = f"user:{user_id}"
        await self.persistence.set(user_key, user)
        
        # Delete token
        await self.persistence.delete(token_key)
        
        # Log event
        await self._log_auth_event(
            user_id=user_id,
            event_type="email_verified",
            success=True,
            metadata={"email": user.get("email")}
        )
        
        return {
            "success": True,
            "message": "Email verified successfully",
            "user_id": user_id
        }
    
    async def search_users(
        self,
        query: str,
        field: str = "username",
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for users by username or email.
        
        Args:
            query: Search query
            field: Field to search (username or email)
            limit: Maximum results
            
        Returns:
            List of matching users
        """
        users = []
        
        if field == "username":
            # Try exact match first
            user_id = await self.persistence.get(f"user:username:{query}")
            if user_id:
                user = await self._get_user_by_id(user_id)
                if user:
                    user.pop("password_hash", None)
                    users.append(user)
            
            # For partial matches, would need to iterate through all users
            # This is inefficient without a proper search index
            
        elif field == "email":
            # Try exact match
            user_id = await self.persistence.get(f"user:email:{query}")
            if user_id:
                user = await self._get_user_by_id(user_id)
                if user:
                    user.pop("password_hash", None)
                    users.append(user)
        
        return users[:limit]
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Get user by email address.
        
        Args:
            email: Email address
            
        Returns:
            User data or None
        """
        email_key = f"user:email:{email}"
        user_id = await self.persistence.get(email_key)
        if user_id:
            user = await self._get_user_by_id(user_id)
            if user:
                user.pop("password_hash", None)
            return user
        return None
    
    # Session Management Completion
    
    async def enforce_session_limit(
        self,
        user_id: str,
        max_sessions: int = 5
    ) -> int:
        """
        Enforce maximum concurrent sessions per user.
        
        Args:
            user_id: User ID
            max_sessions: Maximum allowed sessions
            
        Returns:
            Number of sessions revoked
        """
        # Get user's sessions
        sessions_key = f"user:{user_id}:sessions"
        session_ids = await self.persistence.get(sessions_key) or []
        
        revoked = 0
        if len(session_ids) > max_sessions:
            # Get session details to find oldest
            sessions_with_time = []
            for session_id in session_ids:
                session = await self._get_session(session_id)
                if session:
                    created_at = datetime.fromisoformat(session.get("created_at"))
                    sessions_with_time.append((session_id, created_at))
            
            # Sort by creation time (oldest first)
            sessions_with_time.sort(key=lambda x: x[1])
            
            # Revoke oldest sessions
            to_revoke = len(sessions_with_time) - max_sessions
            for session_id, _ in sessions_with_time[:to_revoke]:
                await self._delete_session(session_id)
                session_ids.remove(session_id)
                revoked += 1
            
            # Update session list
            await self.persistence.set(sessions_key, session_ids)
            
            # Log event
            if revoked > 0:
                await self._log_auth_event(
                    user_id=user_id,
                    event_type="sessions_limit_enforced",
                    success=True,
                    metadata={"revoked": revoked, "limit": max_sessions}
                )
        
        return revoked
    
    async def update_session_activity(self, session_id: str) -> bool:
        """
        Update last activity timestamp for a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if updated
        """
        session = await self._get_session(session_id)
        if not session:
            return False
        
        # Update activity timestamp
        session["last_activity"] = datetime.utcnow().isoformat()
        
        # Save session
        session_key = f"session:{session_id}"
        await self.persistence.set(session_key, session)
        
        # Reset TTL if supported
        if hasattr(self.persistence, 'expire'):
            ttl = self.token_expiry_hours * 3600
            await self.persistence.expire(session_key, ttl)
        
        return True
    
    async def get_session_fingerprint(
        self,
        request_data: Dict[str, Any]
    ) -> str:
        """
        Generate device/browser fingerprint from request.
        
        Args:
            request_data: Request information (headers, IP, etc.)
            
        Returns:
            Fingerprint hash
        """
        # Collect fingerprint components
        components = [
            request_data.get("user_agent", ""),
            request_data.get("accept_language", ""),
            request_data.get("accept_encoding", ""),
            request_data.get("screen_resolution", ""),
            request_data.get("timezone", ""),
            request_data.get("platform", ""),
            # Don't include IP as it can change
        ]
        
        # Create hash
        fingerprint_str = "|".join(components)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()
    
    async def validate_session_fingerprint(
        self,
        session_id: str,
        fingerprint: str
    ) -> bool:
        """
        Validate session fingerprint matches.
        
        Args:
            session_id: Session ID
            fingerprint: Current fingerprint
            
        Returns:
            True if valid
        """
        session = await self._get_session(session_id)
        if not session:
            return False
        
        stored_fingerprint = session.get("fingerprint")
        if not stored_fingerprint:
            # No fingerprint stored, add it
            session["fingerprint"] = fingerprint
            session_key = f"session:{session_id}"
            await self.persistence.set(session_key, session)
            return True
        
        # Check if fingerprint matches
        return stored_fingerprint == fingerprint
    
    async def detect_suspicious_session(
        self,
        session_id: str,
        request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Detect suspicious session activity.
        
        Args:
            session_id: Session ID
            request_data: Current request data
            
        Returns:
            Suspicion analysis
        """
        session = await self._get_session(session_id)
        if not session:
            return {"suspicious": True, "reason": "Session not found"}
        
        suspicious_indicators = []
        
        # Check fingerprint change
        current_fingerprint = await self.get_session_fingerprint(request_data)
        if not await self.validate_session_fingerprint(session_id, current_fingerprint):
            suspicious_indicators.append("fingerprint_mismatch")
        
        # Check for rapid location change
        last_ip = session.get("last_ip")
        current_ip = request_data.get("ip_address")
        if last_ip and current_ip and last_ip != current_ip:
            # In production, would check geographic distance
            suspicious_indicators.append("ip_change")
        
        # Check for unusual activity time
        last_activity = session.get("last_activity")
        if last_activity:
            last_time = datetime.fromisoformat(last_activity)
            time_diff = (datetime.utcnow() - last_time).total_seconds()
            if time_diff > 86400:  # More than 24 hours
                suspicious_indicators.append("long_inactivity")
        
        # Update session with current info
        session["last_ip"] = current_ip
        session["last_activity"] = datetime.utcnow().isoformat()
        session_key = f"session:{session_id}"
        await self.persistence.set(session_key, session)
        
        # Log if suspicious
        if suspicious_indicators:
            user = session.get("user", {})
            await self._log_auth_event(
                user_id=user.get("id"),
                event_type="suspicious_session_activity",
                success=False,
                metadata={
                    "session_id": session_id,
                    "indicators": suspicious_indicators
                }
            )
        
        return {
            "suspicious": len(suspicious_indicators) > 0,
            "indicators": suspicious_indicators,
            "risk_level": "high" if len(suspicious_indicators) > 1 else "medium" if suspicious_indicators else "low"
        }
    
    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions from all users.
        
        Returns:
            Number of sessions cleaned
        """
        cleaned = 0
        
        # Get all users
        users_list_key = "users:list"
        user_ids = await self.persistence.get(users_list_key) or []
        
        for user_id in user_ids:
            # Get user's sessions
            sessions_key = f"user:{user_id}:sessions"
            session_ids = await self.persistence.get(sessions_key) or []
            
            valid_sessions = []
            for session_id in session_ids:
                session = await self._get_session(session_id)
                if session:
                    # Check expiry
                    expires_at = datetime.fromisoformat(session.get("expires_at"))
                    if datetime.utcnow() < expires_at:
                        valid_sessions.append(session_id)
                    else:
                        # Delete expired session
                        await self._delete_session(session_id)
                        cleaned += 1
            
            # Update user's session list
            if len(valid_sessions) != len(session_ids):
                await self.persistence.set(sessions_key, valid_sessions)
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired sessions")
        
        return cleaned
    
    async def get_user_devices(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get list of devices/browsers user has logged in from.
        
        Args:
            user_id: User ID
            
        Returns:
            List of device information
        """
        # Get user's sessions
        sessions = await self.get_active_sessions(user_id)
        
        devices = []
        seen_fingerprints = set()
        
        for session_info in sessions:
            session = await self._get_session(session_info["session_id"])
            if session:
                fingerprint = session.get("fingerprint")
                if fingerprint and fingerprint not in seen_fingerprints:
                    seen_fingerprints.add(fingerprint)
                    devices.append({
                        "fingerprint": fingerprint,
                        "last_seen": session.get("last_activity"),
                        "created_at": session.get("created_at"),
                        "last_ip": session.get("last_ip"),
                        "sessions_count": 1  # Would count all sessions with this fingerprint
                    })
        
        return devices
    
    async def trust_device(
        self,
        user_id: str,
        fingerprint: str,
        trust_duration_days: int = 30
    ) -> Dict[str, Any]:
        """
        Mark a device as trusted for the user.
        
        Args:
            user_id: User ID
            fingerprint: Device fingerprint
            trust_duration_days: How long to trust the device
            
        Returns:
            Trust information
        """
        trust_data = {
            "user_id": user_id,
            "fingerprint": fingerprint,
            "trusted_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(days=trust_duration_days)).isoformat(),
            "trust_id": str(uuid.uuid4())
        }
        
        # Store trusted device
        trust_key = f"trusted_device:{user_id}:{fingerprint}"
        await self.persistence.set(trust_key, trust_data)
        
        # Set expiry
        if hasattr(self.persistence, 'expire'):
            await self.persistence.expire(trust_key, trust_duration_days * 86400)
        
        # Log event
        await self._log_auth_event(
            user_id=user_id,
            event_type="device_trusted",
            success=True,
            metadata={"fingerprint": fingerprint}
        )
        
        return trust_data
    
    async def is_device_trusted(
        self,
        user_id: str,
        fingerprint: str
    ) -> bool:
        """
        Check if a device is trusted.
        
        Args:
            user_id: User ID
            fingerprint: Device fingerprint
            
        Returns:
            True if trusted and not expired
        """
        trust_key = f"trusted_device:{user_id}:{fingerprint}"
        trust_data = await self.persistence.get(trust_key)
        
        if not trust_data:
            return False
        
        # Check expiry
        expires_at = datetime.fromisoformat(trust_data["expires_at"])
        if datetime.utcnow() > expires_at:
            # Expired, clean up
            await self.persistence.delete(trust_key)
            return False
        
        return True


# Import logger if needed
import logging
logger = logging.getLogger(__name__)