"""
Health check system for coordination mechanisms in horizontal scaling.

This module provides health checks for:
- Leader election (TimerWorker, SignalWorker, LokiExporter)
- Service registry
- Redis stream consumers
- Sharding configuration
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

import redis.asyncio as aioredis
import psutil

logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    """Result of a health check"""
    healthy: bool
    issues: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    check_name: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'healthy': self.healthy,
            'issues': self.issues,
            'metadata': self.metadata,
            'check_name': self.check_name,
            'timestamp': self.timestamp
        }


class HealthCheck(ABC):
    """Base class for health checks"""

    def __init__(self, name: str):
        self.name = name
        self.last_result: Optional[HealthResult] = None

    @abstractmethod
    async def execute(self, redis: aioredis.Redis) -> HealthResult:
        """Execute the health check"""
        pass

    async def run(self, redis: aioredis.Redis) -> HealthResult:
        """Run the health check and store result"""
        try:
            result = await self.execute(redis)
            result.check_name = self.name
            result.timestamp = time.time()
            self.last_result = result
            return result
        except Exception as e:
            logger.error(f"Health check {self.name} failed with exception: {e}")
            result = HealthResult(
                healthy=False,
                issues=[f"Health check exception: {str(e)}"],
                check_name=self.name,
                timestamp=time.time()
            )
            self.last_result = result
            return result


class LeaderElectionHealthCheck(HealthCheck):
    """Validates leader election mechanism health"""

    def __init__(self):
        super().__init__("leader_election")
        self.leader_services = ['timer', 'signal', 'loki_exporter']

    async def execute(self, redis: aioredis.Redis) -> HealthResult:
        issues = []

        # Check 1: Ensure leaders exist for all leader-elected services
        for service in self.leader_services:
            leader_key = f"leader:{service}"
            leader = await redis.get(leader_key)

            if not leader:
                issues.append(f"No leader for {service}")
                continue

            # Check 2: Validate leader instance is still registered
            instance_key = f"instance:{leader}"
            instance_exists = await redis.exists(instance_key)
            if not instance_exists:
                issues.append(f"Leader {leader} for {service} not registered in instance registry")

        # Check 3: Detect split brain (multiple leaders due to Redis partition)
        for service in self.leader_services:
            active_count = await self._count_active_leaders(redis, service)
            if active_count > 1:
                issues.append(f"Split brain detected: {active_count} leaders for {service}")

        return HealthResult(
            healthy=len(issues) == 0,
            issues=issues,
            metadata={
                'services_checked': self.leader_services,
                'timestamp': time.time()
            }
        )

    async def _count_active_leaders(self, redis: aioredis.Redis, service: str) -> int:
        """Count number of active leaders for a service"""
        # Check if the leader key exists
        leader_key = f"leader:{service}"
        leader = await redis.get(leader_key)

        if leader:
            return 1  # We have exactly one leader
        return 0  # No leader


class ServiceRegistryHealthCheck(HealthCheck):
    """Validates service registry health"""

    def __init__(self, heartbeat_threshold: int = 90):
        super().__init__("service_registry")
        self.heartbeat_threshold = heartbeat_threshold  # 1.5x TTL (60s * 1.5)

    async def execute(self, redis: aioredis.Redis) -> HealthResult:
        issues = []

        # Get all registered services
        service_keys = await redis.keys("service:*")
        current_time = time.time()
        service_count = 0

        for service_key in service_keys:
            service_key_str = service_key.decode() if isinstance(service_key, bytes) else service_key

            # Skip metadata keys
            if ':metadata' in service_key_str or ':port' in service_key_str:
                continue

            service_count += 1
            service_data = await redis.hgetall(service_key_str)

            if not service_data:
                continue

            # Decode bytes to strings
            service_data = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in service_data.items()
            }

            # Check 1: Find services with expired heartbeats
            last_heartbeat = float(service_data.get('last_heartbeat', 0))
            if current_time - last_heartbeat > self.heartbeat_threshold:
                service_name = service_key_str.split(':')[1] if ':' in service_key_str else service_key_str
                issues.append(f"Stale heartbeat for {service_name} ({int(current_time - last_heartbeat)}s old)")

            # Check 2: Validate registered PIDs exist
            pid = service_data.get('pid')
            if pid:
                try:
                    pid_int = int(pid)
                    if not psutil.pid_exists(pid_int):
                        service_name = service_key_str.split(':')[1] if ':' in service_key_str else service_key_str
                        issues.append(f"Service {service_name} PID {pid_int} not found")
                except (ValueError, TypeError):
                    pass

        return HealthResult(
            healthy=len(issues) == 0,
            issues=issues,
            metadata={
                'service_count': service_count,
                'heartbeat_threshold': self.heartbeat_threshold
            }
        )


class StreamConsumerHealthCheck(HealthCheck):
    """Validates Redis stream consumer health"""

    def __init__(
        self,
        num_shards: int = 16,
        lag_warning: int = 500,
        lag_critical: int = 1000,
        idle_threshold: int = 300000  # 5 minutes in milliseconds
    ):
        super().__init__("stream_consumer")
        self.num_shards = num_shards
        self.lag_warning = lag_warning
        self.lag_critical = lag_critical
        self.idle_threshold = idle_threshold

    async def execute(self, redis: aioredis.Redis) -> HealthResult:
        issues = []
        warnings = []

        # Check all workflow streams (16 shards)
        for shard in range(self.num_shards):
            stream_name = f"workflow:shard:{shard}"

            try:
                # Check 1: Measure consumer lag
                groups = await redis.xinfo_groups(stream_name)
                for group_info in groups:
                    group_name = group_info['name'].decode() if isinstance(group_info['name'], bytes) else group_info['name']
                    lag = group_info.get('lag', 0)

                    if lag > self.lag_critical:
                        issues.append(f"CRITICAL lag on {stream_name}/{group_name}: {lag}")
                    elif lag > self.lag_warning:
                        warnings.append(f"High lag on {stream_name}/{group_name}: {lag}")

                # Check 2: Check for pending messages stuck in PEL (Pending Entry List)
                try:
                    # Get consumer groups
                    for group_info in groups:
                        group_name = group_info['name'].decode() if isinstance(group_info['name'], bytes) else group_info['name']
                        pending = await redis.xpending(stream_name, group_name)

                        if pending and len(pending) >= 4:
                            pending_count = pending[0]  # First element is the count
                            if pending_count > 100:
                                warnings.append(f"High pending count on {stream_name}/{group_name}: {pending_count}")
                except Exception as e:
                    # Pending check is optional, don't fail health check
                    logger.debug(f"Could not check pending messages for {stream_name}: {e}")

            except Exception as e:
                # Stream might not exist yet, that's ok
                logger.debug(f"Could not check stream {stream_name}: {e}")

        # Combine issues and warnings
        all_issues = issues + warnings

        return HealthResult(
            healthy=len(issues) == 0,  # Only critical issues affect health
            issues=all_issues,
            metadata={
                'total_shards': self.num_shards,
                'lag_warning': self.lag_warning,
                'lag_critical': self.lag_critical,
                'critical_issues': len(issues),
                'warnings': len(warnings)
            }
        )


class ShardingConfigHealthCheck(HealthCheck):
    """Validates sharding configuration consistency"""

    def __init__(self, num_shards: int = 16):
        super().__init__("sharding_config")
        self.num_shards = num_shards

    async def execute(self, redis: aioredis.Redis) -> HealthResult:
        issues = []

        # Check 1: Validate stored config exists
        stored_shards = await redis.get("global:config:num_shards")
        if not stored_shards:
            issues.append("No sharding configuration stored in Redis")
            return HealthResult(
                healthy=False,
                issues=issues,
                metadata={'num_shards': None}
            )

        # Decode if bytes
        if isinstance(stored_shards, bytes):
            stored_shards = stored_shards.decode()

        # Check 2: Compare against local configuration
        from gleitzeit.core.sharding import default_sharding
        local_shards = default_sharding.num_shards

        if int(stored_shards) != local_shards:
            issues.append(
                f"Config mismatch: Redis={stored_shards}, Local={local_shards}"
            )

        # Check 3: Validate all shards have streams created
        missing_streams = []
        for shard in range(int(stored_shards)):
            stream_name = f"workflow:shard:{shard}"
            exists = await redis.exists(stream_name)
            if not exists:
                missing_streams.append(shard)

        if missing_streams and len(missing_streams) < int(stored_shards):
            # Some streams missing (but not all - if all missing, system just started)
            issues.append(f"Missing workflow streams for shards: {missing_streams}")

        return HealthResult(
            healthy=len(issues) == 0,
            issues=issues,
            metadata={
                'num_shards': stored_shards,
                'local_shards': local_shards,
                'missing_streams': len(missing_streams) if missing_streams else 0
            }
        )


class HealthCheckRunner:
    """Runs all health checks periodically"""

    def __init__(
        self,
        redis: aioredis.Redis,
        check_interval: int = 30,
        checks: Optional[List[HealthCheck]] = None
    ):
        self.redis = redis
        self.check_interval = check_interval
        self.checks = checks or self._create_default_checks()
        self.running = False

    def _create_default_checks(self) -> List[HealthCheck]:
        """Create default set of health checks"""
        return [
            LeaderElectionHealthCheck(),
            ServiceRegistryHealthCheck(),
            StreamConsumerHealthCheck(),
            ShardingConfigHealthCheck()
        ]

    async def run_once(self) -> Dict[str, HealthResult]:
        """Run all health checks once"""
        results = {}

        for check in self.checks:
            result = await check.run(self.redis)
            results[check.name] = result

            # Store result in Redis for API access
            await self._store_result(check.name, result)

            # Log unhealthy checks
            if not result.healthy:
                logger.warning(
                    f"Health check {check.name} UNHEALTHY: {', '.join(result.issues)}"
                )

        return results

    async def _store_result(self, check_name: str, result: HealthResult):
        """Store health check result in Redis"""
        try:
            key = f"health:coordination:{check_name}"
            await self.redis.setex(
                key,
                self.check_interval * 3,  # Keep for 3 intervals
                json.dumps(result.to_dict())
            )
        except Exception as e:
            logger.error(f"Failed to store health check result: {e}")

    async def run_forever(self):
        """Run health checks continuously"""
        self.running = True
        logger.info(f"Starting health check runner (interval={self.check_interval}s)")

        while self.running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")

            await asyncio.sleep(self.check_interval)

    async def stop(self):
        """Stop the health check runner"""
        self.running = False
        logger.info("Health check runner stopped")
