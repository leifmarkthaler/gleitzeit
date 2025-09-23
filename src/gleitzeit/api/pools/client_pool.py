"""
Client connection pooling for API
"""

import asyncio
import time
import uuid
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)


class ClientConnection:
    """Individual client connection"""

    def __init__(self, user_id: str, connection_id: str):
        self.user_id = user_id
        self.connection_id = connection_id
        self.created_at = time.time()
        self.last_used = time.time()
        self.request_count = 0
        self.is_healthy = True

    def touch(self):
        """Update last used time"""
        self.last_used = time.time()
        self.request_count += 1


class UserPool:
    """Per-user connection pool"""

    def __init__(self, user_id: str, max_connections: int = 10):
        self.user_id = user_id
        self.max_connections = max_connections
        self.connections: List[ClientConnection] = []
        self.available: asyncio.Queue = asyncio.Queue()
        self.lock = asyncio.Lock()

    async def acquire(self) -> ClientConnection:
        """Acquire a connection from the pool"""
        # Try to get available connection
        try:
            conn = await asyncio.wait_for(self.available.get(), timeout=0.1)
            if conn.is_healthy:
                conn.touch()
                return conn
        except asyncio.TimeoutError:
            pass

        # Create new connection if under limit
        async with self.lock:
            if len(self.connections) < self.max_connections:
                conn = ClientConnection(
                    user_id=self.user_id,
                    connection_id=str(uuid.uuid4())[:8]
                )
                self.connections.append(conn)
                logger.debug(f"Created new connection {conn.connection_id} for user {self.user_id}")
                return conn

        # Wait for connection to become available
        conn = await self.available.get()
        conn.touch()
        return conn

    async def release(self, conn: ClientConnection):
        """Return connection to pool"""
        await self.available.put(conn)

    async def is_idle(self, idle_timeout: int = 300) -> bool:
        """Check if pool is idle"""
        now = time.time()
        for conn in self.connections:
            if now - conn.last_used < idle_timeout:
                return False
        return True

    async def shutdown(self):
        """Clean up pool"""
        self.connections.clear()
        # Clear queue
        while not self.available.empty():
            try:
                self.available.get_nowait()
            except asyncio.QueueEmpty:
                break


class ClientPool:
    """Main client connection pool manager"""

    def __init__(self, max_clients_per_user: int = 10):
        self.max_clients_per_user = max_clients_per_user
        self.pools: Dict[str, UserPool] = {}
        self.lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Initialize the pool manager"""
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_idle_pools())
        logger.info(f"Client pool initialized with max {self.max_clients_per_user} connections per user")

    async def get_pool(self, user_id: str) -> UserPool:
        """Get or create pool for user"""
        if user_id not in self.pools:
            async with self.lock:
                if user_id not in self.pools:
                    self.pools[user_id] = UserPool(
                        user_id=user_id,
                        max_connections=self.max_clients_per_user
                    )
                    logger.debug(f"Created pool for user {user_id}")

        return self.pools[user_id]

    @asynccontextmanager
    async def acquire_connection(self, user_id: str):
        """Context manager for acquiring connection"""
        pool = await self.get_pool(user_id)
        conn = await pool.acquire()
        try:
            yield conn
        finally:
            await pool.release(conn)

    async def _cleanup_idle_pools(self):
        """Periodically clean up idle pools"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                idle_users = []
                for user_id, pool in self.pools.items():
                    if await pool.is_idle(idle_timeout=300):  # 5 minutes
                        idle_users.append(user_id)

                for user_id in idle_users:
                    async with self.lock:
                        pool = self.pools.pop(user_id)
                        await pool.shutdown()
                        logger.info(f"Cleaned up idle pool for user {user_id}")

            except Exception as e:
                logger.error(f"Error in pool cleanup: {e}")

    async def shutdown(self):
        """Shutdown pool manager"""
        if self._cleanup_task:
            self._cleanup_task.cancel()

        for pool in self.pools.values():
            await pool.shutdown()

        self.pools.clear()
        logger.info("Client pool shut down")

    def get_stats(self) -> Dict:
        """Get pool statistics"""
        stats = {
            "total_users": len(self.pools),
            "total_connections": sum(len(p.connections) for p in self.pools.values()),
            "users": {}
        }

        for user_id, pool in self.pools.items():
            stats["users"][user_id] = {
                "connections": len(pool.connections),
                "max_connections": pool.max_connections
            }

        return stats