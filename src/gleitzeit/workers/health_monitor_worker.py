"""
Health Monitor Worker - Runs health checks for coordination mechanisms.

This worker periodically checks the health of:
- Leader election mechanisms
- Service registry
- Redis stream consumers
- Sharding configuration

Results are stored in Redis and exposed via the /health/coordination API endpoint.
"""

import asyncio
import argparse
import logging
import signal
import sys

import redis.asyncio as aioredis

from gleitzeit.core.health_checks import HealthCheckRunner
from gleitzeit.core.logging_mixin import LoggingMixin

logger = logging.getLogger(__name__)


class HealthMonitorWorker(LoggingMixin):
    """Worker that monitors coordination mechanism health"""

    def __init__(self, redis_url: str, check_interval: int = 30):
        super().__init__(logger)
        self.redis_url = redis_url
        self.check_interval = check_interval
        self.redis = None
        self.runner = None
        self.running = False

    async def initialize(self):
        """Initialize Redis connection and health check runner"""
        self.redis = await aioredis.from_url(self.redis_url, decode_responses=False)
        self.runner = HealthCheckRunner(
            redis=self.redis,
            check_interval=self.check_interval
        )
        logger.info(f"Health monitor initialized (interval={self.check_interval}s)")

    async def start(self):
        """Start the health monitor"""
        self.running = True
        logger.info("Starting health monitor worker")

        try:
            await self.initialize()
            await self.runner.run_forever()
        except asyncio.CancelledError:
            logger.info("Health monitor worker cancelled")
        except Exception as e:
            logger.error(f"Health monitor worker error: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup resources"""
        self.running = False
        if self.runner:
            await self.runner.stop()
        if self.redis:
            await self.redis.close()
        logger.info("Health monitor worker stopped")

    async def stop(self):
        """Stop the health monitor"""
        logger.info("Stopping health monitor worker")
        self.running = False
        if self.runner:
            await self.runner.stop()


async def main():
    """Main entry point for health monitor worker"""
    parser = argparse.ArgumentParser(description="Gleitzeit Health Monitor Worker")
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379",
        help="Redis URL (default: redis://localhost:6379)"
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=30,
        help="Health check interval in seconds (default: 30)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create worker
    worker = HealthMonitorWorker(
        redis_url=args.redis_url,
        check_interval=args.check_interval
    )

    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(worker.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run worker
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Health monitor interrupted by user")
    except Exception as e:
        logger.error(f"Health monitor failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
