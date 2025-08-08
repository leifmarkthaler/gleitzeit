"""
Main authentication manager

Provides high-level authentication and authorization functionality.
Integrates with storage layer and provides API for the rest of the system.
"""

import os
from typing import Optional, List, Dict, Set
from pathlib import Path

from .models import User, APIKey, Role, Permission, AuthContext
from .storage import AuthStorage


class AuthenticationError(Exception):
    """Authentication failed"""
    pass


class AuthorizationError(Exception):
    """Authorization failed - user lacks required permission"""
    pass


class AuthManager:
    """Main authentication and authorization manager"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize auth manager
        
        Args:
            config_dir: Directory for auth files (default: ~/.gleitzeit)
        """
        self.storage = AuthStorage(config_dir)
        self._current_context: Optional[AuthContext] = None
    
    def initialize(self) -> bool:
        """
        Initialize authentication system
        
        Creates default admin user if no users exist.
        Returns True if initialization was needed.
        """
        users = self.storage.list_users()
        if not users:
            try:
                admin_user, admin_key = self.storage.initialize_default_admin()
                print(f"✅ Created default admin user: {admin_user.username}")
                print(f"🔑 Admin API key: {admin_key}")
                print("⚠️  Store this key securely - it won't be shown again!")
                return True
            except ValueError:
                pass  # Admin already exists
        
        return False
    
    def authenticate_api_key(self, api_key: str, ip_address: Optional[str] = None) -> AuthContext:
        """
        Authenticate using API key
        
        Args:
            api_key: Raw API key string
            ip_address: Client IP address for logging
            
        Returns:
            AuthContext for authenticated user
            
        Raises:
            AuthenticationError: If authentication fails
        """
        # Try to authenticate API key
        key_obj = self.storage.authenticate_api_key(api_key)
        if not key_obj:
            raise AuthenticationError("Invalid API key")
        
        # Get associated user
        user = self.storage.get_user(key_obj.user_id)
        if not user or not user.is_active:
            raise AuthenticationError("User account not found or inactive")
        
        # Update user login time
        from datetime import datetime
        user.last_login_at = datetime.utcnow()
        self.storage.update_user(user)
        
        # Create auth context
        context = AuthContext(
            user=user,
            api_key=key_obj,
            ip_address=ip_address,
            user_agent=None,  # CLI doesn't have user agent
            authenticated_at=datetime.utcnow()
        )
        
        return context
    
    def authenticate_from_environment(self) -> Optional[AuthContext]:
        """
        Authenticate from environment variables or config
        
        Checks:
        1. GLEITZEIT_API_KEY environment variable
        2. Current context from config file
        
        Returns:
            AuthContext if authentication succeeds, None otherwise
        """
        # Try environment variable first
        api_key = os.environ.get('GLEITZEIT_API_KEY')
        if api_key:
            try:
                return self.authenticate_api_key(api_key)
            except AuthenticationError:
                pass
        
        # Try current context from config
        current_context = self.storage.get_current_context()
        if current_context:
            try:
                return self.authenticate_api_key(current_context)
            except AuthenticationError:
                # Clear invalid context
                self.storage.clear_current_context()
        
        return None
    
    def get_current_context(self) -> Optional[AuthContext]:
        """Get current authentication context"""
        if self._current_context is None:
            self._current_context = self.authenticate_from_environment()
        
        return self._current_context
    
    def set_current_context(self, context: AuthContext):
        """Set current authentication context"""
        self._current_context = context
        
        # Save to config if API key is available
        if context.api_key:
            # We need to reconstruct the raw key from the context
            # For CLI usage, we'll store the key ID and let user provide full key
            pass
    
    def clear_current_context(self):
        """Clear current authentication context"""
        self._current_context = None
        self.storage.clear_current_context()
    
    def require_authentication(self) -> AuthContext:
        """
        Require authentication - raises exception if not authenticated
        
        Returns:
            Current auth context
            
        Raises:
            AuthenticationError: If not authenticated
        """
        context = self.get_current_context()
        if not context:
            raise AuthenticationError(
                "Authentication required. Use 'gleitzeit auth login' or set GLEITZEIT_API_KEY"
            )
        
        return context
    
    def require_permission(self, permission: Permission) -> AuthContext:
        """
        Require specific permission - raises exception if not authorized
        
        Args:
            permission: Required permission
            
        Returns:
            Current auth context
            
        Raises:
            AuthenticationError: If not authenticated
            AuthorizationError: If lacking required permission
        """
        context = self.require_authentication()
        
        if not context.has_permission(permission):
            raise AuthorizationError(
                f"Permission denied. Required permission: {permission.value}"
            )
        
        return context
    
    def require_role(self, role: Role) -> AuthContext:
        """
        Require specific role - raises exception if not authorized
        
        Args:
            role: Required role
            
        Returns:
            Current auth context
            
        Raises:
            AuthenticationError: If not authenticated
            AuthorizationError: If lacking required role
        """
        context = self.require_authentication()
        
        if not context.has_role(role):
            raise AuthorizationError(
                f"Access denied. Required role: {role.value}"
            )
        
        return context
    
    # User management
    def create_user(
        self,
        username: str,
        roles: Optional[Set[Role]] = None,
        email: Optional[str] = None,
        full_name: Optional[str] = None
    ) -> User:
        """Create new user (requires admin permission)"""
        self.require_permission(Permission.USER_CREATE)
        
        return self.storage.create_user(
            username=username,
            roles=roles,
            email=email,
            full_name=full_name
        )
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID (requires user view permission)"""
        self.require_permission(Permission.USER_VIEW)
        return self.storage.get_user(user_id)
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username (requires user view permission)"""
        self.require_permission(Permission.USER_VIEW)
        return self.storage.get_user_by_username(username)
    
    def list_users(self) -> List[User]:
        """List all users (requires user view permission)"""
        self.require_permission(Permission.USER_VIEW)
        return self.storage.list_users()
    
    def update_user(self, user: User):
        """Update user (requires user update permission)"""
        self.require_permission(Permission.USER_UPDATE)
        self.storage.update_user(user)
    
    def delete_user(self, user_id: str) -> bool:
        """Delete user (requires user delete permission)"""
        self.require_permission(Permission.USER_DELETE)
        return self.storage.delete_user(user_id)
    
    # API Key management
    def create_api_key(
        self,
        user_id: str,
        name: str,
        expires_in_days: Optional[int] = None,
        scopes: Optional[Set[str]] = None
    ) -> tuple[APIKey, str]:
        """Create API key for user"""
        # Users can create their own keys, admins can create for anyone
        context = self.require_authentication()
        if context.user.user_id != user_id:
            self.require_permission(Permission.USER_UPDATE)
        
        user = self.storage.get_user(user_id)
        if not user:
            raise ValueError(f"User not found: {user_id}")
        
        api_key, raw_key = user.create_api_key(
            name=name,
            expires_in_days=expires_in_days,
            scopes=scopes
        )
        
        self.storage.update_user(user)
        return api_key, raw_key
    
    def revoke_api_key(self, user_id: str, key_id: str) -> bool:
        """Revoke API key"""
        # Users can revoke their own keys, admins can revoke anyone's
        context = self.require_authentication()
        if context.user.user_id != user_id:
            self.require_permission(Permission.USER_UPDATE)
        
        user = self.storage.get_user(user_id)
        if not user:
            return False
        
        result = user.revoke_api_key(key_id)
        if result:
            self.storage.update_user(user)
        
        return result
    
    def list_user_api_keys(self, user_id: str) -> List[APIKey]:
        """List API keys for user"""
        # Users can list their own keys, admins can list anyone's
        context = self.require_authentication()
        if context.user.user_id != user_id:
            self.require_permission(Permission.USER_VIEW)
        
        user = self.storage.get_user(user_id)
        if not user:
            return []
        
        return user.get_active_api_keys()
    
    # Utility methods
    def cleanup_expired_keys(self) -> int:
        """Clean up expired API keys (admin only)"""
        self.require_role(Role.ADMIN)
        return self.storage.cleanup_expired_keys()
    
    def get_stats(self) -> Dict:
        """Get authentication system stats (admin only)"""
        self.require_permission(Permission.SYSTEM_STATS)
        return self.storage.get_stats()
    
    def export_users(self) -> List[Dict]:
        """Export user data (admin only)"""
        self.require_role(Role.ADMIN)
        
        users = self.storage.list_users()
        return [
            {
                'user_id': user.user_id,
                'username': user.username,
                'email': user.email,
                'full_name': user.full_name,
                'roles': [role.value for role in user.roles],
                'created_at': user.created_at.isoformat(),
                'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
                'is_active': user.is_active,
                'api_key_count': len(user.get_active_api_keys())
            }
            for user in users
        ]


# Global auth manager instance
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """Get global auth manager instance"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


def initialize_auth() -> bool:
    """Initialize authentication system"""
    return get_auth_manager().initialize()