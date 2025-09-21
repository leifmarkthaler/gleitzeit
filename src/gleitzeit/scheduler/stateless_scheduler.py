"""
Stateless Event Scheduler for Gleitzeit

A completely stateless scheduler that processes scheduled events when invoked.
NO loops, NO internal state, NO background tasks.
"""

import json
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import hashlib

logger = logging.getLogger(__name__)


class StatelessScheduler:
    """
    Completely stateless event scheduler.

    All scheduling state is stored in Redis sorted sets.
    Processing happens only when invoked - no loops!
    """

    # Redis keys for scheduling
    SCHEDULED_EVENTS_KEY = "scheduler:events:scheduled"
    IMMEDIATE_EVENTS_KEY = "scheduler:events:immediate"
    RETRY_EVENTS_KEY = "scheduler:events:retry"
    RECURRING_EVENTS_KEY = "scheduler:events:recurring"

    @staticmethod
    async def schedule_event(
        redis,
        event_id: str,
        event_data: Dict[str, Any],
        execute_at: datetime,
        recurring: bool = False,
        interval_seconds: Optional[int] = None
    ) -> str:
        """
        Schedule an event for future execution.

        Args:
            redis: Redis client
            event_id: Unique event ID
            event_data: Event data to store
            execute_at: When to execute the event
            recurring: Whether this is a recurring event
            interval_seconds: Interval for recurring events

        Returns:
            Event ID
        """
        timestamp = execute_at.timestamp()

        # Store event data
        event_json = json.dumps({
            "id": event_id,
            "data": event_data,
            "scheduled_at": datetime.utcnow().isoformat(),
            "execute_at": execute_at.isoformat(),
            "recurring": recurring,
            "interval_seconds": interval_seconds
        })

        # Add to scheduled set with timestamp as score
        await redis.zadd(
            StatelessScheduler.SCHEDULED_EVENTS_KEY,
            {event_json: timestamp}
        )

        # If recurring, also store in recurring set
        if recurring and interval_seconds:
            await redis.hset(
                StatelessScheduler.RECURRING_EVENTS_KEY,
                event_id,
                json.dumps({
                    "interval_seconds": interval_seconds,
                    "last_executed": None,
                    "event_data": event_data
                })
            )

        logger.info(f"Scheduled event {event_id} for {execute_at}")
        return event_id

    @staticmethod
    async def process_due_events(redis, max_events: int = 100) -> Tuple[int, List[Dict]]:
        """
        Process all events that are due now. NO LOOPS!

        Args:
            redis: Redis client
            max_events: Maximum events to process

        Returns:
            Tuple of (processed_count, event_list)
        """
        current_time = time.time()
        processed = 0
        events = []

        try:
            # Get all due events (single Redis call)
            due_events = await redis.zrangebyscore(
                StatelessScheduler.SCHEDULED_EVENTS_KEY,
                min=0,
                max=current_time,
                withscores=True,
                start=0,
                num=max_events
            )

            if not due_events:
                return 0, []

            # Process each due event (bounded iteration, not a loop)
            pipe = redis.pipeline()
            for event_json, score in due_events:
                if isinstance(event_json, bytes):
                    event_json = event_json.decode()

                event = json.loads(event_json)
                events.append(event)

                # Remove from scheduled set
                pipe.zrem(StatelessScheduler.SCHEDULED_EVENTS_KEY, event_json)

                # If recurring, reschedule
                if event.get('recurring') and event.get('interval_seconds'):
                    next_time = datetime.utcnow() + timedelta(seconds=event['interval_seconds'])
                    next_event = {
                        **event,
                        "execute_at": next_time.isoformat()
                    }
                    pipe.zadd(
                        StatelessScheduler.SCHEDULED_EVENTS_KEY,
                        {json.dumps(next_event): next_time.timestamp()}
                    )

                processed += 1

            # Execute pipeline (single round trip)
            await pipe.execute()

            logger.info(f"Processed {processed} due events")

        except Exception as e:
            logger.error(f"Error processing due events: {e}")

        return processed, events

    @staticmethod
    async def add_immediate_event(redis, event_data: Dict[str, Any]) -> str:
        """
        Add an event for immediate processing.

        Args:
            redis: Redis client
            event_data: Event data

        Returns:
            Event ID
        """
        event_id = hashlib.md5(
            f"{time.time()}-{json.dumps(event_data)}".encode()
        ).hexdigest()[:16]

        event_json = json.dumps({
            "id": event_id,
            "data": event_data,
            "created_at": datetime.utcnow().isoformat()
        })

        # Add with current timestamp
        await redis.zadd(
            StatelessScheduler.IMMEDIATE_EVENTS_KEY,
            {event_json: time.time()}
        )

        return event_id

    @staticmethod
    async def process_immediate_events(redis, max_events: int = 100) -> Tuple[int, List[Dict]]:
        """
        Process immediate events. NO LOOPS!

        Args:
            redis: Redis client
            max_events: Maximum events to process

        Returns:
            Tuple of (processed_count, event_list)
        """
        processed = 0
        events = []

        try:
            # Get all immediate events (single Redis call)
            immediate_events = await redis.zrange(
                StatelessScheduler.IMMEDIATE_EVENTS_KEY,
                0,
                max_events - 1,
                withscores=False
            )

            if not immediate_events:
                return 0, []

            # Process and remove (bounded iteration)
            pipe = redis.pipeline()
            for event_json in immediate_events:
                if isinstance(event_json, bytes):
                    event_json = event_json.decode()

                event = json.loads(event_json)
                events.append(event)

                # Remove from immediate set
                pipe.zrem(StatelessScheduler.IMMEDIATE_EVENTS_KEY, event_json)
                processed += 1

            # Execute pipeline (single round trip)
            await pipe.execute()

            logger.info(f"Processed {processed} immediate events")

        except Exception as e:
            logger.error(f"Error processing immediate events: {e}")

        return processed, events

    @staticmethod
    async def schedule_retry(
        redis,
        event_data: Dict[str, Any],
        retry_after: datetime,
        attempt: int = 1
    ) -> str:
        """
        Schedule an event for retry.

        Args:
            redis: Redis client
            event_data: Event data
            retry_after: When to retry
            attempt: Retry attempt number

        Returns:
            Event ID
        """
        event_id = event_data.get('id', hashlib.md5(
            f"{time.time()}-retry".encode()
        ).hexdigest()[:16])

        retry_json = json.dumps({
            "id": event_id,
            "data": event_data,
            "retry_attempt": attempt,
            "retry_after": retry_after.isoformat(),
            "created_at": datetime.utcnow().isoformat()
        })

        # Add to retry set with retry timestamp
        await redis.zadd(
            StatelessScheduler.RETRY_EVENTS_KEY,
            {retry_json: retry_after.timestamp()}
        )

        logger.info(f"Scheduled retry for event {event_id} at {retry_after}")
        return event_id

    @staticmethod
    async def process_retry_events(redis, max_events: int = 100) -> Tuple[int, List[Dict]]:
        """
        Process retry events that are due. NO LOOPS!

        Args:
            redis: Redis client
            max_events: Maximum events to process

        Returns:
            Tuple of (processed_count, event_list)
        """
        current_time = time.time()
        processed = 0
        events = []

        try:
            # Get due retry events (single Redis call)
            retry_events = await redis.zrangebyscore(
                StatelessScheduler.RETRY_EVENTS_KEY,
                min=0,
                max=current_time,
                withscores=False,
                start=0,
                num=max_events
            )

            if not retry_events:
                return 0, []

            # Process and remove (bounded iteration)
            pipe = redis.pipeline()
            for event_json in retry_events:
                if isinstance(event_json, bytes):
                    event_json = event_json.decode()

                event = json.loads(event_json)
                events.append(event)

                # Remove from retry set
                pipe.zrem(StatelessScheduler.RETRY_EVENTS_KEY, event_json)
                processed += 1

            # Execute pipeline (single round trip)
            await pipe.execute()

            logger.info(f"Processed {processed} retry events")

        except Exception as e:
            logger.error(f"Error processing retry events: {e}")

        return processed, events

    @staticmethod
    async def get_scheduler_stats(redis) -> Dict[str, Any]:
        """
        Get scheduler statistics. Single invocation, no loops.

        Args:
            redis: Redis client

        Returns:
            Scheduler statistics
        """
        try:
            # Use pipeline for single round trip
            pipe = redis.pipeline()
            pipe.zcard(StatelessScheduler.SCHEDULED_EVENTS_KEY)
            pipe.zcard(StatelessScheduler.IMMEDIATE_EVENTS_KEY)
            pipe.zcard(StatelessScheduler.RETRY_EVENTS_KEY)
            pipe.hlen(StatelessScheduler.RECURRING_EVENTS_KEY)

            results = await pipe.execute()

            # Get next due event
            next_event = await redis.zrange(
                StatelessScheduler.SCHEDULED_EVENTS_KEY,
                0, 0,
                withscores=True
            )

            next_due = None
            if next_event:
                _, score = next_event[0]
                next_due = datetime.fromtimestamp(score).isoformat()

            return {
                "scheduled_count": results[0],
                "immediate_count": results[1],
                "retry_count": results[2],
                "recurring_count": results[3],
                "total_pending": sum(results[:3]),
                "next_due": next_due
            }

        except Exception as e:
            logger.error(f"Error getting scheduler stats: {e}")
            return {}

    @staticmethod
    async def process_all_once(redis, max_events: int = 100) -> Dict[str, Any]:
        """
        Process all types of events once. NO LOOPS!

        This is the main entry point for stateless processing.

        Args:
            redis: Redis client
            max_events: Maximum events to process

        Returns:
            Processing summary
        """
        # Process each type (no loops, just sequential calls)
        due_count, due_events = await StatelessScheduler.process_due_events(redis, max_events // 3)
        immediate_count, immediate_events = await StatelessScheduler.process_immediate_events(redis, max_events // 3)
        retry_count, retry_events = await StatelessScheduler.process_retry_events(redis, max_events // 3)

        total = due_count + immediate_count + retry_count

        return {
            "total_processed": total,
            "due_processed": due_count,
            "immediate_processed": immediate_count,
            "retry_processed": retry_count,
            "events": {
                "due": due_events,
                "immediate": immediate_events,
                "retry": retry_events
            },
            "timestamp": datetime.utcnow().isoformat()
        }


# Pure function entry points

async def process_scheduled_events(redis) -> int:
    """
    Process scheduled events once - no state, no loops.

    Args:
        redis: Redis client

    Returns:
        Number of events processed
    """
    result = await StatelessScheduler.process_all_once(redis, max_events=100)
    return result['total_processed']


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
        processed = await process_scheduled_events(redis)
        print(f"Processed {processed} scheduled events")
        return 0
    finally:
        await redis.close()


# AWS Lambda handler for scheduled processing
def lambda_handler(event, context):
    """
    AWS Lambda handler for scheduled event processing.
    """
    import asyncio
    import aioredis

    redis_url = event.get('redis_url', 'redis://localhost:6379')

    async def process():
        redis = await aioredis.from_url(redis_url)
        try:
            result = await StatelessScheduler.process_all_once(redis)
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
            result = await StatelessScheduler.process_all_once(redis)
            print(f"Processed events: {json.dumps(result, indent=2)}")
            return 0
        finally:
            await redis.close()

    sys.exit(asyncio.run(main()))