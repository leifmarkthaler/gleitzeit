"""
External Trigger Mechanisms for Stateless Event Processing.

This module provides various ways to trigger stateless event consumers
without using persistent loops, enabling true horizontal scaling.
"""

import asyncio
import logging
import json
import time
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, BackgroundTasks
from redis.asyncio import Redis

from gleitzeit.events.stateless_event_consumer import (
    StatelessEventConsumer,
    StatelessEventProcessor
)

logger = logging.getLogger(__name__)


class WebhookTrigger:
    """
    HTTP webhook endpoint for triggering event processing.

    This can be called by:
    - External schedulers (cron, Kubernetes CronJob)
    - Monitoring systems
    - Cloud functions
    - Manual triggers
    """

    def __init__(self, consumer: StatelessEventConsumer):
        """
        Initialize webhook trigger.

        Args:
            consumer: Stateless consumer to trigger
        """
        self.consumer = consumer
        self.processor = StatelessEventProcessor(consumer)
        self.router = self._create_router()

    def _create_router(self) -> APIRouter:
        """Create FastAPI router with trigger endpoints."""
        router = APIRouter(prefix="/triggers", tags=["Event Triggers"])

        @router.post("/process")
        async def trigger_processing(
            max_messages: int = 100,
            duration_seconds: Optional[int] = None
        ):
            """
            Trigger event processing via HTTP.

            Args:
                max_messages: Maximum messages to process
                duration_seconds: Optional duration to process for

            Returns:
                Processing statistics
            """
            try:
                if duration_seconds:
                    # Process for duration
                    stats = await self.processor.trigger_for_duration(
                        duration_seconds
                    )
                else:
                    # Single trigger
                    stats = await self.processor.trigger_once()

                return {
                    "status": "success",
                    "statistics": stats,
                    "timestamp": datetime.utcnow().isoformat()
                }

            except Exception as e:
                logger.error(f"Webhook trigger error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/claim-idle")
        async def trigger_idle_claim(
            idle_time_seconds: int = 60,
            max_messages: int = 100
        ):
            """
            Trigger claiming of idle messages.

            Args:
                idle_time_seconds: How long messages must be idle
                max_messages: Maximum messages to claim

            Returns:
                Number of messages claimed
            """
            try:
                claimed = await self.consumer.claim_idle_messages(
                    idle_time_ms=idle_time_seconds * 1000,
                    max_messages=max_messages
                )

                return {
                    "status": "success",
                    "claimed": claimed,
                    "timestamp": datetime.utcnow().isoformat()
                }

            except Exception as e:
                logger.error(f"Idle claim trigger error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/health")
        async def check_health():
            """Check consumer health."""
            return {
                "status": "healthy",
                "consumer_id": self.consumer.consumer_id,
                "instance_id": self.consumer.instance_id,
                "consumer_group": self.consumer.consumer_group,
                "handlers_registered": len(self.consumer._handlers),
                "timestamp": datetime.utcnow().isoformat()
            }

        return router


class RedisTrigger:
    """
    Redis-based trigger using pub/sub or streams.

    This allows triggering from other services via Redis.
    """

    def __init__(
        self,
        consumer: StatelessEventConsumer,
        redis: Redis,
        trigger_channel: str = "gleitzeit:triggers:process"
    ):
        """
        Initialize Redis trigger.

        Args:
            consumer: Stateless consumer to trigger
            redis: Redis connection
            trigger_channel: Channel to listen for triggers
        """
        self.consumer = consumer
        self.processor = StatelessEventProcessor(consumer)
        self.redis = redis
        self.trigger_channel = trigger_channel

    async def listen_for_triggers(self):
        """
        Listen for trigger messages (single execution).

        This processes ONE trigger and returns.
        """
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.trigger_channel)

        try:
            # Wait for ONE message
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0
            )

            if message and message['type'] == 'message':
                await self._handle_trigger(message['data'])

        finally:
            await pubsub.unsubscribe(self.trigger_channel)
            await pubsub.close()

    async def _handle_trigger(self, data: bytes):
        """Handle trigger message."""
        try:
            # Parse trigger data
            trigger_data = json.loads(data.decode('utf-8'))

            action = trigger_data.get('action', 'process')

            if action == 'process':
                stats = await self.processor.trigger_once()
                logger.info(f"Redis trigger processed: {stats}")

            elif action == 'claim_idle':
                claimed = await self.consumer.claim_idle_messages()
                logger.info(f"Redis trigger claimed {claimed} idle messages")

        except Exception as e:
            logger.error(f"Redis trigger error: {e}")

    @staticmethod
    async def send_trigger(
        redis: Redis,
        action: str = 'process',
        channel: str = "gleitzeit:triggers:process"
    ):
        """
        Send a trigger via Redis.

        Args:
            redis: Redis connection
            action: Action to trigger
            channel: Channel to send on
        """
        trigger_data = {
            'action': action,
            'timestamp': datetime.utcnow().isoformat()
        }

        await redis.publish(
            channel,
            json.dumps(trigger_data)
        )


