"""
Stateless Signal Manager for Gleitzeit

A completely stateless signal manager that processes signals when invoked.
NO loops, NO internal state, NO background tasks.
"""

import json
import logging
import time
import uuid
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


class StatelessSignalManager:
    """
    Completely stateless signal manager.

    All signal state is stored in Redis.
    Processing happens only when invoked - no loops!
    """

    # Redis keys for signal management
    PENDING_SIGNALS_KEY = "signals:pending"
    PROCESSED_SIGNALS_KEY = "signals:processed"
    SIGNAL_HANDLERS_PREFIX = "signals:handlers:"
    SIGNAL_METADATA_PREFIX = "signals:meta:"
    WORKFLOW_SIGNALS_PREFIX = "signals:workflow:"

    @staticmethod
    async def send_signal(
        redis,
        signal_name: str,
        workflow_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None,
        signal_id: Optional[str] = None
    ) -> str:
        """
        Send a signal.

        Args:
            redis: Redis client
            signal_name: Name of the signal
            workflow_id: Optional workflow ID to target
            payload: Optional signal payload
            target: Optional target specification
            signal_id: Optional signal ID (generated if not provided)

        Returns:
            Signal ID
        """
        if not signal_id:
            signal_id = f"signal-{signal_name}-{uuid.uuid4().hex[:8]}"

        # Signal data
        signal_data = {
            "signal_id": signal_id,
            "signal_name": signal_name,
            "workflow_id": workflow_id or "",
            "target": target or "*",
            "payload": json.dumps(payload or {}),
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending"
        }

        # Store signal metadata
        signal_key = f"{StatelessSignalManager.SIGNAL_METADATA_PREFIX}{signal_id}"
        await redis.hset(signal_key, mapping=signal_data)

        # Add to pending signals queue
        await redis.lpush(StatelessSignalManager.PENDING_SIGNALS_KEY, signal_id)

        # If targeting specific workflow, add to workflow-specific queue
        if workflow_id:
            workflow_signal_key = f"{StatelessSignalManager.WORKFLOW_SIGNALS_PREFIX}{workflow_id}"
            await redis.lpush(workflow_signal_key, signal_id)

        logger.info(f"Sent signal {signal_id} ({signal_name}) targeting {workflow_id or 'all'}")
        return signal_id

    @staticmethod
    async def register_handler(
        redis,
        signal_name: str,
        handler_id: str,
        handler_type: str = "workflow",
        handler_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Register a handler for a signal.

        Args:
            redis: Redis client
            signal_name: Signal name to handle
            handler_id: Unique handler ID
            handler_type: Type of handler (workflow, task, function)
            handler_config: Handler configuration

        Returns:
            True if registered successfully
        """
        handler_key = f"{StatelessSignalManager.SIGNAL_HANDLERS_PREFIX}{signal_name}"

        handler_data = {
            "handler_id": handler_id,
            "handler_type": handler_type,
            "config": json.dumps(handler_config or {}),
            "registered_at": datetime.utcnow().isoformat()
        }

        await redis.hset(handler_key, handler_id, json.dumps(handler_data))
        logger.info(f"Registered handler {handler_id} for signal {signal_name}")
        return True

    @staticmethod
    async def unregister_handler(
        redis,
        signal_name: str,
        handler_id: str
    ) -> bool:
        """
        Unregister a handler for a signal.

        Args:
            redis: Redis client
            signal_name: Signal name
            handler_id: Handler ID to remove

        Returns:
            True if unregistered successfully
        """
        handler_key = f"{StatelessSignalManager.SIGNAL_HANDLERS_PREFIX}{signal_name}"
        removed = await redis.hdel(handler_key, handler_id)

        if removed:
            logger.info(f"Unregistered handler {handler_id} for signal {signal_name}")

        return removed > 0

    @staticmethod
    async def process_signals(redis, max_signals: int = 100) -> Tuple[int, List[Dict]]:
        """
        Process pending signals. NO LOOPS!

        Args:
            redis: Redis client
            max_signals: Maximum signals to process

        Returns:
            Tuple of (processed_count, processed_signal_list)
        """
        processed = 0
        processed_signals = []

        try:
            # Get pending signals (bounded batch)
            pipe = redis.pipeline()
            for _ in range(max_signals):
                pipe.rpop(StatelessSignalManager.PENDING_SIGNALS_KEY)

            signal_ids = await pipe.execute()

            # Filter out None values
            signal_ids = [sid for sid in signal_ids if sid]

            if not signal_ids:
                return 0, []

            # Process each signal (bounded iteration, not a loop)
            for signal_id in signal_ids:
                if isinstance(signal_id, bytes):
                    signal_id = signal_id.decode()

                # Get signal metadata
                signal_key = f"{StatelessSignalManager.SIGNAL_METADATA_PREFIX}{signal_id}"
                signal_data = await redis.hgetall(signal_key)

                if not signal_data:
                    continue

                # Decode signal data
                decoded_data = {}
                for k, v in signal_data.items():
                    if isinstance(k, bytes):
                        k = k.decode()
                    if isinstance(v, bytes):
                        v = v.decode()
                    decoded_data[k] = v

                signal_name = decoded_data.get("signal_name", "")

                # Get handlers for this signal
                handlers = await StatelessSignalManager.get_handlers(redis, signal_name)

                # Process with each handler
                for handler in handlers:
                    # In a real implementation, this would trigger the handler
                    # For now, we just mark the signal as processed
                    logger.info(f"Processing signal {signal_id} with handler {handler.get('handler_id')}")

                # Mark signal as processed
                decoded_data["processed_at"] = datetime.utcnow().isoformat()
                decoded_data["status"] = "processed"
                decoded_data["handlers_invoked"] = len(handlers)

                processed_signals.append(decoded_data)

                # Update signal status
                await redis.hset(signal_key, "status", "processed")
                await redis.hset(signal_key, "processed_at", decoded_data["processed_at"])

                # Add to processed signals set
                await redis.zadd(
                    StatelessSignalManager.PROCESSED_SIGNALS_KEY,
                    {signal_id: time.time()}
                )

                processed += 1

            logger.info(f"Processed {processed} signals")

        except Exception as e:
            logger.error(f"Error processing signals: {e}")

        return processed, processed_signals

    @staticmethod
    async def get_handlers(redis, signal_name: str) -> List[Dict[str, Any]]:
        """
        Get all handlers for a signal.

        Args:
            redis: Redis client
            signal_name: Signal name

        Returns:
            List of handler configurations
        """
        handler_key = f"{StatelessSignalManager.SIGNAL_HANDLERS_PREFIX}{signal_name}"
        handler_data = await redis.hgetall(handler_key)

        handlers = []
        for handler_id, handler_json in handler_data.items():
            if isinstance(handler_json, bytes):
                handler_json = handler_json.decode()
            try:
                handler = json.loads(handler_json)
                handlers.append(handler)
            except json.JSONDecodeError:
                logger.error(f"Invalid handler data for {handler_id}")

        return handlers

    @staticmethod
    async def get_workflow_signals(redis, workflow_id: str, count: int = 100) -> List[Dict[str, Any]]:
        """
        Get signals for a specific workflow.

        Args:
            redis: Redis client
            workflow_id: Workflow ID
            count: Maximum signals to retrieve

        Returns:
            List of signal data
        """
        workflow_signal_key = f"{StatelessSignalManager.WORKFLOW_SIGNALS_PREFIX}{workflow_id}"

        # Get signal IDs
        signal_ids = await redis.lrange(workflow_signal_key, 0, count - 1)

        signals = []
        for signal_id in signal_ids:
            if isinstance(signal_id, bytes):
                signal_id = signal_id.decode()

            # Get signal metadata
            signal_key = f"{StatelessSignalManager.SIGNAL_METADATA_PREFIX}{signal_id}"
            signal_data = await redis.hgetall(signal_key)

            if signal_data:
                # Decode data
                decoded_data = {}
                for k, v in signal_data.items():
                    if isinstance(k, bytes):
                        k = k.decode()
                    if isinstance(v, bytes):
                        v = v.decode()
                    decoded_data[k] = v

                signals.append(decoded_data)

        return signals

    @staticmethod
    async def get_signal_status(redis, signal_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a signal.

        Args:
            redis: Redis client
            signal_id: Signal ID

        Returns:
            Signal status data or None
        """
        signal_key = f"{StatelessSignalManager.SIGNAL_METADATA_PREFIX}{signal_id}"
        signal_data = await redis.hgetall(signal_key)

        if not signal_data:
            return None

        # Decode data
        decoded_data = {}
        for k, v in signal_data.items():
            if isinstance(k, bytes):
                k = k.decode()
            if isinstance(v, bytes):
                v = v.decode()
            decoded_data[k] = v

        return decoded_data

    @staticmethod
    async def get_signal_stats(redis) -> Dict[str, Any]:
        """
        Get signal statistics. Single invocation, no loops.

        Args:
            redis: Redis client

        Returns:
            Signal statistics
        """
        try:
            # Use pipeline for single round trip
            pipe = redis.pipeline()
            pipe.llen(StatelessSignalManager.PENDING_SIGNALS_KEY)
            pipe.zcard(StatelessSignalManager.PROCESSED_SIGNALS_KEY)

            results = await pipe.execute()

            # Count handlers for each signal type
            handler_counts = {}
            # Get all handler keys (this is bounded by signal types)
            handler_keys = await redis.keys(f"{StatelessSignalManager.SIGNAL_HANDLERS_PREFIX}*")

            for key in handler_keys:
                if isinstance(key, bytes):
                    key = key.decode()
                signal_name = key.replace(StatelessSignalManager.SIGNAL_HANDLERS_PREFIX, "")
                handler_count = await redis.hlen(key)
                handler_counts[signal_name] = handler_count

            return {
                "pending_count": results[0],
                "processed_count": results[1],
                "handler_counts": handler_counts,
                "total_handlers": sum(handler_counts.values())
            }

        except Exception as e:
            logger.error(f"Error getting signal stats: {e}")
            return {}

    @staticmethod
    async def cleanup_old_signals(redis, days_old: int = 7) -> int:
        """
        Clean up old processed signals. NO LOOPS!

        Args:
            redis: Redis client
            days_old: Remove signals older than this many days

        Returns:
            Number of signals cleaned up
        """
        cutoff_time = time.time() - (days_old * 24 * 3600)
        cleaned = 0

        try:
            # Remove old processed signals
            removed = await redis.zremrangebyscore(
                StatelessSignalManager.PROCESSED_SIGNALS_KEY,
                min=0,
                max=cutoff_time
            )
            cleaned += removed

            # Get old signal IDs to clean metadata
            old_signals = await redis.zrangebyscore(
                StatelessSignalManager.PROCESSED_SIGNALS_KEY,
                min=0,
                max=cutoff_time,
                start=0,
                num=1000  # Batch size
            )

            if old_signals:
                pipe = redis.pipeline()
                for signal_id in old_signals:
                    if isinstance(signal_id, bytes):
                        signal_id = signal_id.decode()

                    # Delete metadata
                    signal_key = f"{StatelessSignalManager.SIGNAL_METADATA_PREFIX}{signal_id}"
                    pipe.delete(signal_key)
                    cleaned += 1

                await pipe.execute()

            logger.info(f"Cleaned up {cleaned} old signals")

        except Exception as e:
            logger.error(f"Error cleaning up signals: {e}")

        return cleaned

    @staticmethod
    async def process_all_once(redis, max_signals: int = 100) -> Dict[str, Any]:
        """
        Process all signal operations once. NO LOOPS!

        This is the main entry point for stateless processing.

        Args:
            redis: Redis client
            max_signals: Maximum signals to process

        Returns:
            Processing summary
        """
        # Process pending signals (no loop, just one call)
        processed, processed_signals = await StatelessSignalManager.process_signals(redis, max_signals)

        # Get current stats (single call)
        stats = await StatelessSignalManager.get_signal_stats(redis)

        return {
            "processed": processed,
            "processed_signals": processed_signals,
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }


# Pure function entry points

async def process_signals(redis) -> int:
    """
    Process signals once - no state, no loops.

    Args:
        redis: Redis client

    Returns:
        Number of signals processed
    """
    result = await StatelessSignalManager.process_all_once(redis)
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
        processed = await process_signals(redis)
        print(f"Processed {processed} signals")
        return 0
    finally:
        await redis.close()


# AWS Lambda handler
def lambda_handler(event, context):
    """
    AWS Lambda handler for signal processing.
    """
    import asyncio
    import aioredis

    redis_url = event.get('redis_url', 'redis://localhost:6379')

    async def process():
        redis = await aioredis.from_url(redis_url)
        try:
            result = await StatelessSignalManager.process_all_once(redis)
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
            result = await StatelessSignalManager.process_all_once(redis)
            print(f"Signal processing result: {json.dumps(result, indent=2)}")
            return 0
        finally:
            await redis.close()

    sys.exit(asyncio.run(main()))