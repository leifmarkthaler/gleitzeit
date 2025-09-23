"""
Authentication mixin for Gleitzeit client.

Provides authentication methods including session management, JWT tokens,
and API key authentication.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Authentication failed."""
    pass


class AuthorizationError(Exception):
    """Authorization failed."""
    pass


class AuthMixin:
    """
    Authentication mixin providing various auth methods.

    Supports:
    - Session-based authentication with cookies
    - JWT token authentication
    - API key authentication
    - Auto-login functionality
    """

    def __init__(self, *args, **kwargs):
        """Initialize authentication configuration."""
        super().__init__(*args, **kwargs)

        # Extract auth-specific parameters
        self.auto_login = kwargs.get('auto_login', True)
        self.username = kwargs.get('username', 'default_user')
        self.password = kwargs.get('password')

        # Set initial auth credentials if provided
        self.session_id = kwargs.get('session_id')
        self.jwt_token = kwargs.get('jwt_token')
        self.api_key = kwargs.get('api_key')

    async def auto_authenticate(self):
        """Automatically authenticate if enabled and no credentials exist."""
        if self.auto_login and not any([self.session_id, self.jwt_token, self.api_key]):
            try:
                logger.info("Auto-login enabled, creating session...")
                await self.create_session(self.username, self.password)
            except Exception as e:
                logger.warning(f"Auto-login failed: {e}")

    async def create_session(self, username: str, password: Optional[str] = None) -> str:
        """
        Create a new client session.

        Args:
            username: Username for authentication
            password: Optional password

        Returns:
            Session ID
        """
        await self.ensure_connected()

        response = await self._request(
            "POST",
            "/auth/session/create",
            json_data={"username": username, "password": password}
        )

        self.session_id = response["session_id"]
        self.username = username
        logger.info(f"Created session for user {username}: {self.session_id}")
        return self.session_id

    async def destroy_session(self) -> Dict[str, Any]:
        """
        Destroy current session.

        Returns:
            Destruction confirmation

        Raises:
            ValueError: If no active session
        """
        if not self.session_id:
            raise ValueError("No active session to destroy")

        response = await self._request(
            "POST",
            "/auth/session/destroy",
            json_data={"session_id": self.session_id}
        )

        logger.info(f"Destroyed session {self.session_id}")
        self.session_id = None
        return response

    async def create_token(self, username: str, password: Optional[str] = None) -> str:
        """
        Create JWT token.

        Args:
            username: Username for authentication
            password: Optional password

        Returns:
            JWT access token
        """
        response = await self._request(
            "POST",
            "/auth/token",
            json_data={"username": username, "password": password}
        )

        self.jwt_token = response["access_token"]
        logger.info(f"Created JWT token for user {username}")
        return self.jwt_token

    async def refresh_token(self, refresh_token: str) -> str:
        """
        Refresh JWT token.

        Args:
            refresh_token: Refresh token

        Returns:
            New access token
        """
        response = await self._request(
            "POST",
            "/auth/token/refresh",
            json_data={"refresh_token": refresh_token}
        )

        self.jwt_token = response["access_token"]
        logger.info("Refreshed JWT token")
        return self.jwt_token

    async def validate_session(self) -> bool:
        """
        Validate current session.

        Returns:
            True if session is valid
        """
        if not self.session_id:
            return False

        try:
            response = await self._request(
                "GET",
                "/auth/session/validate"
            )
            return response.get("valid", False)
        except Exception:
            return False

    async def get_current_user(self) -> Dict[str, Any]:
        """
        Get current authenticated user information.

        Returns:
            User information
        """
        return await self._request("GET", "/auth/me")

    async def handle_auth_error(self, error_code: int) -> bool:
        """
        Handle authentication errors.

        Args:
            error_code: HTTP error code

        Returns:
            True if handled and should retry
        """
        if error_code == 401 and self.auto_login:
            logger.info("Authentication failed, attempting to re-authenticate...")
            try:
                await self.create_session(self.username, self.password)
                return True
            except Exception as e:
                logger.error(f"Re-authentication failed: {e}")
        return False