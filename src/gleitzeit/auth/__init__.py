"""
Gleitzeit Authentication Module

Provides authentication and authorization for the Gleitzeit system.
"""

from .models import User, ApiKey, Role, UserRole
from .middleware import AuthMiddleware
from .permissions import require_permission, has_permission
from .utils import generate_api_key, hash_api_key, verify_password, hash_password

__all__ = [
    'User',
    'ApiKey', 
    'Role',
    'UserRole',
    'AuthMiddleware',
    'require_permission',
    'has_permission',
    'generate_api_key',
    'hash_api_key',
    'verify_password',
    'hash_password'
]