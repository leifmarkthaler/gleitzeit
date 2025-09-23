"""
Base client class with core functionality.

Provides the foundation for all client operations including connection management,
request handling, and configuration.
"""

import logging
import asyncio
import random
from typing import Dict, Any, Optional
import aiohttp

logger = logging.getLogger(__name__)


class BaseClient:
    """
    Base client with core HTTP functionality and connection management.

    This class provides:
    - Connection pooling
    - Cookie management
    - Request/response handling
    - Configuration management
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        pool_size: int = 5,
        timeout: int = 30,
        retry_config: Optional[Dict[str, Any]] = None,
        **kwargs  # Accept and ignore additional kwargs from mixins
    ):
        """Initialize base client with configuration."""
        self.api_url = api_url.rstrip('/')
        self.pool_size = pool_size
        self.timeout = timeout

        # Retry configuration
        self.retry_config = retry_config or {
            "max_retries": 3,
            "initial_delay": 1.0,
            "max_delay": 30.0,
            "exponential_base": 2,
            "jitter": True
        }

        # Connection management
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None
        self._cookie_jar = aiohttp.CookieJar()

        # Authentication state (set by AuthMixin)
        # Preserve existing values set by mixins (e.g., AuthMixin) when present
        self.session_id: Optional[str] = getattr(self, "session_id", None)
        self.jwt_token: Optional[str] = getattr(self, "jwt_token", None)
        self.api_key: Optional[str] = getattr(self, "api_key", None)
        self.username: Optional[str] = getattr(self, "username", None)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def connect(self):
        """Initialize connection pool."""
        if not self._session:
            self._connector = aiohttp.TCPConnector(
                limit=self.pool_size,
                limit_per_host=self.pool_size,
                ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                cookie_jar=self._cookie_jar,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
            logger.info(f"Connected to {self.api_url}")

    async def close(self):
        """Close connection pool."""
        if self._session:
            await self._session.close()
            self._session = None
            self._connector = None
            logger.info("Connection closed")

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {"Content-Type": "application/json"}

        if self.session_id:
            headers["X-Session-ID"] = self.session_id
        elif self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"

        return headers

    async def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        delay = min(
            self.retry_config["initial_delay"] * (
                self.retry_config["exponential_base"] ** attempt
            ),
            self.retry_config["max_delay"]
        )

        # Add jitter if enabled
        if self.retry_config.get("jitter", True):
            delay *= (0.5 + random.random())

        return delay

    async def ensure_connected(self):
        """Ensure client is connected."""
        if not self._session:
            await self.connect()
