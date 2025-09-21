#!/usr/bin/env python
"""
Debug script to check why workflows aren't executing.
"""

import asyncio
import logging
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.core.models import Workflow, Task
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def test_workflow_execution():
    """Test workflow execution and debug why it's not processing."""

    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test",
        default_providers=["python"]
    )

    manager = None
    try:
        # Create manager
        manager = await ModularStreamSystemManager.create(
            config=config,
            instance_id="test_debug",
            create_if_missing=True,
            start_system=True
        )

        logger.info("=" * 60)
        logger.info("System started, checking handlers...")
        logger.info("=" * 60)

        # Check if consumer is running
        if hasattr(manager, 'stream_consumer'):
            logger.info(f"Stream consumer exists: {manager.stream_consumer}")
            logger.info(f"Consumer started: {manager.consumer_started}")

            # Check registered handlers
            if hasattr(manager, 'event_handlers'):
                logger.info(f"Registered event types: {list(manager.event_handlers.keys())}")
                for event_type, handlers in manager.event_handlers.items():
                    logger.info(f"  {event_type}: {len(handlers)} handler(s)")

        # Check if the consumer task is running
        if hasattr(manager, 'stream_consumer') and manager.stream_consumer:
            if hasattr(manager.stream_consumer, '_consumer_task'):
                task = manager.stream_consumer._consumer_task
                if task:
                    logger.info(f"Consumer task exists: {task}")
                    logger.info(f"Task done: {task.done()}")
                    if task.done():
                        try:
                            # Get the exception if any
                            exc = task.exception()
                            if exc:
                                logger.error(f"Consumer task failed with: {exc}")
                        except:
                            pass
                else:
                    logger.warning("No consumer task found!")

        # Submit a simple workflow
        workflow = Workflow(
            id="debug-workflow-001",
            name="Debug Workflow",
            tasks=[
                Task(
                    id="debug-task-1",
                    name="Debug Task",
                    protocol="python/v1",
                    method="python/execute",  # Use 'method' instead of 'operation'
                    params={  # Use 'params' not 'parameters'
                        "file": "test_task.py",  # Just the filename, not absolute path
                        "function": "main"
                    }
                )
            ]
        )

        logger.info("=" * 60)
        logger.info("Submitting workflow...")
        workflow_id = await manager.submit_workflow(workflow)
        logger.info(f"Workflow submitted: {workflow_id}")

        # Give it a moment to process
        await asyncio.sleep(2)

        # Check Redis directly for events
        if manager.persistence and hasattr(manager.persistence, 'redis'):
            redis = manager.persistence.redis

            # Check workflow stream
            workflow_stream = "gleitzeit:events:stream:workflow:submitted"
            length = await redis.xlen(workflow_stream)
            logger.info(f"Workflow stream length: {length}")

            # Check if there are pending messages
            info = await redis.xinfo_stream(workflow_stream)
            logger.info(f"Stream info: {info}")

            # Check consumer groups
            try:
                groups = await redis.xinfo_groups(workflow_stream)
                logger.info(f"Consumer groups: {len(groups)} groups")
                for group in groups:
                    logger.info(f"  Group {group['name']}: lag={group.get('lag', 0)}, consumers={group.get('consumers', 0)}")
            except:
                pass

        # Manually trigger consumption attempt
        if hasattr(manager, 'stream_consumer') and manager.stream_consumer:
            logger.info("=" * 60)
            logger.info("Checking consumer state...")

            # Check if handlers are registered with the consumer
            if hasattr(manager.stream_consumer, 'handlers'):
                logger.info(f"Consumer handlers: {list(manager.stream_consumer.handlers.keys())}")

            # Check if streams were discovered
            if hasattr(manager.stream_consumer, 'streams'):
                logger.info(f"Discovered streams: {manager.stream_consumer.streams}")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    finally:
        if manager:
            await asyncio.sleep(2)  # Give time for processing
            await manager.shutdown()


if __name__ == "__main__":
    asyncio.run(test_workflow_execution())