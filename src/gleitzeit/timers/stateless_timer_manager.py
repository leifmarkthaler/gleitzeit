"""
Stateless Timer Manager for Gleitzeit

A completely stateless timer manager that processes timers when invoked.
NO loops, NO internal state, NO background tasks.
"""

import json
import logging
import time
import uuid
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import hashlib

logger = logging.getLogger(__name__)


class StatelessTimerManager:
    """
    Completely stateless timer manager.

    All timer state is stored in Redis sorted sets.
    Processing happens only when invoked - no loops!
    """

    # Redis keys for timer management
    PENDING_TIMERS_KEY = "timers:pending"
    ACTIVE_TIMERS_KEY = "timers:active"
    CANCELLED_TIMERS_KEY = "timers:cancelled"
    RECURRING_TIMERS_KEY = "timers:recurring"
    TIMER_METADATA_PREFIX = "timers:meta:"

    @staticmethod
    async def create_timer(
        redis,
        workflow_id: str,
        duration_seconds: float,
        task_id: Optional[str] = None,
        timer_type: str = "delay",
        payload: Optional[Dict[str, Any]] = None,
        timer_id: Optional[str] = None
    ) -> str:
        """
        Create a new timer.

        Args:
            redis: Redis client
            workflow_id: Workflow ID
            duration_seconds: Timer duration in seconds
            task_id: Optional task ID
            timer_type: Type of timer (delay, schedule, recurring)
            payload: Additional timer data
            timer_id: Optional timer ID (generated if not provided)

        Returns:
            Timer ID
        """
        if not timer_id:
            timer_id = f"timer-{workflow_id}-{uuid.uuid4().hex[:8]}"

        scheduled_time = datetime.utcnow() + timedelta(seconds=duration_seconds)

        # Timer data
        timer_data = {
            "timer_id": timer_id,
            "workflow_id": workflow_id,
            "task_id": task_id or "",
            "timer_type": timer_type,
            "duration_seconds": duration_seconds,
            "payload": json.dumps(payload or {}),
            "created_at": datetime.utcnow().isoformat(),
            "scheduled_time": scheduled_time.isoformat(),
            "status": "pending"
        }

        # Store timer metadata
        timer_key = f"{StatelessTimerManager.TIMER_METADATA_PREFIX}{timer_id}"
        await redis.hset(timer_key, mapping=timer_data)

        # Add to pending timers sorted set with scheduled time as score
        await redis.zadd(
            StatelessTimerManager.PENDING_TIMERS_KEY,
            {timer_id: scheduled_time.timestamp()}
        )

        # If recurring, also add to recurring set
        if timer_type == "recurring":
            recurring_data = {
                "timer_id": timer_id,
                "workflow_id": workflow_id,
                "duration_seconds": duration_seconds,
                "payload": json.dumps(payload or {})
            }
            await redis.hset(
                StatelessTimerManager.RECURRING_TIMERS_KEY,
                timer_id,
                json.dumps(recurring_data)
            )

        logger.info(f"Created timer {timer_id} scheduled for {scheduled_time}")
        return timer_id

    @staticmethod
    async def cancel_timer(redis, timer_id: str) -> bool:
        """
        Cancel a timer.

        Args:
            redis: Redis client
            timer_id: Timer ID to cancel

        Returns:
            True if timer was cancelled
        """
        try:
            # Remove from pending timers
            removed = await redis.zrem(StatelessTimerManager.PENDING_TIMERS_KEY, timer_id)

            # Add to cancelled set
            await redis.sadd(StatelessTimerManager.CANCELLED_TIMERS_KEY, timer_id)

            # Update timer metadata
            timer_key = f"{StatelessTimerManager.TIMER_METADATA_PREFIX}{timer_id}"
            await redis.hset(timer_key, "status", "cancelled")

            # Remove from recurring if present
            await redis.hdel(StatelessTimerManager.RECURRING_TIMERS_KEY, timer_id)

            logger.info(f"Cancelled timer {timer_id}")
            return removed > 0

        except Exception as e:
            logger.error(f"Error cancelling timer {timer_id}: {e}")
            return False

    @staticmethod
    async def process_due_timers(redis, max_timers: int = 100) -> Tuple[int, List[Dict]]:
        """
        Process all timers that are due now. NO LOOPS!

        Args:
            redis: Redis client
            max_timers: Maximum timers to process

        Returns:
            Tuple of (processed_count, fired_timer_list)
        """
        current_time = time.time()
        processed = 0
        fired_timers = []

        try:
            # Get all due timers (single Redis call)
            due_timers = await redis.zrangebyscore(
                StatelessTimerManager.PENDING_TIMERS_KEY,
                min=0,
                max=current_time,
                start=0,
                num=max_timers
            )

            if not due_timers:
                return 0, []

            # Process each due timer (bounded iteration, not a loop)
            pipe = redis.pipeline()

            for timer_id in due_timers:
                if isinstance(timer_id, bytes):
                    timer_id = timer_id.decode()

                # Check if cancelled
                is_cancelled = await redis.sismember(
                    StatelessTimerManager.CANCELLED_TIMERS_KEY,
                    timer_id
                )

                if is_cancelled:
                    # Remove from pending and skip
                    pipe.zrem(StatelessTimerManager.PENDING_TIMERS_KEY, timer_id)
                    continue

                # Get timer metadata
                timer_key = f"{StatelessTimerManager.TIMER_METADATA_PREFIX}{timer_id}"
                timer_data = await redis.hgetall(timer_key)

                if not timer_data:
                    # Timer metadata missing, remove from pending
                    pipe.zrem(StatelessTimerManager.PENDING_TIMERS_KEY, timer_id)
                    continue

                # Decode timer data
                decoded_data = {}
                for k, v in timer_data.items():
                    if isinstance(k, bytes):
                        k = k.decode()
                    if isinstance(v, bytes):
                        v = v.decode()
                    decoded_data[k] = v

                # Fire the timer
                decoded_data["fired_at"] = datetime.utcnow().isoformat()
                decoded_data["status"] = "fired"

                fired_timers.append(decoded_data)

                # Update timer status
                pipe.hset(timer_key, "status", "fired")
                pipe.hset(timer_key, "fired_at", decoded_data["fired_at"])

                # Remove from pending
                pipe.zrem(StatelessTimerManager.PENDING_TIMERS_KEY, timer_id)

                # Move to active set
                pipe.zadd(
                    StatelessTimerManager.ACTIVE_TIMERS_KEY,
                    {timer_id: time.time()}
                )

                # Handle recurring timers
                if decoded_data.get("timer_type") == "recurring":
                    # Create next occurrence
                    duration = float(decoded_data.get("duration_seconds", 0))
                    if duration > 0:
                        next_time = datetime.utcnow() + timedelta(seconds=duration)
                        next_timer_id = f"{timer_id}-next-{int(time.time())}"

                        # Add next occurrence
                        pipe.zadd(
                            StatelessTimerManager.PENDING_TIMERS_KEY,
                            {next_timer_id: next_time.timestamp()}
                        )

                        # Copy metadata for next timer
                        next_timer_data = decoded_data.copy()
                        next_timer_data["timer_id"] = next_timer_id
                        next_timer_data["created_at"] = datetime.utcnow().isoformat()
                        next_timer_data["scheduled_time"] = next_time.isoformat()
                        next_timer_data["status"] = "pending"
                        next_timer_data.pop("fired_at", None)

                        next_timer_key = f"{StatelessTimerManager.TIMER_METADATA_PREFIX}{next_timer_id}"
                        for k, v in next_timer_data.items():
                            pipe.hset(next_timer_key, k, v)

                processed += 1

            # Execute pipeline (single round trip)
            await pipe.execute()

            logger.info(f"Processed {processed} due timers")

        except Exception as e:
            logger.error(f"Error processing due timers: {e}")

        return processed, fired_timers

    @staticmethod
    async def get_timer_status(redis, timer_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a timer.

        Args:
            redis: Redis client
            timer_id: Timer ID

        Returns:
            Timer status data or None
        """
        timer_key = f"{StatelessTimerManager.TIMER_METADATA_PREFIX}{timer_id}"
        timer_data = await redis.hgetall(timer_key)

        if not timer_data:
            return None

        # Decode data
        decoded_data = {}
        for k, v in timer_data.items():
            if isinstance(k, bytes):
                k = k.decode()
            if isinstance(v, bytes):
                v = v.decode()
            decoded_data[k] = v

        # Check if in cancelled set
        is_cancelled = await redis.sismember(
            StatelessTimerManager.CANCELLED_TIMERS_KEY,
            timer_id
        )

        if is_cancelled:
            decoded_data["status"] = "cancelled"

        # Check if pending
        score = await redis.zscore(StatelessTimerManager.PENDING_TIMERS_KEY, timer_id)
        if score:
            decoded_data["scheduled_timestamp"] = score
            decoded_data["is_due"] = score <= time.time()

        return decoded_data

    @staticmethod
    async def get_timer_stats(redis) -> Dict[str, Any]:
        """
        Get timer statistics. Single invocation, no loops.

        Args:
            redis: Redis client

        Returns:
            Timer statistics
        """
        try:
            # Use pipeline for single round trip
            pipe = redis.pipeline()
            pipe.zcard(StatelessTimerManager.PENDING_TIMERS_KEY)
            pipe.zcard(StatelessTimerManager.ACTIVE_TIMERS_KEY)
            pipe.scard(StatelessTimerManager.CANCELLED_TIMERS_KEY)
            pipe.hlen(StatelessTimerManager.RECURRING_TIMERS_KEY)

            results = await pipe.execute()

            # Get next due timer
            next_timer = await redis.zrange(
                StatelessTimerManager.PENDING_TIMERS_KEY,
                0, 0,
                withscores=True
            )

            next_due = None
            if next_timer:
                timer_id, score = next_timer[0]
                next_due = datetime.fromtimestamp(score).isoformat()

            # Count due timers
            current_time = time.time()
            due_count = await redis.zcount(
                StatelessTimerManager.PENDING_TIMERS_KEY,
                min=0,
                max=current_time
            )

            return {
                "pending_count": results[0],
                "active_count": results[1],
                "cancelled_count": results[2],
                "recurring_count": results[3],
                "due_count": due_count,
                "next_due": next_due
            }

        except Exception as e:
            logger.error(f"Error getting timer stats: {e}")
            return {}

    @staticmethod
    async def cleanup_old_timers(redis, days_old: int = 7) -> int:
        """
        Clean up old fired/cancelled timers. NO LOOPS!

        Args:
            redis: Redis client
            days_old: Remove timers older than this many days

        Returns:
            Number of timers cleaned up
        """
        cutoff_time = time.time() - (days_old * 24 * 3600)
        cleaned = 0

        try:
            # Remove old active timers
            removed = await redis.zremrangebyscore(
                StatelessTimerManager.ACTIVE_TIMERS_KEY,
                min=0,
                max=cutoff_time
            )
            cleaned += removed

            # Get cancelled timers to check age
            cancelled = await redis.smembers(StatelessTimerManager.CANCELLED_TIMERS_KEY)

            pipe = redis.pipeline()
            for timer_id in cancelled:
                if isinstance(timer_id, bytes):
                    timer_id = timer_id.decode()

                # Check timer age
                timer_key = f"{StatelessTimerManager.TIMER_METADATA_PREFIX}{timer_id}"
                created_at = await redis.hget(timer_key, "created_at")

                if created_at:
                    if isinstance(created_at, bytes):
                        created_at = created_at.decode()

                    try:
                        created_time = datetime.fromisoformat(created_at).timestamp()
                        if created_time < cutoff_time:
                            # Remove old cancelled timer
                            pipe.srem(StatelessTimerManager.CANCELLED_TIMERS_KEY, timer_id)
                            pipe.delete(timer_key)
                            cleaned += 1
                    except:
                        pass

            await pipe.execute()

            logger.info(f"Cleaned up {cleaned} old timers")

        except Exception as e:
            logger.error(f"Error cleaning up timers: {e}")

        return cleaned

    @staticmethod
    async def process_all_once(redis, max_timers: int = 100) -> Dict[str, Any]:
        """
        Process all timer operations once. NO LOOPS!

        This is the main entry point for stateless processing.

        Args:
            redis: Redis client
            max_timers: Maximum timers to process

        Returns:
            Processing summary
        """
        # Process due timers (no loop, just one call)
        processed, fired_timers = await StatelessTimerManager.process_due_timers(redis, max_timers)

        # Get current stats (single call)
        stats = await StatelessTimerManager.get_timer_stats(redis)

        return {
            "processed": processed,
            "fired_timers": fired_timers,
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }


# Pure function entry points

async def process_timers(redis) -> int:
    """
    Process timers once - no state, no loops.

    Args:
        redis: Redis client

    Returns:
        Number of timers processed
    """
    result = await StatelessTimerManager.process_all_once(redis)
    return result['processed']


# Kubernetes CronJob entry point
async def kubernetes_cronjob_main():
    """
    Entry point for Kubernetes CronJob - process once and exit.
    """
    import os
    import aioredis

    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    redis = await aioredis.from_url(redis_url)

    try:
        processed = await process_timers(redis)
        print(f"Processed {processed} timers")
        return 0
    finally:
        await redis.close()


# AWS Lambda handler
def lambda_handler(event, context):
    """
    AWS Lambda handler for timer processing.
    """
    import asyncio
    import aioredis

    redis_url = event.get('redis_url', 'redis://localhost:6379')

    async def process():
        redis = await aioredis.from_url(redis_url)
        try:
            result = await StatelessTimerManager.process_all_once(redis)
            return result
        finally:
            await redis.close()

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(process())

    return {
        'statusCode': 200,
        'body': json.dumps(result)
    }


# CLI for manual execution
if __name__ == "__main__":
    import asyncio
    import sys
    import aioredis

    async def main():
        redis = await aioredis.from_url('redis://localhost:6379')
        try:
            result = await StatelessTimerManager.process_all_once(redis)
            print(f"Timer processing result: {json.dumps(result, indent=2)}")
            return 0
        finally:
            await redis.close()

    sys.exit(asyncio.run(main()))