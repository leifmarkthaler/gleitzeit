#!/usr/bin/env python
"""Integration test for Redis Streams with Gleitzeit system."""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import redis.asyncio as redis

# Gleitzeit imports
from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.core.task_executor import TaskExecutor
from gleitzeit.core.dependency_manager import UnifiedDependencyManager
from gleitzeit.task_queue import QueueManager
from gleitzeit.persistence.factory import PersistenceFactory, PersistenceType
from gleitzeit.events.stateless_bus import StatelessEventBus
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.registry import Registry

# Streams imports
from gleitzeit.streams.stream_orchestrator import StreamOrchestrator, StreamMode
from gleitzeit.streams.worker import StreamTaskWorker
from gleitzeit.streams.feature_flags import FeatureFlags

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GleitzeitStreamIntegration:
    """Integration test harness for Redis Streams."""
    
    def __init__(self):
        self.redis_client = None
        self.persistence = None
        self.event_bus = None
        self.orchestrator = None
        self.worker = None
        self.registry = None
        self.feature_flags = None
        
    async def setup(self):
        """Setup all components."""
        logger.info("Setting up Gleitzeit with Redis Streams...")
        
        # Connect to Redis
        self.redis_client = redis.from_url(
            "redis://localhost:6379",
            decode_responses=False
        )
        
        # Test connection
        await self.redis_client.ping()
        logger.info("✓ Connected to Redis")
        
        # Create persistence layer
        self.persistence = await PersistenceFactory.create(
            persistence_type=PersistenceType.REDIS,
            redis_url="redis://localhost:6379/0"
        )
        logger.info("✓ Created persistence layer")
        
        # Create event bus
        self.event_bus = StatelessEventBus(redis_client=self.redis_client)
        logger.info("✓ Initialized event bus")
        
        # Create registry and register provider
        self.registry = Registry()
        python_provider = PythonProvider()
        self.registry.register_provider("python", python_provider)
        logger.info("✓ Registered Python provider")
        
        # Register test functions
        self.registry.register_function(
            "add",
            lambda x, y: x + y,
            provider="python"
        )
        self.registry.register_function(
            "multiply",
            lambda x, y: x * y,
            provider="python"
        )
        self.registry.register_function(
            "slow_task",
            lambda duration: asyncio.run(asyncio.sleep(duration)) or f"Slept for {duration}s",
            provider="python"
        )
        logger.info("✓ Registered test functions")
        
        # Create task executor
        task_executor = TaskExecutor(
            persistence=self.persistence,
            provider_registry=self.registry,
            event_bus=self.event_bus
        )
        
        # Create dependency manager
        dependency_manager = UnifiedDependencyManager(
            persistence=self.persistence
        )
        
        # Create queue manager (for legacy compatibility)
        queue_manager = QueueManager(
            redis_client=self.redis_client,
            persistence=self.persistence,
            event_bus=self.event_bus
        )
        await queue_manager.initialize()
        
        # Setup feature flags
        self.feature_flags = FeatureFlags(self.redis_client)
        await self.feature_flags.initialize()
        
        # Create stream orchestrator
        self.orchestrator = StreamOrchestrator(
            redis_client=self.redis_client,
            queue_manager=queue_manager,
            dependency_manager=dependency_manager,
            task_executor=task_executor,
            persistence=self.persistence,
            event_bus=self.event_bus,
            max_concurrent_tasks=5,
            stream_mode=StreamMode.ENABLED,  # Full streams mode
            stream_percentage=100
        )
        await self.orchestrator.initialize()
        logger.info("✓ Created stream orchestrator")
        
        # Create stream worker
        self.worker = StreamTaskWorker(
            redis_client=self.redis_client,
            worker_id="test-worker-1",
            max_concurrent_tasks=3,
            batch_size=5
        )
        logger.info("✓ Created stream worker")
        
    async def create_simple_workflow(self) -> Workflow:
        """Create a simple test workflow."""
        workflow = Workflow(
            id="test-workflow-1",
            name="Simple Math Workflow",
            tasks=[
                Task(
                    id="task-1",
                    workflow_id="test-workflow-1",
                    function="add",
                    args={"x": 5, "y": 3},
                    dependencies=[]
                ),
                Task(
                    id="task-2",
                    workflow_id="test-workflow-1",
                    function="multiply",
                    args={"x": 2, "y": 4},
                    dependencies=[]
                ),
                Task(
                    id="task-3",
                    workflow_id="test-workflow-1",
                    function="add",
                    args={"x": "${task-1.result}", "y": "${task-2.result}"},
                    dependencies=["task-1", "task-2"]
                )
            ]
        )
        
        # Save workflow to persistence
        await self.persistence.save_workflow(workflow)
        
        return workflow
    
    async def run_workflow_test(self):
        """Test workflow execution with streams."""
        logger.info("\n" + "="*60)
        logger.info("TESTING WORKFLOW EXECUTION WITH STREAMS")
        logger.info("="*60)
        
        # Create workflow
        workflow = await self.create_simple_workflow()
        logger.info(f"Created workflow: {workflow.id}")
        
        # Submit workflow via streams
        await self.orchestrator.submit_workflow(workflow)
        logger.info("✓ Submitted workflow to streams")
        
        # Start orchestrator
        await self.orchestrator.start()
        
        # Start worker in background
        worker_task = asyncio.create_task(self.worker.start())
        logger.info("✓ Started stream worker")
        
        # Wait for workflow to complete
        max_wait = 30  # seconds
        start_time = asyncio.get_event_loop().time()
        
        while True:
            workflow = await self.persistence.get_workflow(workflow.id)
            
            if workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                break
            
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_wait:
                logger.error(f"Workflow did not complete within {max_wait} seconds")
                break
            
            await asyncio.sleep(1)
            logger.info(f"Waiting for workflow... Status: {workflow.status}")
        
        # Get final workflow status
        workflow = await self.persistence.get_workflow(workflow.id)
        logger.info(f"\nWorkflow final status: {workflow.status}")
        
        # Get task results
        for task in workflow.tasks:
            task_obj = await self.persistence.get_task(task.id)
            result = await self.persistence.get_task_result(task.id)
            
            logger.info(f"  Task {task.id}:")
            logger.info(f"    Status: {task_obj.status if task_obj else 'Not found'}")
            if result:
                logger.info(f"    Result: {result.result}")
                if result.error:
                    logger.info(f"    Error: {result.error}")
        
        # Stop worker
        self.worker.shutdown_event.set()
        await asyncio.wait_for(worker_task, timeout=5)
        
        # Stop orchestrator
        await self.orchestrator.stop()
        
        return workflow.status == WorkflowStatus.COMPLETED
    
    async def test_stream_features(self):
        """Test stream-specific features."""
        logger.info("\n" + "="*60)
        logger.info("TESTING STREAM-SPECIFIC FEATURES")
        logger.info("="*60)
        
        # Test feature flags
        logger.info("\n--- Feature Flags ---")
        await self.feature_flags.set_flag("stream_mode", StreamMode.ENABLED.value)
        mode = await self.feature_flags.get_flag("stream_mode")
        logger.info(f"Stream mode: {mode}")
        
        migration_status = await self.feature_flags.get_migration_status()
        logger.info(f"Migration progress: {migration_status['progress']}%")
        
        # Test DLQ
        logger.info("\n--- Dead Letter Queue ---")
        from gleitzeit.streams.dlq_handler import DeadLetterQueueHandler
        dlq = DeadLetterQueueHandler(self.redis_client)
        await dlq.initialize()
        
        # Add a test failure to DLQ
        await dlq.add_to_dlq(
            task_id="failed-task-test",
            workflow_id="test-workflow",
            error="Simulated permanent failure",
            retry_count=3
        )
        
        stats = await dlq.get_dlq_stats()
        logger.info(f"DLQ stats: {stats}")
        
        # Test retry manager
        logger.info("\n--- Retry Manager ---")
        from gleitzeit.streams.retry_manager import StreamRetryManager
        retry_mgr = StreamRetryManager(self.redis_client)
        await retry_mgr.initialize()
        
        scheduled = await retry_mgr.schedule_retry(
            task_id="retry-task-test",
            workflow_id="test-workflow",
            retry_count=0,
            error="Temporary failure"
        )
        logger.info(f"Scheduled retry: {scheduled}")
        
        retry_stats = await retry_mgr.get_retry_stats()
        logger.info(f"Retry queue size: {retry_stats['queue_size']}")
        
        # Test stream info
        logger.info("\n--- Stream Metrics ---")
        metrics = await self.orchestrator.get_metrics()
        logger.info(f"Orchestrator metrics: {metrics}")
        
        return True
    
    async def cleanup(self):
        """Clean up resources."""
        logger.info("\n" + "="*60)
        logger.info("CLEANUP")
        logger.info("="*60)
        
        # Clean up test data
        keys_to_delete = [
            "gleitzeit:*",
            "test-*"
        ]
        
        for pattern in keys_to_delete:
            cursor = 0
            while True:
                cursor, keys = await self.redis_client.scan(cursor, match=pattern, count=100)
                if keys:
                    await self.redis_client.delete(*keys)
                    logger.info(f"Deleted {len(keys)} keys matching {pattern}")
                if cursor == 0:
                    break
        
        # Close connections
        if self.persistence:
            await self.persistence.close()
        
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("✓ Cleanup complete")
    
    async def run(self):
        """Run all integration tests."""
        try:
            await self.setup()
            
            # Run tests
            workflow_success = await self.run_workflow_test()
            features_success = await self.test_stream_features()
            
            # Summary
            logger.info("\n" + "="*60)
            logger.info("TEST SUMMARY")
            logger.info("="*60)
            logger.info(f"Workflow execution: {'✓ PASSED' if workflow_success else '✗ FAILED'}")
            logger.info(f"Stream features: {'✓ PASSED' if features_success else '✗ FAILED'}")
            
            if workflow_success and features_success:
                logger.info("\n🎉 All tests passed!")
            else:
                logger.error("\n❌ Some tests failed")
            
        except Exception as e:
            logger.error(f"Integration test failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.cleanup()


async def main():
    """Main entry point."""
    integration = GleitzeitStreamIntegration()
    await integration.run()


if __name__ == "__main__":
    asyncio.run(main())