class TimerTrigger:
    """
    Timer-based trigger using Redis for coordination.

    This provides scheduled processing without persistent loops.
    """

    def __init__(
        self,
        consumer: StatelessEventConsumer,
        redis: Redis
    ):
        """
        Initialize timer trigger.

        Args:
            consumer: Stateless consumer
            redis: Redis for coordination
        """
        self.consumer = consumer
        self.processor = StatelessEventProcessor(consumer)
        self.redis = redis

    async def check_and_trigger(
        self,
        trigger_key: str = "gleitzeit:triggers:timer",
        interval_seconds: int = 60
    ) -> bool:
        """
        Check if it's time to trigger and do so if needed.

        This uses Redis to coordinate between instances.

        Args:
            trigger_key: Redis key for coordination
            interval_seconds: Minimum interval between triggers

        Returns:
            True if triggered, False if skipped
        """
        # Try to acquire trigger lock
        lock_key = f"{trigger_key}:lock"
        lock_acquired = await self.redis.set(
            lock_key,
            self.consumer.instance_id,
            nx=True,  # Only set if not exists
            ex=30  # 30 second lock expiry
        )

        if not lock_acquired:
            logger.debug("Another instance is processing")
            return False

        try:
            # Check last trigger time
            last_trigger_key = f"{trigger_key}:last"
            last_trigger = await self.redis.get(last_trigger_key)

            if last_trigger:
                last_time = float(last_trigger)
                if time.time() - last_time < interval_seconds:
                    logger.debug("Not enough time since last trigger")
                    return False

            # Perform trigger
            stats = await self.processor.trigger_once()

            # Update last trigger time
            await self.redis.set(
                last_trigger_key,
                str(time.time()),
                ex=interval_seconds * 2  # Expire after 2x interval
            )

            logger.info(f"Timer trigger completed: {stats}")
            return True

        finally:
            # Release lock
            await self.redis.delete(lock_key)


class LambdaTrigger:
    """
    Trigger designed for serverless functions (AWS Lambda, etc).

    Optimized for time-limited execution environments.
    """

    def __init__(
        self,
        consumer: StatelessEventConsumer,
        max_duration_seconds: int = 300  # 5 minutes default
    ):
        """
        Initialize Lambda trigger.

        Args:
            consumer: Stateless consumer
            max_duration_seconds: Maximum execution time
        """
        self.consumer = consumer
        self.processor = StatelessEventProcessor(consumer)
        self.max_duration = max_duration_seconds

    async def handler(self, event: Dict, context: Any) -> Dict:
        """
        Lambda handler function.

        Args:
            event: Lambda event data
            context: Lambda context

        Returns:
            Response with processing statistics
        """
        start_time = time.time()

        # Initialize consumer
        await self.consumer.initialize()

        try:
            # Calculate safe duration (leave 10s buffer)
            remaining_time = context.get_remaining_time_in_millis() / 1000
            safe_duration = min(
                self.max_duration,
                remaining_time - 10
            )

            # Process for duration
            stats = await self.processor.trigger_for_duration(
                int(safe_duration)
            )

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'success',
                    'statistics': stats,
                    'duration': time.time() - start_time
                })
            }

        except Exception as e:
            logger.error(f"Lambda trigger error: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'status': 'error',
                    'error': str(e)
                })
            }

        finally:
            # Cleanup
            await self.consumer.shutdown()


class KubernetesCronJobTrigger:
    """
    Trigger designed for Kubernetes CronJob execution.

    Runs as a one-shot job that processes and exits.
    """

    def __init__(
        self,
        consumer: StatelessEventConsumer,
        process_duration_seconds: int = 60
    ):
        """
        Initialize K8s CronJob trigger.

        Args:
            consumer: Stateless consumer
            process_duration_seconds: How long to process
        """
        self.consumer = consumer
        self.processor = StatelessEventProcessor(consumer)
        self.duration = process_duration_seconds

    async def run(self) -> int:
        """
        Run the job and exit.

        Returns:
            Exit code (0 for success)
        """
        try:
            # Initialize
            await self.consumer.initialize()

            # Process for duration
            stats = await self.processor.trigger_for_duration(
                self.duration
            )

            logger.info(f"CronJob completed: {stats}")

            # Cleanup
            await self.consumer.shutdown()

            return 0  # Success

        except Exception as e:
            logger.error(f"CronJob error: {e}")
            return 1  # Failure


def create_trigger_from_env() -> Optional[Any]:
    """
    Create appropriate trigger based on environment.

    Returns:
        Configured trigger or None
    """
    import os

    trigger_type = os.environ.get('GLEITZEIT_TRIGGER_TYPE', 'webhook')

    if trigger_type == 'lambda':
        # Running in Lambda
        from gleitzeit.events.stateless_event_consumer import StatelessEventConsumer
        consumer = StatelessEventConsumer(redis_client=None)  # Configure
        return LambdaTrigger(consumer)

    elif trigger_type == 'k8s_cronjob':
        # Running as K8s CronJob
        from gleitzeit.events.stateless_event_consumer import StatelessEventConsumer
        consumer = StatelessEventConsumer(redis_client=None)  # Configure
        return KubernetesCronJobTrigger(consumer)

    elif trigger_type == 'webhook':
        # Default webhook
        from gleitzeit.events.stateless_event_consumer import StatelessEventConsumer
        consumer = StatelessEventConsumer(redis_client=None)  # Configure
        return WebhookTrigger(consumer)

    return None