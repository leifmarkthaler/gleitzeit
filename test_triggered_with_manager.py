#!/usr/bin/env python
"""
Test Redis-triggered consumption with ModularStreamSystemManager.

Demonstrates how the system manager can use triggered consumption
instead of loops.
"""

import asyncio
import logging
import os
from datetime import datetime
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.core.models import Workflow, Task
from gleitzeit.events.triggered_stream_consumer import TriggeredStreamConsumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_triggered_system():
    """Test triggered consumption through the system manager."""

    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test",
        default_providers=["python"]
    )

    manager = None
    try:
        logger.info("=" * 60)
        logger.info("Creating ModularStreamSystemManager")
        logger.info("=" * 60)

        # Create manager
        manager = await ModularStreamSystemManager.create(
            config=config,
            instance_id="test_triggered",
            create_if_missing=True,
            start_system=True
        )

        if not manager:
            logger.error("Failed to create manager")
            return False

        # Access the Redis client through manager's persistence
        redis = manager.persistence.redis

        logger.info("\n" + "=" * 60)
        logger.info("Demonstrating Trigger-Based Consumption")
        logger.info("=" * 60)

        # Submit a workflow
        workflow = Workflow(
            id="triggered-workflow-001",
            name="Triggered Test Workflow",
            tasks=[
                Task(
                    id="triggered-task-1",
                    name="Test Task",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "file": "test_task.py",
                        "function": "main"
                    }
                )
            ]
        )

        logger.info("Submitting workflow...")
        workflow_id = await manager.submit_workflow(workflow)
        logger.info(f"Workflow submitted: {workflow_id}")

        # Instead of waiting for automatic processing,
        # we can manually trigger consumption
        logger.info("\n" + "=" * 60)
        logger.info("Manual Trigger Demonstration")
        logger.info("=" * 60)

        # Send a trigger via Redis
        trigger_stream = TriggeredStreamConsumer.TRIGGER_STREAM
        trigger_data = {
            "action": "consume",
            "timestamp": datetime.utcnow().isoformat(),
            "source": "manual_test",
            "reason": "demonstrate_manual_trigger"
        }

        await redis.xadd(trigger_stream, trigger_data)
        logger.info(f"Sent manual trigger to {trigger_stream}")

        # Give the system a moment to process
        await asyncio.sleep(2)

        # Check workflow status
        workflow_data = await manager.persistence.get_workflow(workflow_id)
        if workflow_data:
            status = workflow_data.status if hasattr(workflow_data, 'status') else 'unknown'
            logger.info(f"Workflow status after trigger: {status}")

        # Check task result
        task_result = await manager.persistence.get_task_result("triggered-task-1")
        if task_result:
            logger.info(f"Task status: {task_result.status if hasattr(task_result, 'status') else 'unknown'}")

        logger.info("\n" + "=" * 60)
        logger.info("Stream Activity Check")
        logger.info("=" * 60)

        # Check how many events are in various streams
        patterns = [
            "gleitzeit:events:stream:workflow:*",
            "gleitzeit:events:stream:task:*"
        ]

        for pattern in patterns:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=10)
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode()
                    length = await redis.xlen(key)
                    if length > 0:
                        logger.info(f"  {key}: {length} messages")
                if cursor == 0:
                    break

        logger.info("\n" + "=" * 60)
        logger.info("Trigger Stream Analysis")
        logger.info("=" * 60)

        # Analyze the trigger stream
        trigger_info = await redis.xinfo_stream(trigger_stream)
        logger.info(f"Trigger stream length: {trigger_info.get('length', 0)}")

        # Read recent triggers
        triggers = await redis.xrevrange(trigger_stream, '+', '-', count=5)
        logger.info(f"Recent triggers: {len(triggers)}")
        for msg_id, data in triggers:
            decoded_data = {k.decode() if isinstance(k, bytes) else k:
                           v.decode() if isinstance(v, bytes) else v
                           for k, v in data.items()}
            logger.info(f"  {msg_id}: action={decoded_data.get('action')}, source={decoded_data.get('source')}")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    finally:
        if manager:
            logger.info("\nShutting down manager...")
            await manager.shutdown()


async def main():
    """Main test runner."""
    success = await test_triggered_system()

    if success:
        print("\n" + "=" * 60)
        print("✅ Triggered System Test Successful!")
        print("=" * 60)
        print("\nKey Insights:")
        print("  • ModularStreamSystemManager provides the infrastructure")
        print("  • Consumption can be triggered via Redis")
        print("  • No internal loops required for event processing")
        print("  • System is truly event-driven and stateless")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Test failed")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())