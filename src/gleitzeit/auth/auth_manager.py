"""
Authentication Manager for SystemManager

Provides centralized, stateless authentication services that scale horizontally.
All auth state is stored in persistence backend for true stateless operation.
"""

import os
import jwt
import hashlib
import secrets
import logging
import bcrypt
import uuid
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.errors import (
    SystemError,
    ErrorCode,
    GleitzeitError
)
from gleitzeit.core.events import GleitzeitEvent as Event, EventType

logger = logging.getLogger(__name__)

# Import extensions
from .auth_extras import AuthManagerExtensions
from .user_session_complete import UserSessionComplete


class AuthManager(AuthManagerExtensions, UserSessionComplete):
    """
    Stateless authentication manager integrated with SystemManager.
    
    Features:
    - Stateless session management (all state in persistence)
    - Horizontal scaling support (no in-memory state)
    - Basic and advanced auth modes
    - JWT token generation with persistence-backed validation
    - Permission system integration
    """
    
    def __init__(self, persistence: PersistenceBackend, event_bus=None):
        """
        Initialize AuthManager with persistence backend.
        
        Args:
            persistence: Backend for storing auth state (users, sessions, etc.)
            event_bus: Optional event bus for session lifecycle events
        """
        self.persistence = persistence
        self.event_bus = event_bus
        
        # Configuration from environment
        # For stateless operation, all instances must share the same secret
        # In production, this should be set via environment variable
        default_secret = "gleitzeit-default-secret-key-for-development"
        self.secret_key = os.getenv("GLEITZEIT_SECRET_KEY", default_secret)
        
        self.algorithm = "HS256"
        self.token_expiry_hours = int(os.getenv("GLEITZEIT_TOKEN_EXPIRY_HOURS", "24"))
        
        # Basic user configuration (created on first startup)
        self.basic_username = os.getenv("GLEITZEIT_BASIC_USERNAME", "basic")
        self.basic_password = os.getenv("GLEITZEIT_BASIC_PASSWORD", "basic")
        
        logger.info("AuthManager initialized with authentication always enabled")
        
    def _generate_secret(self) -> str:
        """Generate a secure secret key for JWT signing."""
        return secrets.token_urlsafe(32)
        
    def _get_basic_permissions(self) -> list:
        """Get permissions for basic user - limited to own resources, NO admin."""
        return [
            # Can create new resources
            "workflows:create",
            "tasks:create",
            
            # Can read own resources (ownership checked separately)
            "workflows:read",
            "tasks:read",
            
            # Can modify own resources (ownership checked separately)
            "workflows:update",
            "workflows:delete",
            "workflows:pause",
            "workflows:resume",
            "workflows:cancel",
            "tasks:update",
            "tasks:delete",
            "tasks:cancel",
            
            # Read-only access to system info
            "queues:read",
            "logs:read",
            "events:read",
            "system:read",
            
            # EXPLICITLY NO admin permissions
            # NO users:create, users:read, users:update, users:delete
            # NO queues:manage
            # NO system:debug
            # NO admin:* permissions
        ]
    
    async def ensure_basic_user_exists(self) -> None:
        """
        Ensure the basic user exists in the database.
        Called on startup to guarantee basic user availability.
        """
        try:
            # Check if basic user already exists
            existing_user = await self._get_user_by_username(self.basic_username)
            if existing_user:
                logger.info(f"Basic user '{self.basic_username}' already exists")
                return
            
            # Create basic user directly (bypass validation for system user)
            user_id = "basic-user"  # Fixed ID for basic user
            user = {
                "id": user_id,
                "username": self.basic_username,
                "email": "basic@localhost.local",  # Use .local for internal use
                "password_hash": self._hash_password(self.basic_password),
                "role": "basic",
                "is_active": True,
                "is_basic_user": True,
                "max_sessions": 1,
                "created_at": datetime.utcnow().isoformat(),
                "permissions": self._get_basic_permissions(),
                "description": "Default user for immediate access after installation"
            }
            
            # Store user in persistence
            user_key = f"user:{user_id}"
            await self.persistence.set(user_key, user)
            
            # Create username index
            username_key = f"user:username:{self.basic_username}"
            await self.persistence.set(username_key, user_id)
            
            # Create email index
            email_key = f"user:email:{user['email']}"
            await self.persistence.set(email_key, user_id)
            
            logger.info(f"Created basic user '{self.basic_username}' with default password")
            
        except Exception as e:
            logger.error(f"Failed to ensure basic user exists: {e}")
    
    def get_unauthenticated_user(self) -> Dict[str, Any]:
        """
        Get an unauthenticated user object for when auth is required but not provided.
        Always returns a user with no permissions.
        
        Returns:
            User dict with no permissions
        """
        return {
            "id": "unauthenticated",
            "username": "unauthenticated",
            "email": None,
            "name": "Unauthenticated User",
            "role": "none",
            "is_authenticated": False,
            "permissions": []  # No permissions without auth
        }
        
    async def login(self, username: str, password: str, request_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Authenticate user and create stateless session.
        
        Args:
            username: Username or email
            password: User password
            request_data: Optional request context for fingerprinting
            
        Returns:
            Dict with user info and session token
            
        Raises:
            AuthenticationError: If credentials are invalid
        """
        try:
            # Always validate against user database (no modes)
            # Fetch user from persistence
            user = await self._get_user_by_username(username)
            if not user:
                # Track failed attempt
                await self.track_failed_login(username)
                raise SystemError(
                    message=f"Invalid credentials",
                    code=ErrorCode.AUTHENTICATION_FAILED
                )
            
            # Check for account lockout
            lockout_status = await self.check_account_lockout(username)
            if lockout_status.get("locked"):
                raise SystemError(
                    message=lockout_status.get("message"),
                    code=ErrorCode.ACCOUNT_LOCKED
                )
            
            # Verify password
            if not self._verify_password(password, user.get("password_hash")):
                # Track failed attempt
                await self.track_failed_login(username)
                raise SystemError(
                    message=f"Invalid credentials",
                    code=ErrorCode.AUTHENTICATION_FAILED
                )
            
            # Clear failed login attempts on success
            await self.clear_failed_logins(username)
            
            # Check if user is active
            if not user.get("is_active", True):
                raise SystemError(
                    message="Account is deactivated",
                    code=ErrorCode.AUTHORIZATION_FAILED
                )
            
            # Check if email is verified (optional)
            require_email_verification = os.getenv("GLEITZEIT_REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"
            if require_email_verification and not user.get("email_verified", False):
                raise SystemError(
                    message="Email verification required",
                    code=ErrorCode.EMAIL_NOT_VERIFIED
                )
            
            # Check session limit for basic user
            if user.get("is_basic_user"):
                # For basic user, only allow 1 active session
                existing_sessions_key = f"user:{user['id']}:sessions"
                existing_sessions = await self.persistence.get(existing_sessions_key) or []
                
                # Also check for the fixed basic-user-default session
                basic_session = await self._get_session("basic-user-default")
                if basic_session and not self._is_session_expired(basic_session):
                    if "basic-user-default" not in existing_sessions:
                        existing_sessions.append("basic-user-default")
                
                # Clean up any expired sessions first
                active_sessions = []
                for sid in existing_sessions:
                    session = await self._get_session(sid)
                    if session and not self._is_session_expired(session):
                        active_sessions.append(sid)
                
                if len(active_sessions) >= 1:
                    # Basic user already has an active session
                    raise SystemError(
                        message="Basic user already has an active session. Please logout first or wait for session to expire.",
                        code=ErrorCode.SESSION_LIMIT_EXCEEDED
                    )
            
            # Update last login (preserve password_hash)
            user_copy = user.copy()
            user_copy["last_login"] = datetime.utcnow().isoformat()
            user_key = f"user:{user['id']}"
            await self.persistence.set(user_key, user_copy)
            
            # Remove sensitive data from returned user object
            user.pop("password_hash", None)
            
            # Create session
            token = self._create_token(user)
            session_id = self._generate_session_id(token)
            await self._store_session(session_id, user, token, request_data)
            
            # Track session for user with distributed lock
            user_sessions_lock = f"user:{user['id']}:sessions:lock"
            lock_id = str(uuid.uuid4())
            
            # Try to acquire lock for session list modification
            lock_acquired = False
            if hasattr(self.persistence, 'redis'):
                from ..persistence.atomic_operations import AtomicPersistenceOperations
                atomic_ops = AtomicPersistenceOperations(self.persistence.redis)
                lock_acquired = await atomic_ops.acquire_lock(user_sessions_lock, lock_id, ttl=5)
            
            try:
                sessions_key = f"user:{user['id']}:sessions"
                sessions = await self.persistence.get(sessions_key) or []
                sessions.append(session_id)
                await self.persistence.set(sessions_key, sessions)
                
                # Enforce session limit (5 for regular users, 1 for basic user)
                max_sessions = 1 if user.get("is_basic_user") else 5
                await self.enforce_session_limit(user['id'], max_sessions=max_sessions)
            finally:
                # Release lock if acquired
                if lock_acquired:
                    await atomic_ops.release_lock(user_sessions_lock, lock_id)
            
            # Log successful login
            await self._log_auth_event(
                user_id=user["id"],
                event_type="login_success",
                success=True,
                metadata={"username": username}
            )
            
            logger.info(f"User {username} logged in successfully")
            
            return {
                "success": True,
                "user": user,
                "token": token,
                "session_id": session_id,
                "expires_in": self.token_expiry_hours * 3600
            }
                
        except GleitzeitError:
            raise
        except Exception as e:
            logger.error(f"Login error for user {username}: {e}")
            raise SystemError(
                message="Authentication failed",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
            
    async def logout(self, session_id: str) -> Dict[str, Any]:
        """
        Logout user by invalidating session in persistence.
        
        Args:
            session_id: Session ID to invalidate
            
        Returns:
            Success status
        """
        try:
            # Get session to find user
            session = await self._get_session(session_id)
            user_id = None
            
            if session:
                user = session.get("user", {})
                user_id = user.get("id")
                
                # Remove from user's session list
                if user_id:
                    sessions_key = f"user:{user_id}:sessions"
                    sessions = await self.persistence.get(sessions_key) or []
                    if session_id in sessions:
                        sessions.remove(session_id)
                        await self.persistence.set(sessions_key, sessions)
                    
                    # Log logout event
                    await self._log_auth_event(
                        user_id=user_id,
                        event_type="logout",
                        success=True,
                        metadata={}
                    )
            
            # Remove session from persistence
            await self._delete_session(session_id)
            
            # Emit session revoked event for distributed invalidation
            if self.event_bus and user_id:
                await self.event_bus.emit(Event(
                    event_type=EventType.SESSION_REVOKED,
                    source="auth_manager",
                    data={
                        "session_id": session_id,
                        "user_id": user_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                ))
            
            logger.info(f"Session {session_id} logged out")
            
            return {
                "success": True,
                "message": "Logged out successfully"
            }
            
        except Exception as e:
            logger.error(f"Logout error for session {session_id}: {e}")
            # Logout should always succeed
            return {
                "success": True,
                "message": "Logged out"
            }
            
    async def validate_session(self, token: str) -> Dict[str, Any]:
        """
        Validate session token against persistence (stateless).
        
        Args:
            token: JWT token to validate
            
        Returns:
            User info if valid
            
        Raises:
            AuthenticationError: If token is invalid or expired
        """
        try:
            # Decode token
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Generate session ID from token
            session_id = self._generate_session_id(token)
            
            # Check session exists in persistence (stateless validation)
            session = await self._get_session(session_id)
            if not session:
                raise SystemError(
                    message="Session expired or invalid",
                    code=ErrorCode.AUTHENTICATION_FAILED
                )
            
            # Check expiry
            exp = payload.get("exp")
            if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
                await self._delete_session(session_id)
                raise SystemError(
                    message="Session expired",
                    code=ErrorCode.AUTHENTICATION_FAILED
                )
            
            return session.get("user", {})
            
        except jwt.InvalidTokenError as e:
            raise SystemError(
                message=f"Invalid token: {str(e)}",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
        except GleitzeitError:
            raise
        except Exception as e:
            logger.error(f"Session validation error: {e}")
            raise SystemError(
                message="Session validation failed",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
            
    async def get_or_create_basic_session(self) -> tuple[str, Dict[str, Any]]:
        """
        Get or create a session for the basic user.
        
        Automatically creates a session for the basic user if needed.
        This ensures authentication is always enforced while allowing
        immediate use after pip install.
        
        Returns:
            Tuple of (session_id, user_dict)
        """
        # Ensure basic user exists
        await self.ensure_basic_user_exists()
        
        # Get the basic user
        basic_user = await self._get_user_by_username(self.basic_username)
        if not basic_user:
            raise SystemError(
                message="Basic user not found",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        # Check if we already have a basic session
        basic_session_key = "session:basic-user-default"
        existing_session = await self.persistence.get(basic_session_key)
        
        if existing_session and existing_session.get("user"):
            # Check if expired
            if not self._is_session_expired(existing_session):
                # Return existing session
                return ("basic-user-default", existing_session.get("user"))
        
        # Remove sensitive data from user object
        basic_user.pop("password_hash", None)
        
        # Create new basic session
        token = self._create_token(basic_user)
        session_id = "basic-user-default"  # Fixed session ID for basic user
        await self._store_session(session_id, basic_user, token, None)
        
        # Add to user's session list for limit enforcement
        sessions_key = f"user:basic-user:sessions"
        sessions = await self.persistence.get(sessions_key) or []
        if session_id not in sessions:
            sessions.append(session_id)
            await self.persistence.set(sessions_key, sessions)
        
        logger.info("Created automatic basic user session")
        return (session_id, basic_user)
    
    async def get_current_user(self, session_id: str = None) -> Dict[str, Any]:
        """
        Get current user from session (stateless lookup).
        
        Args:
            session_id: Session ID
            
        Returns:
            User info
            
        Raises:
            AuthenticationError: If session invalid
        """
        try:
            if not session_id:
                raise SystemError(
                    message="No session provided",
                    code=ErrorCode.AUTHENTICATION_REQUIRED
                )
                
            # Get session from persistence
            session = await self._get_session(session_id)
            if not session:
                raise SystemError(
                    message="Session not found",
                    code=ErrorCode.AUTHENTICATION_FAILED
                )
            
            # Check if session expired
            if self._is_session_expired(session):
                await self._delete_session(session_id)
                raise SystemError(
                    message="Session expired",
                    code=ErrorCode.AUTHENTICATION_FAILED
                )
            
            return session.get("user", {})
            
        except GleitzeitError:
            raise
        except Exception as e:
            logger.error(f"Get current user error: {e}")
            raise SystemError(
                message="Failed to get user info",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
            
    async def check_permission(self, user_id: str, permission: str) -> bool:
        """
        Check if user has specific permission (stateless).
        
        Args:
            user_id: User ID
            permission: Permission to check
            
        Returns:
            True if user has permission
        """
        try:
            # Get user permissions from persistence
            user = await self._get_user_by_id(user_id)
            if not user:
                return False
                
            permissions = user.get("permissions", [])
            role_permissions = await self._get_role_permissions(user.get("role"))
            all_permissions = set(permissions) | set(role_permissions)
            
            return permission in all_permissions
            
        except Exception as e:
            logger.error(f"Permission check error: {e}")
            return False
            
    async def refresh_token(self, old_token: str) -> Dict[str, Any]:
        """
        Refresh authentication token (stateless).
        
        Args:
            old_token: Current token to refresh
            
        Returns:
            New token and session info
            
        Raises:
            AuthenticationError: If token invalid
        """
        try:
            # Validate old token
            user = await self.validate_session(old_token)
            
            # Create new token
            new_token = self._create_token(user)
            session_id = self._generate_session_id(new_token)
            
            # Store new session
            await self._store_session(session_id, user, new_token)
            
            # Delete old session
            old_session_id = self._generate_session_id(old_token)
            await self._delete_session(old_session_id)
            
            logger.info(f"Token refreshed for user {user.get('username')}")
            
            return {
                "success": True,
                "token": new_token,
                "session_id": session_id,
                "expires_in": self.token_expiry_hours * 3600
            }
            
        except GleitzeitError:
            raise
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            raise SystemError(
                message="Failed to refresh token",
                code=ErrorCode.AUTHENTICATION_FAILED
            )
            
    # Private helper methods
    
    def _create_token(self, user: Dict[str, Any]) -> str:
        """Create JWT token for user."""
        payload = {
            "user_id": user["id"],
            "username": user.get("username"),
            "role": user.get("role"),
            "exp": datetime.utcnow() + timedelta(hours=self.token_expiry_hours),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        
    def _generate_session_id(self, token: str) -> str:
        """Generate session ID from token (deterministic for stateless)."""
        return hashlib.sha256(token.encode()).hexdigest()[:32]
        
    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt for secure storage."""
        # Generate salt and hash password
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against bcrypt hash."""
        try:
            # Handle both bcrypt and legacy SHA256 hashes
            if password_hash.startswith('$2b$'):  # bcrypt hash
                return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
            else:  # Legacy SHA256 (for backward compatibility)
                return hashlib.sha256(password.encode()).hexdigest() == password_hash
        except Exception:
            return False
        
    async def _get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user from persistence by username."""
        key = f"user:username:{username}"
        user_id = await self.persistence.get(key)
        if user_id:
            return await self._get_user_by_id(user_id)
        return None
        
    async def _get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user from persistence by ID."""
        # Get user from persistence
        key = f"user:{user_id}"
        user_data = await self.persistence.get(key)
        return user_data
        
    async def _get_role_permissions(self, role: str) -> list:
        """Get permissions for a role from persistence."""
        key = f"role:{role}:permissions"
        permissions = await self.persistence.get(key)
        
        # Return default permissions for known roles
        if not permissions:
            if role == "admin":
                return ["*"]  # All permissions
            elif role == "user":
                return self._get_basic_permissions()
        
        return permissions or []
        
    async def _store_session(self, session_id: str, user: Dict[str, Any], token: str, request_data: Optional[Dict[str, Any]] = None):
        """Store session in persistence for stateless validation.
        
        Args:
            session_id: Session identifier
            user: User data dictionary
            token: JWT token
            request_data: Optional request context for fingerprinting
        """
        session_data = {
            "session_id": session_id,
            "user": user,
            "token": token,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(hours=self.token_expiry_hours)).isoformat(),
            "last_activity": datetime.utcnow().isoformat()
        }
        
        # Add fingerprint if request data available
        if request_data:
            session_data["fingerprint"] = await self.get_session_fingerprint(request_data)
            session_data["last_ip"] = request_data.get("ip_address")
        
        # Store in persistence with TTL
        key = f"session:{session_id}"
        await self.persistence.set(key, session_data)
        
        # Add to global session index for efficient management
        await self._add_to_session_index(session_id, user.get("id"))
        
        # Set TTL if Redis backend supports it
        if hasattr(self.persistence, 'expire'):
            await self.persistence.expire(key, self.token_expiry_hours * 3600)
        elif hasattr(self.persistence, 'redis') and hasattr(self.persistence.redis, 'expire'):
            await self.persistence.redis.expire(key, self.token_expiry_hours * 3600)
        
        # Emit session created event
        if self.event_bus:
            await self.event_bus.emit(Event(
                event_type=EventType.SESSION_CREATED,
                source="auth_manager",
                data={
                    "session_id": session_id,
                    "user_id": user.get("id"),
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
        
    async def _get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session from persistence."""
        key = f"session:{session_id}"
        return await self.persistence.get(key)
        
    async def _delete_session(self, session_id: str):
        """Delete session from persistence."""
        # Get session to find user_id for index cleanup
        session = await self._get_session(session_id)
        
        # Delete session
        key = f"session:{session_id}"
        await self.persistence.delete(key)
        
        # Remove from session index
        if session and session.get("user"):
            await self._remove_from_session_index(session_id, session["user"].get("id"))
    
    def _is_session_expired(self, session: Dict[str, Any]) -> bool:
        """
        Check if a session has expired.
        
        Args:
            session: Session data dictionary
            
        Returns:
            True if session is expired, False otherwise
        """
        if not session or not session.get("expires_at"):
            return True
        
        expires_at = datetime.fromisoformat(session["expires_at"])
        return datetime.utcnow() > expires_at
    
    # User Management Functions
    
    async def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str = "user",
        metadata: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new user with proper password hashing.
        
        Args:
            username: Username for the new user
            email: Email address
            password: Password (will be hashed)
            role: User role (default: "user")
            metadata: Additional user metadata
            created_by: ID of user creating this user (for permission check)
        
        Returns:
            Created user info
            
        Raises:
            SystemError: If user lacks permission or user already exists
        """
        # Check if creator has permission to create users
        if created_by:
            creator = await self._get_user_by_id(created_by)
            if creator and creator.get("is_basic_user"):
                raise SystemError(
                    message="Basic user cannot create other users",
                    code=ErrorCode.FORBIDDEN
                )
            # In future, check for users:create permission
            # if "users:create" not in creator.get("permissions", []):
            #     raise SystemError(...)
        
        # Validate inputs
        if not self._validate_username(username):
            raise SystemError(
                message="Invalid username format",
                code=ErrorCode.INVALID_PARAMS,
                data={"field": "username"}
            )
        
        if not self._validate_email(email):
            raise SystemError(
                message="Invalid email format",
                code=ErrorCode.INVALID_PARAMS,
                data={"field": "email"}
            )
        
        if not self._validate_password(password):
            raise SystemError(
                message="Password does not meet requirements",
                code=ErrorCode.INVALID_PARAMS,
                data={"field": "password"}
            )
        
        # Check if user already exists
        existing = await self._get_user_by_username(username)
        if existing:
            raise SystemError(
                message="Username already exists",
                code=ErrorCode.ALREADY_EXISTS
            )
        
        # Check email uniqueness
        email_key = f"user:email:{email}"
        existing_email = await self.persistence.get(email_key)
        if existing_email:
            raise SystemError(
                message="Email already registered",
                code=ErrorCode.ALREADY_EXISTS
            )
        
        # Create user object
        user_id = str(uuid.uuid4())
        user = {
            "id": user_id,
            "username": username,
            "email": email,
            "password_hash": self._hash_password(password),
            "role": role,
            "is_active": True,
            "email_verified": False,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "failed_attempts": 0,
            "last_login": None,
            "metadata": metadata or {}
        }
        
        # Store user in persistence
        user_key = f"user:{user_id}"
        await self.persistence.set(user_key, user)
        
        # Create username index
        username_key = f"user:username:{username}"
        await self.persistence.set(username_key, user_id)
        
        # Create email index
        await self.persistence.set(email_key, user_id)
        
        # Add to users list
        await self._add_to_user_list(user_id)
        
        # Log user creation event
        await self._log_auth_event(
            user_id=user_id,
            event_type="user_created",
            success=True,
            metadata={"username": username, "email": email, "role": role}
        )
        
        # Remove sensitive data before returning
        user.pop("password_hash", None)
        
        logger.info(f"User created: {username} ({user_id})")
        return user
    
    async def update_user(
        self,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update user information."""
        # Get existing user
        user = await self._get_user_by_id(user_id)
        if not user:
            raise SystemError(
                message="User not found",
                code=ErrorCode.NOT_FOUND
            )
        
        # Prevent updating sensitive fields directly
        protected_fields = ["id", "password_hash", "created_at"]
        for field in protected_fields:
            updates.pop(field, None)
        
        # Update user data
        user.update(updates)
        user["updated_at"] = datetime.utcnow().isoformat()
        
        # Save updated user
        user_key = f"user:{user_id}"
        await self.persistence.set(user_key, user)
        
        # Update indices if username or email changed
        if "username" in updates:
            # Remove old username index
            old_username = await self._get_username_by_id(user_id)
            if old_username:
                await self.persistence.delete(f"user:username:{old_username}")
            # Create new username index
            await self.persistence.set(f"user:username:{updates['username']}", user_id)
        
        if "email" in updates:
            # Remove old email index
            old_email = await self._get_email_by_id(user_id)
            if old_email:
                await self.persistence.delete(f"user:email:{old_email}")
            # Create new email index
            await self.persistence.set(f"user:email:{updates['email']}", user_id)
        
        # Remove sensitive data
        user.pop("password_hash", None)
        
        logger.info(f"User updated: {user_id}")
        return user
    
    async def delete_user(self, user_id: str) -> bool:
        """Delete a user and all associated data."""
        # Get user first
        user = await self._get_user_by_id(user_id)
        if not user:
            return False
        
        # Delete user data
        await self.persistence.delete(f"user:{user_id}")
        
        # Delete indices
        if user.get("username"):
            await self.persistence.delete(f"user:username:{user['username']}")
        if user.get("email"):
            await self.persistence.delete(f"user:email:{user['email']}")
        
        # Remove from user list
        await self._remove_from_user_list(user_id)
        
        # Delete all user sessions
        await self._delete_user_sessions(user_id)
        
        # Log deletion
        await self._log_auth_event(
            user_id=user_id,
            event_type="user_deleted",
            success=True,
            metadata={"username": user.get("username")}
        )
        
        logger.info(f"User deleted: {user_id}")
        return True
    
    async def list_users(
        self,
        offset: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List all users with pagination."""
        # Get user IDs from list
        list_key = "users:list"
        user_ids = await self.persistence.get(list_key) or []
        
        # Apply pagination
        paginated_ids = user_ids[offset:offset + limit]
        
        # Fetch user data
        users = []
        for user_id in paginated_ids:
            user = await self._get_user_by_id(user_id)
            if user:
                # Remove sensitive data
                user.pop("password_hash", None)
                users.append(user)
        
        return users
    
    # Validation Functions
    
    def _validate_username(self, username: str) -> bool:
        """Validate username format."""
        if not username or len(username) < 3 or len(username) > 30:
            return False
        # Allow alphanumeric, underscore, and dash
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', username))
    
    def _validate_email(self, email: str) -> bool:
        """Validate email format."""
        if not email:
            return False
        # Basic email regex
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def _validate_password(self, password: str) -> bool:
        """Validate password meets requirements."""
        if not password or len(password) < 8:
            return False
        # Could add more requirements (uppercase, lowercase, numbers, special chars)
        return True
    
    # Helper Functions
    
    async def _add_to_user_list(self, user_id: str):
        """Add user ID to the users list."""
        list_key = "users:list"
        users = await self.persistence.get(list_key) or []
        if user_id not in users:
            users.append(user_id)
            await self.persistence.set(list_key, users)
    
    async def _remove_from_user_list(self, user_id: str):
        """Remove user ID from the users list."""
        list_key = "users:list"
        users = await self.persistence.get(list_key) or []
        if user_id in users:
            users.remove(user_id)
            await self.persistence.set(list_key, users)
    
    async def _get_username_by_id(self, user_id: str) -> Optional[str]:
        """Get username for a user ID."""
        user = await self._get_user_by_id(user_id)
        return user.get("username") if user else None
    
    async def _get_email_by_id(self, user_id: str) -> Optional[str]:
        """Get email for a user ID."""
        user = await self._get_user_by_id(user_id)
        return user.get("email") if user else None
    
    async def _delete_user_sessions(self, user_id: str):
        """Delete all sessions for a user."""
        # This would need to iterate through sessions
        # For now, we'll use a pattern if Redis backend supports it
        pass
    
    async def _log_auth_event(
        self,
        user_id: str,
        event_type: str,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log authentication event for audit trail."""
        event = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "event_type": event_type,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        
        # Store event
        event_key = f"auth_event:{event['id']}"
        await self.persistence.set(event_key, event)
        
        # Add to user's event list
        user_events_key = f"user:{user_id}:auth_events"
        events = await self.persistence.get(user_events_key) or []
        events.append(event['id'])
        # Keep only last 100 events per user
        events = events[-100:]
        await self.persistence.set(user_events_key, events)
    
    # Session Index Management (for scalability)
    
    async def _with_lock(self, resource: str, operation, ttl: int = 5):
        """Execute operation with distributed lock."""
        lock_id = str(uuid.uuid4())
        lock_acquired = False
        
        try:
            # Try to acquire lock if Redis backend
            if hasattr(self.persistence, 'redis'):
                from ..persistence.atomic_operations import AtomicPersistenceOperations
                atomic_ops = AtomicPersistenceOperations(self.persistence.redis)
                lock_acquired = await atomic_ops.acquire_lock(resource, lock_id, ttl=ttl)
            
            # Execute operation
            return await operation()
            
        finally:
            # Release lock if acquired
            if lock_acquired:
                try:
                    await atomic_ops.release_lock(resource, lock_id)
                except:
                    pass  # Lock will expire anyway
    
    async def _add_to_session_index(self, session_id: str, user_id: Optional[str]):
        """Add session to global and user-specific indices for efficient management."""
        # Add to global active sessions index with lock
        async def add_global():
            global_sessions_key = "sessions:active"
            active_sessions = await self.persistence.get(global_sessions_key) or set()
            if isinstance(active_sessions, list):
                active_sessions = set(active_sessions)
            active_sessions.add(session_id)
            await self.persistence.set(global_sessions_key, list(active_sessions))
        
        await self._with_lock("sessions:active:lock", add_global)
        
        # Add to user-specific sessions index if user_id provided
        if user_id:
            async def add_user():
                user_sessions_key = f"user:{user_id}:sessions:indexed"
                user_sessions = await self.persistence.get(user_sessions_key) or set()
                if isinstance(user_sessions, list):
                    user_sessions = set(user_sessions)
                user_sessions.add(session_id)
                await self.persistence.set(user_sessions_key, list(user_sessions))
            
            await self._with_lock(f"user:{user_id}:sessions:lock", add_user)
    
    async def _remove_from_session_index(self, session_id: str, user_id: Optional[str]):
        """Remove session from global and user-specific indices."""
        # Remove from global active sessions index with lock
        async def remove_global():
            global_sessions_key = "sessions:active"
            active_sessions = await self.persistence.get(global_sessions_key) or set()
            if isinstance(active_sessions, list):
                active_sessions = set(active_sessions)
            active_sessions.discard(session_id)
            await self.persistence.set(global_sessions_key, list(active_sessions))
        
        await self._with_lock("sessions:active:lock", remove_global)
        
        # Remove from user-specific sessions index if user_id provided
        if user_id:
            async def remove_user():
                user_sessions_key = f"user:{user_id}:sessions:indexed"
                user_sessions = await self.persistence.get(user_sessions_key) or set()
                if isinstance(user_sessions, list):
                    user_sessions = set(user_sessions)
                user_sessions.discard(session_id)
                await self.persistence.set(user_sessions_key, list(user_sessions))
            
            await self._with_lock(f"user:{user_id}:sessions:lock", remove_user)
    
    async def get_all_active_sessions(self) -> List[str]:
        """Get all active session IDs from the global index."""
        global_sessions_key = "sessions:active"
        active_sessions = await self.persistence.get(global_sessions_key) or []
        return list(active_sessions)
    
    async def cleanup_expired_sessions_indexed(self) -> int:
        """
        Clean up expired sessions using the indexed approach.
        This is much more efficient than iterating through all users.
        
        Returns:
            Number of sessions cleaned
        """
        cleaned = 0
        
        # Get all active sessions from index
        active_sessions = await self.get_all_active_sessions()
        
        for session_id in active_sessions:
            session = await self._get_session(session_id)
            if session:
                # Check expiry
                expires_at = datetime.fromisoformat(session.get("expires_at"))
                if datetime.utcnow() > expires_at:
                    # Delete expired session
                    await self._delete_session(session_id)
                    cleaned += 1
                    
                    # Emit session expired event
                    if self.event_bus and session.get("user"):
                        await self.event_bus.emit(Event(
                            event_type=EventType.SESSION_EXPIRED,
                            source="auth_manager",
                            data={
                                "session_id": session_id,
                                "user_id": session["user"].get("id"),
                                "timestamp": datetime.utcnow().isoformat()
                            }
                        ))
            else:
                # Session doesn't exist but is in index - clean up index
                await self._remove_from_session_index(session_id, None)
                cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired sessions (indexed)")

        return cleaned

    async def shutdown(self):
        """Shutdown the AuthManager (stateless, so just a no-op for compatibility)."""
        logger.info("AuthManager shutdown (stateless - no cleanup needed)")
        # Since we're stateless, there's nothing to clean up
        # All state is in persistence which remains available