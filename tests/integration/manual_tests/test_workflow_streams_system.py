#!/usr/bin/env python
"""Test running workflows with Redis Streams using SystemManager."""

import asyncio
import logging
import sys
import yaml
import uuid
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# System imports
from gleitzeit.system.system_manager import SystemManager
from gleitzeit.core.models import Task, Workflow, WorkflowStatus

# Streams imports
from gleitzeit.streams.stream_orchestrator import StreamOrchestrator, StreamMode
from gleitzeit.streams.feature_flags import FeatureFlags

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StreamWorkflowRunner:
    """Run workflows using SystemManager with Redis Streams."""
    
    def __init__(self):
        self.system = None
        self.feature_flags = None
        
    async def setup(self):
        """Setup system with streams enabled."""
        logger.info("Initializing SystemManager with Redis Streams...")
        
        # Create system manager
        self.system = SystemManager()
        await self.system.initialize()
        logger.info("✓ SystemManager initialized")
        
        # Get components
        redis_client = self.system.redis_client
        
        # Setup feature flags for streams
        self.feature_flags = FeatureFlags(redis_client)
        await self.feature_flags.initialize()
        await self.feature_flags.set_flag("stream_mode", StreamMode.ENABLED.value)
        await self.feature_flags.set_flag("stream_percentage", 100)
        logger.info("✓ Configured for 100% streams mode")
        
        # Replace the orchestrator with stream orchestrator
        if hasattr(self.system, 'orchestrator'):
            # Create stream orchestrator using system components
            stream_orchestrator = StreamOrchestrator(
                redis_client=redis_client,
                queue_manager=self.system.queue_manager,
                dependency_manager=self.system.dependency_manager,
                task_executor=self.system.executor,
                persistence=self.system.persistence,
                event_bus=self.system.event_bus,
                max_concurrent_tasks=5,
                stream_mode=StreamMode.ENABLED,
                stream_percentage=100
            )
            await stream_orchestrator.initialize()
            
            # Replace system's orchestrator
            self.system.orchestrator = stream_orchestrator
            logger.info("✓ Replaced orchestrator with StreamOrchestrator")
        
        # Start the system
        await self.system.start()
        logger.info("✓ System started with Redis Streams")
        
    async def load_workflow(self, workflow_file: str) -> Workflow:
        """Load workflow from YAML file."""
        with open(workflow_file, 'r') as f:
            workflow_data = yaml.safe_load(f)
        
        workflow_id = f"workflow-{uuid.uuid4().hex[:8]}"
        
        # Create tasks from workflow data
        tasks = []
        for i, task_data in enumerate(workflow_data.get('tasks', [])):
            # Handle dependencies
            deps = task_data.get('dependencies', [])
            if isinstance(deps, str):
                deps = [deps]
            
            # Map task names to IDs if needed
            task_deps = []
            for dep in deps:
                if dep.startswith('task-'):
                    task_deps.append(dep)
                else:
                    # Find task by name
                    for j, t in enumerate(workflow_data.get('tasks', [])):
                        if t.get('name') == dep:
                            task_deps.append(f"task-{workflow_id}-{j}")
                            break
            
            task = Task(
                id=f"task-{workflow_id}-{i}",
                workflow_id=workflow_id,
                name=task_data.get('name', f'task-{i}'),
                function=task_data.get('method', 'unknown'),
                args=task_data.get('params', {}),
                dependencies=task_deps,
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
        
        logger.info(f"Loaded workflow: {workflow.name} ({workflow.id})")
        return workflow
    
    async def run_workflow(self, workflow_file: str):
        """Run a workflow from file."""
        logger.info(f"\nRunning workflow from: {workflow_file}")
        logger.info("="*60)
        
        # Load workflow
        workflow = await self.load_workflow(workflow_file)
        
        # Submit workflow through system
        workflow_id = await self.system.submit_workflow(workflow)
        logger.info(f"✓ Submitted workflow {workflow_id}")
        
        # Monitor workflow progress
        start_time = datetime.utcnow()
        last_status = None
        timeout = workflow.timeout
        
        while True:
            # Get workflow status
            workflow_obj = await self.system.persistence.get_workflow(workflow_id)
            
            if workflow_obj and workflow_obj.status != last_status:
                elapsed = (datetime.utcnow() - start_time).seconds
                logger.info(f"[{elapsed}s] Workflow status: {workflow_obj.status}")
                last_status = workflow_obj.status
                
                # Show task statuses
                if workflow_obj.tasks:
                    for task in workflow_obj.tasks:
                        task_obj = await self.system.persistence.get_task(task.id)
                        if task_obj:
                            logger.info(f"  - {task_obj.name}: {task_obj.status}")
            
            if workflow_obj and workflow_obj.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                break
            
            # Check timeout
            if (datetime.utcnow() - start_time).seconds > timeout:
                logger.error(f"Workflow timed out after {timeout}s")
                break
            
            await asyncio.sleep(1)
        
        # Get final results
        logger.info("\n" + "="*60)
        logger.info("WORKFLOW RESULTS")
        logger.info("="*60)
        
        workflow_obj = await self.system.persistence.get_workflow(workflow_id)
        if workflow_obj:
            logger.info(f"Final status: {workflow_obj.status}")
            logger.info(f"Duration: {(datetime.utcnow() - start_time).seconds}s")
            
            # Show task results
            logger.info("\nTask Results:")
            for task in workflow_obj.tasks:
                task_obj = await self.system.persistence.get_task(task.id)
                result = await self.system.persistence.get_task_result(task.id)
                
                logger.info(f"\n{task.name}:")
                logger.info(f"  Status: {task_obj.status if task_obj else 'Unknown'}")
                
                if result:
                    if result.result:
                        logger.info(f"  Result: {result.result}")
                    if result.error:
                        logger.info(f"  Error: {result.error}")
            
            return workflow_obj.status == WorkflowStatus.COMPLETED
        
        return False
    
    async def get_stream_metrics(self):
        """Get Redis Streams metrics."""
        logger.info("\n" + "="*60)
        logger.info("REDIS STREAMS METRICS")
        logger.info("="*60)
        
        if hasattr(self.system.orchestrator, 'get_metrics'):
            metrics = await self.system.orchestrator.get_metrics()
            for key, value in metrics.items():
                logger.info(f"  {key}: {value}")
        
        # Get feature flags status
        if self.feature_flags:
            status = await self.feature_flags.get_migration_status()
            logger.info(f"\nMigration Status:")
            logger.info(f"  Mode: {status['mode']}")
            logger.info(f"  Progress: {status['progress']}%")
    
    async def cleanup(self):
        """Clean up resources."""
        logger.info("\nStopping system...")
        
        if self.system:
            await self.system.stop()
            await self.system.cleanup()
        
        logger.info("✓ System stopped and cleaned up")


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        # Default to simple workflow
        workflow_file = "testworkflows/simple_python_workflow.yaml"
    else:
        workflow_file = sys.argv[1]
    
    # Check if workflow file exists
    if not Path(workflow_file).exists():
        logger.error(f"Workflow file not found: {workflow_file}")
        return False
    
    runner = StreamWorkflowRunner()
    
    try:
        await runner.setup()
        success = await runner.run_workflow(workflow_file)
        await runner.get_stream_metrics()
        
        if success:
            logger.info("\n✅ Workflow completed successfully using Redis Streams!")
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