#!/usr/bin/env python3
"""
Test workflow submission with dict format.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

async def test_dict_workflow():
    """Test workflow submission with dict format."""
    print("Creating ModularStreamSystemManager...")

    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    manager = await ModularStreamSystemManager.create(
        config=config,
        stream_config={'total_shards': 8},
        create_if_missing=True,
        start_system=False  # Don't start consumer initially
    )

    if not manager:
        print("❌ Failed to create manager")
        return False

    print(f"✓ Created manager: {manager.instance_id}")

    try:
        # Create a workflow using dict format (how YAML gets loaded)
        workflow_dict = {
            "name": "test_simple_workflow",
            "tasks": [
                {
                    "id": "task_1",
                    "name": "Python Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": "print('Hello from task')\\nresult = 'completed'"
                    },
                    "dependencies": []
                }
            ]
        }

        print(f"\n✓ Created workflow dict")

        # Submit the workflow
        print("\nSubmitting workflow...")
        workflow_id = await manager.submit_workflow(workflow_dict)
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
            print("❌ Workflow not found")
            return False

        print("\n✅ Workflow submission succeeded!")

        # Now start the system to process the workflow
        print("\nStarting system to process workflow...")
        started = await manager.start_system()
        if not started:
            print("❌ Failed to start system")
            return False

        print("✓ System started")

        # Monitor workflow progress
        print("\nMonitoring workflow...")
        max_wait = 10
        for i in range(max_wait):
            await asyncio.sleep(1)
            workflow_data = await manager.get_workflow(workflow_id)
            print(f"  {i+1}s: Workflow: {workflow_data.status}")

            if workflow_data.tasks:
                for task in workflow_data.tasks:
                    print(f"       Task {task.id}: {task.status}")

            if workflow_data.status in ["completed", "failed"]:
                break

        # Final check
        workflow_data = await manager.get_workflow(workflow_id)
        if workflow_data.status == "completed":
            print("\n✅ Workflow completed successfully!")
            return True
        else:
            print(f"\n❌ Workflow ended with status: {workflow_data.status}")
            return False

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
    result = asyncio.run(test_dict_workflow())
    sys.exit(0 if result else 1)