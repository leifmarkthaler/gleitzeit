#!/usr/bin/env python3
"""
Test running a workflow with file-based Python tasks.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.system import create_system_manager

async def test_file_workflow():
    """Test workflow execution with file-based tasks."""
    print("="*60)
    print("Testing File-Based Python Workflow")
    print("="*60)

    # Create system manager first
    print("\nCreating system manager...")
    system_manager = await create_system_manager()
    print(f"✓ System manager created: {system_manager.instance_id}")

    # Start the system
    print("Starting system...")
    await system_manager.start_system()
    print("✓ System started")

    # Create client with system manager
    client = GleitzeitClient(mode=ClientMode.NATIVE, system_manager=system_manager)
    await client.initialize()

    try:
        # Load and submit the workflow
        workflow_file = Path("workflows/test_calculation.yaml")
        print(f"\n1. Loading workflow from: {workflow_file}")

        with open(workflow_file, 'r') as f:
            import yaml
            workflow_data = yaml.safe_load(f)

        print(f"   Workflow: {workflow_data['name']}")
        print(f"   Tasks: {len(workflow_data['tasks'])}")

        # Submit the workflow
        print("\n2. Submitting workflow...")
        result = await client.submit_workflow(workflow_data)

        # Check if submission was successful
        if isinstance(result, dict) and not result.get('success', True):
            print(f"   ❌ Submission failed: {result.get('error')}")
            return False

        workflow_id = result if isinstance(result, str) else result.get('workflow_id', result)
        print(f"   ✓ Workflow ID: {workflow_id}")

        # Monitor workflow progress
        print("\n3. Monitoring execution...")
        max_wait = 30
        for i in range(max_wait):
            await asyncio.sleep(1)

            # Get workflow
            workflow = await client.get_workflow(workflow_id)
            if workflow:
                print(f"   {i+1}s: Workflow status: {workflow.status}")
                if workflow.tasks:
                    for task in workflow.tasks:
                        print(f"        - {task.id}: {task.status}")
                        if task.status == "failed" and hasattr(task, 'error'):
                            print(f"          Error: {task.error}")

                # Check if complete
                if workflow.status in ["completed", "failed"]:
                    break

        # Final result
        print("\n4. Final Status:")
        workflow = await client.get_workflow(workflow_id)
        print(f"   Workflow: {workflow.status}")

        if workflow.tasks:
            print("\n   Task Results:")
            for task in workflow.tasks:
                print(f"   - {task.id}: {task.status}")
                if task.status == "completed":
                    # Try to get task result
                    try:
                        result = await client.get_task_result(task.id)
                        if result:
                            print(f"     Result: {result}")
                    except:
                        pass

        if workflow.status == "completed":
            print("\n✅ SUCCESS: Workflow completed successfully!")
            return True
        else:
            print(f"\n❌ FAILED: Workflow ended with status: {workflow.status}")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await client.shutdown()
        print("✓ Client shutdown complete")

        # Shutdown system manager
        if 'system_manager' in locals():
            print("Shutting down system manager...")
            await system_manager.shutdown()
            print("✓ System manager shutdown complete")

if __name__ == "__main__":
    result = asyncio.run(test_file_workflow())
    sys.exit(0 if result else 1)