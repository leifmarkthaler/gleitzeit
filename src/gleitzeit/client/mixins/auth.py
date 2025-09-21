"""
Authentication mixin for Gleitzeit client.
"""

from typing import Any, Dict, Optional, List

from gleitzeit.core.errors import SystemError


class AuthMixin:
    """Mixin providing authentication operations."""
    
    # Core auth operations
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login user."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.login(username, password)
    
    async def logout(self) -> Dict[str, Any]:
        """Logout current user."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.logout()
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current authenticated user."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_current_user()
    
    # User management operations
    
    async def create_user(self, username: str, email: str, password: str, 
                         role: str = "user", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a new user."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.create_user(username, email, password, role, metadata)
    
    async def list_users(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List all users."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.list_users(limit, offset)
    
    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_user(user_id)
    
    async def update_user(self, user_id: str, **kwargs) -> Dict[str, Any]:
        """Update user information."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.update_user(user_id, **kwargs)
    
    async def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.delete_user(user_id)
    
    async def activate_user(self, user_id: str) -> Dict[str, Any]:
        """Activate a user account."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.activate_user(user_id)
    
    async def deactivate_user(self, user_id: str) -> Dict[str, Any]:
        """Deactivate a user account."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.deactivate_user(user_id)
    
    async def search_users(self, query: str, field: str = "username") -> List[Dict[str, Any]]:
        """Search for users."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.search_users(query, field)
    
    # Password management operations
    
    async def change_password(self, user_id: str, old_password: str, new_password: str) -> bool:
        """Change user password."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.change_password(user_id, old_password, new_password)
    
    async def request_password_reset(self, email: str) -> Dict[str, Any]:
        """Request a password reset."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.request_password_reset(email)
    
    async def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password with token."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.reset_password(token, new_password)
    
    # Session management operations
    
    async def get_sessions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get active sessions for a user (current user if user_id not provided)."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        
        # If user_id not provided and adapter has method without user_id, use it
        if user_id is None and hasattr(self._adapter, 'get_sessions') and \
           self._adapter.__class__.__name__ == 'APIAdapter':
            # API adapter gets current user's sessions
            return await self._adapter.get_sessions()
        elif user_id:
            # Native adapter needs user_id
            return await self._adapter.get_sessions(user_id)
        else:
            # Get current user's ID first
            user = await self.get_current_user()
            if user and 'id' in user:
                return await self._adapter.get_sessions(user['id'])
        return []
    
    async def revoke_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Revoke a specific session."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        
        # API adapter doesn't need user_id
        if hasattr(self._adapter, 'revoke_session'):
            if self._adapter.__class__.__name__ == 'APIAdapter':
                return await self._adapter.revoke_session(session_id)
            elif user_id:
                return await self._adapter.revoke_session(user_id, session_id)
        return False
    
    async def revoke_all_sessions(self, user_id: Optional[str] = None) -> int:
        """Revoke all sessions for a user."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        
        # API adapter doesn't need user_id
        if hasattr(self._adapter, 'revoke_all_sessions'):
            if self._adapter.__class__.__name__ == 'APIAdapter':
                result = await self._adapter.revoke_all_sessions()
                return result.get('revoked', 0) if isinstance(result, dict) else 0
            elif user_id:
                return await self._adapter.revoke_all_sessions(user_id)
        return 0
    
    async def get_devices(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get user's trusted devices."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        
        # API adapter doesn't need user_id
        if hasattr(self._adapter, 'get_devices'):
            if self._adapter.__class__.__name__ == 'APIAdapter':
                return await self._adapter.get_devices()
            elif user_id:
                return await self._adapter.get_devices(user_id)
        return []
    
    async def trust_device(self, trust_days: int = 30, user_id: Optional[str] = None, 
                          fingerprint: Optional[str] = None) -> Dict[str, Any]:
        """Trust current device."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        
        # API adapter uses current context
        if hasattr(self._adapter, 'trust_device'):
            if self._adapter.__class__.__name__ == 'APIAdapter':
                return await self._adapter.trust_device(trust_days)
            elif user_id and fingerprint:
                return await self._adapter.trust_device(user_id, fingerprint, trust_days)
        return {"success": False, "message": "Not supported"}
    
    async def get_auth_history(self, limit: int = 50, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get authentication history."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        
        # API adapter doesn't need user_id
        if hasattr(self._adapter, 'get_auth_history'):
            if self._adapter.__class__.__name__ == 'APIAdapter':
                return await self._adapter.get_auth_history(limit)
            elif user_id:
                return await self._adapter.get_auth_history(user_id, limit)
        return []
    
    # Email verification operations
    
    async def send_verification_email(self, user_id: str) -> Dict[str, Any]:
        """Send email verification link."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.send_verification_email(user_id)
    
    async def verify_email(self, token: str) -> bool:
        """Verify email with token."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.verify_email(token)