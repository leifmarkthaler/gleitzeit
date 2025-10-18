"""
API Worker - Runs the Gleitzeit API as a self-registering worker

This treats the API service as a worker, using the proven self-registration
pattern instead of external process management.
"""

import asyncio
import logging
import signal
import os
from datetime import datetime
from typing import Optional
import uvicorn

from .base import BaseWorker, WorkerConfig

logger = logging.getLogger(__name__)


class APIWorker(BaseWorker):
    """
    API service as a worker - self-registers and manages heartbeat.

    Unlike traditional workers that process Redis streams, this worker
    runs the Uvicorn API server and uses the same self-registration
    pattern for service discovery.
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.host = config.extra.get("host", "0.0.0.0")
        self.port = config.extra.get("port", 8000)
        self.dev_mode = config.extra.get("dev_mode", False)
        self.server: Optional[uvicorn.Server] = None
        self.start_time = datetime.utcnow()

    async def on_initialize(self):
        """Initialize API application"""
        # Check if port is already in use
        if self._is_port_in_use(self.port, self.host):
            error_msg = f"Cannot start API: Port {self.port} is already in use. "
            error_msg += f"Either stop the existing service or use --api-port to specify a different port."
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Import here to avoid circular dependencies
        from ..api.main import app

        # Create Uvicorn config
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            loop="asyncio",
            log_config=None,
            access_log=False,
            reload=self.dev_mode
        )

        self.server = uvicorn.Server(config)
        self.logger.info(f"API worker initialized on {self.host}:{self.port}")

    def _is_port_in_use(self, port: int, host: str = '0.0.0.0') -> bool:
        """Check if a port is already in use"""
        import socket as sock_module
        try:
            with sock_module.socket(sock_module.AF_INET, sock_module.SOCK_STREAM) as s:
                s.setsockopt(sock_module.SOL_SOCKET, sock_module.SO_REUSEADDR, 1)
                s.bind((host, port))
                return False
        except OSError:
            return True

    def get_base_streams(self):
        """API worker doesn't consume streams"""
        return []

    async def _register_worker(self):
        """
        Register API worker in Redis - includes port info.

        This uses os.getpid() to always get current PID, making it
        stateless and suitable for distributed systems.
        """
        worker_info = {
            "worker_type": "api",
            "worker_id": self.config.worker_id,
            "status": "running",
            "pid": os.getpid(),  # ✅ ALWAYS CURRENT
            "host": self.host,
            "port": str(self.port),
            "started_at": self.start_time.isoformat(),
        }

        # Use worker registry pattern (consistent with other workers)
        key = f"{{shard:0}}:worker:registry:api:{self.config.worker_id}"
        await self.redis.hset(key.encode(), mapping={
            k.encode(): str(v).encode() for k, v in worker_info.items()
        })
        await self.redis.expire(key.encode(), 60)

    async def run(self):
        """
        Main API server loop.

        Overrides BaseWorker.run() since API doesn't process streams,
        but still maintains heartbeat and shutdown handling.
        """
        self._running = True

        # Setup graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._handle_shutdown)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            # Start API server (this blocks until shutdown)
            self.logger.info(f"Starting API server on {self.host}:{self.port}")
            await self.server.serve()

        except Exception as e:
            self.logger.error(f"API server error: {e}", exc_info=True)

        finally:
            self._running = False
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            await self._cleanup()

    async def _cleanup(self):
        """
        Graceful shutdown - unregister from Redis immediately.

        This ensures service disappears from discovery immediately
        instead of waiting for TTL expiration.
        """
        self.logger.info("API worker shutting down...")

        # Unregister immediately (don't wait for TTL)
        try:
            key = f"{{shard:0}}:worker:registry:api:{self.config.worker_id}"
            await self.redis.delete(key.encode())
            self.logger.info("API worker unregistered from service discovery")
        except Exception as e:
            self.logger.error(f"Failed to unregister API worker: {e}")

        # Close Redis connection
        if self.redis:
            try:
                await self.redis.close()
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")

    async def process_message(self, stream: str, msg_id: str, data: dict) -> bool:
        """
        API worker doesn't process messages from streams.

        This method is required by BaseWorker but never called for API worker.
        """
        raise NotImplementedError("API worker does not process stream messages")
