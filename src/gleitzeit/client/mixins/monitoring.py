"""
Monitoring and health check mixin for Gleitzeit client.

Provides methods for system monitoring, health checks, and metrics retrieval.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SystemHealth:
    """System health status."""
    status: str
    api_version: str
    uptime: float
    redis_connected: bool
    worker_count: int
    active_workflows: int
    active_tasks: int


@dataclass
class WorkerStatus:
    """Worker status information."""
    worker_id: str
    worker_type: str
    status: str
    last_heartbeat: str
    tasks_processed: int
    current_task: Optional[str] = None


class MonitoringMixin:
    """
    Monitoring and health check mixin.

    Provides methods for:
    - System health checks
    - Worker monitoring
    - Performance metrics
    - Resource utilization
    - Audit log access
    """

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform basic health check.

        Returns:
            Health status
        """
        return await self._request("GET", "/health")

    async def get_system_health(self) -> SystemHealth:
        """
        Get detailed system health status.

        Returns:
            SystemHealth object
        """
        response = await self._request("GET", "/health/detailed")
        return SystemHealth(
            status=response["status"],
            api_version=response.get("version", "unknown"),
            uptime=response.get("uptime", 0),
            redis_connected=response.get("redis_connected", False),
            worker_count=response.get("worker_count", 0),
            active_workflows=response.get("active_workflows", 0),
            active_tasks=response.get("active_tasks", 0)
        )

    async def get_workers_status(self) -> List[WorkerStatus]:
        """
        Get status of all workers.

        Returns:
            List of WorkerStatus objects
        """
        response = await self._request("GET", "/system/workers")
        workers = []

        for worker in response.get("workers", []):
            workers.append(WorkerStatus(
                worker_id=worker["worker_id"],
                worker_type=worker["worker_type"],
                status=worker["status"],
                last_heartbeat=worker.get("last_heartbeat", ""),
                tasks_processed=worker.get("tasks_processed", 0),
                current_task=worker.get("current_task")
            ))

        return workers

    async def get_system_metrics(self) -> Dict[str, Any]:
        """
        Get system performance metrics.

        Returns:
            Dictionary of metrics
        """
        return await self._request("GET", "/system/metrics")

    async def get_workflow_metrics(self, time_range: str = "1h") -> Dict[str, Any]:
        """
        Get workflow execution metrics.

        Args:
            time_range: Time range (e.g., "1h", "24h", "7d")

        Returns:
            Workflow metrics
        """
        return await self._request(
            "GET",
            "/system/metrics/workflows",
            params={"time_range": time_range}
        )

    async def get_task_metrics(self, time_range: str = "1h") -> Dict[str, Any]:
        """
        Get task execution metrics.

        Args:
            time_range: Time range

        Returns:
            Task metrics
        """
        return await self._request(
            "GET",
            "/system/metrics/tasks",
            params={"time_range": time_range}
        )

    async def get_redis_info(self) -> Dict[str, Any]:
        """
        Get Redis server information.

        Returns:
            Redis info
        """
        return await self._request("GET", "/system/redis/info")

    async def get_queue_depths(self) -> Dict[str, int]:
        """
        Get depths of all queues.

        Returns:
            Dictionary of queue names to depths
        """
        response = await self._request("GET", "/system/queues")
        return response.get("queues", {})

    async def get_audit_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        user: Optional[str] = None,
        action: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get audit logs.

        Args:
            limit: Maximum number of logs
            offset: Offset for pagination
            user: Filter by user
            action: Filter by action

        Returns:
            List of audit log entries
        """
        params = {"limit": limit, "offset": offset}
        if user:
            params["user"] = user
        if action:
            params["action"] = action

        response = await self._request(
            "GET",
            "/system/audit/logs",
            params=params
        )
        return response.get("logs", [])

    async def get_error_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        level: str = "ERROR"
    ) -> List[Dict[str, Any]]:
        """
        Get error logs.

        Args:
            limit: Maximum number of logs
            offset: Offset for pagination
            level: Minimum log level

        Returns:
            List of error log entries
        """
        params = {"limit": limit, "offset": offset, "level": level}
        response = await self._request(
            "GET",
            "/system/logs/errors",
            params=params
        )
        return response.get("logs", [])

    async def get_resource_usage(self) -> Dict[str, Any]:
        """
        Get current resource usage.

        Returns:
            Resource usage information
        """
        return await self._request("GET", "/system/resources")

    async def check_api_version(self) -> str:
        """
        Get API version.

        Returns:
            API version string
        """
        response = await self._request("GET", "/")
        return response.get("version", "unknown")

    async def get_configuration(self) -> Dict[str, Any]:
        """
        Get current system configuration.

        Returns:
            Configuration dictionary
        """
        return await self._request("GET", "/system/config")

    async def trigger_health_check_all_workers(self) -> Dict[str, bool]:
        """
        Trigger health check on all workers.

        Returns:
            Dictionary of worker_id to health status
        """
        response = await self._request("POST", "/system/workers/health-check")
        return response.get("results", {})

    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """
        Get list of active user sessions.

        Returns:
            List of active sessions
        """
        response = await self._request("GET", "/system/sessions")
        return response.get("sessions", [])

    async def get_rate_limit_status(self) -> Dict[str, Any]:
        """
        Get current rate limit status for authenticated user.

        Returns:
            Rate limit information
        """
        response = await self._request("GET", "/auth/rate-limit")
        return {
            "limit": response.get("limit", 0),
            "remaining": response.get("remaining", 0),
            "reset_at": response.get("reset_at", ""),
            "window": response.get("window", 60)
        }