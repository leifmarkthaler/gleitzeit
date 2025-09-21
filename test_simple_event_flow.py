#!/usr/bin/env python3
"""
Simple test to verify event flow without hanging.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_simple_flow():
    """Test basic event flow."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, TaskStatus
    from gleitzeit.core.events import EventType, GleitzeitEvent
    
    logger.info("Starting simple event flow test")
    
    # Create SystemManager with minimal startup
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=False  # Don't start full system
    )
    
    # Start only the essential components
    await system_manager.start_system()
    
    logger.info("System started")
    
    # Check event bus
    if not system_manager.event_bus:
        logger.error("No event bus!")
        return
    
    # Register a simple test handler
    test_results = {'task_submitted': False, 'task_ready': False}
    
    async def test_submitted_handler(event):
        logger.info(f"TEST: Received TASK_SUBMITTED: {event.data}")
        test_results['task_submitted'] = True
    
    async def test_ready_handler(event):
        logger.info(f"TEST: Received TASK_READY: {event.data}")
        test_results['task_ready'] = True
    
    # Register handlers
    system_manager.event_bus.register(EventType.TASK_SUBMITTED, test_submitted_handler)
    system_manager.event_bus.register(EventType.TASK_READY, test_ready_handler)
    
    logger.info("Handlers registered")
    
    # Emit a TASK_SUBMITTED event
    event = GleitzeitEvent(
        event_type=EventType.TASK_SUBMITTED,
        data={"task_id": "test123", "task_name": "Test"},
        source="test"
    )
    
    await system_manager.event_bus.emit(event)
    logger.info("Emitted TASK_SUBMITTED")
    
    # Wait for processing
    await asyncio.sleep(2)
    
    # Check results
    logger.info(f"Results: {test_results}")
    
    if test_results['task_submitted']:
        logger.info("✓ TASK_SUBMITTED was received!")
    else:
        logger.error("✗ TASK_SUBMITTED was NOT received")
    
    # Now emit TASK_READY
    ready_event = GleitzeitEvent(
        event_type=EventType.TASK_READY,
        data={"task_id": "test123"},
        source="test"
    )
    
    await system_manager.event_bus.emit(ready_event)
    logger.info("Emitted TASK_READY")
    
    await asyncio.sleep(2)
    
    if test_results['task_ready']:
        logger.info("✓ TASK_READY was received!")
    else:
        logger.error("✗ TASK_READY was NOT received")
    
    # Shutdown
    await system_manager.shutdown()
    logger.info("Test complete")

if __name__ == "__main__":
    # Run with timeout
    try:
        asyncio.wait_for(asyncio.create_task(test_simple_flow()), timeout=15.0)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.wait_for(test_simple_flow(), timeout=15.0))
    except asyncio.TimeoutError:
        logger.error("Test timed out!")
    except Exception as e:
        logger.error(f"Test failed: {e}")