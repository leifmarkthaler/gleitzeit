"""
Stream Monitor and Health Check System.

Provides comprehensive monitoring, alerting, and health checks
for Redis Streams-based event processing systems.
"""

import asyncio
import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent, EventType
from ..events import EventBus

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class StreamHealth:
    """Health information for a Redis stream."""
    stream_name: str
    status: HealthStatus
    length: int
    consumer_groups: List[str]
    pending_messages: int
    lag: int  # Messages behind
    last_activity: Optional[datetime]
    issues: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class ConsumerGroupHealth:
    """Health information for a consumer group."""
    group_name: str
    stream_name: str
    status: HealthStatus
    total_consumers: int
    active_consumers: int
    idle_consumers: int
    pending_messages: int
    oldest_pending_age: Optional[timedelta]
    throughput_per_second: float
    issues: List[str] = field(default_factory=list)


@dataclass
class SystemHealth:
    """Overall system health summary."""
    status: HealthStatus
    total_streams: int
    healthy_streams: int
    warning_streams: int
    critical_streams: int
    total_messages_per_second: float
    total_pending_messages: int
    redis_memory_usage: Optional[float]
    issues: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class StreamMonitor:
    """
    Comprehensive monitoring system for Redis Streams.

    Features:
    - Real-time health monitoring
    - Performance metrics collection
    - Automatic alerting
    - Trend analysis
    - Capacity planning metrics
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[EventBus] = None,
        monitoring_interval: int = 30,  # seconds
        alert_thresholds: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize Stream Monitor.

        Args:
            persistence: Redis persistence adapter
            event_bus: Event bus for alerts
            monitoring_interval: How often to collect metrics
            alert_thresholds: Thresholds for various alerts
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.monitoring_interval = monitoring_interval

        # Default alert thresholds
        self.thresholds = {
            "max_pending_messages": 10000,
            "max_consumer_idle_time": 300,  # 5 minutes
            "max_message_age": 3600,  # 1 hour
            "min_throughput": 0.1,  # messages/second
            "max_lag": 1000,
            "max_redis_memory_usage": 0.85  # 85%
        }

        if alert_thresholds:
            self.thresholds.update(alert_thresholds)

        # Monitoring state
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False

        # Metrics storage
        self._stream_metrics: Dict[str, List[Dict[str, Any]]] = {}
        self._system_metrics: List[Dict[str, Any]] = []
        self._max_history = 1440  # 24 hours at 1-minute intervals

        # Alerting state
        self._alert_cooldowns: Dict[str, datetime] = {}
        self._alert_cooldown_period = timedelta(minutes=15)

        logger.info(f"Initialized StreamMonitor (interval: {monitoring_interval}s)")

    async def start_monitoring(self):
        """Start continuous monitoring."""
        if self._running:
            return

        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("StreamMonitor started")

    async def stop_monitoring(self):
        """Stop monitoring."""
        self._running = False

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("StreamMonitor stopped")

    async def get_system_health(self) -> SystemHealth:
        """Get overall system health status."""
        try:
            # Discover all streams
            streams = await self._discover_streams()

            # Check health of each stream
            stream_healths = []
            for stream_name in streams:
                health = await self.get_stream_health(stream_name)
                stream_healths.append(health)

            # Aggregate health status
            healthy_count = sum(1 for h in stream_healths if h.status == HealthStatus.HEALTHY)
            warning_count = sum(1 for h in stream_healths if h.status == HealthStatus.WARNING)
            critical_count = sum(1 for h in stream_healths if h.status == HealthStatus.CRITICAL)

            # Determine overall status
            if critical_count > 0:
                overall_status = HealthStatus.CRITICAL
            elif warning_count > 0:
                overall_status = HealthStatus.WARNING
            else:
                overall_status = HealthStatus.HEALTHY

            # Calculate aggregate metrics
            total_pending = sum(h.pending_messages for h in stream_healths)

            # Get Redis memory usage
            redis_memory = await self._get_redis_memory_usage()

            # Collect all issues
            issues = []
            for health in stream_healths:
                issues.extend(health.issues)

            return SystemHealth(
                status=overall_status,
                total_streams=len(streams),
                healthy_streams=healthy_count,
                warning_streams=warning_count,
                critical_streams=critical_count,
                total_messages_per_second=0.0,  # Will be calculated from metrics
                total_pending_messages=total_pending,
                redis_memory_usage=redis_memory,
                issues=issues
            )

        except Exception as e:
            logger.error(f"Error getting system health: {e}")
            return SystemHealth(
                status=HealthStatus.UNKNOWN,
                total_streams=0,
                healthy_streams=0,
                warning_streams=0,
                critical_streams=0,
                total_messages_per_second=0.0,
                total_pending_messages=0,
                redis_memory_usage=None,
                issues=[f"Error checking system health: {e}"]
            )

    async def get_stream_health(self, stream_name: str) -> StreamHealth:
        """Get health status for a specific stream."""
        try:
            # Get stream info
            stream_info = await self.persistence.redis.xinfo_stream(stream_name)
            length = stream_info.get('length', 0)

            # Get consumer groups
            groups_info = await self.persistence.redis.xinfo_groups(stream_name)
            consumer_groups = [
                group['name'].decode() if isinstance(group['name'], bytes) else group['name']
                for group in groups_info
            ]

            # Calculate total pending messages across all groups
            total_pending = 0
            max_lag = 0
            for group_info in groups_info:
                pending = group_info.get('pending', 0)
                total_pending += pending
                max_lag = max(max_lag, pending)

            # Get last activity
            last_entry = stream_info.get('last-entry')
            last_activity = None
            if last_entry and last_entry[1]:
                # Extract timestamp from entry ID (format: timestamp-sequence)
                entry_id = last_entry[0].decode() if isinstance(last_entry[0], bytes) else last_entry[0]
                timestamp_ms = int(entry_id.split('-')[0])
                last_activity = datetime.fromtimestamp(timestamp_ms / 1000)

            # Determine health status
            issues = []
            status = HealthStatus.HEALTHY

            if total_pending > self.thresholds["max_pending_messages"]:
                issues.append(f"High pending messages: {total_pending}")
                status = HealthStatus.WARNING

            if max_lag > self.thresholds["max_lag"]:
                issues.append(f"High consumer lag: {max_lag}")
                status = HealthStatus.WARNING

            if last_activity:
                age = datetime.utcnow() - last_activity
                if age.total_seconds() > self.thresholds["max_message_age"]:
                    issues.append(f"No recent activity: {age}")
                    status = HealthStatus.WARNING

            # If we have warning issues, check if any are critical
            if len(issues) >= 3 or total_pending > self.thresholds["max_pending_messages"] * 2:
                status = HealthStatus.CRITICAL

            return StreamHealth(
                stream_name=stream_name,
                status=status,
                length=length,
                consumer_groups=consumer_groups,
                pending_messages=total_pending,
                lag=max_lag,
                last_activity=last_activity,
                issues=issues,
                metrics={
                    "messages_per_second": 0.0,  # Will be calculated from history
                    "avg_message_size": 0.0,
                    "consumer_efficiency": 0.0
                }
            )

        except Exception as e:
            logger.error(f"Error getting health for stream {stream_name}: {e}")
            return StreamHealth(
                stream_name=stream_name,
                status=HealthStatus.UNKNOWN,
                length=0,
                consumer_groups=[],
                pending_messages=0,
                lag=0,
                last_activity=None,
                issues=[f"Error checking stream health: {e}"]
            )

    async def get_consumer_group_health(self, stream_name: str, group_name: str) -> ConsumerGroupHealth:
        """Get health status for a consumer group."""
        try:
            # Get consumer info
            consumers_info = await self.persistence.redis.xinfo_consumers(stream_name, group_name)

            total_consumers = len(consumers_info)
            active_consumers = 0
            idle_consumers = 0
            max_idle_time = 0

            for consumer in consumers_info:
                idle_time_ms = consumer.get('idle', 0)
                if idle_time_ms < self.thresholds["max_consumer_idle_time"] * 1000:
                    active_consumers += 1
                else:
                    idle_consumers += 1
                max_idle_time = max(max_idle_time, idle_time_ms)

            # Get pending info
            pending_info = await self.persistence.redis.xpending(stream_name, group_name)
            pending_messages = pending_info[0] if pending_info else 0

            # Calculate oldest pending age
            oldest_pending_age = None
            if pending_info and len(pending_info) > 1 and pending_info[1]:
                oldest_id = pending_info[1].decode() if isinstance(pending_info[1], bytes) else pending_info[1]
                timestamp_ms = int(oldest_id.split('-')[0])
                oldest_time = datetime.fromtimestamp(timestamp_ms / 1000)
                oldest_pending_age = datetime.utcnow() - oldest_time

            # Determine health status
            issues = []
            status = HealthStatus.HEALTHY

            if idle_consumers > active_consumers:
                issues.append(f"More idle consumers ({idle_consumers}) than active ({active_consumers})")
                status = HealthStatus.WARNING

            if pending_messages > self.thresholds["max_pending_messages"]:
                issues.append(f"High pending messages: {pending_messages}")
                status = HealthStatus.WARNING

            if oldest_pending_age and oldest_pending_age.total_seconds() > self.thresholds["max_message_age"]:
                issues.append(f"Old pending messages: {oldest_pending_age}")
                status = HealthStatus.WARNING

            return ConsumerGroupHealth(
                group_name=group_name,
                stream_name=stream_name,
                status=status,
                total_consumers=total_consumers,
                active_consumers=active_consumers,
                idle_consumers=idle_consumers,
                pending_messages=pending_messages,
                oldest_pending_age=oldest_pending_age,
                throughput_per_second=0.0,  # Will be calculated from metrics
                issues=issues
            )

        except Exception as e:
            logger.error(f"Error getting consumer group health for {stream_name}/{group_name}: {e}")
            return ConsumerGroupHealth(
                group_name=group_name,
                stream_name=stream_name,
                status=HealthStatus.UNKNOWN,
                total_consumers=0,
                active_consumers=0,
                idle_consumers=0,
                pending_messages=0,
                oldest_pending_age=None,
                throughput_per_second=0.0,
                issues=[f"Error checking consumer group health: {e}"]
            )

    async def collect_metrics(self):
        """Collect metrics for all streams."""
        timestamp = datetime.utcnow()

        try:
            # Discover streams
            streams = await self._discover_streams()

            # Collect metrics for each stream
            for stream_name in streams:
                metrics = await self._collect_stream_metrics(stream_name)
                metrics["timestamp"] = timestamp.isoformat()

                # Store metrics
                if stream_name not in self._stream_metrics:
                    self._stream_metrics[stream_name] = []

                self._stream_metrics[stream_name].append(metrics)

                # Limit history
                if len(self._stream_metrics[stream_name]) > self._max_history:
                    self._stream_metrics[stream_name].pop(0)

            # Collect system-wide metrics
            system_metrics = await self._collect_system_metrics()
            system_metrics["timestamp"] = timestamp.isoformat()

            self._system_metrics.append(system_metrics)
            if len(self._system_metrics) > self._max_history:
                self._system_metrics.pop(0)

            logger.debug(f"Collected metrics for {len(streams)} streams")

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")

    async def _monitoring_loop(self):
        """Main monitoring loop."""
        try:
            while self._running:
                # Collect metrics
                await self.collect_metrics()

                # Check for alerts
                await self._check_alerts()

                # Wait for next interval
                await asyncio.sleep(self.monitoring_interval)

        except asyncio.CancelledError:
            logger.info("Monitoring loop cancelled")
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")

    async def _discover_streams(self) -> List[str]:
        """Discover all Redis streams."""
        try:
            # Look for common stream patterns
            patterns = ["events:*", "timers:*", "signals:*", "*:scheduled", "*:immediate", "*:retry"]

            streams = set()
            for pattern in patterns:
                keys = await self.persistence.redis.keys(pattern)
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode()

                    # Verify it's actually a stream
                    try:
                        await self.persistence.redis.xinfo_stream(key)
                        streams.add(key)
                    except:
                        # Not a stream, skip
                        pass

            return list(streams)

        except Exception as e:
            logger.error(f"Error discovering streams: {e}")
            return []

    async def _collect_stream_metrics(self, stream_name: str) -> Dict[str, Any]:
        """Collect detailed metrics for a stream."""
        try:
            # Get stream info
            stream_info = await self.persistence.redis.xinfo_stream(stream_name)

            # Get consumer groups info
            groups_info = await self.persistence.redis.xinfo_groups(stream_name)

            metrics = {
                "stream_name": stream_name,
                "length": stream_info.get('length', 0),
                "consumer_groups": len(groups_info),
                "total_pending": 0,
                "total_consumers": 0,
                "active_consumers": 0
            }

            # Aggregate consumer group metrics
            for group in groups_info:
                group_name = group['name'].decode() if isinstance(group['name'], bytes) else group['name']

                # Get consumer info
                consumers = await self.persistence.redis.xinfo_consumers(stream_name, group_name)
                metrics["total_consumers"] += len(consumers)

                # Count active consumers
                for consumer in consumers:
                    if consumer.get('idle', 0) < 60000:  # Active if idle < 1 minute
                        metrics["active_consumers"] += 1

                # Add pending messages
                metrics["total_pending"] += group.get('pending', 0)

            return metrics

        except Exception as e:
            logger.error(f"Error collecting metrics for {stream_name}: {e}")
            return {"stream_name": stream_name, "error": str(e)}

    async def _collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system-wide metrics."""
        try:
            # Get Redis info
            redis_info = await self.persistence.redis.info()

            return {
                "redis_memory_used": redis_info.get('used_memory', 0),
                "redis_memory_peak": redis_info.get('used_memory_peak', 0),
                "redis_connections": redis_info.get('connected_clients', 0),
                "redis_commands_processed": redis_info.get('total_commands_processed', 0),
                "redis_keyspace_hits": redis_info.get('keyspace_hits', 0),
                "redis_keyspace_misses": redis_info.get('keyspace_misses', 0)
            }

        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
            return {"error": str(e)}

    async def _get_redis_memory_usage(self) -> Optional[float]:
        """Get Redis memory usage percentage."""
        try:
            redis_info = await self.persistence.redis.info()
            used_memory = redis_info.get('used_memory', 0)
            max_memory = redis_info.get('maxmemory', 0)

            if max_memory > 0:
                return used_memory / max_memory

            return None

        except Exception as e:
            logger.error(f"Error getting Redis memory usage: {e}")
            return None

    async def _check_alerts(self):
        """Check for alert conditions and emit alerts."""
        try:
            system_health = await self.get_system_health()

            # Check system-level alerts
            if system_health.status in [HealthStatus.WARNING, HealthStatus.CRITICAL]:
                await self._emit_alert(
                    alert_type="system_health",
                    level=system_health.status.value,
                    message=f"System health is {system_health.status.value}",
                    details={"issues": system_health.issues}
                )

            # Check Redis memory usage
            if system_health.redis_memory_usage and system_health.redis_memory_usage > self.thresholds["max_redis_memory_usage"]:
                await self._emit_alert(
                    alert_type="redis_memory",
                    level="warning",
                    message=f"Redis memory usage high: {system_health.redis_memory_usage:.1%}",
                    details={"usage": system_health.redis_memory_usage}
                )

            # Check pending messages
            if system_health.total_pending_messages > self.thresholds["max_pending_messages"]:
                await self._emit_alert(
                    alert_type="pending_messages",
                    level="warning",
                    message=f"High pending messages: {system_health.total_pending_messages}",
                    details={"pending": system_health.total_pending_messages}
                )

        except Exception as e:
            logger.error(f"Error checking alerts: {e}")

    async def _emit_alert(self, alert_type: str, level: str, message: str, details: Dict[str, Any]):
        """Emit an alert if not in cooldown."""
        alert_key = f"{alert_type}:{level}"
        now = datetime.utcnow()

        # Check cooldown
        if alert_key in self._alert_cooldowns:
            if now - self._alert_cooldowns[alert_key] < self._alert_cooldown_period:
                return  # Still in cooldown

        # Record alert time
        self._alert_cooldowns[alert_key] = now

        # Emit alert
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.SYSTEM_ALERT,
                data={
                    "alert_type": alert_type,
                    "level": level,
                    "message": message,
                    "details": details,
                    "timestamp": now.isoformat()
                }
            ))

        logger.warning(f"ALERT [{level.upper()}] {alert_type}: {message}")

    def get_metrics_summary(self, hours: int = 1) -> Dict[str, Any]:
        """Get metrics summary for the last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        summary = {
            "period_hours": hours,
            "streams": {},
            "system": {}
        }

        # Stream metrics
        for stream_name, metrics_list in self._stream_metrics.items():
            recent_metrics = [
                m for m in metrics_list
                if datetime.fromisoformat(m["timestamp"]) > cutoff
            ]

            if recent_metrics:
                summary["streams"][stream_name] = {
                    "avg_length": sum(m.get("length", 0) for m in recent_metrics) / len(recent_metrics),
                    "avg_pending": sum(m.get("total_pending", 0) for m in recent_metrics) / len(recent_metrics),
                    "avg_consumers": sum(m.get("total_consumers", 0) for m in recent_metrics) / len(recent_metrics)
                }

        # System metrics
        recent_system_metrics = [
            m for m in self._system_metrics
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]

        if recent_system_metrics:
            summary["system"] = {
                "avg_memory_used": sum(m.get("redis_memory_used", 0) for m in recent_system_metrics) / len(recent_system_metrics),
                "avg_connections": sum(m.get("redis_connections", 0) for m in recent_system_metrics) / len(recent_system_metrics)
            }

        return summary

    def get_status(self) -> Dict[str, Any]:
        """Get monitor status."""
        return {
            "running": self._running,
            "monitoring_interval": self.monitoring_interval,
            "thresholds": self.thresholds,
            "metrics_history_size": len(self._system_metrics),
            "tracked_streams": len(self._stream_metrics),
            "alert_cooldowns": len(self._alert_cooldowns)
        }