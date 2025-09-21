#!/usr/bin/env python3
"""
Test the enhanced error handling in the Easy Syntax client.

This demonstrates how the error system from ERROR-SYSTEM-DOCUMENTATION.md
is integrated into the easy client for better error handling and validation.
"""

from gleitzeit.easy import t, w
from gleitzeit.easy.errors import (
    InvalidProtocolFormatError,
    InvalidConfigurationError,
    DuplicateTaskError,
    CircularDependencyError,
    InvalidDependencyError
)
from gleitzeit.core.errors import ErrorCode


def test_validation_errors():
    """Test that validation errors are properly raised."""
    print("=== Testing Validation Errors ===\n")

    # Test invalid task ID
    print("1. Testing invalid task ID:")
    try:
        task = t("invalid-task-id!", "python/v1:execute")
        print("❌ Should have raised TaskBuilderError")
    except Exception as e:
        print(f"✅ Caught error: {e.__class__.__name__}: {e}")
        print(f"   Error code: {e.code if hasattr(e, 'code') else 'N/A'}")
        print()

    # Test invalid protocol format
    print("2. Testing invalid protocol format:")
    try:
        task = t("test_task", "invalid-protocol")
        print("❌ Should have raised InvalidProtocolFormatError")
    except InvalidProtocolFormatError as e:
        print(f"✅ Caught error: {e.__class__.__name__}: {e}")
        print(f"   Error code: {e.code.name if hasattr(e, 'code') else 'N/A'}")
        print(f"   Data: {e.data if hasattr(e, 'data') else 'N/A'}")
        print()

    # Test invalid configuration
    print("3. Testing invalid retry count:")
    try:
        task = t("test_task", "python/v1:execute").retry(-1)
        print("❌ Should have raised InvalidConfigurationError")
    except InvalidConfigurationError as e:
        print(f"✅ Caught error: {e.__class__.__name__}: {e}")
        print(f"   Error code: {e.code.name if hasattr(e, 'code') else 'N/A'}")
        print()

    print("4. Testing invalid timeout:")
    try:
        task = t("test_task", "python/v1:execute").timeout(5000)
        print("❌ Should have raised InvalidConfigurationError")
    except InvalidConfigurationError as e:
        print(f"✅ Caught error: {e.__class__.__name__}: {e}")
        print(f"   Error code: {e.code.name if hasattr(e, 'code') else 'N/A'}")
        print()


def test_workflow_validation_errors():
    """Test workflow validation errors."""
    print("=== Testing Workflow Validation Errors ===\n")

    # Test duplicate task IDs
    print("1. Testing duplicate task IDs:")
    try:
        task1 = t("duplicate_id", "python/v1:execute")
        task2 = t("duplicate_id", "python/v1:execute")
        workflow = w(task1, task2)
        workflow.validate()
        print("❌ Should have raised DuplicateTaskError")
    except DuplicateTaskError as e:
        print(f"✅ Caught error: {e.__class__.__name__}: {e}")
        print(f"   Error code: {e.code.name if hasattr(e, 'code') else 'N/A'}")
        print(f"   Duplicate IDs: {e.data.get('duplicate_task_ids') if hasattr(e, 'data') else 'N/A'}")
        print()

    # Test invalid dependency
    print("2. Testing invalid dependency:")
    try:
        task1 = t("task1", "python/v1:execute").needs("non_existent_task")
        workflow = w(task1)
        workflow.validate()
        print("❌ Should have raised InvalidDependencyError")
    except InvalidDependencyError as e:
        print(f"✅ Caught error: {e.__class__.__name__}: {e}")
        print(f"   Error code: {e.code.name if hasattr(e, 'code') else 'N/A'}")
        print()

    # Test circular dependency
    print("3. Testing circular dependency:")
    try:
        task1 = t("task1", "python/v1:execute").needs("task2")
        task2 = t("task2", "python/v1:execute").needs("task3")
        task3 = t("task3", "python/v1:execute").needs("task1")
        workflow = w(task1, task2, task3)
        workflow.validate()
        print("❌ Should have raised CircularDependencyError")
    except CircularDependencyError as e:
        print(f"✅ Caught error: {e.__class__.__name__}: {e}")
        print(f"   Error code: {e.code.name if hasattr(e, 'code') else 'N/A'}")
        print(f"   Cycle: {e.data.get('dependency_cycle') if hasattr(e, 'data') else 'N/A'}")
        print()


