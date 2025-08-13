"""
Authentication data models
"""

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set


class Permission(Enum):
    """System permissions"""
    # Workflow permissions
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_READ = "workflow:read" 
    WORKFLOW_UPDATE = "workflow:update"
    WORKFLOW_DELETE = "workflow:delete"
    WORKFLOW_EXECUTE = "workflow:execute"
    
    # Cluster management
    CLUSTER_VIEW = "cluster:view"
    CLUSTER_MANAGE = "cluster:manage"
    CLUSTER_ADMIN = "cluster:admin"
    
    # Endpoint management
    ENDPOINT_VIEW = "endpoint:view"
    ENDPOINT_ADD = "endpoint:add"
    ENDPOINT_REMOVE = "endpoint:remove"
    ENDPOINT_CONFIGURE = "endpoint:configure"
    
    # User management
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update" 
    USER_DELETE = "user:delete"
    
    # System operations
    SYSTEM_STATS = "system:stats"
    SYSTEM_LOGS = "system:logs"
    SYSTEM_CONFIG = "system:config"


class Role(Enum):
    """Predefined user roles with permission sets"""
    
    # Basic user - can create and run workflows
    USER = "user"
    
    # Power user - can manage endpoints and view system info
    OPERATOR = "operator"
    
    # Administrator - full system access
    ADMIN = "admin"
    
    # Read-only access for monitoring/dashboards
    READONLY = "readonly"
    
    # Service account for automated systems
    SERVICE = "service"


# Define role permissions step by step to avoid forward reference issues
_READONLY_PERMISSIONS = {
    Permission.WORKFLOW_READ,
    Permission.CLUSTER_VIEW,
    Permission.ENDPOINT_VIEW,
    Permission.SYSTEM_STATS
}

_USER_PERMISSIONS = {
    Permission.WORKFLOW_CREATE,
    Permission.WORKFLOW_READ,
    Permission.WORKFLOW_UPDATE,
    Permission.WORKFLOW_DELETE,
    Permission.WORKFLOW_EXECUTE,
    Permission.CLUSTER_VIEW,
    Permission.ENDPOINT_VIEW,
    Permission.SYSTEM_STATS
}

_SERVICE_PERMISSIONS = {
    # Automated systems - workflow execution focus
    Permission.WORKFLOW_CREATE,
    Permission.WORKFLOW_READ,
    Permission.WORKFLOW_EXECUTE,
    Permission.CLUSTER_VIEW,
    Permission.ENDPOINT_VIEW,
    Permission.SYSTEM_STATS
}

_OPERATOR_PERMISSIONS = {
    # All user permissions plus:
    *_USER_PERMISSIONS,
    Permission.CLUSTER_MANAGE,
    Permission.ENDPOINT_ADD,
    Permission.ENDPOINT_REMOVE,
    Permission.ENDPOINT_CONFIGURE,
    Permission.SYSTEM_LOGS,
    Permission.USER_VIEW
}

_ADMIN_PERMISSIONS = {
    # All permissions
    *[perm for perm in Permission]
}

# Role to permissions mapping
ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.READONLY: _READONLY_PERMISSIONS,
    Role.USER: _USER_PERMISSIONS,
    Role.OPERATOR: _OPERATOR_PERMISSIONS,
    Role.SERVICE: _SERVICE_PERMISSIONS,
    Role.ADMIN: _ADMIN_PERMISSIONS
}


