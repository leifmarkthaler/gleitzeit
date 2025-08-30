"""
Test admin and user management functionality in Gleitzeit Client
"""
import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from gleitzeit.client import GleitzeitClient, ClientMode


@pytest.fixture
async def admin_client():
    """Create a test client with admin privileges"""
    client = GleitzeitClient(mode=ClientMode.API, api_host="localhost", api_port=8000)
    
    # Mock the adapter
    mock_adapter = AsyncMock()
    client._adapter = mock_adapter
    client._initialized = True
    
    return client


class TestUserManagement:
    """Test user management operations"""
    
    @pytest.mark.asyncio
    async def test_create_user(self, admin_client):
        """Test creating a new user"""
        expected_user = {
            "id": "user-123",
            "username": "testuser",
            "email": "test@example.com",
            "role": "user",
            "created_at": "2025-01-01T10:00:00"
        }
        
        admin_client._adapter.create_user.return_value = expected_user
        
        result = await admin_client.create_user(
            username="testuser",
            email="test@example.com",
            password="securepass123",
            role="user"
        )
        
        assert result == expected_user
        admin_client._adapter.create_user.assert_called_once_with(
            "testuser", "test@example.com", "securepass123", "user"
        )
    
    @pytest.mark.asyncio
    async def test_list_users(self, admin_client):
        """Test listing users with filters"""
        expected_users = [
            {"id": "user-1", "username": "admin", "role": "admin"},
            {"id": "user-2", "username": "user1", "role": "user"}
        ]
        
        admin_client._adapter.list_users.return_value = expected_users
        
        result = await admin_client.list_users(role="admin", active=True, limit=50)
        
        assert result == expected_users
        admin_client._adapter.list_users.assert_called_once_with("admin", True, 50, 0)
    
    @pytest.mark.asyncio
    async def test_get_user(self, admin_client):
        """Test getting user details"""
        user_id = "user-123"
        expected_user = {
            "id": user_id,
            "username": "testuser",
            "email": "test@example.com",
            "role": "user",
            "active": True
        }
        
        admin_client._adapter.get_user.return_value = expected_user
        
        result = await admin_client.get_user(user_id)
        
        assert result == expected_user
        admin_client._adapter.get_user.assert_called_once_with(user_id)
    
    @pytest.mark.asyncio
    async def test_update_user(self, admin_client):
        """Test updating user details"""
        user_id = "user-123"
        expected_user = {
            "id": user_id,
            "username": "testuser",
            "email": "newemail@example.com",
            "role": "admin"
        }
        
        admin_client._adapter.update_user.return_value = expected_user
        
        result = await admin_client.update_user(
            user_id,
            email="newemail@example.com",
            role="admin"
        )
        
        assert result == expected_user
        admin_client._adapter.update_user.assert_called_once_with(
            user_id,
            email="newemail@example.com",
            role="admin"
        )
    
    @pytest.mark.asyncio
    async def test_delete_user(self, admin_client):
        """Test deleting a user"""
        user_id = "user-123"
        expected_result = {"deleted": True, "user_id": user_id}
        
        admin_client._adapter.delete_user.return_value = expected_result
        
        result = await admin_client.delete_user(user_id)
        
        assert result == expected_result
        admin_client._adapter.delete_user.assert_called_once_with(user_id)
    
    @pytest.mark.asyncio
    async def test_reset_user_password(self, admin_client):
        """Test resetting user password"""
        user_id = "user-123"
        expected_result = {
            "user_id": user_id,
            "password_reset": True,
            "temporary_password": "temp123"
        }
        
        admin_client._adapter.reset_user_password.return_value = expected_result
        
        result = await admin_client.reset_user_password(user_id)
        
        assert result == expected_result
        admin_client._adapter.reset_user_password.assert_called_once_with(user_id, None)
    
    @pytest.mark.asyncio
    async def test_disable_user(self, admin_client):
        """Test disabling a user account"""
        user_id = "user-123"
        reason = "Suspicious activity"
        expected_result = {
            "user_id": user_id,
            "active": False,
            "disabled_reason": reason
        }
        
        admin_client._adapter.update_user.return_value = expected_result
        
        result = await admin_client.disable_user(user_id, reason)
        
        assert result == expected_result
        admin_client._adapter.update_user.assert_called_once_with(
            user_id,
            active=False,
            disabled_reason=reason
        )
    
    @pytest.mark.asyncio
    async def test_enable_user(self, admin_client):
        """Test enabling a user account"""
        user_id = "user-123"
        expected_result = {
            "user_id": user_id,
            "active": True,
            "disabled_reason": None
        }
        
        admin_client._adapter.update_user.return_value = expected_result
        
        result = await admin_client.enable_user(user_id)
        
        assert result == expected_result
        admin_client._adapter.update_user.assert_called_once_with(
            user_id,
            active=True,
            disabled_reason=None
        )


