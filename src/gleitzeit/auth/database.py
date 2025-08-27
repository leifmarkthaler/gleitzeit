"""
Database adapter for authentication
Can use either SQL or in-memory storage for development
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
import json

from .models import User, ApiKey, Role, Session, AuditLog, DEFAULT_ROLES
from .utils import hash_password

logger = logging.getLogger(__name__)


class AuthDatabase:
    """Base authentication database interface"""
    
    async def get_user(self, user_id: UUID) -> Optional[User]:
        raise NotImplementedError
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        raise NotImplementedError
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        raise NotImplementedError
    
    async def create_user(self, user_data: dict) -> User:
        raise NotImplementedError
    
    async def update_user_last_login(self, user_id: UUID):
        raise NotImplementedError
    
    async def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        raise NotImplementedError
    
    async def create_api_key(self, user_id: UUID, key_data: dict) -> ApiKey:
        raise NotImplementedError
    
    async def update_api_key_last_used(self, key_id: UUID):
        raise NotImplementedError
    
    async def get_session_by_token_hash(self, token_hash: str) -> Optional[Session]:
        raise NotImplementedError
    
    async def create_session(self, user_id: UUID, session_data: dict) -> Session:
        raise NotImplementedError
    
    async def update_session_activity(self, session_id: UUID):
        raise NotImplementedError
    
    async def create_audit_log(self, **kwargs):
        raise NotImplementedError


class InMemoryAuthDatabase(AuthDatabase):
    """
    In-memory authentication database for development/testing
    """
    
    def __init__(self):
        self.users: Dict[UUID, User] = {}
        self.api_keys: Dict[UUID, ApiKey] = {}
        self.roles: Dict[UUID, Role] = {}
        self.sessions: Dict[UUID, Session] = {}
        self.audit_logs: List[AuditLog] = []
        
        # Initialize default roles
        self._init_default_roles()
        
        # Create default admin user if configured
        if os.getenv("GLEITZEIT_AUTH_CREATE_ADMIN", "true").lower() == "true":
            self._create_default_admin()
    
    def _init_default_roles(self):
        """Initialize default roles"""
        for role_data in DEFAULT_ROLES:
            role = Role(
                id=uuid4(),
                name=role_data["name"],
                description=role_data["description"],
                permissions=role_data["permissions"],
                is_system=role_data["is_system"]
            )
            self.roles[role.id] = role
            logger.info(f"Created default role: {role.name}")
    
    def _create_default_admin(self):
        """Create default admin user"""
        admin_email = os.getenv("GLEITZEIT_AUTH_ADMIN_EMAIL", "admin@localhost")
        admin_password = os.getenv("GLEITZEIT_AUTH_ADMIN_PASSWORD", "admin")
        
        # Check if admin already exists
        for user in self.users.values():
            if user.email == admin_email:
                return
        
        # Create admin user
        admin_user = User(
            id=uuid4(),
            email=admin_email,
            username="admin",
            password_hash=hash_password(admin_password),
            full_name="System Administrator",
            is_active=True,
            is_superuser=True,
            created_at=datetime.utcnow()
        )
        
        # Add admin role
        admin_role = next((r for r in self.roles.values() if r.name == "admin"), None)
        if admin_role:
            admin_user.roles = [admin_role]
        
        self.users[admin_user.id] = admin_user
        logger.info(f"Created default admin user: {admin_email}")
    
    async def get_user(self, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        return self.users.get(user_id)
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        for user in self.users.values():
            if user.email == email:
                return user
        return None
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        for user in self.users.values():
            if user.username == username:
                return user
        return None
    
    async def create_user(self, user_data: dict) -> User:
        """Create a new user"""
        user = User(
            id=uuid4(),
            email=user_data["email"],
            username=user_data.get("username"),
            password_hash=hash_password(user_data["password"]) if "password" in user_data else None,
            full_name=user_data.get("full_name"),
            is_active=user_data.get("is_active", True),
            is_superuser=user_data.get("is_superuser", False),
            created_at=datetime.utcnow()
        )
        
        # Add default role
        viewer_role = next((r for r in self.roles.values() if r.name == "viewer"), None)
        if viewer_role:
            user.roles = [viewer_role]
        
        self.users[user.id] = user
        return user
    
    async def update_user_last_login(self, user_id: UUID):
        """Update user's last login timestamp"""
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        user = self.users.get(user_id)
        if user:
            user.last_login = datetime.utcnow()
    
    async def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """Get API key by hash"""
        for api_key in self.api_keys.values():
            if api_key.key_hash == key_hash:
                return api_key
        return None
    
    async def create_api_key(self, user_id: UUID, key_data: dict) -> ApiKey:
        """Create a new API key"""
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        api_key = ApiKey(
            id=uuid4(),
            user_id=user_id,
            key_hash=key_data["key_hash"],
            key_prefix=key_data["key_prefix"],
            name=key_data.get("name"),
            description=key_data.get("description"),
            expires_at=key_data.get("expires_at"),
            permissions=key_data.get("permissions", []),
            scopes=key_data.get("scopes", []),
            created_at=datetime.utcnow()
        )
        
        # Set user relationship
        api_key.user = self.users.get(user_id)
        
        self.api_keys[api_key.id] = api_key
        return api_key
    
    async def update_api_key_last_used(self, key_id: UUID):
        """Update API key's last used timestamp"""
        if isinstance(key_id, str):
            key_id = UUID(key_id)
        api_key = self.api_keys.get(key_id)
        if api_key:
            api_key.last_used_at = datetime.utcnow()
    
    async def revoke_api_key(self, key_id: UUID):
        """Revoke an API key"""
        if isinstance(key_id, str):
            key_id = UUID(key_id)
        api_key = self.api_keys.get(key_id)
        if api_key:
            api_key.revoked_at = datetime.utcnow()
    
    async def get_session_by_token_hash(self, token_hash: str) -> Optional[Session]:
        """Get session by token hash"""
        for session in self.sessions.values():
            if session.token_hash == token_hash:
                return session
        return None
    
    async def create_session(self, user_id: UUID, session_data: dict) -> Session:
        """Create a new session"""
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        session = Session(
            id=uuid4(),
            user_id=user_id,
            token_hash=session_data["token_hash"],
            refresh_token_hash=session_data.get("refresh_token_hash"),
            expires_at=session_data["expires_at"],
            refresh_expires_at=session_data.get("refresh_expires_at"),
            ip_address=session_data.get("ip_address"),
            user_agent=session_data.get("user_agent"),
            created_at=datetime.utcnow(),
            last_activity=datetime.utcnow()
        )
        
        self.sessions[session.id] = session
        return session
    
    async def update_session_activity(self, session_id: UUID):
        """Update session's last activity timestamp"""
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        session = self.sessions.get(session_id)
        if session:
            session.last_activity = datetime.utcnow()
    
    async def revoke_session(self, session_id: UUID):
        """Revoke a session"""
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        session = self.sessions.get(session_id)
        if session:
            session.revoked_at = datetime.utcnow()
    
    async def create_audit_log(self, **kwargs):
        """Create an audit log entry"""
        audit_log = AuditLog(
            id=uuid4(),
            user_id=kwargs.get("user_id"),
            action=kwargs.get("action"),
            resource_type=kwargs.get("resource_type"),
            resource_id=kwargs.get("resource_id"),
            details=kwargs.get("details"),
            ip_address=kwargs.get("ip_address"),
            user_agent=kwargs.get("user_agent"),
            created_at=datetime.utcnow()
        )
        
        self.audit_logs.append(audit_log)
        
        # Limit audit log size in memory
        if len(self.audit_logs) > 10000:
            self.audit_logs = self.audit_logs[-5000:]
    
    async def get_audit_logs(
        self,
        user_id: Optional[UUID] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AuditLog]:
        """
        Retrieve audit logs with filtering.
        
        Args:
            user_id: Filter by user ID
            action: Filter by action type
            resource_type: Filter by resource type
            since: Get logs since timestamp
            limit: Maximum logs to return
            offset: Pagination offset
            
        Returns:
            List of matching audit logs
        """
        # Start with all logs (in reverse chronological order)
        filtered_logs = list(reversed(self.audit_logs))
        
        # Apply filters
        if user_id:
            if isinstance(user_id, str):
                user_id = UUID(user_id)
            filtered_logs = [log for log in filtered_logs if log.user_id == user_id]
        
        if action:
            filtered_logs = [log for log in filtered_logs if log.action == action]
        
        if resource_type:
            filtered_logs = [log for log in filtered_logs if log.resource_type == resource_type]
        
        if since:
            filtered_logs = [log for log in filtered_logs if log.created_at >= since]
        
        # Apply pagination
        start = offset
        end = offset + limit
        return filtered_logs[start:end]
    
    async def get_user_api_keys(self, user_id: UUID) -> List[ApiKey]:
        """Get all API keys for a user"""
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        return [
            api_key for api_key in self.api_keys.values()
            if api_key.user_id == user_id and not api_key.revoked_at
        ]
    
    async def get_role_by_name(self, name: str) -> Optional[Role]:
        """Get role by name"""
        for role in self.roles.values():
            if role.name == name:
                return role
        return None
    
    async def add_user_role(self, user_id: UUID, role_name: str):
        """Add a role to a user"""
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        user = self.users.get(user_id)
        role = await self.get_role_by_name(role_name)
        
        if user and role:
            if not user.roles:
                user.roles = []
            if role not in user.roles:
                user.roles.append(role)


