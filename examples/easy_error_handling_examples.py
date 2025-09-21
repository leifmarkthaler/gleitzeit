#!/usr/bin/env python3
"""
Examples of error handling with the Gleitzeit Easy Client.

These examples demonstrate how to use the actual implemented error
handling features including retry, timeout, and error discovery.
"""

import asyncio
import json
from typing import List, Dict, Any
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


# ==============================================================================
# Example 1: Basic Retry and Timeout
# ==============================================================================

async def example_basic_error_handling():
    """
    Basic example of using retry and timeout with the easy client.
    """
    print("=" * 60)
    print("Example 1: Basic Retry and Timeout")
    print("=" * 60)

    # Create a task with retry and timeout
    data_processing = (
        t("process_data", "python/v1:python/execute")
        .with_(file="process_large_dataset.py")
        .with_retry(max_attempts=3, delay=2.0)  # Retry up to 3 times
        .with_timeout(120)  # 2 minute timeout
    )

    # Create workflow
    workflow = (
        w(data_processing)
        .name("data_processing_with_errors")
        .version("1.0.0")
        .description("Process data with error handling")
    )

    # Validate
    errors = workflow.validate()
    if errors:
        print(f"❌ Validation errors: {errors}")
        return

    print("✅ Workflow validated successfully")

    # Show the generated structure
    print("\nGenerated workflow structure:")
    print(json.dumps(workflow.to_dict(), indent=2))

    # Submit (optional - uncomment to actually submit)
    # client = GleitzeitClient(base_url="http://localhost:8000")
    # await client.initialize()
    # result = await client.submit_workflow(workflow.to_dict())
    # print(f"\n✅ Submitted workflow: {result['workflow_id']}")


# ==============================================================================
# Example 2: Multi-Stage Pipeline with Different Error Handling
# ==============================================================================

async def example_pipeline_error_handling():
    """
    Example of a multi-stage pipeline where each stage has different
    error handling requirements.
    """
    print("\n" + "=" * 60)
    print("Example 2: Multi-Stage Pipeline")
    print("=" * 60)

    # Stage 1: Fetch data from API (network errors likely)
    fetch_data = (
        t("fetch_data", "python/v1:python/execute")
        .with_(file="fetch_from_api.py")
        .with_retry(max_attempts=5, delay=3.0)  # More retries for network
        .with_timeout(30)  # Short timeout for API calls
    )

    # Stage 2: Process with LLM (expensive, timeout likely)
    analyze_data = (
        t("analyze_data", "llm/v1:llm/generate")
        .needs("fetch_data")
        .with_(
            model="gpt-4",
            prompt="Analyze this data: ${fetch_data.result}"
        )
        .with_retry(max_attempts=2, delay=5.0)  # Fewer retries (expensive)
        .with_timeout(300)  # 5 minute timeout for LLM
    )

    # Stage 3: Transform data (CPU intensive)
    transform_data = (
        t("transform_data", "python/v1:python/execute")
        .needs("analyze_data")
        .with_(file="heavy_computation.py")
        .with_retry(max_attempts=3, delay=1.0)
        .with_timeout(600)  # 10 minute timeout for computation
    )

    # Stage 4: Save to database (connection errors possible)
    save_results = (
        t("save_results", "python/v1:python/execute")
        .needs("transform_data")
        .with_(file="save_to_database.py")
        .with_retry(max_attempts=5, delay=2.0)  # More retries for DB
        .with_timeout(60)
    )

    # Create workflow
    workflow = (
        w(fetch_data, analyze_data, transform_data, save_results)
        .name("resilient_data_pipeline")
        .version("2.0.0")
        .description("Data pipeline with stage-specific error handling")
    )

    # Validate
    errors = workflow.validate()
    print(f"\nValidation: {'✅ Passed' if not errors else f'❌ Failed: {errors}'}")

    # Show task configurations
    print("\nTask configurations:")
    for task in workflow.to_dict()["tasks"]:
        print(f"\n  {task['id']}:")
        if "metadata" in task:
            print(f"    Retries: {task['metadata'].get('max_attempts', 'N/A')}")
            print(f"    Delay: {task['metadata'].get('retry_delay', 'N/A')}s")
        if "timeout" in task:
            print(f"    Timeout: {task['timeout']}s")


# ==============================================================================
# Example 3: Error Discovery and Adaptive Configuration
# ==============================================================================

