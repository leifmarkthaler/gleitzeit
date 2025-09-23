"""
Session management for cookie-based authentication
"""

import uuid
import json
from datetime import datetime, timedelta
from typing import Optional
import redis.asyncio as aioredis
import logging

from .models import User, Session

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages user sessions in Redis"""

    def __init__(
        self,
        redis: aioredis.Redis,
        session_ttl: int = 86400,  # 24 hours
        auto_extend: bool = True
    ):
        self.redis = redis
        self.session_ttl = session_ttl
        self.auto_extend = auto_extend

    async def create_session(self, user: User) -> Session:
        """Create new session for user"""

        session_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self.session_ttl)

        session = Session(
            session_id=session_id,
            user_id=user.id,
            created_at=now,
            expires_at=expires_at,
            last_activity=now
        )

        # Store in Redis
        key = f"session:{session_id}"
        await self.redis.hset(
            key.encode(),
            mapping={
                b"user_id": user.id.encode(),
                b"username": user.username.encode(),
                b"role": user.role.encode(),
                b"created_at": now.isoformat().encode(),
                b"expires_at": expires_at.isoformat().encode(),
                b"last_activity": now.isoformat().encode()
            }
        )

        # Set expiration
        await self.redis.expire(key.encode(), self.session_ttl)

        logger.info(f"Created session {session_id} for user {user.username}")
        return session

    async def get_session(self, session_id: str) -> Optional[User]:
        """Get user from session ID"""

        key = f"session:{session_id}"
        data = await self.redis.hgetall(key.encode())

        if not data:
            logger.debug(f"Session {session_id} not found")
            return None

        # Check expiration
        expires_at = datetime.fromisoformat(data[b"expires_at"].decode())
        if datetime.utcnow() > expires_at:
            logger.debug(f"Session {session_id} has expired")
            await self.delete_session(session_id)
            return None

        # Auto-extend session if enabled
        if self.auto_extend:
            await self.extend_session(session_id)

        # Return user object
        return User(
            id=data[b"user_id"].decode(),
            username=data[b"username"].decode(),
            role=data[b"role"].decode()
        )

    async def extend_session(self, session_id: str) -> bool:
        """Extend session TTL"""

        key = f"session:{session_id}"

        # Update last activity
        await self.redis.hset(
            key.encode(),
            b"last_activity",
            datetime.utcnow().isoformat().encode()
        )

        # Extend expiration
        result = await self.redis.expire(key.encode(), self.session_ttl)

        if result:
            logger.debug(f"Extended session {session_id}")

        return result

    async def delete_session(self, session_id: str) -> bool:
        """Delete session (logout)"""

        key = f"session:{session_id}"
        result = await self.redis.delete(key.encode())

        if result:
            logger.info(f"Deleted session {session_id}")

        return bool(result)

    async def get_user_sessions(self, user_id: str) -> list[Session]:
        """Get all active sessions for a user"""

        # Find all session keys
        pattern = "session:*"
        sessions = []

        async for key in self.redis.scan_iter(pattern.encode()):
            data = await self.redis.hgetall(key)

            if data and data.get(b"user_id", b"").decode() == user_id:
                session_id = key.decode().split(":")[-1]
                sessions.append(Session(
                    session_id=session_id,
                    user_id=user_id,
                    created_at=datetime.fromisoformat(data[b"created_at"].decode()),
                    expires_at=datetime.fromisoformat(data[b"expires_at"].decode()),
                    last_activity=datetime.fromisoformat(data[b"last_activity"].decode())
                ))

        return sessions

    async def delete_user_sessions(self, user_id: str) -> int:
        """Delete all sessions for a user"""

        sessions = await self.get_user_sessions(user_id)
        deleted = 0

        for session in sessions:
            if await self.delete_session(session.session_id):
                deleted += 1

        logger.info(f"Deleted {deleted} sessions for user {user_id}")
        return deleted