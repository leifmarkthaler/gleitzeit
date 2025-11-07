#!/usr/bin/env python
"""
Comprehensive test for retry error classification.
Tests which errors are retryable vs non-retryable.

Run with: python test_error_classification.py
"""

import sys
import asyncio
import redis.asyncio as aioredis
from typing import List, Tuple
from dataclasses import dataclass

# Add src to path
sys.path.insert(0, '/Users/leifmarkthaler/github/gleitzeit 0.0.7/src')

from gleitzeit.core.stateless_retry_service import StatelessRetryService, RetryContext, RetryDecision


@dataclass
class ErrorTestCase:
    """Test case for error classification"""
    error_type: str
    error_msg: str
    should_retry: bool
    category: str


# Define comprehensive test cases
TEST_CASES = [
    # ============== NON-RETRYABLE ERRORS ==============
    # Programming/Logic Errors
    ErrorTestCase("ValueError", "Invalid value provided", False, "Programming Error"),
    ErrorTestCase("KeyError", "Key 'foo' not found", False, "Programming Error"),
    ErrorTestCase("TypeError", "Expected str, got int", False, "Programming Error"),
    ErrorTestCase("AttributeError", "'NoneType' has no attribute 'foo'", False, "Programming Error"),
    ErrorTestCase("ImportError", "No module named 'foo'", False, "Programming Error"),
    ErrorTestCase("SyntaxError", "Invalid syntax", False, "Programming Error"),

    # Circuit Breaker
    ErrorTestCase("CircuitOpenError", "Circuit breaker is open", False, "Circuit Breaker"),

    # Validation Errors (pattern-based)
    ErrorTestCase("ValidationError", "validation failed for field 'email'", False, "Validation"),
    ErrorTestCase("RequestError", "[INVALID_PARAMS] Missing required field", False, "Validation"),
    ErrorTestCase("BadRequest", "Missing required parameter: user_id", False, "Validation"),
    ErrorTestCase("DataError", "Data is invalid for processing", False, "Validation"),

    # ============== RETRYABLE ERRORS ==============
    # Network/Connection Errors
    ErrorTestCase("ConnectionError", "Connection refused", True, "Network"),
    ErrorTestCase("ConnectionResetError", "Connection reset by peer", True, "Network"),
    ErrorTestCase("BrokenPipeError", "Broken pipe", True, "Network"),
    ErrorTestCase("TimeoutError", "Request timed out", True, "Network"),
    ErrorTestCase("ReadTimeoutError", "Read timed out", True, "Network"),
    ErrorTestCase("ConnectTimeoutError", "Connect timeout", True, "Network"),

    # HTTP Errors
    ErrorTestCase("HTTPError", "503 Service Unavailable", True, "HTTP 5xx"),
    ErrorTestCase("HTTP500Error", "Internal Server Error", True, "HTTP 5xx"),
    ErrorTestCase("HTTP502Error", "Bad Gateway", True, "HTTP 5xx"),
    ErrorTestCase("HTTP503Error", "Service Unavailable", True, "HTTP 5xx"),
    ErrorTestCase("HTTP504Error", "Gateway Timeout", True, "HTTP 5xx"),
    ErrorTestCase("HTTP429Error", "Too Many Requests", True, "Rate Limit"),

    # Database Errors
    ErrorTestCase("DatabaseError", "Database connection lost", True, "Database"),
    ErrorTestCase("OperationalError", "MySQL server has gone away", True, "Database"),
    ErrorTestCase("InterfaceError", "Connection already closed", True, "Database"),
    ErrorTestCase("DBConnectionError", "Unable to connect to database", True, "Database"),

    # Resource Errors
    ErrorTestCase("ResourceExhausted", "No workers available", True, "Resource"),
    ErrorTestCase("MemoryError", "Out of memory", True, "Resource"),
    ErrorTestCase("DiskFullError", "No space left on device", True, "Resource"),

    # Temporary/Transient Errors
    ErrorTestCase("TemporaryError", "Temporary failure, please retry", True, "Temporary"),
    ErrorTestCase("TransientError", "Transient error occurred", True, "Temporary"),
    ErrorTestCase("RetryableError", "Operation failed, but is retryable", True, "Temporary"),

    # Service Errors
    ErrorTestCase("ServiceUnavailable", "Service temporarily unavailable", True, "Service"),
    ErrorTestCase("UpstreamError", "Upstream service error", True, "Service"),
    ErrorTestCase("DependencyError", "Dependency service failed", True, "Service"),

    # Concurrency Errors
    ErrorTestCase("LockError", "Could not acquire lock", True, "Concurrency"),
    ErrorTestCase("DeadlockError", "Transaction deadlock detected", True, "Concurrency"),
    ErrorTestCase("ConflictError", "Concurrent modification detected", True, "Concurrency"),

    # Edge Cases
    ErrorTestCase("UnknownError", "An unknown error occurred", True, "Unknown"),
    ErrorTestCase("SystemError", "System error", True, "System"),
    ErrorTestCase("Exception", "Generic exception", True, "Generic"),
]


