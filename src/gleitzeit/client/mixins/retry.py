"""
Retry and error handling mixin for Gleitzeit client.

Provides retry logic with exponential backoff, error classification,
and rate limit handling.
"""

import logging
import asyncio
from typing import Any, Optional, Dict

import aiohttp

logger = logging.getLogger(__name__)


class RetryMixin:
    """
    Retry and error handling mixin.

    Provides:
    - Exponential backoff with jitter
    - Rate limit handling
    - Error classification
    - Circuit breaker pattern (future)
    """

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        **kwargs
    ) -> Any:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method
            endpoint: API endpoint
            json_data: JSON payload
            **kwargs: Additional request parameters

        Returns:
            Response data

        Raises:
            AuthenticationError: On 401 responses
            AuthorizationError: On 403 responses
            aiohttp.ClientResponseError: On other HTTP errors
        """
        await self.ensure_connected()

        url = f"{self.api_url}{endpoint}"
        last_exception = None

        for attempt in range(self.retry_config["max_retries"]):
            try:
                async with self._session.request(
                    method,
                    url,
                    json=json_data,
                    headers=self._get_headers(),
                    **kwargs
                ) as resp:
                    # Handle authentication errors
                    if resp.status == 401:
                        # Try to re-authenticate once if we have AuthMixin
                        if hasattr(self, 'handle_auth_error') and attempt == 0:
                            if await self.handle_auth_error(401):
                                continue  # Retry with new credentials

                        from .auth import AuthenticationError
                        raise AuthenticationError("Authentication failed")

                    elif resp.status == 403:
                        from .auth import AuthorizationError
                        raise AuthorizationError("Authorization failed")

                    # Handle rate limiting
                    elif resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", "60"))
                        logger.warning(f"Rate limited, retry after {retry_after} seconds")
                        await asyncio.sleep(retry_after)
                        continue

                    # Retry on server errors
                    elif resp.status >= 500:
                        error_text = await resp.text()
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=f"Server error: {error_text}"
                        )

                    # Don't retry client errors (except rate limits)
                    elif resp.status >= 400:
                        error_text = await resp.text()
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=f"Client error: {error_text}"
                        )

                    # Success - parse response
                    if resp.content_type == 'application/json':
                        return await resp.json()
                    return await resp.text()

            except Exception as e:
                # Check if it's an auth error (don't retry these)
                if e.__class__.__name__ in ['AuthenticationError', 'AuthorizationError']:
                    raise  # Don't retry auth errors

                # Handle client/timeout errors with retry
                if not isinstance(e, (aiohttp.ClientError, asyncio.TimeoutError)):
                    raise  # Don't retry unexpected errors
                last_exception = e

                if attempt < self.retry_config["max_retries"] - 1:
                    delay = await self._calculate_retry_delay(attempt)
                    logger.warning(
                        f"Request to {endpoint} failed (attempt {attempt + 1}/{self.retry_config['max_retries']}), "
                        f"retrying in {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Request to {endpoint} failed after {self.retry_config['max_retries']} attempts"
                    )
                    raise

        if last_exception:
            raise last_exception

    async def _request_with_timeout(
        self,
        method: str,
        endpoint: str,
        timeout: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        Make request with custom timeout.

        Args:
            method: HTTP method
            endpoint: API endpoint
            timeout: Custom timeout in seconds
            **kwargs: Additional parameters

        Returns:
            Response data
        """
        if timeout:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            kwargs['timeout'] = timeout_obj

        return await self._request(method, endpoint, **kwargs)