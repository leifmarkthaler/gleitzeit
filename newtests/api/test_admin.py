"""
Tests for admin API endpoints.
"""

import pytest
from fastapi import status


class TestAdminUserManagement:
    """Test admin user management endpoints."""
    
    def test_create_user(self, client, admin_headers, mock_client):
        """Test create user endpoint."""
        user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "securepass123",
            "roles": ["user"]
        }
        
        response = client.post(
            "/admin/users",
            json=user_data,
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user_id"] == "user_123"
        assert data["username"] == "testuser"
        
        mock_client.create_user.assert_called_once_with(
            "testuser", "test@example.com", "securepass123", ["user"]
        )
        
    def test_create_user_without_admin(self, client, user_headers, mock_client):
        """Test create user without admin privileges."""
        user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "securepass123"
        }
        
        response = client.post(
            "/admin/users",
            json=user_data,
            headers=user_headers
        )
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in response.json()["detail"]
        
    def test_list_users(self, client, admin_headers, mock_client):
        """Test list users endpoint."""
        response = client.get(
            "/admin/users",
            params={"limit": 50, "offset": 0},
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["username"] == "testuser"
        
        mock_client.list_users.assert_called_once_with(50, 0)
        
    def test_get_user(self, client, admin_headers, mock_client):
        """Test get user by ID."""
        response = client.get(
            "/admin/users/user_123",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "user_123"
        assert data["username"] == "testuser"
        
        mock_client.get_user.assert_called_once_with("user_123")
        
    def test_update_user(self, client, admin_headers, mock_client):
        """Test update user."""
        updates = {"email": "newemail@example.com"}
        response = client.put(
            "/admin/users/user_123",
            json=updates,
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"] is True
        
        mock_client.update_user.assert_called_once_with("user_123", updates)
        
    def test_delete_user(self, client, admin_headers, mock_client):
        """Test delete user."""
        response = client.delete(
            "/admin/users/user_123",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data is True
        
        mock_client.delete_user.assert_called_once_with("user_123")
        
    def test_activate_user(self, client, admin_headers, mock_client):
        """Test activate user."""
        response = client.post(
            "/admin/users/user_123/activate",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "active"
        
        mock_client.activate_user.assert_called_once_with("user_123")
        
    def test_deactivate_user(self, client, admin_headers, mock_client):
        """Test deactivate user."""
        response = client.post(
            "/admin/users/user_123/deactivate",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "inactive"
        
        mock_client.deactivate_user.assert_called_once_with("user_123")


class TestAdminAPIKeyManagement:
    """Test admin API key management endpoints."""
    
    def test_create_api_key(self, client, admin_headers, mock_client):
        """Test create API key."""
        key_data = {
            "name": "test_key",
            "permissions": ["read", "write"],
            "expires_in_days": 30
        }
        
        response = client.post(
            "/admin/api-keys",
            json=key_data,
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key_id"] == "key_123"
        assert data["key"] == "secret_key"
        
        mock_client.create_api_key.assert_called_once_with(
            "test_key", ["read", "write"], 30
        )
        
    def test_list_api_keys(self, client, admin_headers, mock_client):
        """Test list API keys."""
        response = client.get(
            "/admin/api-keys",
            params={"limit": 100, "offset": 0},
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "test_key"
        
        mock_client.list_api_keys.assert_called_once_with(100, 0)
        
    def test_revoke_api_key(self, client, admin_headers, mock_client):
        """Test revoke API key."""
        response = client.delete(
            "/admin/api-keys/key_123",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data is True
        
        mock_client.revoke_api_key.assert_called_once_with("key_123")


class TestAdminRoleManagement:
    """Test admin role management endpoints."""
    
    def test_create_role(self, client, admin_headers, mock_client):
        """Test create role."""
        role_data = {
            "name": "test_role",
            "permissions": ["read", "write", "execute"],
            "description": "Test role for API testing"
        }
        
        response = client.post(
            "/admin/roles",
            json=role_data,
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["role_id"] == "role_123"
        assert data["name"] == "test_role"
        
        mock_client.create_role.assert_called_once_with(
            "test_role", ["read", "write", "execute"], "Test role for API testing"
        )
        
    def test_list_roles(self, client, admin_headers, mock_client):
        """Test list roles."""
        response = client.get(
            "/admin/roles",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "test_role"
        
        mock_client.list_roles.assert_called_once()
        
    def test_delete_role(self, client, admin_headers, mock_client):
        """Test delete role."""
        response = client.delete(
            "/admin/roles/role_123",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data is True
        
        mock_client.delete_role.assert_called_once_with("role_123")


class TestAdminAuditAndSystem:
    """Test admin audit and system endpoints."""
    
    def test_get_audit_logs(self, client, admin_headers, mock_client):
        """Test get audit logs."""
        response = client.get(
            "/admin/audit-logs",
            params={
                "limit": 50,
                "offset": 0,
                "user_id": "user_123",
                "action_type": "login"
            },
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["action"] == "test_action"
        
        mock_client.get_audit_logs.assert_called_once_with(50, 0, "user_123", "login")
        
    def test_get_system_statistics(self, client, admin_headers, mock_client):
        """Test get system statistics."""
        response = client.get(
            "/admin/system-stats",
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "cpu_usage" in data
        assert "memory_usage" in data
        
        mock_client.get_system_statistics.assert_called_once()


class TestAdminAuthentication:
    """Test admin authentication requirements."""
    
    def test_admin_endpoint_without_auth(self, client, mock_client):
        """Test admin endpoint without authentication."""
        response = client.get("/admin/users")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Authentication required" in response.json()["detail"]
        
    def test_admin_endpoint_with_user_role(self, client, user_headers, mock_client):
        """Test admin endpoint with user role (not admin)."""
        response = client.get("/admin/users", headers=user_headers)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in response.json()["detail"]