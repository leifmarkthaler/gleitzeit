#!/usr/bin/env python
"""Simple test to validate Redis Streams components work."""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import redis.asyncio as redis

# Streams imports
from gleitzeit.streams.task_stream import TaskStreamManager
from gleitzeit.streams.workflow_stream import WorkflowStreamManager
from gleitzeit.streams.dlq_handler import DeadLetterQueueHandler
from gleitzeit.streams.retry_manager import StreamRetryManager
from gleitzeit.streams.feature_flags import FeatureFlags
from gleitzeit.streams.stream_orchestrator import StreamMode
from gleitzeit.persistence.factory import PersistenceFactory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_task_stream():
    """Test TaskStreamManager functionality."""
    logger.info("\n" + "="*60)
    logger.info("TESTING TASK STREAM MANAGER")
    logger.info("="*60)
    
    redis_client = redis.from_url("redis://localhost:6379", decode_responses=False)
    
    try:
        await redis_client.ping()
        logger.info("✓ Connected to Redis")
        
        # Create task stream (initializes on demand)
        task_stream = TaskStreamManager(redis_client)
        # Ensure consumer groups for each priority
        for priority in ["high", "normal", "low"]:
            await task_stream.ensure_consumer_group(priority)
        logger.info("✓ Task stream initialized")
        
        # Enqueue tasks with different priorities
        tasks = []
        priority_map = {"high": 8, "normal": 5, "low": 1}
        for i, (name, priority_val) in enumerate(priority_map.items()):
            msg_id = await task_stream.enqueue_task(
                task_id=f"test-task-{i}",
                workflow_id="test-workflow",
                priority=priority_val
            )
            tasks.append((msg_id, f"test-task-{i}", name))
            logger.info(f"  Enqueued task {i} with priority {name} ({priority_val}): {msg_id}")
        
        # Read tasks from stream
        logger.info("\nReading tasks from streams...")
        read_tasks = await task_stream.claim_tasks("test-consumer", count=10)
        
        for task in read_tasks:
            logger.info(f"  Read task: {task['task_id']} (priority: {task['priority']})")
            # Acknowledge the task
            await task_stream.ack_task(task['stream'], task['msg_id'])
            logger.info(f"    ✓ Acknowledged")
        
        # Get stream lengths
        lengths = await task_stream.get_stream_length()
        logger.info(f"\nStream lengths:")
        for key, value in lengths.items():
            logger.info(f"  {key}: {value}")
        
        return True
        
    except Exception as e:
        logger.error(f"Task stream test failed: {e}")
        return False
    finally:
        await redis_client.close()


async def test_workflow_stream():
    """Test WorkflowStreamManager functionality."""
    logger.info("\n" + "="*60)
    logger.info("TESTING WORKFLOW STREAM MANAGER")
    logger.info("="*60)
    
    redis_client = redis.from_url("redis://localhost:6379", decode_responses=False)
    
    try:
        # Create and initialize workflow stream
        workflow_stream = WorkflowStreamManager(redis_client)
        await workflow_stream.ensure_consumer_group()
        logger.info("✓ Workflow stream initialized")
        
        # Submit a workflow
        workflow_id = "test-workflow-1"
        msg_id = await workflow_stream.submit_workflow(workflow_id)
        logger.info(f"✓ Submitted workflow {workflow_id}: {msg_id}")
        
        # Add workflow events
        await workflow_stream.trigger_dependency_check(workflow_id, "task-1")
        await workflow_stream.notify_task_completed(workflow_id, "task-1")
        await workflow_stream.notify_task_failed(workflow_id, "task-2", is_permanent=False)
        logger.info("✓ Added workflow events")
        
        # Read workflow events
        events = await workflow_stream.claim_workflow_events("test-manager", count=10)
        logger.info(f"\nRead {len(events)} workflow events:")
        for event in events:
            logger.info(f"  {event['action']} for workflow {event['workflow_id']}")
            await workflow_stream.ack_event(event['msg_id'])
        
        # Mark workflow complete
        await workflow_stream.mark_workflow_complete(workflow_id)
        logger.info(f"✓ Marked workflow {workflow_id} as complete")
        
        return True
        
    except Exception as e:
        logger.error(f"Workflow stream test failed: {e}")
        return False
    finally:
        await redis_client.close()


