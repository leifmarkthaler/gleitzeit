"""
Admin and user management mixin for Gleitzeit client.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime


class AdminMixin:
    """Mixin providing admin and user management operations."""
    
    # User Management
    
    async def create_user(self, 
                         username: str,
                         email: str,
                         password: str,
                         role: Optional[str] = "user",
                         **kwargs) -> Dict[str, Any]:
        """
        Create a new user.
        
        Args:
            username: Username for the new user
            email: Email address
            password: User password
            role: User role (default: "user")
            **kwargs: Additional user properties
            
        Returns:
            Created user details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.create_user(username, email, password, role, **kwargs)
    
    async def list_users(self,
                        role: Optional[str] = None,
                        active: Optional[bool] = None,
                        limit: int = 100,
                        offset: int = 0) -> List[Dict[str, Any]]:
        """
        List users with optional filtering.
        
        Args:
            role: Filter by role
            active: Filter by active status
            limit: Maximum number of users to return
            offset: Offset for pagination
            
        Returns:
            List of user details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.list_users(role, active, limit, offset)
    
    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """
        Get details of a specific user.
        
        Args:
            user_id: User ID
            
        Returns:
            User details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_user(user_id)
    
    async def update_user(self, 
                         user_id: str,
                         **updates) -> Dict[str, Any]:
        """
        Update user details.
        
        Args:
            user_id: User ID to update
            **updates: Fields to update (email, role, active, etc.)
            
        Returns:
            Updated user details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.update_user(user_id, **updates)
    
    async def delete_user(self, user_id: str) -> Dict[str, Any]:
        """
        Delete a user.
        
        Args:
            user_id: User ID to delete
            
        Returns:
            Deletion confirmation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.delete_user(user_id)
    
    async def reset_user_password(self, 
                                 user_id: str,
                                 new_password: Optional[str] = None) -> Dict[str, Any]:
        """
        Reset user password.
        
        Args:
            user_id: User ID
            new_password: New password (if None, generates temporary password)
            
        Returns:
            Password reset result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.reset_user_password(user_id, new_password)
    
    async def disable_user(self, user_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Disable a user account.
        
        Args:
            user_id: User ID to disable
            reason: Optional reason for disabling
            
        Returns:
            Updated user status
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.update_user(user_id, active=False, disabled_reason=reason)
    
    async def enable_user(self, user_id: str) -> Dict[str, Any]:
        """
        Enable a previously disabled user account.
        
        Args:
            user_id: User ID to enable
            
        Returns:
            Updated user status
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.update_user(user_id, active=True, disabled_reason=None)
    
    # API Key Management
    
    async def create_api_key(self,
                           name: str,
                           user_id: Optional[str] = None,
                           expires_at: Optional[datetime] = None,
                           scopes: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create a new API key.
        
        Args:
            name: Name/description for the API key
            user_id: User ID to associate with (None for current user)
            expires_at: Optional expiration time
            scopes: Optional list of permission scopes
            
        Returns:
            API key details including the key value
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.create_api_key(name, user_id, expires_at, scopes)
    
    async def list_api_keys(self,
                          user_id: Optional[str] = None,
                          active_only: bool = True) -> List[Dict[str, Any]]:
        """
        List API keys.
        
        Args:
            user_id: Filter by user ID (None for all users)
            active_only: Only show active keys
            
        Returns:
            List of API key details (without key values)
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.list_api_keys(user_id, active_only)
    
    async def get_api_key(self, key_id: str) -> Dict[str, Any]:
        """
        Get details of a specific API key.
        
        Args:
            key_id: API key ID
            
        Returns:
            API key details (without key value)
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_api_key(key_id)
    
    async def revoke_api_key(self, key_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Revoke an API key.
        
        Args:
            key_id: API key ID to revoke
            reason: Optional reason for revocation
            
        Returns:
            Revocation confirmation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.revoke_api_key(key_id, reason)
    
    async def rotate_api_key(self, key_id: str) -> Dict[str, Any]:
        """
        Rotate an API key (revoke old, create new).
        
        Args:
            key_id: API key ID to rotate
            
        Returns:
            New API key details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.rotate_api_key(key_id)
    
    # Role Management
    
    async def create_role(self,
                        name: str,
                        permissions: List[str],
                        description: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new role.
        
        Args:
            name: Role name
            permissions: List of permission strings
            description: Optional role description
            
        Returns:
            Created role details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.create_role(name, permissions, description)
    
    async def list_roles(self) -> List[Dict[str, Any]]:
        """
        List all available roles.
        
        Returns:
            List of role details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.list_roles()
    
    async def get_role(self, role_id: str) -> Dict[str, Any]:
        """
        Get details of a specific role.
        
        Args:
            role_id: Role ID
            
        Returns:
            Role details including permissions
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_role(role_id)
    
    async def update_role(self,
                        role_id: str,
                        permissions: Optional[List[str]] = None,
                        description: Optional[str] = None) -> Dict[str, Any]:
        """
        Update role details.
        
        Args:
            role_id: Role ID to update
            permissions: New permissions list
            description: New description
            
        Returns:
            Updated role details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.update_role(role_id, permissions, description)
    
    async def delete_role(self, role_id: str) -> Dict[str, Any]:
        """
        Delete a role.
        
        Args:
            role_id: Role ID to delete
            
        Returns:
            Deletion confirmation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.delete_role(role_id)
    
    async def assign_role_to_user(self, user_id: str, role_id: str) -> Dict[str, Any]:
        """
        Assign a role to a user.
        
        Args:
            user_id: User ID
            role_id: Role ID to assign
            
        Returns:
            Assignment confirmation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.assign_role_to_user(user_id, role_id)
    
    async def remove_role_from_user(self, user_id: str, role_id: str) -> Dict[str, Any]:
        """
        Remove a role from a user.
        
        Args:
            user_id: User ID
            role_id: Role ID to remove
            
        Returns:
            Removal confirmation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.remove_role_from_user(user_id, role_id)
    
    # Audit Logs
    
    async def get_audit_logs(self,
                           user_id: Optional[str] = None,
                           action: Optional[str] = None,
                           resource_type: Optional[str] = None,
                           start_time: Optional[datetime] = None,
                           end_time: Optional[datetime] = None,
                           limit: int = 100,
                           offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get audit logs with optional filtering.
        
        Args:
            user_id: Filter by user ID
            action: Filter by action type
            resource_type: Filter by resource type
            start_time: Start time for log range
            end_time: End time for log range
            limit: Maximum number of logs to return
            offset: Offset for pagination
            
        Returns:
            List of audit log entries
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_audit_logs(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
    
    async def get_user_activity(self,
                               user_id: str,
                               start_time: Optional[datetime] = None,
                               end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get activity summary for a specific user.
        
        Args:
            user_id: User ID
            start_time: Start time for activity range
            end_time: End time for activity range
            
        Returns:
            User activity summary
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_user_activity(user_id, start_time, end_time)
    
    async def export_audit_logs(self,
                              format: str = "json",
                              start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None) -> bytes:
        """
        Export audit logs in specified format.
        
        Args:
            format: Export format (json, csv, etc.)
            start_time: Start time for export range
            end_time: End time for export range
            
        Returns:
            Audit log data as bytes
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.export_audit_logs(format, start_time, end_time)
    
    # Permission Management
    
    async def check_user_permission(self,
                                   user_id: str,
                                   permission: str,
                                   resource: Optional[str] = None) -> bool:
        """
        Check if user has a specific permission.
        
        Args:
            user_id: User ID
            permission: Permission to check
            resource: Optional resource identifier
            
        Returns:
            True if user has permission, False otherwise
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        result = await self._adapter.check_user_permission(user_id, permission, resource)
        return result.get("has_permission", False)
    
    async def get_user_permissions(self, user_id: str) -> List[str]:
        """
        Get all permissions for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of permission strings
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        result = await self._adapter.get_user_permissions(user_id)
        return result.get("permissions", [])