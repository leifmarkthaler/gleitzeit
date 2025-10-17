"""
Reconciliation Worker Sharding - Distributes reconciliation work across instances.

This module implements shard assignment for reconciliation workers, ensuring that
when multiple instances run, each processes a subset of the 16 workflow shards.
This prevents duplicate work and reduces Redis load.

Key features:
- Automatic shard assignment based on active instances
- Dynamic rebalancing when instances join/leave
- Shard ownership locks to prevent duplicate processing
- Heartbeat mechanism for instance registration
"""

import asyncio
import json
import logging
import time
from typing import List, Set, Dict, Optional

import redis.asyncio as aioredis

from gleitzeit.core.instance import get_current_instance

logger = logging.getLogger(__name__)


class ReconciliationShardAssignment:
    """Manages shard assignment for reconciliation workers"""

    def __init__(
        self,
        redis: aioredis.Redis,
        total_shards: int = 16,
        heartbeat_interval: int = 30
    ):
        self.redis = redis
        self.total_shards = total_shards
        self.heartbeat_interval = heartbeat_interval

        # Get current instance ID
        instance = get_current_instance()
        if not instance:
            # Fallback: Generate a unique ID for this worker process
            # This shouldn't happen in normal operation, but makes the worker resilient
            import uuid
            import socket
            hostname = socket.gethostname()
            self.instance_id = f"reconciliation-{hostname}-{uuid.uuid4().hex[:8]}"
            logger.warning(
                f"Instance identity not initialized, using generated ID: {self.instance_id}"
            )
        else:
            self.instance_id = instance.instance_id

        self.assignment_key = "global:reconciliation:shard_assignment"
        self.assigned_shards: List[int] = []
        self._last_known_instances: Set[str] = set()
        self.running = False

    async def get_assigned_shards(self) -> List[int]:
        """Get shards assigned to this instance"""

        # Step 1: Register this instance
        await self._register_instance()

        # Step 2: Get all active instances
        active_instances = await self._get_active_instances()

        # Step 3: Calculate shard distribution
        num_instances = len(active_instances)
        shards_per_instance = self.total_shards // num_instances
        remainder = self.total_shards % num_instances

        # Step 4: Sort instances for consistent ordering
        sorted_instances = sorted(active_instances)
        instance_index = sorted_instances.index(self.instance_id)

        # Step 5: Assign shards
        start_shard = instance_index * shards_per_instance
        end_shard = start_shard + shards_per_instance

        # Distribute remainder shards to first N instances
        if instance_index < remainder:
            start_shard += instance_index
            end_shard += instance_index + 1
        else:
            start_shard += remainder
            end_shard += remainder

        assigned_shards = list(range(start_shard, end_shard))

        # Log if assignment changed
        if assigned_shards != self.assigned_shards:
            logger.info(
                f"Reconciliation worker shard assignment changed: "
                f"{self.assigned_shards} -> {assigned_shards} "
                f"({num_instances} instances)"
            )
            self.assigned_shards = assigned_shards

        return assigned_shards

    async def _register_instance(self):
        """Register this instance as active reconciliation worker"""
        key = f"{self.assignment_key}:{self.instance_id}"
        await self.redis.setex(
            key,
            self.heartbeat_interval * 2,  # 2x heartbeat for safety
            json.dumps({
                'instance_id': self.instance_id,
                'timestamp': time.time()
            })
        )

    async def _get_active_instances(self) -> List[str]:
        """Get all active reconciliation worker instances"""
        pattern = f"{self.assignment_key}:*"
        keys = await self.redis.keys(pattern)

        instances = []
        for key in keys:
            # Decode key if bytes
            key_str = key.decode() if isinstance(key, bytes) else key
            instance_id = key_str.split(":")[-1]
            instances.append(instance_id)

        return instances

    async def detect_rebalance(self) -> bool:
        """Detect if rebalancing is needed"""
        current_instances = set(await self._get_active_instances())

        if current_instances != self._last_known_instances:
            logger.info(
                f"Instance count changed: {len(self._last_known_instances)} -> "
                f"{len(current_instances)}"
            )
            self._last_known_instances = current_instances
            return True

        return False

    async def start_heartbeat(self):
        """Maintain instance registration via periodic heartbeat"""
        self.running = True
        logger.info(f"Starting reconciliation shard assignment heartbeat (interval={self.heartbeat_interval}s)")

        while self.running:
            try:
                await self._register_instance()

                # Check if rebalancing needed
                if await self.detect_rebalance():
                    # Refresh shard assignment
                    await self.get_assigned_shards()

            except Exception as e:
                logger.error(f"Error in shard assignment heartbeat: {e}")

            await asyncio.sleep(self.heartbeat_interval)

    async def stop_heartbeat(self):
        """Stop the heartbeat loop"""
        self.running = False
        logger.info("Stopping reconciliation shard assignment heartbeat")

        # Unregister this instance
        key = f"{self.assignment_key}:{self.instance_id}"
        await self.redis.delete(key)

    async def acquire_shard_lock(self, shard: int, ttl: int = 90) -> bool:
        """
        Acquire lock for processing a specific shard.

        Args:
            shard: Shard number to lock
            ttl: Lock TTL in seconds

        Returns:
            True if lock acquired, False otherwise
        """
        lock_key = f"reconciliation:shard:{shard}:lock"
        acquired = await self.redis.set(
            lock_key,
            self.instance_id,
            nx=True,  # Only set if not exists
            ex=ttl  # Expiry
        )

        return bool(acquired)

    async def release_shard_lock(self, shard: int):
        """
        Release lock for a specific shard.

        Only releases if we still own the lock.
        """
        lock_key = f"reconciliation:shard:{shard}:lock"

        # Check if we still own the lock
        current_owner = await self.redis.get(lock_key)
        if current_owner:
            if isinstance(current_owner, bytes):
                current_owner = current_owner.decode()

            if current_owner == self.instance_id:
                await self.redis.delete(lock_key)
                return True

        return False

    def get_stats(self) -> Dict[str, any]:
        """Get shard assignment statistics"""
        return {
            'instance_id': self.instance_id,
            'assigned_shards': self.assigned_shards,
            'num_assigned_shards': len(self.assigned_shards),
            'total_shards': self.total_shards,
            'num_instances': len(self._last_known_instances),
            'heartbeat_interval': self.heartbeat_interval
        }
