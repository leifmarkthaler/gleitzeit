#!/usr/bin/env python3
"""
Test that error handlers work with the easy client.
"""

import asyncio
import json
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


def create_workflow_with_error_handlers():
    """Create a workflow with tasks that will fail and trigger error handlers."""
    print("=== Creating Workflow with Error Handlers ===\n")

    # Create a task that will fail
    failing_task = (
        t("will_fail", "python/v1:python/execute")
        .with_(
            file="nonexistent_file.py"  # This file doesn't exist, will cause error
        )
    )

    # Add error handler - but Python provider needs files, not inline code
    # So let's check if the event handler structure is even included in the workflow
    failing_task.on_error().run(
        "error_handler", "python/v1:python/execute"
    ).with_(
        file="log_error.py"  # We created this file earlier
    )

    # Create workflow
    workflow = (
        w(failing_task)
        .name("error_handler_test")
        .version("1.0.0")
        .description("Test error handler functionality")
    )

    # Validate
    try:
        errors = workflow.validate()
        if not errors:
            print("✅ Workflow validation passed!")
        else:
            print(f"❌ Validation errors: {errors}")
            return None
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        return None

    print(f"\nWorkflow created:")
    print(f"  Name: {workflow.workflow_metadata['name']}")
    print(f"  Tasks: {workflow.get_task_count()}")
    print(f"  Event handlers: {workflow.get_event_handler_count()}")

    return workflow


async def test_error_handlers():
    """Test if error handlers are triggered."""
    print("\n=== Testing Error Handler Submission ===\n")

    workflow = create_workflow_with_error_handlers()
    if not workflow:
        return

    # Check the workflow structure
    workflow_dict = workflow.to_dict()
    print("\nWorkflow structure:")
    print(json.dumps(workflow_dict, indent=2))

    # Check if event_handlers are included
    if "event_handlers" in workflow_dict:
        print(f"\n✅ Event handlers are included in workflow: {len(workflow_dict['event_handlers'])} handlers")
        for handler in workflow_dict['event_handlers']:
            print(f"  - {handler['event_type']} on {handler['parent_task_id']}")
    else:
        print("\n❌ No event handlers in workflow structure!")

    # Initialize client
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    try:
        # Submit the workflow
        print("\nSubmitting workflow with error handlers...")
        result = await client.submit_workflow(workflow_dict)
        workflow_id = result.get("workflow_id")
        print(f"✅ Workflow submitted: {workflow_id}")

        # Wait for completion
        print("\nWaiting for workflow to process (including error handlers)...")
        max_attempts = 15
        for i in range(max_attempts):
            workflow_obj = await client.get_workflow(workflow_id)
            print(f"  Status: {workflow_obj.status}")

            if workflow_obj.status in ["completed", "failed"]:
                break

            await asyncio.sleep(2)

        # Check results
        print("\n=== Results ===\n")
        final_workflow = await client.get_workflow(workflow_id)
        print(f"Final status: {final_workflow.status}")

        # Check if error handler was executed
        if hasattr(final_workflow, 'task_results'):
            print(f"Task results available: {final_workflow.task_results}")
            if "error_handler" in final_workflow.task_results:
                print("✅ Error handler was executed!")
            else:
                print("❌ Error handler was not executed")
        else:
            print("No task_results field available")

        # Check failed tasks
        if hasattr(final_workflow, 'failed_tasks') and final_workflow.failed_tasks:
            print(f"Failed tasks: {final_workflow.failed_tasks}")

    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main test function."""
    print("=" * 60)
    print("TESTING ERROR HANDLERS WITH EASY CLIENT")
    print("=" * 60)
    print()

    await test_error_handlers()

    print("\n" + "=" * 60)
    print("ERROR HANDLER TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())