async def test_dlq_and_retry():
    """Test DLQ and Retry Manager functionality."""
    logger.info("\n" + "="*60)
    logger.info("TESTING DLQ AND RETRY MANAGER")
    logger.info("="*60)
    
    redis_client = redis.from_url("redis://localhost:6379", decode_responses=False)
    
    try:
        # Test DLQ
        dlq = DeadLetterQueueHandler(redis_client)
        await dlq.initialize()
        logger.info("✓ DLQ handler initialized")
        
        # Add failed task to DLQ
        dlq_msg_id = await dlq.add_to_dlq(
            task_id="failed-task-1",
            workflow_id="test-workflow",
            error="Connection timeout after 3 retries",
            retry_count=3,
            metadata={"reason": "network_error"}
        )
        logger.info(f"✓ Added task to DLQ: {dlq_msg_id}")
        
        # Get DLQ stats
        dlq_stats = await dlq.get_dlq_stats()
        logger.info(f"DLQ stats: {dlq_stats}")
        
        # Test Retry Manager  
        retry_mgr = StreamRetryManager(redis_client)
        # Initialize the components that retry manager depends on
        retry_mgr.task_stream = TaskStreamManager(redis_client)
        for priority in ["high", "normal", "low"]:
            await retry_mgr.task_stream.ensure_consumer_group(priority)
        await retry_mgr.dlq_handler.initialize()
        retry_mgr.persistence = await PersistenceFactory.create()
        logger.info("\n✓ Retry manager initialized")
        
        # Schedule retries
        for i in range(2):
            scheduled = await retry_mgr.schedule_retry(
                task_id=f"retry-task-{i}",
                workflow_id="test-workflow",
                retry_count=i,
                error=f"Temporary error #{i}"
            )
            logger.info(f"  Scheduled retry for task {i}: {scheduled}")
        
        # Get retry stats
        retry_stats = await retry_mgr.get_retry_stats()
        logger.info(f"\nRetry stats:")
        logger.info(f"  Queue size: {retry_stats['queue_size']}")
        logger.info(f"  Total retries: {retry_stats['total_retries']}")
        
        return True
        
    except Exception as e:
        logger.error(f"DLQ/Retry test failed: {e}")
        return False
    finally:
        await redis_client.close()


async def test_feature_flags():
    """Test feature flags functionality."""
    logger.info("\n" + "="*60)
    logger.info("TESTING FEATURE FLAGS")
    logger.info("="*60)
    
    redis_client = redis.from_url("redis://localhost:6379", decode_responses=False)
    
    try:
        flags = FeatureFlags(redis_client)
        await flags.initialize()
        logger.info("✓ Feature flags initialized")
        
        # Set and get flags
        await flags.set_flag("stream_mode", StreamMode.PARTIAL.value)
        await flags.set_flag("stream_percentage", 50)
        
        mode = await flags.get_flag("stream_mode")
        percentage = await flags.get_flag("stream_percentage")
        logger.info(f"  Stream mode: {mode}")
        logger.info(f"  Stream percentage: {percentage}%")
        
        # Test gradual enablement
        logger.info("\nTesting gradual enablement...")
        await flags.enable_streams_gradually(target_percentage=100, increment=25)
        
        # Get migration status
        status = await flags.get_migration_status()
        logger.info(f"\nMigration status:")
        logger.info(f"  Mode: {status['mode']}")
        logger.info(f"  Progress: {status['progress']}%")
        logger.info(f"  Config: {status['config']}")
        
        return True
        
    except Exception as e:
        logger.error(f"Feature flags test failed: {e}")
        return False
    finally:
        await redis_client.close()


async def cleanup():
    """Clean up test data."""
    logger.info("\n" + "="*60)
    logger.info("CLEANUP")
    logger.info("="*60)
    
    redis_client = redis.from_url("redis://localhost:6379", decode_responses=False)
    
    try:
        # Clean up test keys
        patterns = [
            "gleitzeit:tasks:stream:*",
            "gleitzeit:workflows",
            "gleitzeit:dlq:*",
            "gleitzeit:retry:*",
            "gleitzeit:feature_*",
            "gleitzeit:processing:*",
            "gleitzeit:workers:*"
        ]
        
        for pattern in patterns:
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis_client.delete(*keys)
                    logger.info(f"  Deleted {len(keys)} keys matching {pattern}")
                if cursor == 0:
                    break
        
        logger.info("✓ Cleanup complete")
        
    finally:
        await redis_client.close()


async def main():
    """Run all tests."""
    logger.info("Starting Redis Streams Component Tests")
    logger.info("="*60)
    
    results = {}
    
    # Run tests
    results["task_stream"] = await test_task_stream()
    results["workflow_stream"] = await test_workflow_stream()
    results["dlq_retry"] = await test_dlq_and_retry()
    results["feature_flags"] = await test_feature_flags()
    
    # Cleanup
    await cleanup()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        logger.info(f"{test_name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        logger.info("\n🎉 All Redis Streams component tests passed!")
    else:
        logger.error("\n❌ Some tests failed")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)