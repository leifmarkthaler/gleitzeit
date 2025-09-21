#!/usr/bin/env python3
"""
Test that the provider registration fix works.
This tests that tasks can now execute through the pooling adapter.
"""

import asyncio
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_provider_registration():
    """Test that providers are correctly registered and tasks can execute."""
    
    # Import after setting up logging
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.core.models import Task, Workflow, WorkflowStatus
    import uuid
    
    logger.info("Starting provider registration test")
    
    # Create system config
    config = SystemConfig(
        deployment_mode="development",
        environment="test",
        default_providers=["python"],
        persistence_backend="unified",
        max_workers=1
    )
    
    # Create system manager
    system_manager = SystemManager(config)
    
    try:
        # Initialize and start system manager
        logger.info("Initializing system manager...")
        await system_manager.initialize()
        logger.info("System manager initialized successfully")
        
        logger.info("Starting system manager...")
        await system_manager.start_system()
        logger.info("System manager started successfully")
        
        # Create a simple Python file to execute
        test_file = Path("test_hello.py")
        test_file.write_text("""
# Test Python script
result = 'Hello from Python provider!'
print(f"Result: {result}")
""")
        
        # Create a Python task to execute the file
        task = Task(
            id=f"test_task_{uuid.uuid4().hex[:8]}",
            name="Test Python Task",
            protocol="python/v1",
            method="python/execute",  # Correct method name
            params={
                "file_path": str(test_file.absolute()),
                "return_output": True
            }
        )
        
        # Create workflow with the task
        workflow = Workflow(
            id=f"test_workflow_{uuid.uuid4().hex[:8]}",
            name="Test Provider Workflow",
            tasks=[task]
        )
        
        logger.info(f"Submitting workflow {workflow.id} with task {task.id}")
        
        # Submit workflow through workflow manager
        if system_manager.workflow_manager:
            result = await system_manager.workflow_manager.execute_workflow(workflow)
            logger.info(f"Workflow execution started: {result}")
            
            # Wait for workflow to complete (with timeout)
            import asyncio
            max_wait = 10  # seconds
            check_interval = 0.5
            elapsed = 0
            
            while elapsed < max_wait:
                # Get workflow status from persistence
                if system_manager.persistence:
                    workflow_data = await system_manager.persistence.get_workflow(workflow.id)
                    if workflow_data:
                        logger.info(f"Workflow status: {workflow_data.status}")
                        
                        if str(workflow_data.status) == "WorkflowStatus.COMPLETED" or workflow_data.status == WorkflowStatus.COMPLETED:
                            # Get task results
                            task_result = await system_manager.persistence.get_task_result(task.id)
                            if task_result:
                                logger.info("✅ SUCCESS: Task executed through pooling adapter!")
                                logger.info(f"Task result: {task_result.result}")
                                logger.info(f"Task output: {task_result.output if hasattr(task_result, 'output') else 'N/A'}")
                                return True
                            else:
                                logger.warning("Task completed but no result found")
                                
                        elif workflow_data.status == "FAILED":
                            logger.error(f"❌ FAILED: Workflow failed")
                            # Try to get task result for error details
                            task_result = await system_manager.persistence.get_task_result(task.id)
                            if task_result:
                                logger.error(f"Task error: {task_result.error}")
                            return False
                            
                await asyncio.sleep(check_interval)
                elapsed += check_interval
                
            logger.error(f"❌ TIMEOUT: Workflow did not complete within {max_wait} seconds")
            
            # Check final status
            if system_manager.persistence:
                workflow_data = await system_manager.persistence.get_workflow(workflow.id)
                if workflow_data:
                    logger.error(f"Final workflow status: {workflow_data.status}")
                    
                task_data = await system_manager.persistence.get_task(task.id)
                if task_data:
                    logger.error(f"Final task status: {task_data.status}")
                    
            return False
        else:
            logger.error("❌ FAILED: WorkflowManager not available")
            return False
            
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        logger.info("Shutting down system manager...")
        await system_manager.shutdown()
        logger.info("System manager shutdown complete")

async def main():
    """Run the test."""
    success = await test_provider_registration()
    
    if success:
        print("\n✅ Provider registration fix is working!")
        print("Tasks can now execute through the pooling adapter.")
    else:
        print("\n❌ Provider registration fix is NOT working.")
        print("Check the logs above for details.")
    
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)