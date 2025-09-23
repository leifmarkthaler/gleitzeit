"""
Gleitzeit Python Client SDK

Client library for interacting with Gleitzeit API.
Supports client sessions for authentication.
"""

import json
import asyncio
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import aiohttp
import uuid

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResponse:
    """Workflow submission response"""
    workflow_id: str
    status: str
    message: str
    submitted_at: str


@dataclass
class TaskResponse:
    """Task status response"""
    task_id: str
    state: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None


class GleitzeitClient:
    """
    Client for Gleitzeit API.

    Supports:
    - Client session authentication
    - JWT token authentication
    - API key authentication
    - Connection pooling
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        session_id: Optional[str] = None,
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
        pool_size: int = 5,
        auto_start_server: bool = False
    ):
        self.api_url = api_url.rstrip('/')
        self.session_id = session_id
        self.api_key = api_key
        self.jwt_token = jwt_token
        self.pool_size = pool_size

        # Connection pool
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None

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
        """Initialize connection pool"""
        if not self._session:
            self._connector = aiohttp.TCPConnector(
                limit=self.pool_size,
                limit_per_host=self.pool_size
            )
            self._session = aiohttp.ClientSession(
                connector=self._connector
            )

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

    # Authentication methods

    async def create_session(self, username: str, password: Optional[str] = None) -> str:
        """Create a new client session"""
        if not self._session:
            await self.connect()

        async with self._session.post(
            f"{self.api_url}/auth/session/create",
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"}
        ) as resp:
            data = await resp.json()
            self.session_id = data["session_id"]
            logger.info(f"Created session for user {username}")
            return self.session_id

    async def destroy_session(self):
        """Destroy current session"""
        if not self.session_id:
            raise ValueError("No active session")

        if not self._session:
            await self.connect()

        async with self._session.post(
            f"{self.api_url}/auth/session/destroy",
            json={"session_id": self.session_id},
            headers=self._get_headers()
        ) as resp:
            data = await resp.json()
            self.session_id = None
            logger.info("Session destroyed")
            return data

    async def create_token(self, username: str, password: Optional[str] = None) -> str:
        """Create JWT token"""
        if not self._session:
            await self.connect()

        async with self._session.post(
            f"{self.api_url}/auth/token",
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"}
        ) as resp:
            data = await resp.json()
            self.jwt_token = data["access_token"]
            logger.info(f"Created token for user {username}")
            return self.jwt_token

    # Workflow operations

    async def submit_workflow(
        self,
        workflow: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> WorkflowResponse:
        """Submit a workflow for execution"""
        if not self._session:
            await self.connect()

        request_data = {
            "workflow": workflow,
            "workflow_id": workflow_id or str(uuid.uuid4())
        }

        async with self._session.post(
            f"{self.api_url}/workflows/submit",
            json=request_data,
            headers=self._get_headers()
        ) as resp:
            data = await resp.json()
            return WorkflowResponse(**data)

    async def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status"""
        if not self._session:
            await self.connect()

        async with self._session.get(
            f"{self.api_url}/workflows/{workflow_id}",
            headers=self._get_headers()
        ) as resp:
            return await resp.json()

    async def get_workflow_tasks(self, workflow_id: str) -> Dict[str, Any]:
        """Get all tasks for a workflow"""
        if not self._session:
            await self.connect()

        async with self._session.get(
            f"{self.api_url}/workflows/{workflow_id}/tasks",
            headers=self._get_headers()
        ) as resp:
            return await resp.json()

    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a workflow"""
        if not self._session:
            await self.connect()

        async with self._session.post(
            f"{self.api_url}/workflows/{workflow_id}/cancel",
            headers=self._get_headers()
        ) as resp:
            return await resp.json()

    # Task operations

    async def get_task(self, task_id: str) -> TaskResponse:
        """Get task status and result"""
        if not self._session:
            await self.connect()

        async with self._session.get(
            f"{self.api_url}/tasks/{task_id}",
            headers=self._get_headers()
        ) as resp:
            data = await resp.json()
            return TaskResponse(**data)

    async def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Retry a failed task"""
        if not self._session:
            await self.connect()

        async with self._session.post(
            f"{self.api_url}/tasks/{task_id}/retry",
            headers=self._get_headers()
        ) as resp:
            return await resp.json()

    # System operations

    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status"""
        if not self._session:
            await self.connect()

        async with self._session.get(
            f"{self.api_url}/system/status",
            headers=self._get_headers()
        ) as resp:
            return await resp.json()

    async def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics"""
        if not self._session:
            await self.connect()

        async with self._session.get(
            f"{self.api_url}/system/metrics",
            headers=self._get_headers()
        ) as resp:
            return await resp.json()

    # Synchronous wrappers for convenience

    def submit_workflow_sync(self, workflow: Dict[str, Any]) -> WorkflowResponse:
        """Synchronous wrapper for submit_workflow"""
        return asyncio.run(self.submit_workflow(workflow))

    def get_task_sync(self, task_id: str) -> TaskResponse:
        """Synchronous wrapper for get_task"""
        return asyncio.run(self.get_task(task_id))

    def wait_for_completion(
        self,
        workflow_id: str,
        timeout: int = 300,
        poll_interval: int = 2
    ) -> Dict[str, Any]:
        """Wait for workflow to complete (synchronous)"""
        start = time.time()

        while time.time() - start < timeout:
            status = asyncio.run(self.get_workflow(workflow_id))

            if status["state"].get("status") in ["completed", "failed", "cancelled"]:
                return status

            time.sleep(poll_interval)

        raise TimeoutError(f"Workflow {workflow_id} did not complete within {timeout} seconds")

    def create_session_sync(self, username: str) -> str:
        """Synchronous wrapper for create_session"""
        return asyncio.run(self.create_session(username))