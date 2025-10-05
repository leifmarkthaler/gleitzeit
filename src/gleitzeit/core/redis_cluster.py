"""
Redis Cluster support for Gleitzeit 0.0.7

All Redis operations use cluster-compatible key formats with hash tags
to ensure workflow locality.
"""

import os
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
import redis.asyncio as aioredis
from redis.asyncio.cluster import RedisCluster
from redis.cluster import ClusterNode

logger = logging.getLogger(__name__)


@dataclass
class RedisConfig:
    """Redis Cluster configuration"""
    cluster_nodes: List[Dict[str, Any]]
    max_connections_per_node: int = 50
    socket_keepalive: bool = True
    decode_responses: bool = False
    skip_full_coverage_check: bool = False
    socket_connect_timeout: int = 5
    socket_timeout: int = 5
    retry_on_timeout: bool = True
    health_check_interval: int = 30

    @classmethod
    def from_env(cls) -> 'RedisConfig':
        """Create config from environment variables or ConfigurationManager"""
        # First try environment variables (NO FALLBACK)
        nodes_str = os.getenv("REDIS_CLUSTER_NODES")
        if not nodes_str:
            # Try REDIS_URL format from environment
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                # Parse redis://host:port/db format
                import urllib.parse
                parsed = urllib.parse.urlparse(redis_url)
                if parsed.hostname and parsed.port:
                    nodes_str = f"{parsed.hostname}:{parsed.port}"

        # If still no config from environment, use ConfigurationManager
        if not nodes_str:
            from ..core.config_manager import ConfigurationManager
            config_manager = ConfigurationManager(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'), {})
            redis_url = config_manager.get_redis_url()

            # Parse the URL from ConfigurationManager
            import urllib.parse
            parsed = urllib.parse.urlparse(redis_url)
            if parsed.hostname and parsed.port:
                nodes_str = f"{parsed.hostname}:{parsed.port}"
            else:
                raise ValueError(f"Invalid Redis URL from configuration: {redis_url}")

        nodes = []
        for node_str in nodes_str.split(","):
            if ":" in node_str:
                host, port = node_str.strip().split(":")
                nodes.append({"host": host, "port": int(port)})

        return cls(
            cluster_nodes=nodes,
            max_connections_per_node=int(os.getenv("REDIS_MAX_CONNECTIONS", "50")),
            socket_keepalive=os.getenv("REDIS_KEEPALIVE", "true").lower() == "true",
            decode_responses=False,  # Always use bytes for Gleitzeit
            health_check_interval=int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))
        )


