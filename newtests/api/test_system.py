"""
Tests for system API endpoints.
"""

import pytest
from fastapi import status


class TestSystemEndpoints:
    """Test system API endpoints."""
    
    def test_health_check(self, client, mock_client):
        """Test health check endpoint."""
        response = client.get("/system/health")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        
        mock_client.health_check.assert_called_once()
        
    def test_get_system_status(self, client, mock_client):
        """Test get system status."""
        response = client.get("/system/status")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "operational"
        assert data["uptime"] == 3600
        
        mock_client.get_system_status.assert_called_once()
        
    def test_get_system_info(self, client, mock_client):
        """Test get system information."""
        response = client.get("/system/info")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["version"] == "0.0.6"
        assert data["environment"] == "test"
        
        mock_client.get_system_info.assert_called_once()
        
    def test_get_system_metrics(self, client, mock_client):
        """Test get system metrics."""
        response = client.get("/system/metrics")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data
        assert data["cpu"] == 25.5
        
        mock_client.get_system_metrics.assert_called_once()
        
    def test_get_system_config(self, client, admin_headers, mock_client):
        """Test get system configuration (admin only)."""
        response = client.get("/system/config", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "config" in data
        assert data["config"]["key"] == "value"
        
        mock_client.get_system_config.assert_called_once()
        
    def test_get_system_config_without_admin(self, client, user_headers, mock_client):
        """Test get system config without admin privileges."""
        response = client.get("/system/config", headers=user_headers)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in response.json()["detail"]


class TestSystemMaintenanceEndpoints:
    """Test system maintenance endpoints."""
    
    def test_start_maintenance_mode(self, client, admin_headers, mock_client):
        """Test start maintenance mode."""
        response = client.post("/system/maintenance/start", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "maintenance_started"
        
        mock_client.start_maintenance_mode.assert_called_once()
        
    def test_start_maintenance_mode_without_admin(self, client, user_headers, mock_client):
        """Test start maintenance mode without admin privileges."""
        response = client.post("/system/maintenance/start", headers=user_headers)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in response.json()["detail"]
        
    def test_stop_maintenance_mode(self, client, admin_headers, mock_client):
        """Test stop maintenance mode."""
        response = client.post("/system/maintenance/stop", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "maintenance_stopped"
        
        mock_client.stop_maintenance_mode.assert_called_once()
        
    def test_shutdown_system(self, client, admin_headers, mock_client):
        """Test shutdown system."""
        response = client.post("/system/shutdown", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "System shutting down"
        
        mock_client.shutdown_system.assert_called_once()
        
    def test_shutdown_system_without_admin(self, client, user_headers, mock_client):
        """Test shutdown system without admin privileges."""
        response = client.post("/system/shutdown", headers=user_headers)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in response.json()["detail"]


class TestSystemErrorHandling:
    """Test error handling in system endpoints."""
    
    def test_health_check_service_error(self, client, mock_client):
        """Test health check with service error."""
        mock_client.health_check.side_effect = RuntimeError("Service unavailable")
        
        response = client.get("/system/health")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Service unavailable" in response.json()["detail"]
        
    def test_get_metrics_timeout_error(self, client, mock_client):
        """Test get metrics with timeout error."""
        mock_client.get_system_metrics.side_effect = TimeoutError("Metrics collection timeout")
        
        response = client.get("/system/metrics")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        
    def test_maintenance_mode_error(self, client, admin_headers, mock_client):
        """Test maintenance mode with error."""
        mock_client.start_maintenance_mode.side_effect = RuntimeError("Already in maintenance mode")
        
        response = client.post("/system/maintenance/start", headers=admin_headers)
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestSystemAuthentication:
    """Test system authentication requirements."""
    
    def test_public_endpoints_no_auth_required(self, client, mock_client):
        """Test that public system endpoints don't require auth."""
        # These endpoints should work without authentication
        endpoints = [
            "/system/health",
            "/system/status", 
            "/system/info",
            "/system/metrics"
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == status.HTTP_200_OK
            
    def test_admin_endpoints_require_auth(self, client, mock_client):
        """Test that admin system endpoints require authentication."""
        # These endpoints should require admin auth
        admin_endpoints = [
            ("/system/config", "get"),
            ("/system/shutdown", "post"),
            ("/system/maintenance/start", "post"),
            ("/system/maintenance/stop", "post"),
        ]
        
        for endpoint, method in admin_endpoints:
            if method == "get":
                response = client.get(endpoint)
            else:
                response = client.post(endpoint)
            
            assert response.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Authentication required" in response.json()["detail"]