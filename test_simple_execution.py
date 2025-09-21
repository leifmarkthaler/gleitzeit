#!/usr/bin/env python3
"""
Test very simple workflow execution.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system import create_system_manager
from gleitzeit.core.models import Workflow, Task, WorkflowStatus, TaskStatus
import uuid
from datetime import datetime

async def test_simple_execution():
    """Test simple workflow execution."""
    print("="*60)
    print("Testing Simple Workflow Execution")
    print("="*60)

    # Create system manager
    print("\nCreating system manager...")
    system_manager = await create_system_manager()
    print(f"✓ System manager created: {system_manager.instance_id}")

    # Start the system
    print("Starting system...")
    await system_manager.start_system()
    print("✓ System started")

    try:
        # Create a very simple workflow with a Python task
        workflow = Workflow(
            id=f"test_{uuid.uuid4().hex[:8]}",
            name="test_simple",
            tasks=[
                Task(
                    id="task_1",
                    name="Simple Task",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "file": "tasks/simple_calculation.py"
                    },
                    dependencies=[]
                )
            ],
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow()
        )

        print(f"\n✓ Created workflow: {workflow.id}")
        print(f"  Task: {workflow.tasks[0].id}")

        # Submit the workflow
        print("\nSubmitting workflow...")
        workflow_id = await system_manager.submit_workflow(workflow)
        print(f"✓ Workflow submitted: {workflow_id}")

        # Wait a moment
        await asyncio.sleep(2)

        # Check status
        workflow_data = await system_manager.get_workflow(workflow_id)
        if workflow_data:
            print(f"\nWorkflow status: {workflow_data.status}")
            if workflow_data.tasks:
                for task in workflow_data.tasks:
                    print(f"  Task {task.id}: {task.status}")

        # Wait a bit more
        await asyncio.sleep(3)

        # Final check
        workflow_data = await system_manager.get_workflow(workflow_id)
        print(f"\nFinal workflow status: {workflow_data.status}")
        if workflow_data.tasks:
            for task in workflow_data.tasks:
                print(f"  Task {task.id}: {task.status}")

        if workflow_data.status == "completed":
            print("\n✅ SUCCESS: Workflow completed!")
            return True
        else:
            print(f"\n⚠️ Workflow status: {workflow_data.status}")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print("\nShutting down...")
        await system_manager.shutdown()
        print("✓ Shutdown complete")

if __name__ == "__main__":
    result = asyncio.run(test_simple_execution())
    sys.exit(0 if result else 1)
