"""
JWT token management
"""

import os
import jwt
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging

from .models import User, Token

logger = logging.getLogger(__name__)


class JWTManager:
    """Manages JWT token creation and validation"""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 60 * 24  # 24 hours
    ):
        self.secret_key = secret_key or os.getenv("JWT_SECRET", "dev-secret-key-change-in-production")
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes

        if self.secret_key == "dev-secret-key-change-in-production":
            logger.warning("Using default JWT secret key. Change this in production!")

    def create_access_token(self, user: User) -> Token:
        """Create JWT access token for user"""

        expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)

        payload = {
            "sub": user.id,  # Subject (user ID)
            "username": user.username,
            "role": user.role.value if hasattr(user.role, 'value') else str(user.role),  # Convert enum to string
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "access"
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

        return Token(
            access_token=token,
            expires_in=self.access_token_expire_minutes * 60
        )

    def verify_token(self, token: str) -> Optional[Dict]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.debug("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"Invalid token: {e}")
            return None

    def create_refresh_token(self, user: User) -> str:
        """Create refresh token with longer expiration"""

        expire = datetime.utcnow() + timedelta(days=30)

        payload = {
            "sub": user.id,
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "refresh"
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def refresh_access_token(self, refresh_token: str) -> Optional[Token]:
        """Create new access token from refresh token"""

        payload = self.verify_token(refresh_token)

        if not payload or payload.get("type") != "refresh":
            return None

        # Create minimal user object for token generation
        user = User(
            id=payload["sub"],
            username=payload.get("username", "unknown"),
            role=payload.get("role", "user")
        )

        return self.create_access_token(user)