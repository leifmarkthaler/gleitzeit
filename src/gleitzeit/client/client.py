"""
Modular Gleitzeit Python Client SDK.

This is the main client class that combines all mixins to provide
the complete Gleitzeit client functionality.
"""

import logging
from typing import Optional, Dict, Any

from .base import BaseClient
from .mixins import (
    AuthMixin,
    RetryMixin,
    WorkflowMixin,
    TaskMixin,
    MonitoringMixin
)

logger = logging.getLogger(__name__)


class GleitzeitClient(
    AuthMixin,
    RetryMixin,
    WorkflowMixin,
    TaskMixin,
    MonitoringMixin,
    BaseClient
):
    """
    Complete Gleitzeit client with modular mixin architecture.

    This client combines all functionality through mixins:
    - AuthMixin: Authentication and session management
    - RetryMixin: Retry logic and error handling
    - WorkflowMixin: Workflow operations
    - TaskMixin: Task operations
    - MonitoringMixin: System monitoring and health checks
    - BaseClient: Core HTTP functionality

    Example usage:
        ```python
        async with GleitzeitClient() as client:
            # Auto-login happens automatically if enabled
            response = await client.submit_workflow({
                "workflow_id": "example",
                "tasks": [...]
            })

            # Wait for completion
            status = await client.wait_for_workflow(response.workflow_id)
        ```

    The client supports multiple authentication methods:
    - Session-based auth with cookies (default with auto-login)
    - JWT token authentication
    - API key authentication

    All operations include:
    - Automatic retry with exponential backoff
    - Rate limit handling
    - Connection pooling
    - Error classification
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        session_id: Optional[str] = None,
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
        pool_size: int = 5,
        timeout: int = 30,
        auto_login: bool = True,
        username: Optional[str] = None,
        password: Optional[str] = None,
        retry_config: Optional[Dict[str, Any]] = None,
        auto_start_server: bool = False
    ):
        """
        Initialize Gleitzeit client with all mixin functionality.

        Args:
            api_url: Base URL of the Gleitzeit API
            session_id: Existing session ID for authentication
            api_key: API key for authentication
            jwt_token: JWT token for authentication
            pool_size: Size of the connection pool
            timeout: Default request timeout in seconds
            auto_login: Whether to automatically create a session
            username: Username for auto-login
            password: Password for authentication
            retry_config: Custom retry configuration
            auto_start_server: Whether to attempt starting the server
        """
        # Initialize all mixins and base class
        super().__init__(
            api_url=api_url,
            session_id=session_id,
            api_key=api_key,
            jwt_token=jwt_token,
            pool_size=pool_size,
            timeout=timeout,
            auto_login=auto_login,
            username=username,
            password=password,
            retry_config=retry_config
        )

        self.auto_start_server = auto_start_server
        if auto_start_server:
            self._ensure_server_running()

        logger.info(f"Initialized modular Gleitzeit client for {api_url}")

    def _ensure_server_running(self):
        """Check if server is running and attempt to start if needed."""
        import requests
        try:
            response = requests.get(f"{self.api_url}/health", timeout=2)
            if response.status_code == 200:
                logger.info("API server is already running")
                return
        except:
            logger.info("API server not running")
            # Could implement server startup here if needed
            pass

    async def connect(self):
        """
        Initialize connection and perform auto-authentication if configured.

        This method:
        1. Establishes the HTTP connection pool
        2. Performs auto-login if enabled and no credentials exist
        """
        await super().connect()

        # Auto-authenticate if configured (from AuthMixin)
        await self.auto_authenticate()

    async def initialize(self):
        """
        Alias for connect() for backward compatibility.
        """
        await self.connect()

    async def shutdown(self):
        """
        Alias for close() for backward compatibility.
        """
        await self.close()

    def __repr__(self) -> str:
        """String representation of the client."""
        auth_method = "none"
        if self.session_id:
            auth_method = "session"
        elif self.jwt_token:
            auth_method = "jwt"
        elif self.api_key:
            auth_method = "api_key"

        return (
            f"<GleitzeitClient("
            f"api_url='{self.api_url}', "
            f"auth='{auth_method}', "
            f"pool_size={self.pool_size}"
            f")>"
        )


# Backward compatibility - export the new modular client as the main client
__all__ = ['GleitzeitClient']