async def example_adaptive_error_handling():
    """
    Example that discovers provider capabilities and adapts error handling.
    """
    print("\n" + "=" * 60)
    print("Example 3: Adaptive Error Handling with Discovery")
    print("=" * 60)

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Discover errors for Python provider
    print("\nDiscovering Python provider errors...")
    try:
        errors = await client.get_provider_errors("python/v1")

        retryable = [e for e in errors if e.get('is_retryable', False)]
        print(f"  Found {len(errors)} total errors")
        print(f"  Retryable: {len(retryable)}")

        # Show some retryable errors
        if retryable:
            print("\n  Retryable error types:")
            for error in retryable[:5]:
                print(f"    - {error['name']}: {error.get('error_code_name', 'N/A')}")
    except Exception as e:
        print(f"  Could not discover errors: {e}")
        errors = []
        retryable = []

    # Create task with adaptive configuration
    task = t("adaptive_task", "python/v1:python/execute").with_(file="task.py")

    # Configure based on discovery
    if retryable:
        # Provider supports retryable errors
        print("\n✅ Provider supports retryable errors - configuring retry")
        task = task.with_retry(max_attempts=3, delay=2.0)
    else:
        print("\n⚠️  No retryable errors found - skipping retry configuration")

    # Check for timeout support
    timeout_errors = [e for e in errors if 'TIMEOUT' in e.get('error_code_name', '')]
    if timeout_errors:
        print("✅ Provider supports timeout - configuring timeout")
        task = task.with_timeout(60)
    else:
        print("⚠️  No timeout errors found - using default timeout")

    # Create workflow
    workflow = w(task).name("adaptive_workflow")

    print("\nFinal task configuration:")
    task_dict = workflow.to_dict()["tasks"][0]
    print(json.dumps(task_dict, indent=2))


# ==============================================================================
# Example 4: Error Report Generation
# ==============================================================================

async def example_error_report():
    """
    Example of generating error reports for documentation.
    """
    print("\n" + "=" * 60)
    print("Example 4: Error Report Generation")
    print("=" * 60)

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Get errors for all providers
    print("\nGenerating error report for all providers...")

    try:
        all_errors = await client.get_all_provider_errors()

        for provider_id, errors in all_errors.items():
            if not errors:
                continue

            print(f"\n### Provider: {provider_id}")
            print(f"Total errors: {len(errors)}")

            # Categorize errors
            retryable = [e for e in errors if e.get('is_retryable', False)]
            non_retryable = [e for e in errors if not e.get('is_retryable', False)]

            print(f"\nRetryable errors ({len(retryable)}):")
            for error in retryable:
                code = error.get('error_code_name', 'N/A')
                desc = error.get('description', 'No description')[:50]
                print(f"  ✓ {error['name']} ({code}): {desc}...")

            print(f"\nNon-retryable errors ({len(non_retryable)}):")
            for error in non_retryable[:3]:  # Show first 3
                code = error.get('error_code_name', 'N/A')
                desc = error.get('description', 'No description')[:50]
                print(f"  ✗ {error['name']} ({code}): {desc}...")

            if len(non_retryable) > 3:
                print(f"  ... and {len(non_retryable) - 3} more")

    except Exception as e:
        print(f"Could not generate error report: {e}")


# ==============================================================================
# Example 5: Workflow with Validation Errors
# ==============================================================================

