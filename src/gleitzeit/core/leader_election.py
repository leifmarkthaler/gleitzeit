"""
Atomic leader election using Redis Lua scripts.

Provides race-condition-free leader election for distributed workers.
"""

import logging
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class LeaderStatus(Enum):
    """Leader election status"""
    BECAME_LEADER = "became_leader"
    STILL_LEADER = "still_leader"
    NOT_LEADER = "not_leader"
    LOST_LEADERSHIP = "lost_leadership"


class LeaderElection:
    """
    Atomic leader election using Redis Lua scripts.

    Prevents race conditions and split-brain scenarios.
    """

    # Lua script for atomic leader election
    ELECT_SCRIPT = """
    -- KEYS[1]: leader key
    -- ARGV[1]: worker_id
    -- ARGV[2]: ttl in seconds
    -- Returns: 1 if became/remains leader, 0 otherwise

    local current = redis.call('get', KEYS[1])

    if not current then
        -- No leader, try to become one
        redis.call('setex', KEYS[1], ARGV[2], ARGV[1])
        return 1
    elseif current == ARGV[1] then
        -- We are the current leader, extend TTL
        redis.call('expire', KEYS[1], ARGV[2])
        return 1
    else
        -- Someone else is leader
        return 0
    end
    """

    # Lua script for atomic leadership check and extend
    CHECK_AND_EXTEND_SCRIPT = """
    -- KEYS[1]: leader key
    -- ARGV[1]: worker_id
    -- ARGV[2]: ttl in seconds
    -- Returns: 1 if still leader, 0 if not

    local current = redis.call('get', KEYS[1])

    if current == ARGV[1] then
        -- We are still the leader, extend TTL
        redis.call('expire', KEYS[1], ARGV[2])
        return 1
    else
        return 0
    end
    """

    # Lua script for graceful leadership release
    RELEASE_SCRIPT = """
    -- KEYS[1]: leader key
    -- ARGV[1]: worker_id
    -- Returns: 1 if released, 0 if not our lock

    local current = redis.call('get', KEYS[1])

    if current == ARGV[1] then
        redis.call('del', KEYS[1])
        return 1
    else
        return 0
    end
    """

    def __init__(self, redis_client, leader_key: str, worker_id: str, ttl: int = 30):
        """
        Initialize leader election.

        Args:
            redis_client: Redis client instance
            leader_key: Redis key for leadership
            worker_id: Unique worker identifier
            ttl: Leadership TTL in seconds
        """
        self.redis = redis_client
        self.leader_key = leader_key
        self.worker_id = worker_id
        self.ttl = ttl
        self.is_leader = False

    async def try_elect(self) -> LeaderStatus:
        """
        Try to become leader or extend leadership atomically.

        Returns:
            LeaderStatus indicating the result
        """
        try:
            # Execute atomic election script
            result = await self.redis.eval(
                self.ELECT_SCRIPT,
                1,
                self.leader_key.encode(),
                self.worker_id.encode(),
                str(self.ttl).encode()
            )

            if result == 1:
                if not self.is_leader:
                    self.is_leader = True
                    logger.info(f"Worker {self.worker_id} became leader for {self.leader_key}")
                    return LeaderStatus.BECAME_LEADER
                else:
                    return LeaderStatus.STILL_LEADER
            else:
                if self.is_leader:
                    self.is_leader = False
                    logger.info(f"Worker {self.worker_id} lost leadership for {self.leader_key}")
                    return LeaderStatus.LOST_LEADERSHIP
                else:
                    return LeaderStatus.NOT_LEADER

        except Exception as e:
            logger.error(f"Leader election error for {self.worker_id}: {e}")
            self.is_leader = False
            return LeaderStatus.NOT_LEADER

    async def check_and_extend(self) -> bool:
        """
        Check if still leader and extend TTL atomically.

        Returns:
            True if still leader, False otherwise
        """
        try:
            result = await self.redis.eval(
                self.CHECK_AND_EXTEND_SCRIPT,
                1,
                self.leader_key.encode(),
                self.worker_id.encode(),
                str(self.ttl).encode()
            )

            self.is_leader = (result == 1)
            return self.is_leader

        except Exception as e:
            logger.error(f"Leadership check error for {self.worker_id}: {e}")
            self.is_leader = False
            return False

    async def release(self) -> bool:
        """
        Gracefully release leadership.

        Returns:
            True if leadership was released, False if not leader
        """
        try:
            result = await self.redis.eval(
                self.RELEASE_SCRIPT,
                1,
                self.leader_key.encode(),
                self.worker_id.encode()
            )

            if result == 1:
                self.is_leader = False
                logger.info(f"Worker {self.worker_id} released leadership for {self.leader_key}")
                return True
            return False

        except Exception as e:
            logger.error(f"Leadership release error for {self.worker_id}: {e}")
            return False

    async def get_current_leader(self) -> Optional[str]:
        """
        Get the current leader ID.

        Returns:
            Worker ID of current leader, or None if no leader
        """
        try:
            leader = await self.redis.get(self.leader_key.encode())
            return leader.decode() if leader else None
        except Exception as e:
            logger.error(f"Error getting current leader: {e}")
            return None