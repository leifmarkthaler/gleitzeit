"""
Authentication and authorization system for Gleitzeit Cluster

Provides CLI-first authentication with API keys and role-based access control.
Designed to be easily extensible to web UI and future OAuth/JWT systems.
"""

from .auth_manager import AuthManager, User, Role, Permission
from .cli_auth import CLIAuthenticator
from .decorators import require_auth, require_role, require_permission

__all__ = [
    "AuthManager",
    "User", 
    "Role",
    "Permission",
    "CLIAuthenticator",
    "require_auth",
    "require_role", 
    "require_permission"
]