class TestAPIKeyManagement:
    """Test API key management operations"""
    
    @pytest.mark.asyncio
    async def test_create_api_key(self, admin_client):
        """Test creating an API key"""
        expected_key = {
            "id": "key-123",
            "name": "Test API Key",
            "key": "sk_test_123456",
            "created_at": "2025-01-01T10:00:00"
        }
        
        admin_client._adapter.create_api_key.return_value = expected_key
        
        result = await admin_client.create_api_key(
            name="Test API Key",
            user_id="user-123",
            scopes=["read", "write"]
        )
        
        assert result == expected_key
        admin_client._adapter.create_api_key.assert_called_once_with(
            "Test API Key",
            "user-123",
            None,
            ["read", "write"]
        )
    
    @pytest.mark.asyncio
    async def test_list_api_keys(self, admin_client):
        """Test listing API keys"""
        expected_keys = [
            {"id": "key-1", "name": "Key 1", "active": True},
            {"id": "key-2", "name": "Key 2", "active": True}
        ]
        
        admin_client._adapter.list_api_keys.return_value = expected_keys
        
        result = await admin_client.list_api_keys(user_id="user-123", active_only=True)
        
        assert result == expected_keys
        admin_client._adapter.list_api_keys.assert_called_once_with("user-123", True)
    
    @pytest.mark.asyncio
    async def test_get_api_key(self, admin_client):
        """Test getting API key details"""
        key_id = "key-123"
        expected_key = {
            "id": key_id,
            "name": "Test Key",
            "active": True,
            "scopes": ["read", "write"]
        }
        
        admin_client._adapter.get_api_key.return_value = expected_key
        
        result = await admin_client.get_api_key(key_id)
        
        assert result == expected_key
        admin_client._adapter.get_api_key.assert_called_once_with(key_id)
    
    @pytest.mark.asyncio
    async def test_revoke_api_key(self, admin_client):
        """Test revoking an API key"""
        key_id = "key-123"
        reason = "Compromised"
        expected_result = {
            "id": key_id,
            "revoked": True,
            "revoked_at": "2025-01-01T10:00:00",
            "reason": reason
        }
        
        admin_client._adapter.revoke_api_key.return_value = expected_result
        
        result = await admin_client.revoke_api_key(key_id, reason)
        
        assert result == expected_result
        admin_client._adapter.revoke_api_key.assert_called_once_with(key_id, reason)
    
    @pytest.mark.asyncio
    async def test_rotate_api_key(self, admin_client):
        """Test rotating an API key"""
        key_id = "key-123"
        expected_result = {
            "old_key_id": key_id,
            "new_key_id": "key-456",
            "new_key": "sk_test_789",
            "rotated_at": "2025-01-01T10:00:00"
        }
        
        admin_client._adapter.rotate_api_key.return_value = expected_result
        
        result = await admin_client.rotate_api_key(key_id)
        
        assert result == expected_result
        admin_client._adapter.rotate_api_key.assert_called_once_with(key_id)


