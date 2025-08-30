"""
Test fixtures and configuration for API tests.
"""

import pytest
from unittest.mock import AsyncMock, Mock
from fastapi.testclient import TestClient
from fastapi import FastAPI
import asyncio
from typing import Dict, Any

# Import the modular routes
from gleitzeit.api.routes.workflows import router as workflow_router
from gleitzeit.api.routes.tasks import router as task_router
from gleitzeit.api.routes.admin import router as admin_router
from gleitzeit.api.routes.system import router as system_router
from gleitzeit.api.routes.auth import router as auth_router
from gleitzeit.api.routes.logs import router as logs_router
from gleitzeit.api.routes.errors import router as errors_router
from gleitzeit.api.routes.base import _shared_client
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task, TaskStatus


@pytest.fixture
def mock_client():
    """Mock client with all mixin methods."""
    client = AsyncMock(spec=GleitzeitClient)
    
    # Mock initialization status
    client.is_initialized.return_value = True
    
    # Mock workflow methods
    client.submit_workflow = AsyncMock(return_value={"workflow_id": "wf_123", "status": "submitted"})
    client.get_workflow = AsyncMock(return_value={"id": "wf_123", "name": "test_workflow", "status": "running"})
    client.list_workflows = AsyncMock(return_value={"workflows": [{"id": "wf_123", "name": "test"}], "total": 1})
    client.cancel_workflow = AsyncMock(return_value={"workflow_id": "wf_123", "status": "cancelled"})
    client.pause_workflow = AsyncMock(return_value={"workflow_id": "wf_123", "status": "paused"})
    client.resume_workflow = AsyncMock(return_value={"workflow_id": "wf_123", "status": "running"})
    client.delete_workflow = AsyncMock(return_value=True)
    client.get_workflow_tasks = AsyncMock(return_value=[{"id": "task_123", "name": "test_task"}])
    client.wait_for_workflow = AsyncMock(return_value={"workflow_id": "wf_123", "status": "completed"})
    client.clone_workflow = AsyncMock(return_value={"workflow_id": "wf_456", "status": "created"})
    client.get_workflow_statistics = AsyncMock(return_value={"total": 5, "completed": 3, "success_rate": 60.0})
    client.get_workflow_timeline = AsyncMock(return_value={"timeline": []})
    client.get_workflow_dependencies = AsyncMock(return_value={"dependencies": {}})
    client.get_workflow_critical_path = AsyncMock(return_value={"critical_path": []})
    client.run_workflow = AsyncMock(return_value={"workflow_id": "wf_789", "status": "started"})
    
    # Mock task methods
    client.submit_task = AsyncMock(return_value={"task_id": "task_123", "status": "submitted"})
    client.get_task = AsyncMock(return_value={
        "id": "task_123", 
        "name": "test_task", 
        "protocol": "shell/v1",
        "method": "execute", 
        "status": "executing"
    })
    client.list_tasks = AsyncMock(return_value={"tasks": [{"id": "task_123", "name": "test"}], "total": 1})
    client.cancel_task = AsyncMock(return_value={"task_id": "task_123", "status": "cancelled"})
    client.pause_task = AsyncMock(return_value={"task_id": "task_123", "status": "paused"})
    client.resume_task = AsyncMock(return_value={"task_id": "task_123", "status": "running"})
    client.update_task = AsyncMock(return_value={"task_id": "task_123", "updated": True})
    client.wait_for_task = AsyncMock(return_value={"task_id": "task_123", "status": "completed"})
    
    # Mock admin methods
    client.create_user = AsyncMock(return_value={"user_id": "user_123", "username": "testuser"})
    client.list_users = AsyncMock(return_value=[{"id": "user_123", "username": "testuser"}])
    client.get_user = AsyncMock(return_value={"id": "user_123", "username": "testuser"})
    client.update_user = AsyncMock(return_value={"user_id": "user_123", "updated": True})
    client.delete_user = AsyncMock(return_value=True)
    client.activate_user = AsyncMock(return_value={"user_id": "user_123", "status": "active"})
    client.deactivate_user = AsyncMock(return_value={"user_id": "user_123", "status": "inactive"})
    client.create_api_key = AsyncMock(return_value={"key_id": "key_123", "key": "secret_key"})
    client.list_api_keys = AsyncMock(return_value=[{"id": "key_123", "name": "test_key"}])
    client.revoke_api_key = AsyncMock(return_value=True)
    client.create_role = AsyncMock(return_value={"role_id": "role_123", "name": "test_role"})
    client.list_roles = AsyncMock(return_value=[{"id": "role_123", "name": "test_role"}])
    client.delete_role = AsyncMock(return_value=True)
    client.get_audit_logs = AsyncMock(return_value=[{"id": "log_123", "action": "test_action"}])
    client.get_system_statistics = AsyncMock(return_value={"cpu_usage": 45.2, "memory_usage": 62.1})
    
    # Mock system methods
    client.health_check = AsyncMock(return_value={"status": "healthy", "timestamp": "2023-01-01T00:00:00Z"})
    client.get_system_status = AsyncMock(return_value={"status": "operational", "uptime": 3600})
    client.get_system_info = AsyncMock(return_value={"version": "0.0.6", "environment": "test"})
    client.get_system_metrics = AsyncMock(return_value={"cpu": 25.5, "memory": 40.2, "disk": 15.8})
    client.shutdown_system = AsyncMock(return_value={"message": "System shutting down"})
    client.start_maintenance_mode = AsyncMock(return_value={"status": "maintenance_started"})
    client.stop_maintenance_mode = AsyncMock(return_value={"status": "maintenance_stopped"})
    client.get_system_config = AsyncMock(return_value={"config": {"key": "value"}})
    
    # Mock auth methods
    client.login = AsyncMock(return_value={"token": "jwt_token_123", "user_id": "user_123"})
    client.logout = AsyncMock(return_value={"message": "Logged out successfully"})
    client.get_current_user = AsyncMock(return_value={"id": "user_123", "username": "testuser", "email": "test@example.com"})
    client.register_user = AsyncMock(return_value={"user_id": "user_456", "username": "newuser"})
    client.refresh_token = AsyncMock(return_value={"token": "new_jwt_token_456"})
    client.change_password = AsyncMock(return_value={"message": "Password changed successfully"})
    client.reset_password = AsyncMock(return_value={"message": "Password reset email sent"})
    client.get_user_permissions = AsyncMock(return_value={"permissions": ["read", "write", "execute"]})
    
    # Mock log methods
    client.get_logs = AsyncMock(return_value=[{"id": "log_1", "level": "INFO", "message": "Test log", "timestamp": "2023-01-01T00:00:00Z"}])
    client.get_log_levels = AsyncMock(return_value=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    client.get_log_sources = AsyncMock(return_value=["api", "worker", "scheduler"])
    client.get_task_logs = AsyncMock(return_value=[{"id": "log_2", "task_id": "task_123", "message": "Task log"}])
    client.get_workflow_logs = AsyncMock(return_value=[{"id": "log_3", "workflow_id": "wf_123", "message": "Workflow log"}])
    client.clear_logs = AsyncMock(return_value={"deleted": 100, "message": "Logs cleared"})
    client.get_log_statistics = AsyncMock(return_value={"total": 1000, "by_level": {"INFO": 500, "ERROR": 100}})
    client.export_logs = AsyncMock(return_value={"file": "logs_export.json", "size": 1024})
    
    # Mock error methods
    client.get_event_errors = AsyncMock(return_value=[{"id": "err_1", "severity": "high", "message": "Test error"}])
    client.get_event_error = AsyncMock(return_value={"id": "err_1", "severity": "high", "message": "Test error", "status": "new"})
    client.update_event_error = AsyncMock(return_value={"id": "err_1", "status": "acknowledged"})
    client.acknowledge_error = AsyncMock(return_value={"id": "err_1", "status": "acknowledged"})
    client.resolve_error = AsyncMock(return_value={"id": "err_1", "status": "resolved"})
    client.ignore_error = AsyncMock(return_value={"id": "err_1", "status": "ignored"})
    client.retry_failed_event = AsyncMock(return_value={"id": "err_1", "retry_status": "submitted"})
    client.get_task_errors = AsyncMock(return_value=[{"id": "err_2", "task_id": "task_123", "message": "Task error"}])
    client.get_workflow_errors = AsyncMock(return_value=[{"id": "err_3", "workflow_id": "wf_123", "message": "Workflow error"}])
    client.get_error_statistics = AsyncMock(return_value={"total": 50, "by_severity": {"high": 10, "medium": 20}})
    client.clear_errors = AsyncMock(return_value={"deleted": 25, "message": "Errors cleared"})
    
    return client


@pytest.fixture
def test_app(mock_client):
    """FastAPI test app with mocked client."""
    app = FastAPI(title="Test API")
    
    # Override all the route module clients with our mock
    import gleitzeit.api.routes.base as base_module
    import gleitzeit.api.routes.workflows as workflow_module
    import gleitzeit.api.routes.tasks as task_module
    import gleitzeit.api.routes.admin as admin_module
    import gleitzeit.api.routes.system as system_module
    import gleitzeit.api.routes.auth as auth_module
    import gleitzeit.api.routes.logs as logs_module
    import gleitzeit.api.routes.errors as errors_module
    
    # Set the shared client
    base_module._shared_client = mock_client
    
    # Override each module's client instance
    # Reset to None first to ensure fresh instances
    workflow_module._workflow_routes = None
    task_module._task_routes = None
    admin_module._admin_routes = None
    system_module._system_routes = None
    auth_module._auth_routes = None
    logs_module._log_routes = None
    errors_module._error_routes = None
    
    # Now set with our mock client
    workflow_module._workflow_routes = base_module.APIRouteBase(mock_client)
    task_module._task_routes = base_module.APIRouteBase(mock_client) 
    admin_module._admin_routes = base_module.APIRouteBase(mock_client)
    system_module._system_routes = base_module.APIRouteBase(mock_client)
    auth_module._auth_routes = base_module.APIRouteBase(mock_client)
    logs_module._log_routes = base_module.APIRouteBase(mock_client)
    errors_module._error_routes = base_module.APIRouteBase(mock_client)
    
    # Include all routers
    app.include_router(workflow_router)
    app.include_router(task_router)
    app.include_router(admin_router)
    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(logs_router)
    app.include_router(errors_router)
    
    return app


@pytest.fixture
def client(test_app):
    """Test client for making HTTP requests."""
    return TestClient(test_app)


@pytest.fixture
def admin_headers():
    """Headers for admin authentication."""
    return {
        "X-User-ID": "admin_123",
        "X-User-Role": "admin"
    }


@pytest.fixture
def user_headers():
    """Headers for regular user authentication."""
    return {
        "X-User-ID": "user_123",
        "X-User-Role": "user"
    }


@pytest.fixture
def sample_workflow():
    """Sample workflow data for tests."""
    return {
        "name": "test_workflow",
        "description": "Test workflow for API testing",
        "tasks": [
            {
                "id": "task_1",
                "name": "test_task",
                "protocol": "shell/v1",
                "method": "execute",
                "params": {"command": "echo 'test'"},
                "status": TaskStatus.PENDING
            }
        ]
    }


@pytest.fixture
def sample_task():
    """Sample task data for tests."""
    return {
        "id": "test_task_123",
        "name": "test_task",
        "protocol": "shell/v1",
        "method": "execute",
        "params": {"command": "echo 'Hello World'"},
        "status": TaskStatus.PENDING
    }