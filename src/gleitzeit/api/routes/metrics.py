"""
Prometheus Metrics Endpoint for Grafana Integration

Exports log statistics and system metrics in Prometheus format.
"""

import logging
from fastapi import APIRouter, Depends
import redis.asyncio as aioredis

from ..dependencies import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/metrics")
async def metrics(redis: aioredis.Redis = Depends(get_redis)):
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format for scraping.
    Grafana can use this to create dashboards and alerts.
    """
    from gleitzeit.core.stateless_log_service import StatelessLogService

    try:
        # Get log counts by level
        stats = {}
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            count = await StatelessLogService.get_log_count(
                redis=redis,
                level=level
            )
            stats[level.lower()] = count

        # Build Prometheus format output
        lines = []

        # Add HELP and TYPE comments
        lines.append("# HELP gleitzeit_logs_total Total number of logs by level")
        lines.append("# TYPE gleitzeit_logs_total gauge")

        # Add metrics
        for level, count in stats.items():
            lines.append(f'gleitzeit_logs_total{{level="{level}"}} {count}')

        # Add total
        total = sum(stats.values())
        lines.append("# HELP gleitzeit_logs_total_all Total number of all logs")
        lines.append("# TYPE gleitzeit_logs_total_all gauge")
        lines.append(f"gleitzeit_logs_total_all {total}")

        # TODO: Add more metrics:
        # - gleitzeit_workflows_total
        # - gleitzeit_workflows_running
        # - gleitzeit_workflows_completed
        # - gleitzeit_workflows_failed
        # - gleitzeit_tasks_total
        # - gleitzeit_tasks_pending
        # - gleitzeit_tasks_running
        # - gleitzeit_tasks_completed
        # - gleitzeit_tasks_failed
        # - gleitzeit_redis_memory_usage
        # - gleitzeit_worker_count

        return "\n".join(lines) + "\n"

    except Exception as e:
        logger.error(f"Error generating metrics: {e}", exc_info=True)
        # Return empty metrics on error (Prometheus prefers this to HTTP errors)
        return "# Error generating metrics\n"
