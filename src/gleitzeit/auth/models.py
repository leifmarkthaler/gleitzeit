"""
Authentication database models using SQLAlchemy
"""

from datetime import datetime
from typing import Optional, List, Dict
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, JSON, Text, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.ext.hybrid import hybrid_property

Base = declarative_base()

# Association table for many-to-many relationship between users and roles
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id'), primary_key=True),
    Column('role_id', UUID(as_uuid=True), ForeignKey('roles.id'), primary_key=True),
    Column('granted_at', DateTime, default=datetime.utcnow),
    Column('expires_at', DateTime, nullable=True)
)


class User(Base):
    """User model for authentication"""
    __tablename__ = 'users'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)  # For basic auth
    full_name = Column(String(255), nullable=True)
    avatar_url = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    metadata_json = Column(JSON, default=dict)
    
    # Relationships
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    audit_logs = relationship("AuditLog", back_populates="user")
    
    def to_dict(self) -> Dict:
        """Convert user to dictionary"""
        return {
            "id": str(self.id),
            "email": self.email,
            "username": self.username,
            "full_name": self.full_name,
            "avatar_url": self.avatar_url,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "roles": [role.name for role in self.roles]
        }
    
    @hybrid_property
    def permissions(self) -> List[str]:
        """Get all permissions for this user"""
        perms = set()
        for role in self.roles:
            perms.update(role.permissions or [])
        if self.is_superuser:
            perms.add("*")  # Superuser has all permissions
        return list(perms)


class ApiKey(Base):
    """API Key model for authentication"""
    __tablename__ = 'api_keys'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)  # SHA256 hash
    key_prefix = Column(String(20), nullable=False)  # For identification (glzt_prod_)
    name = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    permissions = Column(JSON, default=list)  # Optional custom permissions
    metadata_json = Column(JSON, default=dict)
    scopes = Column(JSON, default=list)  # API scopes like ['read:tasks', 'write:workflows']
    
    # Relationships
    user = relationship("User", back_populates="api_keys")
    
    @property
    def is_valid(self) -> bool:
        """Check if API key is still valid"""
        if self.revoked_at:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True
    
    def to_dict(self) -> Dict:
        """Convert API key to dictionary (without sensitive data)"""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "key_prefix": self.key_prefix,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_valid": self.is_valid,
            "scopes": self.scopes
        }


class Role(Base):
    """Role model for RBAC"""
    __tablename__ = 'roles'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    permissions = Column(JSON, nullable=False, default=list)
    is_system = Column(Boolean, default=False)  # Built-in roles
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = relationship("User", secondary=user_roles, back_populates="roles")
    
    def to_dict(self) -> Dict:
        """Convert role to dictionary"""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "permissions": self.permissions,
            "is_system": self.is_system,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class UserRole(Base):
    """User-Role association with additional metadata"""
    __tablename__ = 'user_role_metadata'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey('roles.id'), nullable=False)
    granted_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    granted_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    metadata_json = Column(JSON, default=dict)


class AuditLog(Base):
    """Audit log for tracking authentication and authorization events"""
    __tablename__ = 'audit_logs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    action = Column(String(100), nullable=False)  # login, logout, api_key_created, etc.
    resource_type = Column(String(50), nullable=True)  # workflow, task, etc.
    resource_id = Column(String(255), nullable=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)  # Support IPv6
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")
    
    def to_dict(self) -> Dict:
        """Convert audit log to dictionary"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Session(Base):
    """Session model for tracking active user sessions"""
    __tablename__ = 'sessions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    refresh_token_hash = Column(String(255), unique=True, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    refresh_expires_at = Column(DateTime, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    
    @property
    def is_valid(self) -> bool:
        """Check if session is still valid"""
        if self.revoked_at:
            return False
        if self.expires_at < datetime.utcnow():
            return False
        return True


# Default roles that should be created on initialization
DEFAULT_ROLES = [
    {
        "name": "admin",
        "description": "Full system access",
        "permissions": ["*"],
        "is_system": True
    },
    {
        "name": "developer",
        "description": "Create and manage workflows",
        "permissions": [
            "workflows:create",
            "workflows:read",
            "workflows:update",
            "workflows:delete",
            "tasks:create",
            "tasks:read",
            "tasks:cancel",
            "tasks:retry",
            "logs:read",
            "providers:read"
        ],
        "is_system": True
    },
    {
        "name": "operator",
        "description": "Monitor and operate workflows",
        "permissions": [
            "workflows:read",
            "workflows:pause",
            "workflows:resume",
            "tasks:read",
            "tasks:cancel",
            "tasks:retry",
            "queues:read",
            "logs:read",
            "statistics:read"
        ],
        "is_system": True
    },
    {
        "name": "viewer",
        "description": "Read-only access",
        "permissions": [
            "workflows:read",
            "tasks:read",
            "queues:read",
            "statistics:read",
            "logs:read"
        ],
        "is_system": True
    }
]