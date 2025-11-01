"""
Redis Monitor Worker

Monitors Redis server health and performance metrics, storing results in Redis
for access via the /health/redis API endpoint.

Metrics tracked:
- Memory usage (used_memory, peak memory, memory fragmentation)
- Client connections (connected clients, blocked clients)
- Command stats (ops/sec, hit rate)
- Persistence (last save time, changes since last save)
- Replication status (if configured)
- Stream metrics (pending messages, consumer groups)
- Key space statistics

Architecture:
1. Polls Redis INFO every N seconds
2. Parses and stores metrics in structured format
3. Tracks historical trends (min/max/avg)
4. Provides alerts for threshold violations
5. Uses leader election to prevent duplicate monitoring
"""

import asyncio
import argparse
import logging
import signal
import sys
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import redis.asyncio as aioredis

from ..core.config_manager import ConfigurationManager
from ..core.leader_election import LeaderElection, LeaderStatus
from ..core.sharding import default_sharding

logger = logging.getLogger(__name__)


class RedisMonitorWorker:
    """Worker that monitors Redis server health and performance"""

    def __init__(
        self,
        redis_url: str = None,
        check_interval: int = None,
        retention_seconds: int = None,
        worker_id: str = "redis-monitor",
        config_manager: ConfigurationManager = None
    ):
        # Load configuration
        self.config_manager = config_manager or ConfigurationManager(config_file="gleitzeit.yaml")

        # Get Redis monitoring config from gleitzeit.yaml
        redis_config = self.config_manager.get_all_config().get('redis', {})
        monitoring_config = redis_config.get('monitoring', {})
        health_config = redis_config.get('health', {})

        # Use provided values or fall back to config, then defaults
        self.check_interval = (
            check_interval or
            monitoring_config.get('check_interval') or
            health_config.get('check_interval') or
            10
        )
        self.retention_seconds = (
            retention_seconds or
            monitoring_config.get('retention_seconds') or
            3600
        )

        # Build Redis URL from config if not provided
        if redis_url:
            self.redis_url = redis_url
        else:
            redis_mode = redis_config.get('mode', 'single')
            if redis_mode == 'single':
                single_config = redis_config.get('single_node', {})
                host = single_config.get('host', 'localhost')
                port = single_config.get('port', 6379)
                db = single_config.get('db', 0)
                self.redis_url = f"redis://{host}:{port}/{db}"
            else:
                # Default fallback
                self.redis_url = "redis://localhost:6379"

        self.worker_id = worker_id
        self.redis: Optional[aioredis.Redis] = None
        self.running = False

        # Leader election
        self.leader_election: Optional[LeaderElection] = None
        self.leader_key = ""
        self.leader_ttl = 30

        # Metrics tracking
        self.last_check_time = 0
        self.check_count = 0

        # Service registry heartbeat
        self.heartbeat_interval = 30  # Refresh every 30s (TTL is 60s)

    async def initialize(self):
        """Initialize Redis connection and leader election"""
        self.redis = await aioredis.from_url(
            self.redis_url,
            decode_responses=True
        )

        # Initialize leader election
        self.leader_key = default_sharding.get_global_key("redis_monitor:leader")
        self.leader_election = LeaderElection(
            self.redis,
            self.leader_key,
            self.worker_id,
            self.leader_ttl
        )

        logger.info(
            f"Redis monitor initialized (interval={self.check_interval}s, "
            f"retention={self.retention_seconds}s)"
        )

    async def collect_metrics(self) -> Dict[str, Any]:
        """Collect Redis server metrics"""
        try:
            # Get Redis INFO
            info = await self.redis.info()

            # Parse key metrics
            metrics = {
                "timestamp": time.time(),
                "server": {
                    "redis_version": info.get("redis_version"),
                    "uptime_seconds": info.get("uptime_in_seconds", 0),
                    "process_id": info.get("process_id"),
                },
                "clients": {
                    "connected": info.get("connected_clients", 0),
                    "blocked": info.get("blocked_clients", 0),
                    "max_clients": info.get("maxclients", 0),
                },
                "memory": {
                    "used_bytes": info.get("used_memory", 0),
                    "used_human": info.get("used_memory_human", "0B"),
                    "peak_bytes": info.get("used_memory_peak", 0),
                    "peak_human": info.get("used_memory_peak_human", "0B"),
                    "rss_bytes": info.get("used_memory_rss", 0),
                    "fragmentation_ratio": info.get("mem_fragmentation_ratio", 0),
                },
                "stats": {
                    "total_connections_received": info.get("total_connections_received", 0),
                    "total_commands_processed": info.get("total_commands_processed", 0),
                    "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
                    "rejected_connections": info.get("rejected_connections", 0),
                    "expired_keys": info.get("expired_keys", 0),
                    "evicted_keys": info.get("evicted_keys", 0),
                    "keyspace_hits": info.get("keyspace_hits", 0),
                    "keyspace_misses": info.get("keyspace_misses", 0),
                },
                "persistence": {
                    "rdb_last_save_time": info.get("rdb_last_save_time", 0),
                    "rdb_changes_since_last_save": info.get("rdb_changes_since_last_save", 0),
                    "aof_enabled": info.get("aof_enabled", 0) == 1,
                },
                "replication": {
                    "role": info.get("role", "unknown"),
                    "connected_slaves": info.get("connected_slaves", 0),
                },
                "cpu": {
                    "used_cpu_sys": info.get("used_cpu_sys", 0),
                    "used_cpu_user": info.get("used_cpu_user", 0),
                }
            }

            # Calculate hit rate
            hits = metrics["stats"]["keyspace_hits"]
            misses = metrics["stats"]["keyspace_misses"]
            total = hits + misses
            if total > 0:
                metrics["stats"]["hit_rate"] = hits / total
            else:
                metrics["stats"]["hit_rate"] = 0

            # Get keyspace info
            keyspace = {}
            for key, value in info.items():
                if key.startswith("db"):
                    keyspace[key] = value
            metrics["keyspace"] = keyspace

            # Check stream metrics (Gleitzeit-specific)
            try:
                stream_metrics = await self.collect_stream_metrics()
                metrics["streams"] = stream_metrics
            except Exception as e:
                logger.warning(f"Failed to collect stream metrics: {e}")
                metrics["streams"] = {}

            return metrics

        except Exception as e:
            logger.error(f"Failed to collect metrics: {e}", exc_info=True)
            return {"error": str(e), "timestamp": time.time()}

    async def collect_stream_metrics(self) -> Dict[str, Any]:
        """Collect metrics about Redis streams used by Gleitzeit"""
        stream_metrics = {
            "total_streams": 0,
            "total_pending_messages": 0,
            "streams_detail": []
        }

        try:
            # Get all stream keys
            cursor = 0
            streams = []
            while True:
                cursor, keys = await self.redis.scan(
                    cursor,
                    match="*:workflow:*",
                    count=100
                )
                streams.extend([k for k in keys if isinstance(k, str)])
                if cursor == 0:
                    break

            stream_metrics["total_streams"] = len(streams)

            # Sample up to 10 streams for detailed info
            for stream_key in streams[:10]:
                try:
                    # Get stream length
                    length = await self.redis.xlen(stream_key)

                    stream_metrics["streams_detail"].append({
                        "key": stream_key,
                        "length": length,
                    })
                    stream_metrics["total_pending_messages"] += length

                except Exception as e:
                    logger.debug(f"Failed to get info for stream {stream_key}: {e}")

        except Exception as e:
            logger.warning(f"Failed to collect stream metrics: {e}")

        return stream_metrics

    async def store_metrics(self, metrics: Dict[str, Any]):
        """Store metrics in Redis with TTL"""
        try:
            # Store current metrics
            key = default_sharding.get_global_key("redis_monitor:current")
            await self.redis.setex(
                key,
                self.retention_seconds,
                str(metrics)  # Convert to JSON in production
            )

            # Store in time series (for trending)
            ts_key = default_sharding.get_global_key("redis_monitor:timeseries")
            timestamp = int(time.time())
            await self.redis.zadd(
                ts_key,
                {str(metrics): timestamp}
            )

            # Trim old entries
            cutoff = timestamp - self.retention_seconds
            await self.redis.zremrangebyscore(ts_key, 0, cutoff)

            # Emit health status
            await self.emit_health_status(metrics)

        except Exception as e:
            logger.error(f"Failed to store metrics: {e}", exc_info=True)

    async def emit_health_status(self, metrics: Dict[str, Any]):
        """Emit health status based on metrics"""
        status = "healthy"
        warnings = []
        errors = []

        # Check memory usage
        memory = metrics.get("memory", {})
        if memory.get("fragmentation_ratio", 0) > 2.0:
            warnings.append("High memory fragmentation (>2.0)")

        # Check connections
        clients = metrics.get("clients", {})
        connected = clients.get("connected", 0)
        max_clients = clients.get("max_clients", 10000)
        if connected > max_clients * 0.9:
            errors.append(f"Near max clients ({connected}/{max_clients})")
            status = "unhealthy"
        elif connected > max_clients * 0.7:
            warnings.append(f"High client connections ({connected}/{max_clients})")
            status = "degraded"

        # Check hit rate
        stats = metrics.get("stats", {})
        hit_rate = stats.get("hit_rate", 0)
        if hit_rate < 0.5 and stats.get("keyspace_hits", 0) > 100:
            warnings.append(f"Low cache hit rate ({hit_rate:.1%})")

        # Check rejected connections
        if stats.get("rejected_connections", 0) > 0:
            errors.append(f"Rejected connections: {stats['rejected_connections']}")
            status = "unhealthy"

        # Store health status
        health_key = default_sharding.get_global_key("redis_monitor:health")
        health_data = {
            "status": status,
            "warnings": warnings,
            "errors": errors,
            "checked_at": datetime.utcnow().isoformat(),
            "uptime_seconds": metrics.get("server", {}).get("uptime_seconds", 0)
        }

        await self.redis.setex(
            health_key,
            self.retention_seconds,
            str(health_data)
        )

        # Log warnings/errors
        if errors:
            logger.error(f"Redis health errors: {', '.join(errors)}")
        elif warnings:
            logger.warning(f"Redis health warnings: {', '.join(warnings)}")
        else:
            logger.debug(f"Redis health: {status}")

    async def monitor_loop(self):
        """Main monitoring loop"""
        logger.info("Starting Redis monitor loop")

        while self.running:
            try:
                # Only monitor if we're the leader
                if not self.leader_election or not self.leader_election.is_leader:
                    await asyncio.sleep(self.check_interval)
                    continue

                # Collect and store metrics
                self.last_check_time = time.time()
                self.check_count += 1

                metrics = await self.collect_metrics()
                await self.store_metrics(metrics)

                if self.check_count % 10 == 0:
                    logger.info(
                        f"Collected Redis metrics (check #{self.check_count}): "
                        f"mem={metrics['memory']['used_human']}, "
                        f"clients={metrics['clients']['connected']}, "
                        f"ops/sec={metrics['stats']['instantaneous_ops_per_sec']}"
                    )

                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("Monitor loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Monitor loop error: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)

    async def heartbeat_loop(self):
        """Service registry heartbeat loop to maintain registration"""
        logger.info(f"Starting service registry heartbeat for {self.worker_id}")

        while self.running:
            try:
                # Re-register in service registry to refresh TTL
                service_key = f"service:registry:{self.worker_id}"
                service_info = {
                    "worker_id": self.worker_id,
                    "worker_type": "redis_monitor",
                    "started_at": datetime.utcnow().isoformat(),
                    "mode": "native",
                    "last_heartbeat": datetime.utcnow().isoformat()
                }

                await self.redis.hset(service_key, mapping=service_info)
                await self.redis.expire(service_key, 60)  # 60s TTL

                logger.debug(f"Service registry heartbeat sent for {self.worker_id}")
                await asyncio.sleep(self.heartbeat_interval)

            except asyncio.CancelledError:
                logger.info("Heartbeat loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Heartbeat error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def leader_election_loop(self):
        """Leader election loop"""
        logger.info(f"Starting leader election loop for {self.worker_id}")

        while self.running:
            try:
                status = await self.leader_election.try_elect()

                if status == LeaderStatus.BECAME_LEADER:
                    logger.info(f"🎖️  RedisMonitor {self.worker_id} BECAME LEADER")
                elif status == LeaderStatus.LOST_LEADERSHIP:
                    logger.warning(f"👥 RedisMonitor {self.worker_id} LOST LEADERSHIP")
                elif status == LeaderStatus.STILL_LEADER:
                    logger.debug(f"RedisMonitor {self.worker_id} still leader")
                else:
                    current_leader = await self.leader_election.get_current_leader()
                    logger.debug(
                        f"RedisMonitor {self.worker_id} not leader "
                        f"(current leader: {current_leader})"
                    )

                await asyncio.sleep(self.leader_ttl // 3)

            except asyncio.CancelledError:
                logger.info("Leader election loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Leader election error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def start(self):
        """Start the Redis monitor"""
        self.running = True
        logger.info("Starting Redis monitor worker")

        try:
            await self.initialize()

            # Run all loops concurrently
            await asyncio.gather(
                self.leader_election_loop(),
                self.monitor_loop(),
                self.heartbeat_loop()
            )

        except asyncio.CancelledError:
            logger.info("Redis monitor worker cancelled")
        except Exception as e:
            logger.error(f"Redis monitor worker error: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup resources"""
        self.running = False

        # Release leadership
        if self.leader_election and self.leader_election.is_leader:
            await self.leader_election.release()
            logger.info(f"Released leadership for {self.worker_id}")

        if self.redis:
            await self.redis.close()

        logger.info("Redis monitor worker stopped")

    async def stop(self):
        """Stop the Redis monitor"""
        logger.info("Stopping Redis monitor worker")
        self.running = False


async def main():
    """Main entry point for Redis monitor worker"""
    parser = argparse.ArgumentParser(description="Gleitzeit Redis Monitor Worker")
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL (default: from gleitzeit.yaml)"
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=None,
        help="Check interval in seconds (default: from gleitzeit.yaml or 10)"
    )
    parser.add_argument(
        "--retention",
        type=int,
        default=None,
        help="Metrics retention in seconds (default: from gleitzeit.yaml or 3600)"
    )
    parser.add_argument(
        "--worker-id",
        default="redis-monitor",
        help="Worker ID for leader election (default: redis-monitor)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )
    parser.add_argument(
        "--config",
        default="gleitzeit.yaml",
        help="Path to config file (default: gleitzeit.yaml)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load configuration manager
    config_manager = ConfigurationManager(config_file=args.config)

    # Create worker with config
    worker = RedisMonitorWorker(
        redis_url=args.redis_url,
        check_interval=args.check_interval,
        retention_seconds=args.retention,
        worker_id=args.worker_id,
        config_manager=config_manager
    )

    logger.info(f"Redis monitor starting with config from {args.config}")
    logger.info(f"  Redis URL: {worker.redis_url}")
    logger.info(f"  Check interval: {worker.check_interval}s")
    logger.info(f"  Retention: {worker.retention_seconds}s")

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
        logger.info("Redis monitor interrupted by user")
    except Exception as e:
        logger.error(f"Redis monitor failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
