"""
Authentication persistence adapter for SQL and Redis backends
Integrates with Gleitzeit's existing persistence layer
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from ..persistence.factory import PersistenceFactory
from ..persistence.unified_sqlalchemy import UnifiedSQLAlchemyPersistence
from ..persistence.redis_adapter import RedisAdapter
from .models import User, ApiKey, Role, Session, AuditLog, DEFAULT_ROLES
from .database import AuthDatabase

logger = logging.getLogger(__name__)


class AuthSQLPersistence(AuthDatabase):
    """
    SQL-based authentication persistence using Gleitzeit's existing SQLAlchemy backend
    """
    
    def __init__(self, persistence: UnifiedSQLAlchemyPersistence):
        self.persistence = persistence
        self.session = persistence.Session()
        
        # Create auth tables if they don't exist
        self._create_tables()
        
        # Initialize default roles
        self._init_default_roles()
        
        # Create default admin if configured
        import os
        if os.getenv("GLEITZEIT_AUTH_CREATE_ADMIN", "true").lower() == "true":
            self._create_default_admin()
    
    def _create_tables(self):
        """Create authentication tables in the database"""
        try:
            # Import models to ensure tables are registered
            from .models import Base
            
            # Create all auth tables
            Base.metadata.create_all(self.persistence.engine)
            logger.info("Created authentication tables")
        except Exception as e:
            logger.error(f"Error creating auth tables: {e}")
    
    def _init_default_roles(self):
        """Initialize default roles in database"""
        try:
            for role_data in DEFAULT_ROLES:
                # Check if role already exists
                existing = self.session.query(Role).filter_by(name=role_data["name"]).first()
                if not existing:
                    role = Role(
                        id=uuid4(),
                        name=role_data["name"],
                        description=role_data["description"],
                        permissions=role_data["permissions"],
                        is_system=role_data["is_system"]
                    )
                    self.session.add(role)
            
            self.session.commit()
            logger.info("Initialized default roles in SQL database")
        except Exception as e:
            logger.error(f"Error initializing roles: {e}")
            self.session.rollback()
    
    def _create_default_admin(self):
        """Create default admin user in database"""
        import os
        from .utils import hash_password
        
        admin_email = os.getenv("GLEITZEIT_AUTH_ADMIN_EMAIL", "admin@localhost")
        admin_password = os.getenv("GLEITZEIT_AUTH_ADMIN_PASSWORD", "admin")
        
        try:
            # Check if admin already exists
            existing = self.session.query(User).filter_by(email=admin_email).first()
            if existing:
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
            admin_role = self.session.query(Role).filter_by(name="admin").first()
            if admin_role:
                admin_user.roles.append(admin_role)
            
            self.session.add(admin_user)
            self.session.commit()
            logger.info(f"Created default admin user: {admin_email}")
        except Exception as e:
            logger.error(f"Error creating admin user: {e}")
            self.session.rollback()
    
    async def get_user(self, user_id: UUID) -> Optional[User]:
        """Get user by ID from SQL database"""
        try:
            if isinstance(user_id, str):
                user_id = UUID(user_id)
            return self.session.query(User).filter_by(id=user_id).first()
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email from SQL database"""
        try:
            return self.session.query(User).filter_by(email=email).first()
        except Exception as e:
            logger.error(f"Error getting user by email: {e}")
            return None
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username from SQL database"""
        try:
            return self.session.query(User).filter_by(username=username).first()
        except Exception as e:
            logger.error(f"Error getting user by username: {e}")
            return None
    
    async def create_user(self, user_data: dict) -> User:
        """Create a new user in SQL database"""
        from .utils import hash_password
        
        try:
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
            viewer_role = self.session.query(Role).filter_by(name="viewer").first()
            if viewer_role:
                user.roles.append(viewer_role)
            
            self.session.add(user)
            self.session.commit()
            return user
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            self.session.rollback()
            raise
    
    async def update_user_last_login(self, user_id: UUID):
        """Update user's last login timestamp"""
        try:
            if isinstance(user_id, str):
                user_id = UUID(user_id)
            
            user = self.session.query(User).filter_by(id=user_id).first()
            if user:
                user.last_login = datetime.utcnow()
                self.session.commit()
        except Exception as e:
            logger.error(f"Error updating last login: {e}")
            self.session.rollback()
    
    async def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """Get API key by hash from SQL database"""
        try:
            return self.session.query(ApiKey).filter_by(key_hash=key_hash).first()
        except Exception as e:
            logger.error(f"Error getting API key: {e}")
            return None
    
    async def create_api_key(self, user_id: UUID, key_data: dict) -> ApiKey:
        """Create a new API key in SQL database"""
        try:
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
            
            self.session.add(api_key)
            self.session.commit()
            return api_key
        except Exception as e:
            logger.error(f"Error creating API key: {e}")
            self.session.rollback()
            raise
    
    async def update_api_key_last_used(self, key_id: UUID):
        """Update API key's last used timestamp"""
        try:
            if isinstance(key_id, str):
                key_id = UUID(key_id)
            
            api_key = self.session.query(ApiKey).filter_by(id=key_id).first()
            if api_key:
                api_key.last_used_at = datetime.utcnow()
                self.session.commit()
        except Exception as e:
            logger.error(f"Error updating API key last used: {e}")
            self.session.rollback()
    
    async def get_session_by_token_hash(self, token_hash: str) -> Optional[Session]:
        """Get session by token hash from SQL database"""
        try:
            return self.session.query(Session).filter_by(token_hash=token_hash).first()
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None
    
    async def create_session(self, user_id: UUID, session_data: dict) -> Session:
        """Create a new session in SQL database"""
        try:
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
            
            self.session.add(session)
            self.session.commit()
            return session
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            self.session.rollback()
            raise
    
    async def update_session_activity(self, session_id: UUID):
        """Update session's last activity timestamp"""
        try:
            if isinstance(session_id, str):
                session_id = UUID(session_id)
            
            session = self.session.query(Session).filter_by(id=session_id).first()
            if session:
                session.last_activity = datetime.utcnow()
                self.session.commit()
        except Exception as e:
            logger.error(f"Error updating session activity: {e}")
            self.session.rollback()
    
    async def create_audit_log(self, **kwargs):
        """Create an audit log entry in SQL database"""
        try:
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
            
            self.session.add(audit_log)
            self.session.commit()
        except Exception as e:
            logger.error(f"Error creating audit log: {e}")
            self.session.rollback()


