"""
Modular API routes that delegate to client methods.

This package contains route modules that follow the delegation pattern:
each route module corresponds to a client mixin and delegates API calls
to the appropriate client methods.

Architecture:
- base.py: Foundation classes and shared client management
- workflows.py: Workflow operations (→ WorkflowMixin)
- tasks.py: Task operations (→ TaskMixin)  
- admin.py: Admin operations (→ AdminMixin)
- system.py: System operations (→ SystemMixin)
- auth.py: Authentication operations (→ AuthMixin)
- logs.py: Log management (→ LogMixin)
- errors.py: Error management (→ EventErrorMixin)

Usage:
    from gleitzeit.api.routes import workflow_router, task_router
    
    app.include_router(workflow_router)
    app.include_router(task_router)
"""

from .workflows import router as workflow_router
from .tasks import router as task_router  
from .admin import router as admin_router
from .system import router as system_router
from .auth import router as auth_router
from .logs import router as logs_router
from .errors import router as errors_router
from .base import initialize_shared_client, shutdown_shared_client

__all__ = [
    "workflow_router",
    "task_router", 
    "admin_router",
    "system_router",
    "auth_router",
    "logs_router",
    "errors_router",
    "initialize_shared_client",
    "shutdown_shared_client"
]