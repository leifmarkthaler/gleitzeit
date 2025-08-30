"""
Tests for authentication API endpoints.
"""

import pytest
from fastapi import status


class TestAuthEndpoints:
    """Test authentication API endpoints."""
    
    def test_login(self, client, mock_client):
        """Test user login."""
        response = client.post(
            "/auth/login",
            json={"username": "testuser", "password": "testpass123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["token"] == "jwt_token_123"
        assert data["user_id"] == "user_123"
        
        mock_client.login.assert_called_once_with("testuser", "testpass123")
    
    def test_logout(self, client, mock_client):
        """Test user logout."""
        response = client.post(
            "/auth/logout",
            headers={"Authorization": "Bearer jwt_token_123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Logged out successfully"
        
        mock_client.logout.assert_called_once()
    
    def test_logout_without_auth(self, client, mock_client):
        """Test logout without authentication."""
        response = client.post("/auth/logout")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Not authenticated" in response.json()["detail"]
    
    def test_get_current_user(self, client, mock_client):
        """Test get current user."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer jwt_token_123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "user_123"
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"
        
        mock_client.get_current_user.assert_called_once()
    
    def test_get_current_user_without_auth(self, client, mock_client):
        """Test get current user without authentication."""
        response = client.get("/auth/me")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Not authenticated" in response.json()["detail"]
    
    def test_register_user(self, client, mock_client):
        """Test user registration."""
        response = client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "newpass123",
                "full_name": "New User"
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user_id"] == "user_456"
        assert data["username"] == "newuser"
        
        mock_client.register_user.assert_called_once_with(
            "newuser", "new@example.com", "newpass123", "New User"
        )
    
    def test_register_user_minimal(self, client, mock_client):
        """Test user registration with minimal data."""
        response = client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "newpass123"
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.register_user.assert_called_once_with(
            "newuser", "new@example.com", "newpass123", None
        )
    
    def test_refresh_token(self, client, mock_client):
        """Test token refresh."""
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": "Bearer jwt_token_123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["token"] == "new_jwt_token_456"
        
        mock_client.refresh_token.assert_called_once()
    
    def test_refresh_token_without_auth(self, client, mock_client):
        """Test token refresh without authentication."""
        response = client.post("/auth/refresh")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Not authenticated" in response.json()["detail"]
    
    def test_change_password(self, client, mock_client):
        """Test password change."""
        response = client.post(
            "/auth/change-password",
            params={"old_password": "oldpass123", "new_password": "newpass456"},
            headers={"Authorization": "Bearer jwt_token_123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Password changed successfully"
        
        mock_client.change_password.assert_called_once_with("oldpass123", "newpass456")
    
    def test_change_password_without_auth(self, client, mock_client):
        """Test password change without authentication."""
        response = client.post(
            "/auth/change-password",
            params={"old_password": "oldpass123", "new_password": "newpass456"}
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Not authenticated" in response.json()["detail"]
    
    def test_reset_password(self, client, mock_client):
        """Test password reset request."""
        response = client.post(
            "/auth/reset-password",
            params={"email": "test@example.com"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Password reset email sent"
        
        mock_client.reset_password.assert_called_once_with("test@example.com")
    
    def test_get_user_permissions(self, client, mock_client):
        """Test get user permissions."""
        response = client.get(
            "/auth/permissions",
            headers={"Authorization": "Bearer jwt_token_123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "permissions" in data
        assert "read" in data["permissions"]
        assert "write" in data["permissions"]
        assert "execute" in data["permissions"]
        
        mock_client.get_user_permissions.assert_called_once()
    
    def test_get_user_permissions_without_auth(self, client, mock_client):
        """Test get permissions without authentication."""
        response = client.get("/auth/permissions")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Not authenticated" in response.json()["detail"]


class TestAuthErrorHandling:
    """Test error handling in auth endpoints."""
    
    def test_login_invalid_credentials(self, client, mock_client):
        """Test login with invalid credentials."""
        mock_client.login.side_effect = ValueError("Invalid username or password")
        
        response = client.post(
            "/auth/login",
            json={"username": "baduser", "password": "badpass"}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_register_duplicate_user(self, client, mock_client):
        """Test registering duplicate user."""
        mock_client.register_user.side_effect = ValueError("Username already exists")
        
        response = client.post(
            "/auth/register",
            json={
                "username": "existinguser",
                "email": "existing@example.com",
                "password": "pass123"
            }
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR