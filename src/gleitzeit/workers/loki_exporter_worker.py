"""
Loki Exporter Worker

Reads logs from Redis and exports them to Grafana Loki for long-term storage.
This creates a hybrid logging architecture:
- Redis: Fast, in-memory, short-term (24-48 hours)
- Loki: Persistent, compressed, long-term storage

Architecture:
1. Polls Redis for new logs every few seconds
2. Batches logs and pushes to Loki
3. Tracks last processed timestamp to avoid duplicates
4. Handles backpressure and retries
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import aiohttp
import redis.asyncio as aioredis

from ..core.config_manager import ConfigurationManager
from ..core.logging_mixin import LoggingMixin

logger = logging.getLogger(__name__)


class LokiExporterWorker:
    """
    Worker that exports logs from Redis to Loki.

    Runs continuously, polling Redis for new logs and pushing them to Loki
    in batches for efficient storage and retrieval.
    """

    def __init__(
        self,
        redis_url: str,
        loki_url: str = "http://localhost:3100",
        batch_size: int = 100,
        poll_interval: int = 5,
        worker_id: str = "loki-exporter"
    ):
        self.redis_url = redis_url
        self.loki_url = loki_url.rstrip('/')
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.worker_id = worker_id
        self.redis: Optional[aioredis.Redis] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_exported_timestamp: Dict[str, int] = {}  # Track per level
        self.running = False

        # Set up logging with standard Python logger
        self.logger = logging.getLogger(f"LokiExporter.{worker_id}")

    async def initialize(self):
        """Initialize Redis and HTTP connections"""
        self.redis = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        self.session = aiohttp.ClientSession()
        self.logger.info(f"Loki exporter worker initialized (loki_url={self.loki_url}, batch_size={self.batch_size}, poll_interval={self.poll_interval})")

    async def shutdown(self):
        """Clean shutdown"""
        self.running = False
        if self.session:
            await self.session.close()
        if self.redis:
            await self.redis.close()
        self.logger.info("Loki exporter worker shutdown complete")

    async def export_logs_to_loki(self, logs: List[Dict[str, Any]]) -> bool:
        """
        Export a batch of logs to Loki using the Push API.

        Loki expects logs in this format:
        {
          "streams": [
            {
              "stream": {"label1": "value1", "label2": "value2"},
              "values": [
                ["<unix_timestamp_ns>", "<log_line>"]
              ]
            }
          ]
        }
        """
        if not logs:
            return True

        # Group logs by label set (level, component, workflow_id)
        streams: Dict[str, Dict[str, Any]] = {}

        for log in logs:
            # Create label set for this log
            labels = {
                "level": log.get("level", "INFO").lower(),
                "component": log.get("component", "unknown"),
                "job": "gleitzeit",
            }

            # Add optional labels if present
            if log.get("workflow_id"):
                labels["workflow_id"] = log["workflow_id"]
            if log.get("task_id"):
                labels["task_id"] = log["task_id"]
            if log.get("operation"):
                labels["operation"] = log["operation"]

            # Create label string as key
            label_key = json.dumps(labels, sort_keys=True)

            # Initialize stream if needed
            if label_key not in streams:
                streams[label_key] = {
                    "stream": labels,
                    "values": []
                }

            # Convert timestamp to nanoseconds (Loki requirement)
            timestamp_ms = log.get("timestamp", int(time.time() * 1000))
            timestamp_ns = str(timestamp_ms * 1_000_000)  # ms to ns

            # Create log line with full context
            log_line = json.dumps({
                "message": log.get("message", ""),
                "log_id": log.get("log_id", ""),
                "metadata": log.get("metadata", {}),
                "error_type": log.get("error_type"),
                "stack_trace": log.get("stack_trace")
            })

            streams[label_key]["values"].append([timestamp_ns, log_line])

        # Prepare Loki payload
        payload = {
            "streams": list(streams.values())
        }

        # Push to Loki
        try:
            async with self.session.post(
                f"{self.loki_url}/loki/api/v1/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 204:
                    self.logger.debug(f"Successfully exported {len(logs)} logs to Loki")
                    return True
                else:
                    error_text = await resp.text()
                    self.logger.warning(f"Loki returned status {resp.status}: {error_text}")
                    return False
        except Exception as e:
            self.logger.error(f"Failed to export logs to Loki: {e}", exc_info=True)
            return False

    async def fetch_logs_from_redis(
        self,
        level: str,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Fetch logs from Redis that haven't been exported yet"""
        from ..core.stateless_log_service import StatelessLogService

        # Get last timestamp for this level
        min_timestamp = self.last_exported_timestamp.get(level, 0)

        # Query logs newer than last export
        logs = await StatelessLogService.query_logs(
            redis=self.redis,
            level=level,
            limit=limit,
            start_time=min_timestamp + 1  # +1 to avoid duplicates
        )

        return logs

    async def export_level(self, level: str):
        """Export all new logs for a specific level"""
        try:
            # Fetch new logs
            logs = await self.fetch_logs_from_redis(level, self.batch_size)

            if not logs:
                return

            # Export to Loki
            success = await self.export_logs_to_loki(logs)

            if success:
                # Update last exported timestamp
                max_timestamp = max(log.get("timestamp", 0) for log in logs)
                self.last_exported_timestamp[level] = max_timestamp

                self.logger.debug(f"Exported {len(logs)} {level} logs (up to {max_timestamp})")

        except Exception as e:
            self.logger.error(f"Error exporting {level} logs: {e}", exc_info=True)

    async def run(self):
        """Main worker loop"""
        await self.initialize()
        self.running = True

        self.logger.info(f"Loki exporter worker started (worker_id={self.worker_id})")

        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]

        while self.running:
            try:
                # Export each level
                for level in levels:
                    await self.export_level(level)

                # Wait before next poll
                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                self.logger.info("Loki exporter received cancellation signal")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in Loki exporter loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

        await self.shutdown()


async def main():
    """Entry point for running the Loki exporter as a standalone worker"""
    import argparse

    parser = argparse.ArgumentParser(description="Gleitzeit Loki Exporter Worker")
    parser.add_argument("--redis-url", default="redis://localhost:6379", help="Redis URL")
    parser.add_argument("--loki-url", default="http://localhost:3100", help="Loki URL")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for export")
    parser.add_argument("--poll-interval", type=int, default=5, help="Polling interval in seconds")
    parser.add_argument("--worker-id", default="loki-exporter", help="Worker ID")

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create and run worker
    worker = LokiExporterWorker(
        redis_url=args.redis_url,
        loki_url=args.loki_url,
        batch_size=args.batch_size,
        poll_interval=args.poll_interval,
        worker_id=args.worker_id
    )

    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
        await worker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
