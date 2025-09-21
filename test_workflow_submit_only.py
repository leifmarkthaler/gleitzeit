#!/usr/bin/env python3
"""
Test workflow submission without stream consumer.
"""

import asyncio
import sys
from pathlib import Path
import uuid
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.core.models import Workflow, Task, WorkflowStatus, TaskStatus

async def test_submit_only():
    """Test workflow submission without starting consumer."""
    print("Creating ModularStreamSystemManager...")

    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    manager = await ModularStreamSystemManager.create(
        config=config,
        stream_config={'total_shards': 8},
        create_if_missing=True,
        start_system=False  # Don't start consumer
    )

    if not manager:
        print("❌ Failed to create manager")
        return False

    print(f"✓ Created manager: {manager.instance_id}")

    try:
        # Create a simple workflow
        workflow = Workflow(
            id=f"test_{uuid.uuid4().hex[:8]}",
            name="test_workflow",
            tasks=[
                Task(
                    id="task_1",
                    name="Python Task",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "code": "print('Test')\\nresult = 'done'"
                    },
                    dependencies=[]
                )
            ],
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow()
        )

        print(f"\n✓ Created workflow: {workflow.id}")

        # Submit the workflow
        print("\nSubmitting workflow...")
        workflow_id = await manager.submit_workflow(workflow)
        print(f"✓ Workflow submitted: {workflow_id}")

        # Check if workflow was saved
        saved_workflow = await manager.get_workflow(workflow_id)
        if saved_workflow:
            print(f"✓ Workflow saved with status: {saved_workflow.status}")
            print(f"  Tasks: {len(saved_workflow.tasks)}")
            if saved_workflow.tasks:
                for task in saved_workflow.tasks:
                    print(f"    - {task.id}: {task.status}")
        else:
            print("❌ Workflow not found in persistence")
            return False

        print("\n✅ Workflow submission works without stream consumer!")

        # Now let's try starting just the workflow manager's scheduler
        print("\nStarting workflow manager scheduler...")
        if hasattr(manager.workflow_manager, 'start_scheduler'):
            await manager.workflow_manager.start_scheduler()
            print("✓ Scheduler started")

            # Wait a bit to see if tasks get picked up
            await asyncio.sleep(2)

            # Check workflow status again
            updated_workflow = await manager.get_workflow(workflow_id)
            print(f"\nAfter scheduler start:")
            print(f"  Workflow status: {updated_workflow.status}")
            if updated_workflow.tasks:
                for task in updated_workflow.tasks:
                    print(f"    - {task.id}: {task.status}")

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print("\nShutting down...")
        await manager.shutdown()
        print("✓ Shutdown complete")

if __name__ == "__main__":
    result = asyncio.run(test_submit_only())
    sys.exit(0 if result else 1)