class TestRoleManagement:
    """Test role management operations"""
    
    @pytest.mark.asyncio
    async def test_create_role(self, admin_client):
        """Test creating a role"""
        expected_role = {
            "id": "role-123",
            "name": "editor",
            "permissions": ["read", "write", "edit"],
            "description": "Editor role"
        }
        
        admin_client._adapter.create_role.return_value = expected_role
        
        result = await admin_client.create_role(
            name="editor",
            permissions=["read", "write", "edit"],
            description="Editor role"
        )
        
        assert result == expected_role
        admin_client._adapter.create_role.assert_called_once_with(
            "editor",
            ["read", "write", "edit"],
            "Editor role"
        )
    
    @pytest.mark.asyncio
    async def test_list_roles(self, admin_client):
        """Test listing roles"""
        expected_roles = [
            {"id": "role-1", "name": "admin", "permissions": ["*"]},
            {"id": "role-2", "name": "user", "permissions": ["read"]}
        ]
        
        admin_client._adapter.list_roles.return_value = expected_roles
        
        result = await admin_client.list_roles()
        
        assert result == expected_roles
        admin_client._adapter.list_roles.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_role(self, admin_client):
        """Test getting role details"""
        role_id = "role-123"
        expected_role = {
            "id": role_id,
            "name": "admin",
            "permissions": ["*"],
            "description": "Administrator role"
        }
        
        admin_client._adapter.get_role.return_value = expected_role
        
        result = await admin_client.get_role(role_id)
        
        assert result == expected_role
        admin_client._adapter.get_role.assert_called_once_with(role_id)
    
    @pytest.mark.asyncio
    async def test_update_role(self, admin_client):
        """Test updating a role"""
        role_id = "role-123"
        expected_role = {
            "id": role_id,
            "name": "editor",
            "permissions": ["read", "write", "edit", "delete"],
            "description": "Enhanced editor"
        }
        
        admin_client._adapter.update_role.return_value = expected_role
        
        result = await admin_client.update_role(
            role_id,
            permissions=["read", "write", "edit", "delete"],
            description="Enhanced editor"
        )
        
        assert result == expected_role
        admin_client._adapter.update_role.assert_called_once_with(
            role_id,
            ["read", "write", "edit", "delete"],
            "Enhanced editor"
        )
    
    @pytest.mark.asyncio
    async def test_delete_role(self, admin_client):
        """Test deleting a role"""
        role_id = "role-123"
        expected_result = {"deleted": True, "role_id": role_id}
        
        admin_client._adapter.delete_role.return_value = expected_result
        
        result = await admin_client.delete_role(role_id)
        
        assert result == expected_result
        admin_client._adapter.delete_role.assert_called_once_with(role_id)
    
    @pytest.mark.asyncio
    async def test_assign_role_to_user(self, admin_client):
        """Test assigning role to user"""
        user_id = "user-123"
        role_id = "role-456"
        expected_result = {
            "user_id": user_id,
            "role_id": role_id,
            "assigned": True
        }
        
        admin_client._adapter.assign_role_to_user.return_value = expected_result
        
        result = await admin_client.assign_role_to_user(user_id, role_id)
        
        assert result == expected_result
        admin_client._adapter.assign_role_to_user.assert_called_once_with(user_id, role_id)
    
    @pytest.mark.asyncio
    async def test_remove_role_from_user(self, admin_client):
        """Test removing role from user"""
        user_id = "user-123"
        role_id = "role-456"
        expected_result = {
            "user_id": user_id,
            "role_id": role_id,
            "removed": True
        }
        
        admin_client._adapter.remove_role_from_user.return_value = expected_result
        
        result = await admin_client.remove_role_from_user(user_id, role_id)
        
        assert result == expected_result
        admin_client._adapter.remove_role_from_user.assert_called_once_with(user_id, role_id)