class GleitzeitRedisCluster:
    """
    Redis Cluster client for Gleitzeit.

    All keys use hash tags to ensure workflow locality:
    - {shard:N} prefix ensures all workflow data stays on same node
    - Enables atomic operations, pipelines, and Lua scripts
    """

    def __init__(self, config: RedisConfig = None, redis_url: str = None):
        """
        Initialize Redis Cluster client.
        ALWAYS uses ConfigurationManager for configuration.

        Args:
            config: Redis configuration (optional override)
            redis_url: Redis URL to use (optional override, e.g. from environment)
        """
        if redis_url:
            # Parse redis_url to create config
            import urllib.parse
            parsed = urllib.parse.urlparse(redis_url)
            if parsed.hostname and parsed.port:
                self.config = RedisConfig(
                    cluster_nodes=[{"host": parsed.hostname, "port": parsed.port}],
                    decode_responses=False
                )
            else:
                raise ValueError(f"Invalid redis_url: {redis_url}")
        elif config:
            self.config = config
        else:
            # ALWAYS use from_env which uses ConfigurationManager
            self.config = RedisConfig.from_env()

        self.client: Optional[RedisCluster] = None
        self._initialized = False

    async def initialize(self):
        """
        Initialize the Redis client.

        If only one node is configured, uses regular Redis client (for testing).
        Otherwise, uses RedisCluster for production.

        Returns:
            Initialized Redis client
        """
        if self._initialized:
            return self.client

        # If only one node, use regular Redis (for testing/development)
        if len(self.config.cluster_nodes) == 1:
            node = self.config.cluster_nodes[0]
            self.client = await aioredis.from_url(
                f"redis://{node['host']}:{node['port']}",
                decode_responses=self.config.decode_responses,
                socket_keepalive=self.config.socket_keepalive,
                socket_connect_timeout=self.config.socket_connect_timeout,
                max_connections=self.config.max_connections_per_node,
            )
            logger.info(f"Redis single instance initialized at {node['host']}:{node['port']}")
        else:
            # Create startup nodes for cluster
            startup_nodes = [
                ClusterNode(node["host"], node["port"])
                for node in self.config.cluster_nodes
            ]

            # Create cluster client with connection pooling per node
            cluster_args = {
                "startup_nodes": startup_nodes,
                "decode_responses": self.config.decode_responses,
                "socket_keepalive": self.config.socket_keepalive,
                "socket_connect_timeout": self.config.socket_connect_timeout,
            }

            # Add optional parameters if they're supported
            if self.config.socket_keepalive:
                cluster_args["socket_keepalive_options"] = {
                    1: 1,   # TCP_KEEPIDLE
                    2: 1,   # TCP_KEEPINTVL
                    3: 5,   # TCP_KEEPCNT
                }

            self.client = RedisCluster(**cluster_args)
            logger.info(f"Redis Cluster initialized with {len(startup_nodes)} nodes")

        self._initialized = True
        return self.client

    async def close(self):
        """Close all connections"""
        if self.client:
            await self.client.close()
            # Only cluster has connection_pool.disconnect()
            if hasattr(self.client, 'connection_pool') and hasattr(self.client.connection_pool, 'disconnect'):
                await self.client.connection_pool.disconnect()
            self._initialized = False
            logger.info("Redis connections closed")

    def pipeline(self, transaction: bool = False):
        """
        Create a pipeline for batch operations.

        Note: In cluster mode, all operations in a pipeline must target
        the same hash slot (ensured by our {shard:N} key format).
        """
        if not self._initialized:
            raise RuntimeError("Redis client not initialized. Call initialize() first")
        return self.client.pipeline(transaction=transaction)

    async def execute_lua(self, script: str, keys: List[str], args: List[Any] = None):
        """
        Execute a Lua script on the cluster.

        All keys must belong to the same hash slot (ensured by our key format).
        """
        if not self._initialized:
            raise RuntimeError("Redis client not initialized. Call initialize() first")

        return await self.client.eval(script, len(keys), *keys, *(args or []))

    async def healthcheck(self) -> bool:
        """Check Redis health"""
        try:
            # For single instance, just ping
            if len(self.config.cluster_nodes) == 1:
                await self.client.ping()
                return True
            else:
                # For cluster, check cluster state
                info = await self.client.cluster_info()
                return info.get('cluster_state') == 'ok'
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    # Proxy all Redis commands to the client
    def __getattr__(self, name):
        """Proxy all other attributes to the underlying cluster client"""
        if not self._initialized:
            raise RuntimeError("Redis client not initialized. Call initialize() first")
        return getattr(self.client, name)


# Global cluster instance for convenience
_global_cluster: Optional[GleitzeitRedisCluster] = None


async def get_redis_cluster() -> GleitzeitRedisCluster:
    """
    Get or create the global Redis cluster instance.

    Returns:
        Initialized GleitzeitRedisCluster instance
    """
    global _global_cluster
    if _global_cluster is None:
        _global_cluster = GleitzeitRedisCluster()
        await _global_cluster.initialize()
    return _global_cluster


async def close_redis_cluster():
    """Close the global Redis cluster instance"""
    global _global_cluster
    if _global_cluster:
        await _global_cluster.close()
        _global_cluster = None