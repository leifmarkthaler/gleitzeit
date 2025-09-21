#!/usr/bin/env python3
"""
Test signal workflow with ModularStreamSystemManager.
This tests that the SignalProvider is properly registered and working.
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

async def test_signal_workflow():
    """Test signal workflow with ModularStreamSystemManager."""

    print("Creating ModularStreamSystemManager...")
    config = SystemConfig()
    config.deployment_mode = DeploymentMode.DEVELOPMENT

    manager = await ModularStreamSystemManager.create(
        config=config,
        stream_config={'total_shards': 8},
        create_if_missing=True,
        start_system=True  # Start the system
    )

    if not manager:
        print("❌ Failed to create manager")
        return False

    print(f"✓ Created manager: {manager.instance_id}")

    try:
        # Wait for system to be ready
        await asyncio.sleep(1)

        # Create a signal workflow with both timer and signal tasks
        workflow = Workflow(
            id=f"test_signal_{uuid.uuid4().hex[:8]}",
            name="test_signal_workflow",
            tasks=[
                Task(
                    id="task_1_timer",
                    name="Initial Timer",
                    protocol="timer/v1",
                    method="timer/sleep",
                    params={"seconds": 1},
                    dependencies=[]
                ),
                Task(
                    id="task_2_signal",
                    name="Wait for Signal",
                    protocol="signal/v1",
                    method="signal/wait",
                    params={
                        "signal": "test_approval",
                        "timeout": 10  # 10 second timeout
                    },
                    dependencies=["task_1_timer"]
                ),
                Task(
                    id="task_3_complete",
                    name="Complete",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "code": "print('Signal received!')\nresult = 'completed'"
                    },
                    dependencies=["task_2_signal"]
                )
            ],
            status=WorkflowStatus.PENDING,
            created_at=datetime.utcnow()
        )

        print(f"\n✓ Created workflow: {workflow.id}")
        print("  - Task 1: Timer (1 second)")
        print("  - Task 2: Wait for signal 'test_approval'")
        print("  - Task 3: Python task to complete")

        # Submit the workflow
        print("\nSubmitting workflow...")
        workflow_id = await manager.submit_workflow(workflow)
        print(f"✓ Workflow submitted: {workflow_id}")

        # Give it a moment to start
        await asyncio.sleep(2)

        # Check workflow status
        workflow_data = await manager.get_workflow(workflow_id)
        print(f"\nWorkflow status after 2 seconds: {workflow_data.status}")

        # The timer task should be complete, signal task should be waiting
        if workflow_data.tasks:
            for task in workflow_data.tasks:
                print(f"  - {task.id}: {task.status}")
                if task.id == "task_1_timer" and task.status != TaskStatus.COMPLETED:
                    print(f"    ⚠️ Timer task should be completed by now")
                if task.id == "task_2_signal" and task.status == TaskStatus.SLEEPING:
                    print(f"    ✓ Signal task is correctly in SLEEPING state")

        # Now send the signal
        print(f"\n📨 Sending signal 'test_approval'...")
        signal_sent = await manager.send_signal(
            signal_name="test_approval",
            data={"approved_by": "test_script"},
            target_workflow_id=workflow_id
        )

        if signal_sent:
            print("✓ Signal sent successfully")
        else:
            print("❌ Failed to send signal")

        # Wait for workflow to complete
        print("\nWaiting for workflow to complete...")
        max_wait = 10
        for i in range(max_wait):
            await asyncio.sleep(1)
            workflow_data = await manager.get_workflow(workflow_id)
            print(f"  {i+1}s: {workflow_data.status}")
            if workflow_data.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                break

        # Final status
        print(f"\n{'='*50}")
        workflow_data = await manager.get_workflow(workflow_id)
        print(f"Final workflow status: {workflow_data.status}")

        if workflow_data.tasks:
            print("\nTask statuses:")
            for task in workflow_data.tasks:
                print(f"  - {task.id}: {task.status}")
                if task.status == TaskStatus.COMPLETED:
                    print(f"    ✓ Task completed")
                elif task.status == TaskStatus.FAILED:
                    print(f"    ❌ Task failed")
                    if hasattr(task, 'error'):
                        print(f"    Error: {task.error}")

        # Check if workflow completed successfully
        if workflow_data.status == WorkflowStatus.COMPLETED:
            print("\n✅ SUCCESS: Signal workflow completed!")
            print("✅ SignalProvider is working correctly!")
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
    result = asyncio.run(test_signal_workflow())
    sys.exit(0 if result else 1)