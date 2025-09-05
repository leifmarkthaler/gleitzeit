#!/usr/bin/env python3
"""
Fix persistence method calls to use save_workflow/save_task instead of update_*_status.
"""

import asyncio
import logging
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.models import TaskStatus, WorkflowStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_persistence_methods():
    """Test that persistence methods work correctly."""
    persistence = await PersistenceFactory.create()
    
    # Test workflow operations
    logger.info("Testing workflow operations...")
    
    # Get a workflow
    workflows = await persistence.list_workflows(limit=1)
    if workflows and workflows.get('workflows'):
        workflow_id = workflows['workflows'][0].get('id')
        logger.info(f"Found workflow: {workflow_id}")
        
        # Get the workflow object
        workflow = await persistence.get_workflow(workflow_id)
        if workflow:
            logger.info(f"Current status: {workflow.status if hasattr(workflow, 'status') else 'unknown'}")
            
            # Update its status
            if hasattr(workflow, 'status'):
                workflow.status = WorkflowStatus.RUNNING
                await persistence.save_workflow(workflow)
                logger.info("Updated workflow status to RUNNING")
            else:
                logger.warning("Workflow doesn't have status attribute")
    
    # Test task operations
    logger.info("Testing task operations...")
    
    # Get tasks
    tasks = await persistence.list_tasks(limit=1)
    if tasks and tasks.get('tasks'):
        task_dict = tasks['tasks'][0]
        task_id = task_dict.get('id')
        logger.info(f"Found task: {task_id}")
        
        # Get the task object
        task = await persistence.get_task(task_id)
        if task:
            logger.info(f"Current task status: {task.status if hasattr(task, 'status') else 'unknown'}")
            
            # Update its status
            if hasattr(task, 'status'):
                task.status = TaskStatus.RUNNING
                await persistence.save_task(task)
                logger.info("Updated task status to RUNNING")
    
    logger.info("Test complete!")


if __name__ == "__main__":
    asyncio.run(test_persistence_methods())