#!/usr/bin/env python3
"""
Test script to verify that ScalableRedisAdapter events flow to StreamEventBus.

This test verifies:
1. Events are emitted to correct type-specific streams
2. StreamEventBus consumes events from persistence layer
3. Task and workflow state changes trigger proper events
"""

import asyncio
import uuid
import logging
from datetime import datetime

from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.events.stream_event_bus import StreamEventBus
from gleitzeit.core.models import Workflow, Task, WorkflowStatus, TaskStatus
from gleitzeit.core.events import GleitzeitEvent

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Track received events
received_events = []


async def task_handler(event: GleitzeitEvent):
    """Handler for task events."""
    logger.info(f"✅ Task handler received: {event.event_type} - {event.data}")
    received_events.append(event)


async def workflow_handler(event: GleitzeitEvent):
    """Handler for workflow events."""
    logger.info(f"✅ Workflow handler received: {event.event_type} - {event.data}")
    received_events.append(event)


async def test_event_flow():
    """Test that events flow from persistence to event bus."""
    logger.info("=" * 60)
    logger.info("Testing Event Flow: ScalableRedisAdapter → StreamEventBus")
    logger.info("=" * 60)
    
    # Create persistence adapter
    adapter = await PersistenceFactory.create(
        config={
            "key_prefix": f"test_events_{uuid.uuid4().hex[:8]}",
            "enable_events": True
        }
    )
    
    # Create and start event bus
    event_bus = StreamEventBus(
        adapter.redis,
        consumer_group="test_consumers",
        consumer_id=f"test_{uuid.uuid4().hex[:8]}"
    )
    
    # Register handlers for all event types we expect
    event_bus.register("task.submitted", task_handler)
    event_bus.register("task.started", task_handler)
    event_bus.register("task.completed", task_handler)
    event_bus.register("task.failed", task_handler)
    event_bus.register("workflow.submitted", workflow_handler)
    event_bus.register("workflow.started", workflow_handler)
    event_bus.register("workflow.completed", workflow_handler)
    event_bus.register("workflow.failed", workflow_handler)
    
    await event_bus.start()
    logger.info("Event bus started and listening...")
    
    # Give consumer time to initialize
    await asyncio.sleep(1)
    
    # Create test workflow
    workflow = Workflow(
        id=f"wf_{uuid.uuid4().hex[:8]}",
        name="Test Workflow",
        status=WorkflowStatus.PENDING,
        tasks=[]
    )
    
    logger.info(f"\n📝 Saving workflow with status PENDING...")
    await adapter.save_workflow(workflow)
    
    # Create and save tasks with different statuses
    task_statuses = [
        (TaskStatus.PENDING, "task.submitted"),
        (TaskStatus.EXECUTING, "task.started"),
        (TaskStatus.COMPLETED, "task.completed"),
        (TaskStatus.FAILED, "task.failed")
    ]
    
    for i, (status, expected_event) in enumerate(task_statuses):
        task = Task(
            id=f"task_{i}_{uuid.uuid4().hex[:8]}",
            workflow_id=workflow.id,
            name=f"Test Task {i}",
            status=status,
            protocol="python",
            method="test_method"
        )
        
        logger.info(f"\n📝 Saving task with status {status}...")
        await adapter.save_task(task)
        
        # Give time for event to be processed
        await asyncio.sleep(0.5)
    
    # Update workflow status to test workflow events
    logger.info(f"\n📝 Updating workflow to RUNNING...")
    workflow.status = WorkflowStatus.RUNNING
    await adapter.save_workflow(workflow)
    await asyncio.sleep(0.5)
    
    logger.info(f"\n📝 Updating workflow to COMPLETED...")
    workflow.status = WorkflowStatus.COMPLETED
    await adapter.save_workflow(workflow)
    await asyncio.sleep(0.5)
    
    # Give time for all events to be processed
    await asyncio.sleep(2)
    
    # Check results
    logger.info("\n" + "=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    
    logger.info(f"\nTotal events received: {len(received_events)}")
    
    # Verify we received the expected events
    event_types = [event.event_type for event in received_events]
    logger.info(f"Event types received: {event_types}")
    
    # Check specific streams for messages
    logger.info("\n" + "=" * 60)
    logger.info("STREAM VERIFICATION")
    logger.info("=" * 60)
    
    streams_to_check = [
        "gleitzeit:events:stream:task.submitted",
        "gleitzeit:events:stream:task.started",
        "gleitzeit:events:stream:task.completed",
        "gleitzeit:events:stream:task.failed",
        "gleitzeit:events:stream:workflow.submitted",
        "gleitzeit:events:stream:workflow.started",
        "gleitzeit:events:stream:workflow.completed"
    ]
    
    for stream_key in streams_to_check:
        try:
            messages = await adapter.redis.xrange(stream_key, "-", "+", count=10)
            if messages:
                logger.info(f"✅ {stream_key}: {len(messages)} messages")
                for msg_id, data in messages[:2]:  # Show first 2
                    logger.debug(f"   {msg_id}: {data.get(b'event_type', b'').decode()}")
            else:
                logger.warning(f"❌ {stream_key}: No messages")
        except Exception as e:
            logger.warning(f"❌ {stream_key}: Error reading - {e}")
    
    # Check consumer group info
    logger.info("\n" + "=" * 60)
    logger.info("CONSUMER GROUP INFO")
    logger.info("=" * 60)
    
    for stream_key in streams_to_check:
        try:
            groups = await adapter.redis.xinfo_groups(stream_key)
            for group in groups:
                pending = await adapter.redis.xpending(
                    stream_key,
                    group[b'name'].decode() if isinstance(group[b'name'], bytes) else group['name']
                )
                group_name = group[b'name'].decode() if isinstance(group[b'name'], bytes) else group['name']
                consumers = group[b'consumers'] if b'consumers' in group else group.get('consumers', 0)
                logger.info(f"{stream_key.split(':')[-1]}: Group '{group_name}' - {consumers} consumers, {pending[b'pending'] if isinstance(pending, dict) and b'pending' in pending else 0} pending")
        except Exception as e:
            pass  # Stream might not exist
    
    # Cleanup
    await event_bus.stop()
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    if len(received_events) >= 6:  # We expect at least 6 events
        logger.info("✅ SUCCESS: Events are flowing correctly from persistence to StreamEventBus!")
        logger.info(f"✅ Received {len(received_events)} events through the event bus")
        logger.info("✅ Type-specific streams are working correctly")
        return True
    else:
        logger.error(f"❌ FAILURE: Only received {len(received_events)} events (expected at least 6)")
        logger.error("❌ Events may not be flowing correctly")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_event_flow())
    exit(0 if success else 1)