async def test_error_classification():
    """Test error classification logic"""
    print("=" * 80)
    print("ERROR CLASSIFICATION TEST")
    print("=" * 80)

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379', decode_responses=False)

    # Create retry service
    service = StatelessRetryService(redis)

    # Track results
    correct = 0
    incorrect = 0
    results_by_category = {}

    print("\nTesting Error Classification:")
    print("-" * 80)

    for test_case in TEST_CASES:
        # Create context
        context = RetryContext(
            task_id="test_task",
            workflow_id="test_workflow",
            error_type=test_case.error_type,
            error_msg=test_case.error_msg,
            current_attempt=0
        )

        # Get retry decision
        decision, metadata = await service.should_retry(context)

        # Check if decision matches expectation
        actual_retry = decision == RetryDecision.RETRY
        is_correct = actual_retry == test_case.should_retry

        # Track by category
        if test_case.category not in results_by_category:
            results_by_category[test_case.category] = {"correct": 0, "incorrect": 0, "errors": []}

        if is_correct:
            correct += 1
            results_by_category[test_case.category]["correct"] += 1
            status = "✅"
        else:
            incorrect += 1
            results_by_category[test_case.category]["incorrect"] += 1
            results_by_category[test_case.category]["errors"].append(test_case)
            status = "❌"

        # Print result
        retry_str = "RETRY" if actual_retry else "NO RETRY"
        expected_str = "RETRY" if test_case.should_retry else "NO RETRY"

        if not is_correct or True:  # Show all for now
            print(f"{status} {test_case.error_type:25} | Expected: {expected_str:8} | Got: {retry_str:8} | {test_case.category}")

    # Print summary by category
    print("\n" + "=" * 80)
    print("RESULTS BY CATEGORY")
    print("=" * 80)

    for category, results in results_by_category.items():
        total = results["correct"] + results["incorrect"]
        accuracy = (results["correct"] / total * 100) if total > 0 else 0

        status = "✅" if results["incorrect"] == 0 else "⚠️"
        print(f"{status} {category:20} | Correct: {results['correct']:2}/{total:2} ({accuracy:.0f}%)")

        # Show errors if any
        if results["errors"]:
            for error_case in results["errors"]:
                print(f"     ❌ {error_case.error_type}: Expected {error_case.should_retry}, got {not error_case.should_retry}")

    # Overall summary
    print("\n" + "=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)

    total = correct + incorrect
    accuracy = (correct / total * 100) if total > 0 else 0

    print(f"Total Test Cases: {total}")
    print(f"Correct: {correct}")
    print(f"Incorrect: {incorrect}")
    print(f"Accuracy: {accuracy:.1f}%")

    # Check non-retryable list
    print("\n" + "=" * 80)
    print("CURRENT CONFIGURATION")
    print("=" * 80)

    print("\nNon-Retryable Error Types:")
    for error_type in sorted(service.non_retryable_errors):
        print(f"  - {error_type}")

    print("\nNon-Retryable Patterns:")
    for pattern in service.non_retryable_patterns:
        print(f"  - '{pattern}'")

    # Recommendations
    if incorrect > 0:
        print("\n" + "=" * 80)
        print("RECOMMENDATIONS")
        print("=" * 80)

        # Find retryable errors that shouldn't be
        should_not_retry = [tc for tc in TEST_CASES if not tc.should_retry and tc.error_type not in service.non_retryable_errors]
        if should_not_retry:
            print("\nConsider adding these to non_retryable_errors:")
            for tc in should_not_retry:
                if not any(p.lower() in tc.error_msg.lower() for p in service.non_retryable_patterns):
                    print(f"  - {tc.error_type}")

        # Find non-retryable errors that should be retryable
        should_retry = [tc for tc in TEST_CASES if tc.should_retry and tc.error_type in service.non_retryable_errors]
        if should_retry:
            print("\nConsider removing these from non_retryable_errors:")
            for tc in should_retry:
                print(f"  - {tc.error_type}")

    # Close Redis
    await redis.aclose()

    print("\n" + "=" * 80)

    if accuracy == 100:
        print("✅ PERFECT! All errors classified correctly.")
    elif accuracy >= 90:
        print(f"✅ GOOD! {accuracy:.1f}% accuracy in error classification.")
    elif accuracy >= 80:
        print(f"⚠️ ACCEPTABLE! {accuracy:.1f}% accuracy. Some improvements needed.")
    else:
        print(f"❌ NEEDS WORK! Only {accuracy:.1f}% accuracy in error classification.")

    print("=" * 80)

    return incorrect == 0


if __name__ == "__main__":
    success = asyncio.run(test_error_classification())
    sys.exit(0 if success else 1)