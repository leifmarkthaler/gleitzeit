#!/usr/bin/env python
"""Test running a real workflow with Redis Streams implementation."""

import asyncio
import logging
import sys
import yaml
import uuid
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import redis.asyncio as redis

# Gleitzeit imports
from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.persistence.factory import PersistenceFactory, PersistenceType
from gleitzeit.events.stateless_bus import StatelessEventBus
from gleitzeit.providers.pooling_adapter import PoolingAdapter
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.core.task_executor import TaskExecutor
from gleitzeit.core.task_orchestrator import TaskOrchestrator
from gleitzeit.core.dependency_manager import UnifiedDependencyManager
from gleitzeit.task_queue import QueueManager

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


class WorkflowRunner:
    """Run workflows using Redis Streams."""
    
    def __init__(self):
        self.redis_client = None
        self.persistence = None
        self.event_bus = None
        self.orchestrator = None
        self.worker = None
        self.pooling_adapter = None
        self.registry = None
        
    async def setup(self):
        """Setup all components."""
        logger.info("Setting up Gleitzeit with Redis Streams...")
        
        # Connect to Redis
        self.redis_client = redis.from_url(
            "redis://localhost:6379",
            decode_responses=False
        )
        await self.redis_client.ping()
        logger.info("✓ Connected to Redis")
        
        # Create persistence
        self.persistence = await PersistenceFactory.create(
            persistence_type=PersistenceType.REDIS
        )
        logger.info("✓ Created persistence layer")
        
        # Create event bus
        self.event_bus = StatelessEventBus(persistence=self.persistence)
        logger.info("✓ Created event bus")
        
        # Create registry
        self.registry = ProtocolProviderRegistry()
        
        # Create pooling adapter (handles provider execution)
        self.pooling_adapter = PoolingAdapter(
            persistence=self.persistence,
            redis_client=self.redis_client,
            registry=self.registry
        )
        await self.pooling_adapter.initialize()
        logger.info("✓ Initialized pooling adapter")
        
        # Create task executor
        task_executor = TaskExecutor(
            pooling_adapter=self.pooling_adapter,
            persistence=self.persistence,
            event_bus=self.event_bus
        )
        
        # Create dependency manager
        dependency_manager = UnifiedDependencyManager(
            persistence=self.persistence
        )
        
        # Create queue manager (for compatibility)
        queue_manager = QueueManager(
            redis_client=self.redis_client,
            persistence=self.persistence,
            event_bus=self.event_bus
        )
        await queue_manager.initialize()
        
        # Setup feature flags for streams
        feature_flags = FeatureFlags(self.redis_client)
        await feature_flags.initialize()
        await feature_flags.set_flag("stream_mode", StreamMode.ENABLED.value)
        await feature_flags.set_flag("stream_percentage", 100)
        logger.info("✓ Configured for 100% streams mode")
        
        # Create stream orchestrator
        self.orchestrator = StreamOrchestrator(
            redis_client=self.redis_client,
            queue_manager=queue_manager,
            dependency_manager=dependency_manager,
            task_executor=task_executor,
            persistence=self.persistence,
            event_bus=self.event_bus,
            max_concurrent_tasks=5,
            stream_mode=StreamMode.ENABLED,
            stream_percentage=100
        )
        await self.orchestrator.initialize()
        logger.info("✓ Created stream orchestrator")
        
        # Create worker
        self.worker = StreamTaskWorker(
            redis_client=self.redis_client,
            worker_id="workflow-test-worker",
            max_concurrent_tasks=3
        )
        logger.info("✓ Created stream worker")
        
    async def load_workflow(self, workflow_file: str) -> Workflow:
        """Load workflow from YAML file."""
        with open(workflow_file, 'r') as f:
            workflow_data = yaml.safe_load(f)
        
        workflow_id = f"workflow-{uuid.uuid4().hex[:8]}"
        
        # Create tasks from workflow data
        tasks = []
        for i, task_data in enumerate(workflow_data.get('tasks', [])):
            task = Task(
                id=f"task-{workflow_id}-{i}",
                workflow_id=workflow_id,
                name=task_data.get('name', f'task-{i}'),
                function=task_data.get('method', 'unknown'),
                args=task_data.get('params', {}),
                dependencies=task_data.get('dependencies', []),
                priority=task_data.get('priority', 1)
            )
            tasks.append(task)
        
        workflow = Workflow(
            id=workflow_id,
            name=workflow_data.get('name', 'Test Workflow'),
            description=workflow_data.get('description', ''),
            tasks=tasks,
            timeout=workflow_data.get('timeout', 300)
        )
        
        # Save to persistence
        await self.persistence.save_workflow(workflow)
        logger.info(f"Loaded workflow: {workflow.name} ({workflow.id})")
        
        return workflow
    
    async def run_workflow(self, workflow_file: str):
        """Run a workflow from file."""
        logger.info(f"\nRunning workflow from: {workflow_file}")
        logger.info("="*60)
        
        # Load workflow
        workflow = await self.load_workflow(workflow_file)
        
        # Submit workflow via streams
        await self.orchestrator.submit_workflow(workflow)
        logger.info(f"✓ Submitted workflow {workflow.id} to streams")
        
        # Start orchestrator
        await self.orchestrator.start()
        
        # Start worker in background
        worker_task = asyncio.create_task(self.run_worker())
        logger.info("✓ Started stream worker")
        
        # Monitor workflow progress
        start_time = datetime.utcnow()
        last_status = None
        
        while True:
            workflow = await self.persistence.get_workflow(workflow.id)
            
            if workflow.status != last_status:
                elapsed = (datetime.utcnow() - start_time).seconds
                logger.info(f"[{elapsed}s] Workflow status: {workflow.status}")
                last_status = workflow.status
                
                # Show task statuses
                for task in workflow.tasks:
                    task_obj = await self.persistence.get_task(task.id)
                    if task_obj:
                        logger.info(f"  - {task_obj.name}: {task_obj.status}")
            
            if workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                break
            
            # Check timeout
            if (datetime.utcnow() - start_time).seconds > workflow.timeout:
                logger.error(f"Workflow timed out after {workflow.timeout}s")
                break
            
            await asyncio.sleep(1)
        
        # Get final results
        logger.info("\n" + "="*60)
        logger.info("WORKFLOW RESULTS")
        logger.info("="*60)
        
        workflow = await self.persistence.get_workflow(workflow.id)
        logger.info(f"Final status: {workflow.status}")
        logger.info(f"Duration: {(datetime.utcnow() - start_time).seconds}s")
        
        # Show task results
        logger.info("\nTask Results:")
        for task in workflow.tasks:
            task_obj = await self.persistence.get_task(task.id)
            result = await self.persistence.get_task_result(task.id)
            
            logger.info(f"\n{task.name}:")
            logger.info(f"  Status: {task_obj.status if task_obj else 'Unknown'}")
            
            if result:
                if result.result:
                    logger.info(f"  Result: {result.result}")
                if result.error:
                    logger.info(f"  Error: {result.error}")
        
        # Stop worker
        self.worker.shutdown_event.set()
        try:
            await asyncio.wait_for(worker_task, timeout=5)
        except asyncio.TimeoutError:
            logger.warning("Worker shutdown timed out")
        
        # Stop orchestrator
        await self.orchestrator.stop()
        
        return workflow.status == WorkflowStatus.COMPLETED
    
    async def run_worker(self):
        """Run the stream worker."""
        try:
            # Initialize worker
            await self.worker.initialize()
            
            # Process tasks
            while not self.worker.shutdown_event.is_set():
                # Read and process tasks from streams
                for priority in ["high", "normal", "low"]:
                    await self.worker.task_stream.ensure_consumer_group(priority)
                
                tasks = await self.worker.task_stream.claim_tasks(
                    self.worker.consumer_name,
                    count=5
                )
                
                for task_data in tasks:
                    if self.worker.shutdown_event.is_set():
                        break
                    
                    await self.worker._process_task(task_data)
                
                if not tasks:
                    await asyncio.sleep(0.5)
                    
        except Exception as e:
            logger.error(f"Worker error: {e}")
    
    async def cleanup(self):
        """Clean up resources."""
        logger.info("\nCleaning up...")
        
        if self.pooling_adapter:
            await self.pooling_adapter.cleanup()
        
        # Persistence doesn't have close method, just skip
        
        if self.redis_client:
            await self.redis_client.aclose()
        
        logger.info("✓ Cleanup complete")


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        # Default to simple workflow
        workflow_file = "testworkflows/simple_python_workflow.yaml"
    else:
        workflow_file = sys.argv[1]
    
    runner = WorkflowRunner()
    
    try:
        await runner.setup()
        success = await runner.run_workflow(workflow_file)
        
        if success:
            logger.info("\n✅ Workflow completed successfully!")
        else:
            logger.error("\n❌ Workflow failed")
        
        return success
        
    except Exception as e:
        logger.error(f"Error running workflow: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)