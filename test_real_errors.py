#!/usr/bin/env python3
"""
Test the real error handling in the easy client.

This uses the actual implemented error system, not hypothetical event handlers.
"""

import asyncio
import json
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


async def discover_available_errors():
    """Discover what errors are actually available from providers."""
    print("=== Discovering Available Errors ===\n")

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    protocols = ["python/v1", "llm/v1"]

    for protocol in protocols:
        print(f"\nErrors for {protocol}:")
        print("-" * 40)

        try:
            errors = await client.get_provider_errors(protocol)

            if not errors:
                print("  No errors discovered")
                continue

            # Separate retryable from non-retryable
            retryable = [e for e in errors if e.get('is_retryable', False)]
            non_retryable = [e for e in errors if not e.get('is_retryable', False)]

            if retryable:
                print(f"\n  Retryable errors ({len(retryable)}):")
                for error in retryable:
                    code = error.get('error_code_name', 'N/A')
                    print(f"    ✓ {error['name']} - {code}")

            if non_retryable:
                print(f"\n  Non-retryable errors ({len(non_retryable)}):")
                for error in non_retryable[:5]:  # Show first 5
                    code = error.get('error_code_name', 'N/A')
                    print(f"    ✗ {error['name']} - {code}")
                if len(non_retryable) > 5:
                    print(f"    ... and {len(non_retryable) - 5} more")

        except Exception as e:
            print(f"  Error discovering: {e}")


def create_workflow_with_real_error_handling():
    """Create a workflow using real error handling features."""
    print("\n=== Creating Workflow with Real Error Handling ===\n")

    # Create a task that might fail with retry and timeout
    risky_task = (
        t("risky_operation", "python/v1:python/execute")
        .with_(file="process_ollama_response.py")
        .with_retry(max_attempts=3, delay=2.0)  # Real retry system
        .with_timeout(30)  # Real timeout system
    )

    # Create another task that depends on it
    followup_task = (
        t("process_result", "python/v1:python/execute")
        .needs("risky_operation")
        .with_(file="log_error.py")
        .with_retry(max_attempts=2)  # Less retries for follow-up
    )

    # Create workflow
    workflow = (
        w(risky_task, followup_task)
        .name("real_error_handling_test")
        .version("1.0.0")
        .description("Test real error handling features")
    )

    print("Created workflow with:")
    print(f"  - Task 'risky_operation' with 3 retries and 30s timeout")
    print(f"  - Task 'process_result' with 2 retries")

    return workflow


async def test_real_workflow():
    """Test submitting a workflow with real error handling."""
    print("\n=== Testing Real Error Handling Workflow ===\n")

    workflow = create_workflow_with_real_error_handling()

    # Validate
    try:
        errors = workflow.validate()
        if not errors:
            print("✅ Workflow validation passed!")
        else:
            print(f"❌ Validation errors: {errors}")
            return
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        return

    # Show workflow structure
    workflow_dict = workflow.to_dict()
    print("\nWorkflow structure:")
    print(json.dumps(workflow_dict, indent=2))

    # Check that metadata contains retry configuration
    for task in workflow_dict.get("tasks", []):
        if task.get("metadata"):
            print(f"\nTask '{task['id']}' metadata:")
            print(f"  - max_attempts: {task['metadata'].get('max_attempts', 'not set')}")
            print(f"  - retry_delay: {task['metadata'].get('retry_delay', 'not set')}")
        if task.get("timeout"):
            print(f"  - timeout: {task['timeout']}s")

    # Submit to server
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    try:
        print("\nSubmitting workflow...")
        result = await client.submit_workflow(workflow_dict)
        workflow_id = result.get("workflow_id")
        print(f"✅ Workflow submitted: {workflow_id}")

        # Wait briefly to see if it processes
        await asyncio.sleep(5)

        # Check status
        workflow_obj = await client.get_workflow(workflow_id)
        print(f"\nWorkflow status: {workflow_obj.status}")

    except Exception as e:
        print(f"❌ Error submitting workflow: {e}")


async def main():
    """Main test function."""
    print("=" * 60)
    print("TESTING REAL ERROR HANDLING")
    print("=" * 60)
    print()

    # First discover what errors are available
    await discover_available_errors()

    # Then test a workflow with real error handling
    await test_real_workflow()

    print("\n" + "=" * 60)
    print("REAL ERROR HANDLING TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())