#!/usr/bin/env python3
"""
Test script to verify that task submission now emits TASK_SUBMITTED events.
"""

import asyncio
import logging
import sys
import json
from datetime import datetime

# Configure logging to see all debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_task_submission():
    """Test that task submission emits proper events."""
    
    # Import after logging is configured
    from gleitzeit.client import GleitzeitClient
    from gleitzeit.core.models import Task
    from gleitzeit.system.system_manager import SystemManager
    
    logger.info("=== Starting Task Submission Event Test ===")
    
    # Get or create SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    logger.info(f"✓ SystemManager initialized: {system_manager.instance_id}")
    
    # Initialize client (native mode with system_manager)
    client = GleitzeitClient(mode="native", system_manager=system_manager)
    await client.initialize()
    
    # Verify we have an event bus
    if hasattr(client._adapter, 'event_bus'):
        event_bus = client._adapter.event_bus
        if event_bus:
            logger.info(f"✓ Event bus found: {type(event_bus).__name__}")
        else:
            logger.error("✗ Event bus is None in adapter")
    else:
        logger.error("✗ No event_bus attribute in adapter")
    
    # Track events received
    events_received = []
    
    # Register a handler to capture TASK_SUBMITTED events
    if hasattr(client._adapter, 'event_bus') and client._adapter.event_bus:
        from gleitzeit.core.events import EventType
        
        async def capture_event(event):
            logger.info(f"📨 Event received: {event.event_type} - {event.data}")
            events_received.append(event)
        
        client._adapter.event_bus.register(EventType.TASK_SUBMITTED, capture_event)
        logger.info("✓ Registered event handler for TASK_SUBMITTED")
    
    # Create and submit a test task
    test_task = Task(
        id=f"test_task_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        name="Test Task for Event Emission",
        protocol="python/v1",
        method="execute",
        params={"code": "print('Testing event emission')"}
    )
    
    logger.info(f"Submitting task: {test_task.id}")
    
    # Submit the task
    result = await client.submit_task(test_task)
    
    if result.get("success"):
        logger.info(f"✓ Task submitted successfully: {result}")
    else:
        logger.error(f"✗ Task submission failed: {result}")
    
    # Give event bus time to process
    logger.info("Waiting for events to be processed...")
    await asyncio.sleep(2)
    
    # Check if we received events
    if events_received:
        logger.info(f"✓ Received {len(events_received)} events:")
        for event in events_received:
            logger.info(f"  - {event.event_type}: {json.dumps(event.data, indent=2)}")
    else:
        logger.warning("⚠️ No events received directly (they may be in Redis streams)")
    
    # Check Redis streams for the event
    if hasattr(client._adapter, 'persistence') and hasattr(client._adapter.persistence, 'redis'):
        redis = client._adapter.persistence.redis
        stream_key = f"gleitzeit:events:stream:task:submitted"
        
        try:
            # Read last few messages from stream
            messages = await redis.xrevrange(stream_key, count=5)
            if messages:
                logger.info(f"✓ Found {len(messages)} messages in Redis stream {stream_key}:")
                for msg_id, data in messages:
                    # Decode the data
                    decoded = {}
                    for k, v in data.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else v
                        decoded[key] = val
                    
                    # Check if this is our task
                    if 'data' in decoded:
                        task_data = json.loads(decoded['data'])
                        if task_data.get('task_id') == test_task.id:
                            logger.info(f"  ✓ Found our task event: {msg_id.decode() if isinstance(msg_id, bytes) else msg_id}")
                            logger.info(f"    Data: {json.dumps(task_data, indent=4)}")
                            break
            else:
                logger.warning(f"⚠️ No messages found in stream {stream_key}")
        except Exception as e:
            logger.error(f"Error checking Redis stream: {e}")
    
    # Check task status in persistence
    saved_task = await client.get_task(test_task.id)
    if saved_task:
        logger.info(f"✓ Task found in persistence with status: {saved_task.status}")
    else:
        logger.error("✗ Task not found in persistence")
    
    # Cleanup
    await client.shutdown()
    logger.info("=== Test Complete ===")

if __name__ == "__main__":
    try:
        asyncio.run(test_task_submission())
    except KeyboardInterrupt:
        logger.info("Test interrupted")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)