# Global auth database instance
_auth_db: Optional[AuthDatabase] = None


def get_auth_db(persistence=None, redis_adapter=None) -> AuthDatabase:
    """
    Get the authentication database instance based on persistence type
    
    Args:
        persistence: Optional persistence instance (SQL or in-memory)
        redis_adapter: Optional Redis adapter for caching
    
    Returns:
        AuthDatabase instance appropriate for the backend
    """
    global _auth_db
    
    if _auth_db is None:
        # Check environment for persistence type
        persistence_type = os.getenv("GLEITZEIT_PERSISTENCE_TYPE", "memory").lower()
        
        if persistence_type == "redis" and redis_adapter:
            # Redis with optional SQL fallback
            logger.info("Initializing Redis authentication database")
            from .persistence_adapter import AuthRedisPersistence, AuthSQLPersistence
            
            # Check if we also have SQL backend for persistent storage
            sql_backend = None
            if persistence and hasattr(persistence, 'engine'):
                sql_backend = AuthSQLPersistence(persistence)
                logger.info("Using SQL backend for persistent auth storage")
            
            _auth_db = AuthRedisPersistence(redis_adapter, sql_backend)
            
        elif persistence_type == "sql" and persistence:
            # Pure SQL backend
            logger.info("Initializing SQL authentication database")
            from .persistence_adapter import AuthSQLPersistence
            _auth_db = AuthSQLPersistence(persistence)
            
        else:
            # Fall back to in-memory for development
            logger.info("Initializing in-memory authentication database")
            _auth_db = InMemoryAuthDatabase()
    
    return _auth_db


def init_auth_db(persistence=None, redis_adapter=None):
    """
    Initialize the authentication database with specific backends
    
    Args:
        persistence: Persistence instance (SQL or in-memory)
        redis_adapter: Redis adapter for caching
    """
    global _auth_db
    
    # Reset any existing instance
    _auth_db = None
    
    # Initialize with provided backends
    return get_auth_db(persistence, redis_adapter)


def reset_auth_db():
    """Reset the authentication database (for testing)"""
    global _auth_db
    _auth_db = None