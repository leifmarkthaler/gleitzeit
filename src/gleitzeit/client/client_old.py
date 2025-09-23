"""
Enhanced Gleitzeit Python Client SDK with authentication and retry logic.

Client library for interacting with Gleitzeit API.
Supports client sessions, JWT tokens, and API key authentication with automatic retry.
"""

import json
import asyncio
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import aiohttp
import uuid
import random

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResponse:
    """Workflow submission response"""
    workflow_id: str
    status: str
    message: str
    submitted_at: str
    submitted_by: Optional[str] = None


@dataclass
class TaskResponse:
    """Task status response"""
    task_id: str
    state: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None


class AuthenticationError(Exception):
    """Authentication failed"""
    pass


class AuthorizationError(Exception):
    """Authorization failed"""
    pass


class GleitzeitClient:
    """
    Enhanced client with proper authentication and error handling.

    Supports:
    - Client session authentication with auto-login
    - JWT token authentication
    - API key authentication
    - Connection pooling
    - Automatic retry with exponential backoff
    - Cookie-based session management
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        session_id: Optional[str] = None,
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
        pool_size: int = 5,
        auto_start_server: bool = False,
        auto_login: bool = True,
        username: Optional[str] = None,
        password: Optional[str] = None,
        retry_config: Optional[Dict[str, Any]] = None
    ):
        self.api_url = api_url.rstrip('/')
        self.session_id = session_id
        self.api_key = api_key
        self.jwt_token = jwt_token
        self.pool_size = pool_size
        self.auto_login = auto_login
        self.username = username or "default_user"
        self.password = password

        # Retry configuration
        self.retry_config = retry_config or {
            "max_retries": 3,
            "initial_delay": 1.0,
            "max_delay": 30.0,
            "exponential_base": 2,
            "jitter": True
        }

        # Connection pool
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None

        # Cookie jar for session management
        self._cookie_jar = aiohttp.CookieJar()

        if auto_start_server:
            self._ensure_server_running()

    def _ensure_server_running(self):
        """Check if server is running and start if needed"""
        import requests
        try:
            response = requests.get(f"{self.api_url}/health/", timeout=2)
            if response.status_code == 200:
                logger.info("API server is running")
            return
        except:
            logger.info("API server not running, attempting to start...")
            # TODO: Implement server startup
            pass

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def connect(self):
        """Initialize connection pool and authenticate if needed"""
        if not self._session:
            self._connector = aiohttp.TCPConnector(
                limit=self.pool_size,
                limit_per_host=self.pool_size,
                ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                cookie_jar=self._cookie_jar,
                timeout=aiohttp.ClientTimeout(total=30)
            )

            # Auto-login if enabled and no credentials provided
            if self.auto_login and not self.session_id and not self.jwt_token:
                try:
                    await self.create_session(self.username, self.password)
                except Exception as e:
                    logger.warning(f"Auto-login failed: {e}")

    async def close(self):
        """Close connection pool"""
        if self._session:
            await self._session.close()
            self._session = None
            self._connector = None

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication"""
        headers = {"Content-Type": "application/json"}

        if self.session_id:
            headers["X-Session-ID"] = self.session_id
        elif self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"

        return headers

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        **kwargs
    ) -> Any:
        """Make HTTP request with retry logic"""
        if not self._session:
            await self.connect()

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
                    # Check for auth errors (don't retry these)
                    if resp.status == 401:
                        # Try to re-authenticate once if auto-login is enabled
                        if self.auto_login and attempt == 0:
                            logger.info("Authentication failed, attempting to re-authenticate...")
                            await self.create_session(self.username, self.password)
                            continue  # Retry with new session
                        raise AuthenticationError("Authentication failed")
                    elif resp.status == 403:
                        raise AuthorizationError("Authorization failed")

                    # Raise for server errors to trigger retry
                    if resp.status >= 500:
                        error_text = await resp.text()
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=error_text
                        )

                    # Check for rate limiting
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After", "60")
                        logger.warning(f"Rate limited, retry after {retry_after} seconds")
                        await asyncio.sleep(int(retry_after))
                        continue

                    # Success or client error (don't retry client errors)
                    if resp.status >= 400:
                        error_text = await resp.text()
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=error_text
                        )

                    # Parse response
                    if resp.content_type == 'application/json':
                        return await resp.json()
                    return await resp.text()

            except (AuthenticationError, AuthorizationError):
                raise  # Don't retry auth errors
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e

                if attempt < self.retry_config["max_retries"] - 1:
                    # Calculate delay with exponential backoff
                    delay = min(
                        self.retry_config["initial_delay"] * (
                            self.retry_config["exponential_base"] ** attempt
                        ),
                        self.retry_config["max_delay"]
                    )

                    # Add jitter if enabled
                    if self.retry_config["jitter"]:
                        delay *= (0.5 + random.random())

                    logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {delay:.2f}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Request failed after {self.retry_config['max_retries']} attempts")
                    raise

        raise last_exception

    # Authentication methods

    async def create_session(self, username: str, password: Optional[str] = None) -> str:
        """Create a new client session"""
        if not self._session:
            await self.connect()

        data = await self._request_with_retry(
            "POST",
            "/auth/session/create",
            json_data={"username": username, "password": password}
        )

        self.session_id = data["session_id"]
        self.username = username
        logger.info(f"Created session for user {username}")
        return self.session_id

    async def destroy_session(self):
        """Destroy current session"""
        if not self.session_id:
            raise ValueError("No active session")

        data = await self._request_with_retry(
            "POST",
            "/auth/session/destroy",
            json_data={"session_id": self.session_id}
        )

        self.session_id = None
        logger.info("Session destroyed")
        return data

    async def create_token(self, username: str, password: Optional[str] = None) -> str:
        """Create JWT token"""
        data = await self._request_with_retry(
            "POST",
            "/auth/token",
            json_data={"username": username, "password": password}
        )

        self.jwt_token = data["access_token"]
        logger.info(f"Created token for user {username}")
        return self.jwt_token

    # Workflow operations with proper error handling

    async def submit_workflow(
        self,
        workflow: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> WorkflowResponse:
        """Submit a workflow for execution with authentication and retry"""
        request_data = {
            "workflow": workflow,
            "workflow_id": workflow_id or str(uuid.uuid4())
        }

        try:
            data = await self._request_with_retry(
                "POST",
                "/workflows/submit",
                json_data=request_data
            )

            return WorkflowResponse(**data)

        except Exception as e:
            logger.error(f"Failed to submit workflow: {e}")
            raise

    async def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status with authentication and retry"""
        return await self._request_with_retry(
            "GET",
            f"/workflows/{workflow_id}"
        )

    async def get_workflow_tasks(self, workflow_id: str) -> Dict[str, Any]:
        """Get all tasks for a workflow with authentication and retry"""
        return await self._request_with_retry(
            "GET",
            f"/workflows/{workflow_id}/tasks"
        )

    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a workflow with authentication and retry"""
        return await self._request_with_retry(
            "POST",
            f"/workflows/{workflow_id}/cancel"
        )

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """Cancel a task with authentication and retry"""
        return await self._request_with_retry(
            "POST",
            f"/tasks/{task_id}/cancel"
        )

    # Task operations

    async def get_task(self, task_id: str) -> TaskResponse:
        """Get task status and result with authentication and retry"""
        data = await self._request_with_retry(
            "GET",
            f"/tasks/{task_id}"
        )

        # Extract state and result from response
        state = data.get("state", {})
        result = data.get("result")

        return TaskResponse(
            task_id=task_id,
            state=state,
            result=result
        )

    async def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Retry a failed task with authentication and retry"""
        return await self._request_with_retry(
            "POST",
            f"/tasks/{task_id}/retry"
        )

    # System operations

    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status with authentication and retry"""
        return await self._request_with_retry(
            "GET",
            "/system/status"
        )

    async def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics with authentication and retry"""
        return await self._request_with_retry(
            "GET",
            "/system/metrics"
        )

    # Synchronous wrappers for convenience

    def submit_workflow_sync(self, workflow: Dict[str, Any]) -> WorkflowResponse:
        """Synchronous wrapper for submit_workflow"""
        return asyncio.run(self.submit_workflow(workflow))

    def get_task_sync(self, task_id: str) -> TaskResponse:
        """Synchronous wrapper for get_task"""
        return asyncio.run(self.get_task(task_id))

    def create_session_sync(self, username: str, password: Optional[str] = None) -> str:
        """Synchronous wrapper for create_session"""
        return asyncio.run(self.create_session(username, password))

    def wait_for_completion(
        self,
        workflow_id: str,
        timeout: int = 300,
        poll_interval: int = 2
    ) -> Dict[str, Any]:
        """Wait for workflow to complete (synchronous)"""
        start = time.time()

        while time.time() - start < timeout:
            try:
                status = asyncio.run(self.get_workflow(workflow_id))

                if status["state"].get("status") in ["completed", "failed", "cancelled"]:
                    return status

                time.sleep(poll_interval)
            except Exception as e:
                logger.warning(f"Error checking workflow status: {e}")
                time.sleep(poll_interval)

        raise TimeoutError(f"Workflow {workflow_id} did not complete within {timeout} seconds")

    # Batch operations

    async def submit_workflows_batch(
        self,
        workflows: List[Dict[str, Any]],
        concurrency: int = 5
    ) -> List[WorkflowResponse]:
        """Submit multiple workflows concurrently with rate limiting"""
        results = []
        semaphore = asyncio.Semaphore(concurrency)

        async def submit_with_semaphore(workflow):
            async with semaphore:
                try:
                    return await self.submit_workflow(workflow)
                except Exception as e:
                    logger.error(f"Failed to submit workflow: {e}")
                    return None

        tasks = [submit_with_semaphore(w) for w in workflows]
        results = await asyncio.gather(*tasks)

        # Filter out None results from failures
        return [r for r in results if r is not None]

    async def cancel_workflows_batch(
        self,
        workflow_ids: List[str],
        concurrency: int = 5
    ) -> List[Dict[str, Any]]:
        """Cancel multiple workflows concurrently"""
        results = []
        semaphore = asyncio.Semaphore(concurrency)

        async def cancel_with_semaphore(workflow_id):
            async with semaphore:
                try:
                    return await self.cancel_workflow(workflow_id)
                except Exception as e:
                    logger.error(f"Failed to cancel workflow {workflow_id}: {e}")
                    return {"workflow_id": workflow_id, "error": str(e)}

        tasks = [cancel_with_semaphore(wid) for wid in workflow_ids]
        results = await asyncio.gather(*tasks)

        return results