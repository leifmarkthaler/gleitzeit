#!/usr/bin/env python3
"""
Test running a workflow directly with the system manager.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.system import create_system_manager
from gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2

async def test_direct_workflow():
    """Test workflow execution directly."""
    print("="*60)
    print("Testing Direct Workflow Execution")
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
        # Load the workflow
        workflow_file = Path("workflows/test_calculation.yaml")
        print(f"\n1. Loading workflow from: {workflow_file}")

        # Use the system's workflow loader which has the registry
        if hasattr(system_manager, 'workflow_loader') and system_manager.workflow_loader:
            workflow = system_manager.workflow_loader.load_workflow_from_file(str(workflow_file))
        else:
            # Fallback: create loader with registry
            from gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2Config
            config = WorkflowLoaderV2Config()
            loader = WorkflowLoaderV2(
                config=config,
                registry=system_manager.registry if hasattr(system_manager, 'registry') else None
            )
            workflow = loader.load_workflow_from_file(str(workflow_file))

        print(f"   ✓ Workflow loaded: {workflow.id}")
        print(f"   Name: {workflow.name}")
        print(f"   Tasks: {len(workflow.tasks)}")

        # Submit the workflow directly
        print("\n2. Submitting workflow...")
        workflow_id = await system_manager.submit_workflow(workflow)
        print(f"   ✓ Workflow submitted: {workflow_id}")

        # Monitor workflow progress
        print("\n3. Monitoring execution...")
        max_wait = 30
        for i in range(max_wait):
            await asyncio.sleep(1)

            # Get workflow
            workflow_data = await system_manager.get_workflow(workflow_id)
            if workflow_data:
                print(f"   {i+1}s: Workflow status: {workflow_data.status}")
                if workflow_data.tasks:
                    for task in workflow_data.tasks:
                        print(f"        - {task.id}: {task.status}")
                        if task.status == "failed":
                            if hasattr(task, 'error'):
                                print(f"          Error: {task.error}")
                            if hasattr(task, 'error_message'):
                                print(f"          Message: {task.error_message}")

                # Check if complete
                if workflow_data.status in ["completed", "failed"]:
                    break

        # Final result
        print("\n4. Final Status:")
        workflow_data = await system_manager.get_workflow(workflow_id)
        print(f"   Workflow: {workflow_data.status}")

        if workflow_data.tasks:
            print("\n   Task Results:")
            for task in workflow_data.tasks:
                print(f"   - {task.id}: {task.status}")
                if hasattr(task, 'result'):
                    print(f"     Result: {task.result}")

        if workflow_data.status == "completed":
            print("\n✅ SUCCESS: Workflow completed successfully!")
            return True
        else:
            print(f"\n❌ FAILED: Workflow ended with status: {workflow_data.status}")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print("\nShutting down system manager...")
        await system_manager.shutdown()
        print("✓ System manager shutdown complete")

if __name__ == "__main__":
    result = asyncio.run(test_direct_workflow())
    sys.exit(0 if result else 1)