async def example_validation_errors():
    """
    Example showing various validation errors and how to handle them.
    """
    print("\n" + "=" * 60)
    print("Example 5: Validation Error Examples")
    print("=" * 60)

    # Example 1: Invalid protocol format
    print("\n1. Invalid protocol format:")
    try:
        task = t("bad_task", "invalid-protocol")  # Missing version and method
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Example 2: Invalid task ID
    print("\n2. Invalid task ID:")
    try:
        task = t("bad task!", "python/v1:python/execute")  # Invalid character
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Example 3: Circular dependency
    print("\n3. Circular dependency:")
    task1 = t("task1", "python/v1:python/execute").needs("task2").with_(file="a.py")
    task2 = t("task2", "python/v1:python/execute").needs("task1").with_(file="b.py")

    try:
        workflow = w(task1, task2).name("circular_workflow")
        errors = workflow.validate()
        if errors:
            print(f"   ❌ Validation errors: {errors}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Example 4: Missing dependency
    print("\n4. Missing dependency:")
    task = t("task", "python/v1:python/execute").needs("nonexistent").with_(file="c.py")
    try:
        workflow = w(task).name("missing_dep_workflow")
        errors = workflow.validate()
        if errors:
            print(f"   ❌ Validation errors: {errors}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Example 5: Duplicate task IDs
    print("\n5. Duplicate task IDs:")
    task1 = t("duplicate", "python/v1:python/execute").with_(file="d.py")
    task2 = t("duplicate", "python/v1:python/execute").with_(file="e.py")

    try:
        workflow = w(task1, task2).name("duplicate_workflow")
        errors = workflow.validate()
        if errors:
            print(f"   ❌ Validation errors: {errors}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Example 6: Valid workflow
    print("\n6. Valid workflow:")
    task1 = t("fetch", "python/v1:python/execute").with_(file="fetch.py")
    task2 = t("process", "python/v1:python/execute").needs("fetch").with_(file="process.py")

    workflow = w(task1, task2).name("valid_workflow")
    errors = workflow.validate()
    if errors:
        print(f"   ❌ Validation errors: {errors}")
    else:
        print(f"   ✅ Validation passed!")


# ==============================================================================
# Example 6: Real-World Use Case - Web Scraping Pipeline
# ==============================================================================

async def example_web_scraping_pipeline():
    """
    Real-world example: Web scraping pipeline with comprehensive error handling.
    """
    print("\n" + "=" * 60)
    print("Example 6: Web Scraping Pipeline")
    print("=" * 60)

    # Task 1: Fetch URLs from database
    fetch_urls = (
        t("fetch_urls", "python/v1:python/execute")
        .with_(file="fetch_urls_from_db.py")
        .with_retry(max_attempts=3, delay=2.0)  # DB connection might fail
        .with_timeout(30)
    )

    # Task 2: Scrape websites (parallel, high failure rate expected)
    scrape_sites = (
        t("scrape_sites", "python/v1:python/execute")
        .needs("fetch_urls")
        .with_(file="scrape_websites.py")
        .with_retry(max_attempts=5, delay=5.0)  # Websites might be down
        .with_timeout(120)  # 2 minutes for scraping
    )

    # Task 3: Extract content with LLM
    extract_content = (
        t("extract_content", "llm/v1:llm/generate")
        .needs("scrape_sites")
        .with_(
            model="gpt-3.5-turbo",
            prompt="Extract structured data from: ${scrape_sites.result}"
        )
        .with_retry(max_attempts=2, delay=10.0)  # LLM API might be rate limited
        .with_timeout(180)  # 3 minutes for LLM processing
    )

    # Task 4: Validate and clean data
    validate_data = (
        t("validate_data", "python/v1:python/execute")
        .needs("extract_content")
        .with_(file="validate_and_clean.py")
        .with_retry(max_attempts=2, delay=1.0)
        .with_timeout(60)
    )

    # Task 5: Store results
    store_results = (
        t("store_results", "python/v1:python/execute")
        .needs("validate_data")
        .with_(file="store_to_database.py")
        .with_retry(max_attempts=5, delay=3.0)  # Critical - must succeed
        .with_timeout(45)
    )

    # Create workflow
    workflow = (
        w(fetch_urls, scrape_sites, extract_content, validate_data, store_results)
        .name("web_scraping_pipeline")
        .version("1.0.0")
        .description("Production-ready web scraping with error handling")
    )

    # Validate
    errors = workflow.validate()
    print(f"\nValidation: {'✅ Passed' if not errors else f'❌ Failed: {errors}'}")

    # Show pipeline structure
    print("\nPipeline structure:")
    for task in workflow.to_dict()["tasks"]:
        deps = task.get("dependencies", [])
        deps_str = f" (depends on: {', '.join(deps)})" if deps else ""
        print(f"  {task['id']}{deps_str}")

    # Show error handling configuration
    print("\nError handling configuration:")
    for task in workflow.to_dict()["tasks"]:
        print(f"\n  {task['id']}:")
        metadata = task.get("metadata", {})
        print(f"    Max attempts: {metadata.get('max_attempts', 1)}")
        print(f"    Retry delay: {metadata.get('retry_delay', 0)}s")
        print(f"    Timeout: {task.get('timeout', 'None')}s")


# ==============================================================================
# Main Runner
# ==============================================================================

async def main():
    """
    Run all examples.
    """
    print("\n" + "=" * 70)
    print(" GLEITZEIT EASY CLIENT ERROR HANDLING EXAMPLES")
    print("=" * 70)

    # Run examples
    await example_basic_error_handling()
    await example_pipeline_error_handling()

    # These examples need a running server
    try:
        await example_adaptive_error_handling()
        await example_error_report()
    except Exception as e:
        print(f"\n⚠️  Skipping examples that require server: {e}")

    await example_validation_errors()
    await example_web_scraping_pipeline()

    print("\n" + "=" * 70)
    print(" EXAMPLES COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())