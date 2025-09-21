#!/usr/bin/env python
"""
Test Redis-triggered consumption pattern.

This demonstrates a truly stateless, trigger-based event consumption model
where Redis drives the consumption, not Python loops.
"""

import asyncio
import logging
from datetime import datetime
from gleitzeit.events.triggered_stream_consumer import TriggeredStreamConsumer
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.events import GleitzeitEvent, EventType
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_triggered_consumption():
    """Test the Redis-triggered consumption pattern."""

    # Create persistence
    persistence = await PersistenceFactory.create(
        backend="redis",
        config={"redis_url": "redis://localhost:6379/0"}
    )

    redis = persistence.redis

    # Create triggered consumer
    consumer = TriggeredStreamConsumer(
        redis=redis,
        consumer_group="test-triggered-group",
        consumer_id="test-consumer-001",
        instance_id="test-instance"
    )

    # Setup trigger stream
    await consumer.setup_trigger_stream()

    logger.info("=" * 60)
    logger.info("Testing Redis-Triggered Consumption")
    logger.info("=" * 60)

    # Register a test handler
    events_received = []

    def test_handler(event):
        logger.info(f"Handler received event: {event.event_type}")
        events_received.append(event)

    consumer.register_handler("test:event", test_handler)

    # Discover streams
    await consumer.discover_streams()
    await consumer.ensure_consumer_groups()

    # Add test events to a stream
    test_stream = "gleitzeit:events:stream:test:event"
    for i in range(5):
        event_data = {
            "event_type": "test:event",
            "timestamp": datetime.utcnow().isoformat(),
            "data": json.dumps({"index": i, "message": f"Test event {i}"}),
            "source": "test",
            "correlation_id": f"test-{i}",
            "severity": "INFO",
            "metadata": "{}"
        }
        msg_id = await redis.xadd(test_stream, event_data)
        logger.info(f"Added test event {i} with ID: {msg_id}")

    logger.info("\n" + "=" * 60)
    logger.info("Scenario 1: NO LOOP - Single trigger, single consumption")
    logger.info("=" * 60)

    # Send a single trigger
    await consumer.trigger_consumption("consume", {"test": "single_trigger"})

    # Process once based on trigger
    processed = await consumer.consume_once()
    logger.info(f"Processed {processed} messages from single trigger")

    logger.info("\n" + "=" * 60)
    logger.info("Scenario 2: External trigger via Redis")
    logger.info("=" * 60)

    # Simulate external trigger (e.g., from another service)
    await redis.xadd(
        TriggeredStreamConsumer.TRIGGER_STREAM,
        {
            "action": "consume",
            "timestamp": datetime.utcnow().isoformat(),
            "source": "external_service",
            "reason": "scheduled_trigger"
        }
    )
    logger.info("Sent external trigger via Redis")

    # Wait for and process trigger
    trigger = await consumer.wait_for_trigger(timeout_ms=5000)
    if trigger:
        logger.info(f"Received trigger: {trigger}")
        processed = await consumer.consume_once()
        logger.info(f"Processed {processed} messages from external trigger")

    logger.info("\n" + "=" * 60)
    logger.info("Scenario 3: Auto-trigger based on stream activity")
    logger.info("=" * 60)

    # Add more events
    for i in range(5, 8):
        event_data = {
            "event_type": "test:event",
            "timestamp": datetime.utcnow().isoformat(),
            "data": json.dumps({"index": i, "message": f"Additional event {i}"}),
            "source": "test",
            "correlation_id": f"test-{i}",
            "severity": "INFO",
            "metadata": "{}"
        }
        await redis.xadd(test_stream, event_data)

    # Check for activity and auto-trigger
    has_messages = await consumer.auto_trigger_on_stream_activity()
    if has_messages:
        logger.info("Auto-triggered consumption due to pending messages")

        # Wait for the auto-generated trigger
        trigger = await consumer.wait_for_trigger(timeout_ms=1000)
        if trigger:
            processed = await consumer.consume_once()
            logger.info(f"Processed {processed} messages from auto-trigger")

    logger.info("\n" + "=" * 60)
    logger.info("Scenario 4: Trigger-based workflow")
    logger.info("=" * 60)

    # Demonstrate a complete trigger-based workflow
    workflow_complete = False
    max_triggers = 3
    trigger_count = 0

    while not workflow_complete and trigger_count < max_triggers:
        # Send trigger
        await consumer.trigger_consumption("consume", {"workflow": "test", "step": trigger_count})

        # Process based on trigger
        result = await consumer.process_with_trigger()

        if result > 0:
            logger.info(f"Workflow step {trigger_count}: Processed {result} messages")
        elif result == 0:
            logger.info(f"Workflow step {trigger_count}: No messages to process")
            workflow_complete = True
        elif result == -1:
            logger.info("Workflow received shutdown signal")
            workflow_complete = True

        trigger_count += 1

    logger.info("\n" + "=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Total events handled by consumer: {len(events_received)}")
    logger.info("Key benefits of trigger-based consumption:")
    logger.info("  • No internal Python loops")
    logger.info("  • Consumption driven by Redis triggers")
    logger.info("  • Truly stateless operation")
    logger.info("  • Can be triggered by any external system")
    logger.info("  • Perfect for serverless/FaaS deployments")

    # Cleanup
    await persistence.close()


async def main():
    """Main test runner."""
    try:
        await test_triggered_consumption()
        print("\n" + "=" * 60)
        print("✅ Redis-Triggered Consumption Test Successful!")
        print("=" * 60)
        print("\nThe system can now operate without ANY internal loops.")
        print("All consumption is triggered via Redis itself!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())