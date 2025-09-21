"""Demo script to test Redis Streams implementation."""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import redis.asyncio as redis
from gleitzeit.streams.task_stream import TaskStreamManager
from gleitzeit.streams.workflow_stream import WorkflowStreamManager
from gleitzeit.streams.dlq_handler import DeadLetterQueueHandler
from gleitzeit.streams.retry_manager import StreamRetryManager
from gleitzeit.streams.feature_flags import FeatureFlags
from gleitzeit.streams.stream_orchestrator import StreamMode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def demo_task_stream(redis_client):
    """Demonstrate task stream functionality."""
    logger.info("\n=== Testing Task Stream Manager ===")
    
    task_stream = TaskStreamManager(redis_client)
    await task_stream.initialize()
    
    # Enqueue some tasks
    logger.info("Enqueueing tasks...")
    task_ids = []
    for i in range(3):
        priority = ["high", "normal", "low"][i]
        msg_id = await task_stream.enqueue_task(
            task_id=f"task-{i}",
            workflow_id="workflow-demo",
            priority=priority,
            metadata={"index": i}
        )
        task_ids.append(msg_id)
        logger.info(f"  Enqueued task-{i} with priority {priority}: {msg_id}")
    
    # Read tasks
    logger.info("\nReading tasks from stream...")
    tasks = await task_stream.read_tasks("demo-consumer", count=5, block_ms=1000)
    for task in tasks:
        logger.info(f"  Read task: {task['task_id']} (priority: {task['priority']})")
        # Acknowledge the task
        await task_stream.acknowledge_task(task['id'])
    
    # Get stream info
    info = await task_stream.get_stream_info()
    logger.info(f"\nStream info: {info}")
    
    return task_ids


async def demo_workflow_stream(redis_client):
    """Demonstrate workflow stream functionality."""
    logger.info("\n=== Testing Workflow Stream Manager ===")
    
    workflow_stream = WorkflowStreamManager(redis_client)
    await workflow_stream.ensure_consumer_group()
    
    # Submit a workflow
    logger.info("Submitting workflow...")
    msg_id = await workflow_stream.submit_workflow("workflow-demo")
    logger.info(f"  Workflow submitted: {msg_id}")
    
    # Add some workflow events
    await workflow_stream.trigger_dependency_check("workflow-demo", "task-0")
    await workflow_stream.notify_task_completed("workflow-demo", "task-0")
    
    # Read workflow events
    logger.info("\nReading workflow events...")
    events = await workflow_stream.claim_workflow_events("demo-manager", count=10)
    for event in events:
        logger.info(f"  Event: {event['action']} for {event['workflow_id']}")
        await workflow_stream.ack_event(event['msg_id'])
    
    # Mark workflow complete
    await workflow_stream.mark_workflow_complete("workflow-demo")
    logger.info("Workflow marked as complete")


async def demo_dlq_handler(redis_client):
    """Demonstrate DLQ handler functionality."""
    logger.info("\n=== Testing Dead Letter Queue Handler ===")
    
    dlq = DeadLetterQueueHandler(redis_client)
    await dlq.initialize()
    
    # Add a failed task to DLQ
    logger.info("Adding failed task to DLQ...")
    dlq_msg_id = await dlq.add_to_dlq(
        task_id="task-failed",
        workflow_id="workflow-demo",
        error="Max retries exceeded: Connection timeout",
        retry_count=3,
        metadata={"reason": "timeout"}
    )
    logger.info(f"  Added to DLQ: {dlq_msg_id}")
    
    # Get DLQ entries
    entries = await dlq.get_dlq_entries(count=10)
    logger.info(f"\nDLQ entries: {len(entries)}")
    for entry in entries:
        logger.info(f"  Task {entry['task_id']}: {entry['error'][:50]}...")
    
    # Get DLQ stats
    stats = await dlq.get_dlq_stats()
    logger.info(f"\nDLQ stats: {stats}")


async def demo_retry_manager(redis_client):
    """Demonstrate retry manager functionality."""
    logger.info("\n=== Testing Retry Manager ===")
    
    retry_mgr = StreamRetryManager(redis_client)
    await retry_mgr.initialize()
    
    # Schedule some retries
    logger.info("Scheduling task retries...")
    for i in range(2):
        scheduled = await retry_mgr.schedule_retry(
            task_id=f"task-retry-{i}",
            workflow_id="workflow-demo",
            retry_count=i,
            error=f"Temporary failure #{i}"
        )
        logger.info(f"  Scheduled retry for task-retry-{i}: {scheduled}")
    
    # Get pending retries
    pending = await retry_mgr.get_pending_retries()
    logger.info(f"\nPending retries: {len(pending)}")
    for retry in pending:
        logger.info(f"  Task {retry['task_id']}: attempt {retry['retry_count']+1}")
    
    # Get retry stats
    stats = await retry_mgr.get_retry_stats()
    logger.info(f"\nRetry stats: {stats}")


async def demo_feature_flags(redis_client):
    """Demonstrate feature flags functionality."""
    logger.info("\n=== Testing Feature Flags ===")
    
    flags = FeatureFlags(redis_client)
    await flags.initialize()
    
    # Set some flags
    logger.info("Setting feature flags...")
    await flags.set_flag("stream_mode", StreamMode.SHADOW.value)
    await flags.set_flag("stream_percentage", 25)
    
    # Get flags
    mode = await flags.get_flag("stream_mode")
    percentage = await flags.get_flag("stream_percentage")
    logger.info(f"  Stream mode: {mode}")
    logger.info(f"  Stream percentage: {percentage}%")
    
    # Simulate gradual enablement
    logger.info("\nSimulating gradual stream enablement...")
    await flags.enable_streams_gradually(target_percentage=50, increment=10)
    
    # Get migration status
    status = await flags.get_migration_status()
    logger.info(f"\nMigration status:")
    logger.info(f"  Mode: {status['mode']}")
    logger.info(f"  Progress: {status['progress']}%")
    logger.info(f"  Recommendations: {status['recommendations']}")


async def cleanup_demo_data(redis_client):
    """Clean up demo data from Redis."""
    logger.info("\n=== Cleaning up demo data ===")
    
    keys_to_delete = [
        "gleitzeit:tasks:stream:*",
        "gleitzeit:workflows",
        "gleitzeit:dlq:*",
        "gleitzeit:retry:*",
        "gleitzeit:feature_*",
        "gleitzeit:processing:*",
        "gleitzeit:workers:*"
    ]
    
    for pattern in keys_to_delete:
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
            if keys:
                await redis_client.delete(*keys)
                logger.info(f"  Deleted {len(keys)} keys matching {pattern}")
            if cursor == 0:
                break


async def main():
    """Run the demo."""
    logger.info("Starting Redis Streams Demo")
    logger.info("=" * 50)
    
    # Connect to Redis
    redis_client = redis.from_url(
        "redis://localhost:6379",
        decode_responses=False  # We handle decoding manually
    )
    
    try:
        # Test connection
        await redis_client.ping()
        logger.info("Connected to Redis successfully")
        
        # Run demos
        await demo_task_stream(redis_client)
        await demo_workflow_stream(redis_client)
        await demo_dlq_handler(redis_client)
        await demo_retry_manager(redis_client)
        await demo_feature_flags(redis_client)
        
        # Cleanup
        await cleanup_demo_data(redis_client)
        
        logger.info("\n" + "=" * 50)
        logger.info("Demo completed successfully!")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())