class AuthRedisPersistence(AuthDatabase):
    """
    Redis-based authentication persistence with caching
    Uses Redis for session/token storage and caching, with SQL fallback for persistent data
    """
    
    def __init__(self, redis_adapter: RedisAdapter, sql_backend: Optional[AuthSQLPersistence] = None):
        self.redis = redis_adapter
        self.sql_backend = sql_backend  # Optional SQL backend for persistent storage
        
        # Key prefixes for Redis
        self.USER_KEY = "auth:user:"
        self.API_KEY = "auth:apikey:"
        self.SESSION_KEY = "auth:session:"
        self.ROLE_KEY = "auth:role:"
        
        # TTL settings
        self.USER_CACHE_TTL = 300  # 5 minutes
        self.API_KEY_CACHE_TTL = 600  # 10 minutes
        self.SESSION_TTL = 3600  # 1 hour
        
        # Initialize default data if SQL backend is not available
        if not self.sql_backend:
            self._init_redis_defaults()
    
    def _init_redis_defaults(self):
        """Initialize default roles and admin user in Redis"""
        import os
        from .utils import hash_password
        
        # Initialize default roles
        for role_data in DEFAULT_ROLES:
            role_key = f"{self.ROLE_KEY}{role_data['name']}"
            if not self.redis.client.exists(role_key):
                self.redis.client.hset(role_key, mapping={
                    "id": str(uuid4()),
                    "name": role_data["name"],
                    "description": role_data["description"],
                    "permissions": json.dumps(role_data["permissions"]),
                    "is_system": str(role_data["is_system"])
                })
                logger.info(f"Created default role in Redis: {role_data['name']}")
        
        # Create default admin if configured
        if os.getenv("GLEITZEIT_AUTH_CREATE_ADMIN", "true").lower() == "true":
            admin_email = os.getenv("GLEITZEIT_AUTH_ADMIN_EMAIL", "admin@localhost")
            admin_password = os.getenv("GLEITZEIT_AUTH_ADMIN_PASSWORD", "admin")
            
            admin_key = f"{self.USER_KEY}email:{admin_email}"
            if not self.redis.client.exists(admin_key):
                admin_id = str(uuid4())
                user_data = {
                    "id": admin_id,
                    "email": admin_email,
                    "username": "admin",
                    "password_hash": hash_password(admin_password),
                    "full_name": "System Administrator",
                    "is_active": "true",
                    "is_superuser": "true",
                    "roles": json.dumps(["admin"]),
                    "created_at": datetime.utcnow().isoformat()
                }
                
                # Store user data
                self.redis.client.hset(f"{self.USER_KEY}{admin_id}", mapping=user_data)
                # Create email index
                self.redis.client.set(admin_key, admin_id)
                
                logger.info(f"Created default admin user in Redis: {admin_email}")
    
    async def get_user(self, user_id: UUID) -> Optional[Dict[str, Any]]:
        """Get user by ID from Redis cache or SQL backend"""
        try:
            if isinstance(user_id, str):
                user_id = UUID(user_id)
            
            # Check Redis cache first
            user_key = f"{self.USER_KEY}{user_id}"
            cached_data = self.redis.client.hgetall(user_key)
            
            if cached_data:
                # Parse cached data
                user_data = self._parse_redis_user(cached_data)
                return user_data
            
            # Fall back to SQL if available
            if self.sql_backend:
                user = await self.sql_backend.get_user(user_id)
                if user:
                    # Cache in Redis
                    self._cache_user(user)
                    return user.to_dict()
            
            return None
        except Exception as e:
            logger.error(f"Error getting user from Redis: {e}")
            return None
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email from Redis cache or SQL backend"""
        try:
            # Check email index in Redis
            email_key = f"{self.USER_KEY}email:{email}"
            user_id = self.redis.client.get(email_key)
            
            if user_id:
                return await self.get_user(user_id)
            
            # Fall back to SQL if available
            if self.sql_backend:
                user = await self.sql_backend.get_user_by_email(email)
                if user:
                    # Cache in Redis
                    self._cache_user(user)
                    # Create email index
                    self.redis.client.set(email_key, str(user.id), ex=self.USER_CACHE_TTL)
                    return user.to_dict()
            
            return None
        except Exception as e:
            logger.error(f"Error getting user by email from Redis: {e}")
            return None
    
    async def get_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        """Get API key by hash from Redis cache or SQL backend"""
        try:
            # Check Redis cache
            api_key_key = f"{self.API_KEY}hash:{key_hash}"
            cached_data = self.redis.client.hgetall(api_key_key)
            
            if cached_data:
                return self._parse_redis_api_key(cached_data)
            
            # Fall back to SQL if available
            if self.sql_backend:
                api_key = await self.sql_backend.get_api_key_by_hash(key_hash)
                if api_key:
                    # Cache in Redis
                    self._cache_api_key(api_key)
                    return api_key.to_dict()
            
            return None
        except Exception as e:
            logger.error(f"Error getting API key from Redis: {e}")
            return None
    
    async def create_session(self, user_id: UUID, session_data: dict) -> Dict[str, Any]:
        """Create a new session in Redis"""
        try:
            if isinstance(user_id, str):
                user_id = UUID(user_id)
            
            session_id = str(uuid4())
            session_key = f"{self.SESSION_KEY}{session_id}"
            
            # Store session in Redis with TTL
            session_data.update({
                "id": session_id,
                "user_id": str(user_id),
                "created_at": datetime.utcnow().isoformat(),
                "last_activity": datetime.utcnow().isoformat()
            })
            
            self.redis.client.hset(session_key, mapping={
                k: str(v) if v is not None else ""
                for k, v in session_data.items()
            })
            self.redis.client.expire(session_key, self.SESSION_TTL)
            
            # Create token hash index
            if "token_hash" in session_data:
                token_key = f"{self.SESSION_KEY}token:{session_data['token_hash']}"
                self.redis.client.set(token_key, session_id, ex=self.SESSION_TTL)
            
            # Also store in SQL if available
            if self.sql_backend:
                await self.sql_backend.create_session(user_id, session_data)
            
            return session_data
        except Exception as e:
            logger.error(f"Error creating session in Redis: {e}")
            raise
    
    async def get_session_by_token_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Get session by token hash from Redis"""
        try:
            # Check token index in Redis
            token_key = f"{self.SESSION_KEY}token:{token_hash}"
            session_id = self.redis.client.get(token_key)
            
            if session_id:
                session_key = f"{self.SESSION_KEY}{session_id}"
                session_data = self.redis.client.hgetall(session_key)
                
                if session_data:
                    # Check if session is still valid
                    expires_at = session_data.get(b"expires_at", b"").decode()
                    if expires_at:
                        expiry = datetime.fromisoformat(expires_at)
                        if expiry < datetime.utcnow():
                            # Session expired
                            self.redis.client.delete(session_key, token_key)
                            return None
                    
                    return self._parse_redis_session(session_data)
            
            # Fall back to SQL if available
            if self.sql_backend:
                session = await self.sql_backend.get_session_by_token_hash(token_hash)
                if session and session.is_valid:
                    # Cache in Redis
                    self._cache_session(session)
                    return {
                        "id": str(session.id),
                        "user_id": str(session.user_id),
                        "is_valid": session.is_valid
                    }
            
            return None
        except Exception as e:
            logger.error(f"Error getting session from Redis: {e}")
            return None
    
    async def update_session_activity(self, session_id: UUID):
        """Update session's last activity timestamp in Redis"""
        try:
            if isinstance(session_id, str):
                session_id = UUID(session_id)
            
            session_key = f"{self.SESSION_KEY}{session_id}"
            if self.redis.client.exists(session_key):
                self.redis.client.hset(session_key, "last_activity", datetime.utcnow().isoformat())
                self.redis.client.expire(session_key, self.SESSION_TTL)  # Reset TTL
            
            # Also update in SQL if available
            if self.sql_backend:
                await self.sql_backend.update_session_activity(session_id)
        except Exception as e:
            logger.error(f"Error updating session activity in Redis: {e}")
    
    async def update_api_key_last_used(self, key_id: UUID):
        """Update API key's last used timestamp"""
        try:
            if isinstance(key_id, str):
                key_id = UUID(key_id)
            
            # Update in SQL if available
            if self.sql_backend:
                await self.sql_backend.update_api_key_last_used(key_id)
            
            # Update cache if present
            api_key_key = f"{self.API_KEY}{key_id}"
            if self.redis.client.exists(api_key_key):
                self.redis.client.hset(api_key_key, "last_used_at", datetime.utcnow().isoformat())
        except Exception as e:
            logger.error(f"Error updating API key last used: {e}")
    
    async def create_audit_log(self, **kwargs):
        """Create audit log entry - store in Redis Stream for real-time processing"""
        try:
            # Add to Redis Stream for real-time processing
            audit_data = {
                "user_id": str(kwargs.get("user_id", "")),
                "action": kwargs.get("action", ""),
                "resource_type": kwargs.get("resource_type", ""),
                "resource_id": kwargs.get("resource_id", ""),
                "ip_address": kwargs.get("ip_address", ""),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Add to audit stream
            self.redis.client.xadd("auth:audit:stream", audit_data, maxlen=10000)
            
            # Also store in SQL if available for long-term storage
            if self.sql_backend:
                await self.sql_backend.create_audit_log(**kwargs)
        except Exception as e:
            logger.error(f"Error creating audit log in Redis: {e}")
    
    # Helper methods for Redis data parsing
    def _parse_redis_user(self, data: dict) -> dict:
        """Parse user data from Redis"""
        return {
            "id": data.get(b"id", b"").decode(),
            "email": data.get(b"email", b"").decode(),
            "username": data.get(b"username", b"").decode(),
            "full_name": data.get(b"full_name", b"").decode(),
            "is_active": data.get(b"is_active", b"true").decode() == "true",
            "is_superuser": data.get(b"is_superuser", b"false").decode() == "true",
            "roles": json.loads(data.get(b"roles", b"[]").decode()),
            "permissions": json.loads(data.get(b"permissions", b"[]").decode())
        }
    
    def _parse_redis_api_key(self, data: dict) -> dict:
        """Parse API key data from Redis"""
        return {
            "id": data.get(b"id", b"").decode(),
            "user_id": data.get(b"user_id", b"").decode(),
            "key_hash": data.get(b"key_hash", b"").decode(),
            "key_prefix": data.get(b"key_prefix", b"").decode(),
            "is_valid": data.get(b"is_valid", b"true").decode() == "true",
            "scopes": json.loads(data.get(b"scopes", b"[]").decode())
        }
    
    def _parse_redis_session(self, data: dict) -> dict:
        """Parse session data from Redis"""
        return {
            "id": data.get(b"id", b"").decode(),
            "user_id": data.get(b"user_id", b"").decode(),
            "token_hash": data.get(b"token_hash", b"").decode(),
            "is_valid": True  # If it's in Redis, it's valid
        }
    
    def _cache_user(self, user: User):
        """Cache user in Redis"""
        user_key = f"{self.USER_KEY}{user.id}"
        user_data = {
            "id": str(user.id),
            "email": user.email,
            "username": user.username or "",
            "full_name": user.full_name or "",
            "is_active": str(user.is_active),
            "is_superuser": str(user.is_superuser),
            "roles": json.dumps([role.name for role in user.roles]),
            "permissions": json.dumps(user.permissions)
        }
        self.redis.client.hset(user_key, mapping=user_data)
        self.redis.client.expire(user_key, self.USER_CACHE_TTL)
    
    def _cache_api_key(self, api_key: ApiKey):
        """Cache API key in Redis"""
        api_key_key = f"{self.API_KEY}hash:{api_key.key_hash}"
        api_key_data = {
            "id": str(api_key.id),
            "user_id": str(api_key.user_id),
            "key_hash": api_key.key_hash,
            "key_prefix": api_key.key_prefix,
            "is_valid": str(api_key.is_valid),
            "scopes": json.dumps(api_key.scopes or [])
        }
        self.redis.client.hset(api_key_key, mapping=api_key_data)
        self.redis.client.expire(api_key_key, self.API_KEY_CACHE_TTL)
    
    def _cache_session(self, session: Session):
        """Cache session in Redis"""
        session_key = f"{self.SESSION_KEY}{session.id}"
        session_data = {
            "id": str(session.id),
            "user_id": str(session.user_id),
            "token_hash": session.token_hash,
            "expires_at": session.expires_at.isoformat() if session.expires_at else ""
        }
        self.redis.client.hset(session_key, mapping=session_data)
        
        # Set TTL based on expiry
        if session.expires_at:
            ttl = int((session.expires_at - datetime.utcnow()).total_seconds())
            if ttl > 0:
                self.redis.client.expire(session_key, min(ttl, self.SESSION_TTL))