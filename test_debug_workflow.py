#!/usr/bin/env python3
"""
Debug test for workflow execution with ModularStreamSystemManager.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.core.models import Workflow, Task, WorkflowStatus, TaskStatus
import uuid
from datetime import datetime

async def test_simple_workflow():
    """Test a very simple workflow."""

    print("Creating ModularStreamSystemManager...")
    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    manager = await ModularStreamSystemManager.create(
        config=config,
        stream_config={'total_shards': 8},
        create_if_missing=True,
        start_system=True
    )

    if not manager:
        print("❌ Failed to create manager")
        return False

    print(f"✓ Created manager: {manager.instance_id}")

    try:
        # Wait for system to be ready
        await asyncio.sleep(1)

        # Create a very simple workflow with just a Python task
        workflow = Workflow(
            id=f"test_simple_{uuid.uuid4().hex[:8]}",
            name="test_simple_workflow",
            tasks=[
                Task(
                    id="task_1",
                    name="Simple Python Task",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "code": "print('Hello from Python task')\\nresult = 'success'"
                    },
                    dependencies=[]
                )
            ],
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow()
        )

        print(f"\n✓ Created workflow: {workflow.id}")
        print("  - Task 1: Simple Python task")

        # Submit the workflow
        print("\nSubmitting workflow...")
        workflow_id = await manager.submit_workflow(workflow)
        print(f"✓ Workflow submitted: {workflow_id}")

        # Monitor workflow progress
        print("\nMonitoring workflow progress...")
        for i in range(10):
            await asyncio.sleep(1)
            workflow_data = await manager.get_workflow(workflow_id)
            print(f"  {i+1}s: Workflow status: {workflow_data.status}")

            if workflow_data.tasks:
                for task in workflow_data.tasks:
                    print(f"       Task {task.id}: {task.status}")

            if workflow_data.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                break

        # Final status
        print(f"\n{'='*50}")
        workflow_data = await manager.get_workflow(workflow_id)
        print(f"Final workflow status: {workflow_data.status}")

        if workflow_data.status == WorkflowStatus.COMPLETED:
            print("\n✅ SUCCESS: Simple workflow completed!")
            return True
        else:
            print(f"\n❌ FAILED: Workflow did not complete successfully")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print("\nShutting down manager...")
        await manager.shutdown()
        print("✓ Manager shutdown complete")

if __name__ == "__main__":
    result = asyncio.run(test_simple_workflow())
    sys.exit(0 if result else 1)