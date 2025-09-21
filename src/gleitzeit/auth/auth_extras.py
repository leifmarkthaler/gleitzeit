"""
Extended authentication functions for AuthManager.

These functions provide password management, session security,
and other advanced authentication features.
"""

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from gleitzeit.core.errors import (
    SystemError,
    TaskValidationError,
    ErrorCode
)


class AuthManagerExtensions:
    """Mix-in class providing extended authentication functionality."""
    
    async def change_password(
        self,
        user_id: str,
        old_password: str,
        new_password: str
    ) -> bool:
        """
        Change user password with verification.
        
        Args:
            user_id: User ID
            old_password: Current password for verification
            new_password: New password to set
            
        Returns:
            True if successful
            
        Raises:
            SystemError: If old password incorrect or user not found
        """
        # Get user
        user = await self._get_user_by_id(user_id)
        if not user:
            raise SystemError(
                message="User not found",
                code=ErrorCode.NOT_FOUND
            )
        
        # Verify old password
        if not self._verify_password(old_password, user.get("password_hash", "")):
            # Log failed attempt
            await self._log_auth_event(
                user_id=user_id,
                event_type="password_change_failed",
                success=False,
                metadata={"reason": "incorrect_old_password"}
            )
            raise SystemError(
                message="Current password is incorrect",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
        
        # Validate new password
        if not self._validate_password(new_password):
            raise SystemError(
                message="New password does not meet requirements",
                code=ErrorCode.INVALID_PARAMS
            )
        
        # Hash and update password
        user["password_hash"] = self._hash_password(new_password)
        user["updated_at"] = datetime.utcnow().isoformat()
        user["password_changed_at"] = datetime.utcnow().isoformat()
        
        # Save user
        user_key = f"user:{user_id}"
        await self.persistence.set(user_key, user)
        
        # Invalidate all existing sessions (force re-login)
        await self.revoke_all_user_sessions(user_id)
        
        # Log success
        await self._log_auth_event(
            user_id=user_id,
            event_type="password_changed",
            success=True,
            metadata={}
        )
        
        return True
    
    async def request_password_reset(
        self,
        email: str
    ) -> Dict[str, Any]:
        """
        Request password reset token.
        
        Args:
            email: User's email address
            
        Returns:
            Reset token info (in production, would send email)
        """
        # Find user by email
        email_key = f"user:email:{email}"
        user_id = await self.persistence.get(email_key)
        if not user_id:
            # Don't reveal if email exists
            return {"message": "If the email exists, a reset link has been sent"}
        
        # Generate reset token
        reset_token = secrets.token_urlsafe(32)
        reset_data = {
            "user_id": user_id,
            "token": reset_token,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "used": False
        }
        
        # Store reset token
        token_key = f"password_reset:{reset_token}"
        await self.persistence.set(token_key, reset_data)
        
        # Set expiry
        if hasattr(self.persistence, 'expire'):
            await self.persistence.expire(token_key, 3600)  # 1 hour
        
        # Log event
        await self._log_auth_event(
            user_id=user_id,
            event_type="password_reset_requested",
            success=True,
            metadata={"email": email}
        )
        
        # In production, would send email here
        # For development, return token
        return {
            "message": "Password reset requested",
            "token": reset_token,  # Don't return in production!
            "expires_in": 3600
        }
    
    async def reset_password(
        self,
        reset_token: str,
        new_password: str
    ) -> bool:
        """
        Reset password using token.
        
        Args:
            reset_token: Password reset token
            new_password: New password to set
            
        Returns:
            True if successful
        """
        # Get reset token data
        token_key = f"password_reset:{reset_token}"
        reset_data = await self.persistence.get(token_key)
        
        if not reset_data:
            raise SystemError(
                message="Invalid or expired reset token",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
        
        # Check if already used
        if reset_data.get("used"):
            raise SystemError(
                message="Reset token already used",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
        
        # Check expiry
        expires_at = datetime.fromisoformat(reset_data["expires_at"])
        if datetime.utcnow() > expires_at:
            raise SystemError(
                message="Reset token expired",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
        
        # Validate new password
        if not self._validate_password(new_password):
            raise SystemError(
                message="Password does not meet requirements",
                code=ErrorCode.INVALID_PARAMS
            )
        
        # Get user
        user_id = reset_data["user_id"]
        user = await self._get_user_by_id(user_id)
        if not user:
            raise SystemError(
                message="User not found",
                code=ErrorCode.NOT_FOUND
            )
        
        # Update password
        user["password_hash"] = self._hash_password(new_password)
        user["updated_at"] = datetime.utcnow().isoformat()
        user["password_changed_at"] = datetime.utcnow().isoformat()
        
        # Save user
        user_key = f"user:{user_id}"
        await self.persistence.set(user_key, user)
        
        # Mark token as used
        reset_data["used"] = True
        reset_data["used_at"] = datetime.utcnow().isoformat()
        await self.persistence.set(token_key, reset_data)
        
        # Invalidate all sessions
        await self.revoke_all_user_sessions(user_id)
        
        # Log event
        await self._log_auth_event(
            user_id=user_id,
            event_type="password_reset_completed",
            success=True,
            metadata={}
        )
        
        return True
    
    async def get_active_sessions(
        self,
        user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all active sessions for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of active sessions
        """
        # Get session IDs from user's session list
        sessions_key = f"user:{user_id}:sessions"
        session_ids = await self.persistence.get(sessions_key) or []
        
        # Fetch session data
        sessions = []
        for session_id in session_ids:
            session = await self._get_session(session_id)
            if session:
                # Check if not expired
                expires_at = datetime.fromisoformat(session.get("expires_at"))
                if datetime.utcnow() < expires_at:
                    sessions.append({
                        "session_id": session_id,
                        "created_at": session.get("created_at"),
                        "expires_at": session.get("expires_at"),
                        "last_activity": session.get("last_activity")
                    })
        
        return sessions
    
    async def revoke_session(
        self,
        user_id: str,
        session_id: str
    ) -> bool:
        """
        Revoke a specific session.
        
        Args:
            user_id: User ID (for verification)
            session_id: Session to revoke
            
        Returns:
            True if revoked
        """
        # Verify session belongs to user
        session = await self._get_session(session_id)
        if not session or session.get("user", {}).get("id") != user_id:
            return False
        
        # Delete session
        await self._delete_session(session_id)
        
        # Remove from user's session list
        sessions_key = f"user:{user_id}:sessions"
        session_ids = await self.persistence.get(sessions_key) or []
        if session_id in session_ids:
            session_ids.remove(session_id)
            await self.persistence.set(sessions_key, session_ids)
        
        # Log event
        await self._log_auth_event(
            user_id=user_id,
            event_type="session_revoked",
            success=True,
            metadata={"session_id": session_id}
        )
        
        return True
    
    async def revoke_all_user_sessions(
        self,
        user_id: str
    ) -> int:
        """
        Revoke all sessions for a user (logout everywhere).
        
        Args:
            user_id: User ID
            
        Returns:
            Number of sessions revoked
        """
        # Get all user sessions
        sessions_key = f"user:{user_id}:sessions"
        session_ids = await self.persistence.get(sessions_key) or []
        
        # Delete each session
        count = 0
        for session_id in session_ids:
            await self._delete_session(session_id)
            count += 1
        
        # Clear session list
        await self.persistence.delete(sessions_key)
        
        # Log event
        if count > 0:
            await self._log_auth_event(
                user_id=user_id,
                event_type="all_sessions_revoked",
                success=True,
                metadata={"count": count}
            )
        
        return count
    
    async def check_account_lockout(self, username: str) -> Dict[str, Any]:
        """
        Check if account is locked without incrementing failure count.
        
        Args:
            username: Username to check
            
        Returns:
            Dict with locked status and message
        """
        key = f"login_failures:{username}"
        failures = await self.persistence.get(key)
        
        if not failures or not failures.get("locked_until"):
            return {"locked": False}
        
        locked_until = datetime.fromisoformat(failures["locked_until"])
        if datetime.utcnow() < locked_until:
            remaining = (locked_until - datetime.utcnow()).total_seconds()
            return {
                "locked": True,
                "remaining_seconds": int(remaining),
                "message": f"Account locked for {int(remaining)} seconds"
            }
        
        return {"locked": False}
    
    async def track_failed_login(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Track failed login attempt for brute force protection.
        
        Args:
            username: Username attempted
            ip_address: IP address of attempt
            
        Returns:
            Status including lockout info
        """
        # Get or create failure tracking
        key = f"login_failures:{username}"
        failures = await self.persistence.get(key) or {
            "count": 0,
            "first_attempt": None,
            "last_attempt": None,
            "locked_until": None
        }
        
        # Check if currently locked
        if failures.get("locked_until"):
            locked_until = datetime.fromisoformat(failures["locked_until"])
            if datetime.utcnow() < locked_until:
                remaining = (locked_until - datetime.utcnow()).total_seconds()
                return {
                    "locked": True,
                    "remaining_seconds": int(remaining),
                    "message": f"Account locked for {int(remaining)} seconds"
                }
            else:
                # Lockout expired, reset
                failures = {"count": 0, "first_attempt": None, "last_attempt": None, "locked_until": None}
        
        # Increment failure count
        failures["count"] += 1
        failures["last_attempt"] = datetime.utcnow().isoformat()
        if not failures["first_attempt"]:
            failures["first_attempt"] = failures["last_attempt"]
        
        # Check if should lock account
        lockout_threshold = 5  # Lock after 5 failed attempts
        lockout_duration = 300  # 5 minutes
        
        if failures["count"] >= lockout_threshold:
            failures["locked_until"] = (
                datetime.utcnow() + timedelta(seconds=lockout_duration)
            ).isoformat()
            
            # Log lockout event
            user = await self._get_user_by_username(username)
            if user:
                await self._log_auth_event(
                    user_id=user["id"],
                    event_type="account_locked",
                    success=False,
                    metadata={
                        "reason": "brute_force",
                        "attempts": failures["count"],
                        "ip_address": ip_address
                    }
                )
            
            await self.persistence.set(key, failures)
            
            return {
                "locked": True,
                "remaining_seconds": lockout_duration,
                "message": f"Account locked due to {failures['count']} failed attempts"
            }
        
        # Not locked yet
        await self.persistence.set(key, failures)
        
        # Set expiry for failure tracking (reset after 1 hour of no attempts)
        if hasattr(self.persistence, 'expire'):
            await self.persistence.expire(key, 3600)
        
        return {
            "locked": False,
            "attempts": failures["count"],
            "remaining_attempts": lockout_threshold - failures["count"],
            "message": f"{lockout_threshold - failures['count']} attempts remaining before lockout"
        }
    
    async def clear_failed_logins(
        self,
        username: str
    ) -> bool:
        """
        Clear failed login attempts after successful login.
        
        Args:
            username: Username to clear
            
        Returns:
            True if cleared
        """
        key = f"login_failures:{username}"
        await self.persistence.delete(key)
        return True
    
    async def get_auth_history(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get authentication history for a user.
        
        Args:
            user_id: User ID
            limit: Maximum number of events to return
            
        Returns:
            List of auth events
        """
        # Get user's event IDs
        user_events_key = f"user:{user_id}:auth_events"
        event_ids = await self.persistence.get(user_events_key) or []
        
        # Get most recent events
        recent_ids = event_ids[-limit:] if len(event_ids) > limit else event_ids
        recent_ids.reverse()  # Most recent first
        
        # Fetch event data
        events = []
        for event_id in recent_ids:
            event_key = f"auth_event:{event_id}"
            event = await self.persistence.get(event_key)
            if event:
                events.append(event)
        
        return events