#!/usr/bin/env python3
"""
Test the easy client with an Ollama workflow.

This demonstrates that the enhanced error-aware easy client
works correctly with real providers like Ollama.
"""

import asyncio
import json
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


def create_ollama_workflow():
    """Create an Ollama workflow using the easy syntax."""
    print("=== Creating Ollama Workflow with Easy Syntax ===\n")

    # Create a simple question-answer task
    ask_question = (
        t("ask_ollama", "llm/v1:llm/generate")
        .with_(
            model="llama3.2",
            prompt="What is the capital of France? Answer in one word.",
            max_tokens=10,
            temperature=0.1
        )
    )

    # Create a follow-up task to process the response
    process_response = (
        t("process_response", "python/v1:python/execute")
        .needs("ask_ollama")
        .with_(
            file="process_ollama_response.py"
        )
    )

    # Create the workflow
    workflow = (
        w(ask_question, process_response)
        .name("ollama_test")
        .version("1.0.0")
        .description("Test Ollama integration with easy client")
    )

    # Validate the workflow
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

    return workflow


async def submit_and_run_workflow(workflow):
    """Submit the workflow to Gleitzeit and monitor execution."""
    print("\n=== Submitting Workflow to Gleitzeit ===\n")

    # Create and initialize client
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    try:
        # Convert workflow to dict
        workflow_dict = workflow.to_dict()

        print("Workflow structure:")
        print(json.dumps(workflow_dict, indent=2))

        # Submit the workflow
        print("\nSubmitting workflow...")
        result = await client.submit_workflow(workflow_dict)

        workflow_id = result.get("workflow_id")
        print(f"✅ Workflow submitted: {workflow_id}")

        # Wait for completion
        print("\nWaiting for workflow to complete...")
        max_attempts = 30
        for i in range(max_attempts):
            workflow = await client.get_workflow(workflow_id)
            print(f"  Status: {workflow.status}")

            if workflow.status in ["completed", "failed"]:
                break

            await asyncio.sleep(2)

        # Get results
        print("\n=== Workflow Results ===\n")
        final_workflow = await client.get_workflow(workflow_id)

        print(f"Final status: {final_workflow.status}")

        # Print available fields for debugging
        print(f"Workflow fields: {dir(final_workflow)}")

        if final_workflow.status == "completed":
            print(f"\n✅ Workflow completed successfully!")
            # The workflow completed, which means our easy client worked!
        else:
            print(f"\n❌ Workflow failed: {final_workflow.error if hasattr(final_workflow, 'error') else 'Unknown error'}")

            # Check for failed tasks
            failed_tasks = final_workflow.failed_tasks or []
            if failed_tasks:
                print(f"Failed tasks: {failed_tasks}")

                # Get task errors
                for task_id in failed_tasks:
                    task = await client.get_task(task_id)
                    if hasattr(task, 'error') and task.error:
                        print(f"  {task_id} error: {task.error}")

        return final_workflow

    except Exception as e:
        print(f"❌ Error submitting workflow: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        pass  # Client doesn't have close method


async def main():
    """Main function to test the easy client with Ollama."""
    print("=" * 60)
    print("TESTING EASY CLIENT WITH OLLAMA WORKFLOW")
    print("=" * 60)
    print()

    # Create the workflow
    workflow = create_ollama_workflow()
    if not workflow:
        print("Failed to create workflow")
        return

    # Submit and run
    result = await submit_and_run_workflow(workflow)

    print("\n" + "=" * 60)
    if result and hasattr(result, 'status') and result.status == "completed":
        print("✅ OLLAMA WORKFLOW TEST SUCCESSFUL")
    else:
        print("❌ OLLAMA WORKFLOW TEST FAILED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())