class TestAuditLogs:
    """Test audit log operations"""
    
    @pytest.mark.asyncio
    async def test_get_audit_logs(self, admin_client):
        """Test getting audit logs with filters"""
        expected_logs = [
            {
                "id": "log-1",
                "user_id": "user-123",
                "action": "create",
                "resource_type": "workflow",
                "timestamp": "2025-01-01T10:00:00"
            },
            {
                "id": "log-2",
                "user_id": "user-123",
                "action": "delete",
                "resource_type": "task",
                "timestamp": "2025-01-01T10:05:00"
            }
        ]
        
        admin_client._adapter.get_audit_logs.return_value = expected_logs
        
        result = await admin_client.get_audit_logs(
            user_id="user-123",
            action="create",
            resource_type="workflow",
            limit=50
        )
        
        assert result == expected_logs
        admin_client._adapter.get_audit_logs.assert_called_once_with(
            user_id="user-123",
            action="create",
            resource_type="workflow",
            start_time=None,
            end_time=None,
            limit=50,
            offset=0
        )
    
    @pytest.mark.asyncio
    async def test_get_user_activity(self, admin_client):
        """Test getting user activity summary"""
        user_id = "user-123"
        expected_activity = {
            "user_id": user_id,
            "total_actions": 150,
            "by_action": {
                "create": 50,
                "update": 60,
                "delete": 20,
                "read": 20
            },
            "by_resource": {
                "workflow": 40,
                "task": 110
            }
        }
        
        admin_client._adapter.get_user_activity.return_value = expected_activity
        
        result = await admin_client.get_user_activity(user_id)
        
        assert result == expected_activity
        admin_client._adapter.get_user_activity.assert_called_once_with(user_id, None, None)
    
    @pytest.mark.asyncio
    async def test_export_audit_logs(self, admin_client):
        """Test exporting audit logs"""
        expected_data = b"audit,log,data"
        start_time = datetime(2025, 1, 1)
        end_time = datetime(2025, 1, 2)
        
        admin_client._adapter.export_audit_logs.return_value = expected_data
        
        result = await admin_client.export_audit_logs(
            format="csv",
            start_time=start_time,
            end_time=end_time
        )
        
        assert result == expected_data
        admin_client._adapter.export_audit_logs.assert_called_once_with(
            "csv",
            start_time,
            end_time
        )


class TestPermissionManagement:
    """Test permission management operations"""
    
    @pytest.mark.asyncio
    async def test_check_user_permission(self, admin_client):
        """Test checking user permission"""
        user_id = "user-123"
        permission = "workflow.create"
        resource = "workflow-456"
        
        admin_client._adapter.check_user_permission.return_value = {
            "has_permission": True,
            "reason": "User has admin role"
        }
        
        result = await admin_client.check_user_permission(user_id, permission, resource)
        
        assert result == True
        admin_client._adapter.check_user_permission.assert_called_once_with(
            user_id,
            permission,
            resource
        )
    
    @pytest.mark.asyncio
    async def test_check_user_permission_denied(self, admin_client):
        """Test checking permission when denied"""
        user_id = "user-123"
        permission = "admin.delete"
        
        admin_client._adapter.check_user_permission.return_value = {
            "has_permission": False,
            "reason": "Insufficient privileges"
        }
        
        result = await admin_client.check_user_permission(user_id, permission)
        
        assert result == False
        admin_client._adapter.check_user_permission.assert_called_once_with(
            user_id,
            permission,
            None
        )
    
    @pytest.mark.asyncio
    async def test_get_user_permissions(self, admin_client):
        """Test getting all user permissions"""
        user_id = "user-123"
        
        admin_client._adapter.get_user_permissions.return_value = {
            "permissions": [
                "workflow.create",
                "workflow.read",
                "task.create",
                "task.read"
            ]
        }
        
        result = await admin_client.get_user_permissions(user_id)
        
        assert result == ["workflow.create", "workflow.read", "task.create", "task.read"]
        admin_client._adapter.get_user_permissions.assert_called_once_with(user_id)
    
    @pytest.mark.asyncio
    async def test_not_initialized_error(self):
        """Test error when client not initialized"""
        client = GleitzeitClient(mode="api")
        # Don't initialize
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.create_user("test", "test@example.com", "pass")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])