def test_error_aware_handlers():
    """Test error-aware event handlers."""
    print("=== Testing Error-Aware Event Handlers ===\n")

    print("1. Creating task with provider timeout handler:")
    task = (t("api_call", "api/v1:fetch")
            .with_(url="https://example.com")
            .timeout(30))

    # Add error-aware handler for provider timeout
    task.errors().on_provider_timeout().run("log_timeout", "log/v1:write").with_(
        message="Provider timeout occurred",
        task_id="${task.id}"
    )

    print(f"✅ Task created with provider timeout handler")
    print(f"   Event handlers: {len(task.get_event_handlers())}")
    print()

    print("2. Creating task with retryable error handling:")
    task2 = (t("unstable_api", "api/v1:fetch")
             .with_(url="https://flaky-api.com"))

    # Add automatic retry for retryable errors
    task2.errors().on_retryable_error().with_exponential_backoff(
        max_retries=5,
        initial_delay=1.0
    )

    print(f"✅ Task created with retryable error handling")
    print(f"   Retry count: {task2._retry_count}")
    print(f"   Event handlers: {len(task2.get_event_handlers())}")
    print()

    print("3. Creating task with critical error handling:")
    task3 = (t("secure_operation", "secure/v1:process")
             .with_(data="${input.sensitive_data}"))

    # Add critical error handler
    task3.errors().on_critical_error().notify_and_halt()

    print(f"✅ Task created with critical error handling")
    print(f"   Event handlers: {len(task3.get_event_handlers())}")
    print()


def test_error_specific_handlers():
    """Test handling specific error codes."""
    print("=== Testing Error-Specific Handlers ===\n")

    print("1. Handling specific provider errors:")
    task = t("llm_call", "llm/v1:generate").with_(prompt="${input.prompt}")

    # Handle different error scenarios
    task.errors().on_resource_exhausted().run("reduce_tokens", "llm/v1:truncate").with_(
        original_prompt="${input.prompt}",
        max_tokens=1000
    )

    task.errors().on_rate_limit_exceeded().wait(60).retry_self()

    task.errors().on_authentication_failed().run("refresh_token", "auth/v1:refresh")

    print(f"✅ Task configured with multiple error-specific handlers")
    print(f"   Event handlers: {len(task.get_event_handlers())}")

    # Show the handlers
    for handler in task.get_event_handlers():
        print(f"   - {handler.event_type}: {handler.condition or 'any'}")
    print()


def test_valid_workflow():
    """Test a valid workflow with proper error handling."""
    print("=== Testing Valid Workflow with Error Handling ===\n")

    # Create tasks with error handling
    fetch_data = (t("fetch_data", "api/v1:fetch")
                  .with_(endpoint="${input.endpoint}")
                  .retry(3)
                  .timeout(30))

    # Add error handlers
    fetch_data.errors().on_provider_timeout().run(
        "log_timeout", "log/v1:write"
    ).with_(message="Fetch timed out")

    process_data = (t("process_data", "python/v1:execute")
                    .needs("fetch_data")
                    .with_(data="${fetch_data.result}"))

    process_data.errors().on_task_validation_failed().run(
        "log_validation_error", "log/v1:write"
    ).with_(error="${error}")

    save_results = (t("save_results", "storage/v1:save")
                    .needs("process_data")
                    .with_(data="${process_data.result}"))

    save_results.errors().on_retryable_error().with_linear_backoff(
        max_retries=5,
        delay=2.0
    )

    # Create workflow
    workflow = (w(fetch_data, process_data, save_results)
                .name("data_pipeline")
                .version("1.0.0")
                .description("Data pipeline with comprehensive error handling"))

    # Validate workflow
    try:
        errors = workflow.validate()
        if not errors:
            print("✅ Workflow validation passed!")
        else:
            print(f"❌ Validation errors: {errors}")
    except Exception as e:
        print(f"❌ Unexpected error during validation: {e}")

    print(f"\nWorkflow summary:")
    print(f"  Name: {workflow.workflow_metadata['name']}")
    print(f"  Tasks: {workflow.get_task_count()}")
    print(f"  Event handlers: {workflow.get_event_handler_count()}")
    print(f"  Task IDs: {workflow.get_task_ids()}")

    # Show workflow structure
    import json
    workflow_dict = workflow.to_dict()
    print(f"\nWorkflow structure:")
    print(json.dumps(workflow_dict, indent=2))


def main():
    """Run all error handling tests."""
    print("=" * 60)
    print("TESTING EASY CLIENT ERROR HANDLING")
    print("=" * 60)
    print()

    test_validation_errors()
    test_workflow_validation_errors()
    test_error_aware_handlers()
    test_error_specific_handlers()
    test_valid_workflow()

    print()
    print("=" * 60)
    print("ALL ERROR HANDLING TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()