@dataclass
class APIKey:
    """API key for authentication"""
    key_id: str                    # Short identifier (first 8 chars)
    key_hash: str                  # SHA256 hash of full key
    name: str                      # Human-readable name
    user_id: str                   # Owner user ID
    created_at: datetime           # Creation timestamp
    expires_at: Optional[datetime] # Expiration (None = never expires)
    last_used_at: Optional[datetime] = None  # Last usage timestamp
    last_used_ip: Optional[str] = None       # Last usage IP
    is_active: bool = True         # Whether key is active
    scopes: Set[str] = field(default_factory=set)  # Additional scopes
    
    @classmethod
    def generate(
        cls,
        name: str,
        user_id: str,
        expires_in_days: Optional[int] = None,
        scopes: Optional[Set[str]] = None
    ) -> tuple['APIKey', str]:
        """Generate a new API key"""
        # Generate secure random key
        raw_key = f"gzt_{secrets.token_urlsafe(32)}"
        
        # Create key metadata
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = raw_key[-8:]  # Last 8 chars as ID
        
        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        
        api_key = cls(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            user_id=user_id,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            scopes=scopes or set()
        )
        
        return api_key, raw_key
    
    def is_valid(self) -> bool:
        """Check if API key is valid"""
        if not self.is_active:
            return False
        
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
            
        return True
    
    def matches_key(self, raw_key: str) -> bool:
        """Verify if raw key matches this API key"""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        return key_hash == self.key_hash
    
    def update_last_used(self, ip_address: Optional[str] = None):
        """Update last used timestamp and IP"""
        self.last_used_at = datetime.utcnow()
        if ip_address:
            self.last_used_ip = ip_address


@dataclass  
class User:
    """User account"""
    user_id: str                   # Unique user identifier  
    username: str                  # Human-readable username
    email: Optional[str]           # Email address
    full_name: Optional[str]       # Display name
    roles: Set[Role]               # Assigned roles
    created_at: datetime           # Account creation
    last_login_at: Optional[datetime] = None  # Last login timestamp
    is_active: bool = True         # Account status
    api_keys: Dict[str, APIKey] = field(default_factory=dict)  # User's API keys
    metadata: Dict[str, str] = field(default_factory=dict)     # Additional metadata
    
    @classmethod
    def create(
        cls,
        username: str,
        roles: Optional[Set[Role]] = None,
        email: Optional[str] = None,
        full_name: Optional[str] = None
    ) -> 'User':
        """Create a new user"""
        user_id = f"user_{int(time.time())}_{secrets.token_hex(4)}"
        
        return cls(
            user_id=user_id,
            username=username,
            email=email,
            full_name=full_name,
            roles=roles or {Role.USER},
            created_at=datetime.utcnow()
        )
    
    def get_permissions(self) -> Set[Permission]:
        """Get all permissions for this user based on roles"""
        permissions = set()
        for role in self.roles:
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        return permissions
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if user has specific permission"""
        return permission in self.get_permissions()
    
    def has_role(self, role: Role) -> bool:
        """Check if user has specific role"""
        return role in self.roles
    
    def add_role(self, role: Role):
        """Add role to user"""
        self.roles.add(role)
    
    def remove_role(self, role: Role):
        """Remove role from user"""
        self.roles.discard(role)
    
    def create_api_key(
        self,
        name: str,
        expires_in_days: Optional[int] = None,
        scopes: Optional[Set[str]] = None
    ) -> tuple[APIKey, str]:
        """Create new API key for this user"""
        api_key, raw_key = APIKey.generate(
            name=name,
            user_id=self.user_id,
            expires_in_days=expires_in_days,
            scopes=scopes
        )
        
        self.api_keys[api_key.key_id] = api_key
        return api_key, raw_key
    
    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key"""
        if key_id in self.api_keys:
            self.api_keys[key_id].is_active = False
            return True
        return False
    
    def get_active_api_keys(self) -> List[APIKey]:
        """Get all active API keys"""
        return [key for key in self.api_keys.values() if key.is_valid()]


@dataclass
class AuthContext:
    """Authentication context for requests"""
    user: User                     # Authenticated user
    api_key: Optional[APIKey]      # API key used (if any)
    ip_address: Optional[str]      # Client IP address
    user_agent: Optional[str]      # Client user agent
    authenticated_at: datetime     # When authentication occurred
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if authenticated user has permission"""
        return self.user.has_permission(permission)
    
    def has_role(self, role: Role) -> bool:
        """Check if authenticated user has role"""
        return self.user.has_role(role)
    
    def log_access(self, resource: str, action: str):
        """Log access for audit trail"""
        # TODO: Implement audit logging
        pass