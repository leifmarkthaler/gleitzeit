"""
Consumer Lifecycle Management for Horizontal Scaling.

Manages consumer registration, heartbeats, and automatic cleanup of dead consumers.
This is critical for preventing stuck workflows and enabling proper horizontal scaling.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ConsumerLifecycle:
    """
    Manages consumer lifecycle with TTL-based registration.

    This ensures dead consumers are automatically cleaned up, preventing
    message accumulation and enabling proper work distribution in a
    horizontally scaled environment.
    """

    def __init__(
        self,
        redis: Redis,
        scheduler = None,
        consumer_group: str = "gleitzeit-workers",
        ttl: int = 60,
        heartbeat_interval: int = 20
    ):
        """
        Initialize consumer lifecycle manager.

        Args:
            redis: Redis connection
            scheduler: Event scheduler for heartbeat operations
            consumer_group: Consumer group name
            ttl: Time-to-live for consumer registration (seconds)
            heartbeat_interval: How often to send heartbeat (seconds)
        """
        self.redis = redis
        self.scheduler = scheduler
        self.consumer_group = consumer_group
        self.ttl = ttl
        self.heartbeat_interval = heartbeat_interval
        self.consumer_id = f"consumer_{uuid.uuid4().hex[:8]}"

    async def register_consumer(self, consumer_id: Optional[str] = None) -> str:
        """
        Register consumer with automatic expiry.

        Args:
            consumer_id: Optional consumer ID (auto-generated if not provided)

        Returns:
            Consumer ID that was registered
        """
        if consumer_id:
            self.consumer_id = consumer_id

        registration = {
            "consumer_id": self.consumer_id,
            "started": time.time(),
            "pid": os.getpid(),
            "hostname": os.uname().nodename,
            "last_heartbeat": time.time()
        }

        # Register with TTL
        await self.redis.setex(
            f"consumer:{self.consumer_group}:{self.consumer_id}:alive",
            self.ttl,
            json.dumps(registration)
        )

        logger.info(f"Registered consumer {self.consumer_id} with TTL {self.ttl}s")
        return self.consumer_id

    async def heartbeat(self) -> bool:
        """
        Send heartbeat to extend consumer TTL.

        Returns:
            True if heartbeat succeeded
        """
        try:
            key = f"consumer:{self.consumer_group}:{self.consumer_id}:alive"

            # Update registration data
            registration_data = await self.redis.get(key)
            if registration_data:
                registration = json.loads(registration_data)
                registration["last_heartbeat"] = time.time()

                # Update with new TTL
                await self.redis.setex(
                    key,
                    self.ttl,
                    json.dumps(registration)
                )

                logger.debug(f"Heartbeat sent for consumer {self.consumer_id}")
                return True
            else:
                # Re-register if key expired
                logger.warning(f"Consumer {self.consumer_id} expired, re-registering")
                await self.register_consumer(self.consumer_id)
                return True

        except Exception as e:
            logger.error(f"Heartbeat failed for {self.consumer_id}: {e}")
            return False

    async def _handle_heartbeat_event(self, event_data: Dict) -> Dict[str, Any]:
        """Handle heartbeat event from scheduler."""
        try:
            logger.debug(f"Processing heartbeat event for consumer {self.consumer_id}")

            success = await self.heartbeat()

            # Schedule next heartbeat event
            if self.scheduler:
                event_name = f"consumer_heartbeat_{self.consumer_id}"
                await self.scheduler.schedule_event(event_name, self.heartbeat_interval)

            return {
                "consumer_id": self.consumer_id,
                "heartbeat_success": success,
                "next_heartbeat_in": self.heartbeat_interval
            }

        except Exception as e:
            logger.error(f"Error in heartbeat event handler: {e}")
            # Still schedule next heartbeat
            if self.scheduler:
                event_name = f"consumer_heartbeat_{self.consumer_id}"
                await self.scheduler.schedule_event(event_name, self.heartbeat_interval)
            return {"error": str(e), "consumer_id": self.consumer_id}

    async def start_heartbeat_loop(self):
        """Start event-driven heartbeat with scheduler."""
        if self.scheduler:
            event_name = f"consumer_heartbeat_{self.consumer_id}"
            await self.scheduler.register_handler(event_name, self._handle_heartbeat_event)
            await self.scheduler.schedule_event(event_name, self.heartbeat_interval)
            logger.info(f"Started event-driven heartbeat for {self.consumer_id}")
        else:
            logger.warning(f"No scheduler available for {self.consumer_id} - heartbeat disabled")

    async def stop_heartbeat_loop(self):
        """Stop event-driven heartbeat (handled by scheduler cleanup)."""
        logger.info(f"Stopped heartbeat for {self.consumer_id}")

    async def unregister_consumer(self):
        """Unregister consumer on shutdown."""
        key = f"consumer:{self.consumer_group}:{self.consumer_id}:alive"
        await self.redis.delete(key)
        logger.info(f"Unregistered consumer {self.consumer_id}")

    async def get_active_consumers(self) -> List[Dict[str, Any]]:
        """
        Get list of active consumers in the group.

        Returns:
            List of active consumer registrations
        """
        pattern = f"consumer:{self.consumer_group}:*:alive"
        active_consumers = []

        async for key in self.redis.scan_iter(match=pattern):
            try:
                data = await self.redis.get(key)
                if data:
                    registration = json.loads(data)
                    active_consumers.append(registration)
            except Exception as e:
                logger.error(f"Error reading consumer registration {key}: {e}")

        return active_consumers

    async def cleanup_dead_consumers(self, stream_keys: List[str]) -> int:
        """
        Remove dead consumers from Redis consumer groups.

        This checks all consumers in the Redis consumer groups and removes
        those that don't have an active registration.

        Args:
            stream_keys: List of stream keys to check

        Returns:
            Number of dead consumers removed
        """
        removed_count = 0
        active_consumer_ids = {c["consumer_id"] for c in await self.get_active_consumers()}

        for stream_key in stream_keys:
            try:
                # Get consumer group info
                groups = await self.redis.xinfo_groups(stream_key)

                for group in groups:
                    if group["name"] != self.consumer_group:
                        continue

                    # Get consumers in this group
                    try:
                        consumers = await self.redis.xinfo_consumers(stream_key, self.consumer_group)

                        for consumer in consumers:
                            consumer_name = consumer["name"]
                            idle_time = consumer.get("idle", 0)

                            # Check if consumer is dead (not in active list and idle > TTL)
                            if consumer_name not in active_consumer_ids and idle_time > (self.ttl * 1000):
                                # Remove dead consumer
                                await self.redis.xgroup_delconsumer(
                                    stream_key,
                                    self.consumer_group,
                                    consumer_name
                                )
                                removed_count += 1
                                logger.info(
                                    f"Removed dead consumer {consumer_name} from {stream_key} "
                                    f"(idle: {idle_time/1000:.1f}s)"
                                )

                    except Exception as e:
                        logger.error(f"Error checking consumers for {stream_key}: {e}")

            except Exception as e:
                logger.error(f"Error checking groups for {stream_key}: {e}")

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} dead consumers")

        return removed_count

    async def get_consumer_stats(self) -> Dict[str, Any]:
        """
        Get statistics about consumer health.

        Returns:
            Dictionary with consumer statistics
        """
        active = await self.get_active_consumers()
        now = time.time()

        stats = {
            "total_active": len(active),
            "consumers": [],
            "oldest_heartbeat": None,
            "newest_heartbeat": None
        }

        for consumer in active:
            last_heartbeat = consumer.get("last_heartbeat", 0)
            age = now - last_heartbeat

            stats["consumers"].append({
                "id": consumer["consumer_id"],
                "hostname": consumer.get("hostname", "unknown"),
                "pid": consumer.get("pid", 0),
                "heartbeat_age": age,
                "healthy": age < self.ttl
            })

            if stats["oldest_heartbeat"] is None or last_heartbeat < stats["oldest_heartbeat"]:
                stats["oldest_heartbeat"] = last_heartbeat

            if stats["newest_heartbeat"] is None or last_heartbeat > stats["newest_heartbeat"]:
                stats["newest_heartbeat"] = last_heartbeat

        return stats


class ConsumerCleanupService:
    """
    Service that periodically cleans up dead consumers.

    This can be run as a separate service or integrated into the main application.
    It ensures the system stays healthy by removing dead consumers that would
    otherwise hold messages indefinitely.
    """

    def __init__(
        self,
        redis: Redis,
        scheduler = None,
        cleanup_interval: int = 30,
        stream_keys: Optional[List[str]] = None
    ):
        """
        Initialize cleanup service.

        Args:
            redis: Redis connection
            scheduler: Event scheduler for lifecycle operations
            cleanup_interval: How often to run cleanup (seconds)
            stream_keys: Stream keys to monitor (auto-discover if not provided)
        """
        self.redis = redis
        self.scheduler = scheduler
        self.cleanup_interval = cleanup_interval
        self.stream_keys = stream_keys or []
        self.lifecycle = ConsumerLifecycle(redis, scheduler)

    async def discover_stream_keys(self) -> List[str]:
        """Discover all Gleitzeit event stream keys."""
        keys = []
        patterns = [
            "gleitzeit:events:*",
            "gleitzeit:stream:*"
        ]

        for pattern in patterns:
            async for key in self.redis.scan_iter(match=pattern):
                # Check if it's actually a stream
                try:
                    await self.redis.xinfo_stream(key)
                    keys.append(key)
                except:
                    pass

        return keys

    async def run_cleanup_once(self) -> int:
        """
        Run cleanup once and return number of consumers removed.

        This is stateless and can be called from external triggers.
        """
        if not self.stream_keys:
            self.stream_keys = await self.discover_stream_keys()

        if not self.stream_keys:
            logger.warning("No stream keys found for cleanup")
            return 0

        return await self.lifecycle.cleanup_dead_consumers(self.stream_keys)

    async def get_health_report(self) -> Dict[str, Any]:
        """
        Get comprehensive health report of consumer groups.

        Returns:
            Health report with consumer and stream statistics
        """
        if not self.stream_keys:
            self.stream_keys = await self.discover_stream_keys()

        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "consumer_stats": await self.lifecycle.get_consumer_stats(),
            "streams": []
        }

        for stream_key in self.stream_keys:
            try:
                info = await self.redis.xinfo_stream(stream_key)
                groups = await self.redis.xinfo_groups(stream_key)

                stream_data = {
                    "key": stream_key,
                    "length": info.get("length", 0),
                    "groups": []
                }

                for group in groups:
                    consumers = await self.redis.xinfo_consumers(stream_key, group["name"])

                    stream_data["groups"].append({
                        "name": group["name"],
                        "pending": group.get("pending", 0),
                        "consumers": len(consumers),
                        "last_delivered_id": group.get("last-delivered-id")
                    })

                report["streams"].append(stream_data)

            except Exception as e:
                logger.error(f"Error getting info for {stream_key}: {e}")

        return report