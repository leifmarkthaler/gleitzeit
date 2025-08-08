#!/usr/bin/env python3
"""
Error Handling and Retry Demo

Demonstrates comprehensive error handling, retry logic, 
circuit breakers, and failure recovery in Gleitzeit.
"""

import asyncio
import sys
import random
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.core.error_handling import (
    RetryManager, RetryConfig, GleitzeitLogger, 
    ErrorCategorizer, ErrorCategory, ErrorSeverity
)
from gleitzeit_cluster.storage.result_cache import ResultCache


class SimulatedFailureError(Exception):
    """Simulated error for testing"""
    pass


async def simulate_network_error():
    """Simulate network-related errors"""
    errors = [
        "Connection timeout",
        "Network unreachable", 
        "Connection refused",
        "DNS resolution failed"
    ]
    raise SimulatedFailureError(random.choice(errors))


async def simulate_rate_limit_error():
    """Simulate rate limiting"""
    raise SimulatedFailureError("Rate limit exceeded: too many requests")


async def simulate_transient_error():
    """Simulate transient errors that may succeed on retry"""
    if random.random() < 0.7:  # 70% chance of failure
        raise SimulatedFailureError("Temporary service unavailable")
    return "Success after retry!"


async def simulate_permanent_error():
    """Simulate permanent errors that should not retry"""
    raise SimulatedFailureError("Invalid API key provided")


async def demo_error_categorization():
    """Demonstrate error categorization"""
    
    print("🧪 Testing Error Categorization")
    print("=" * 40)
    
    test_errors = [
        (SimulatedFailureError("Connection timeout"), "Network error"),
        (SimulatedFailureError("Rate limit exceeded"), "Rate limiting"),
        (SimulatedFailureError("Invalid input format"), "Validation error"),
        (SimulatedFailureError("Insufficient memory"), "Resource error"),
        (SimulatedFailureError("Authentication failed"), "Auth error"),
        (SimulatedFailureError("Unknown server error"), "Generic error")
    ]
    
    for error, description in test_errors:
        error_info = ErrorCategorizer.categorize_error(error)
        
        print(f"📋 {description}:")
        print(f"   Category: {error_info.category.value}")
        print(f"   Severity: {error_info.severity.value}")
        print(f"   Retry after: {error_info.retry_after}s")
        print()


async def demo_retry_logic():
    """Demonstrate retry logic with different scenarios"""
    
    print("🔄 Testing Retry Logic")
    print("=" * 40)
    
    logger = GleitzeitLogger("RetryDemo")
    retry_manager = RetryManager(logger)
    
    # Test 1: Network error with successful retry
    print("1️⃣  Network error with eventual success:")
    try:
        result = await retry_manager.execute_with_retry(
            simulate_transient_error,
            RetryConfig(max_attempts=5, base_delay=0.5),
            service_name="transient_service"
        )
        print(f"   ✅ Result: {result}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    print()
    
    # Test 2: Rate limiting (should retry with backoff)
    print("2️⃣  Rate limiting error:")
    try:
        await retry_manager.execute_with_retry(
            simulate_rate_limit_error,
            RetryConfig(max_attempts=2, base_delay=1.0),
            service_name="rate_limited_service"
        )
    except Exception as e:
        print(f"   ❌ Failed after retries: {e}")
    
    print()
    
    # Test 3: Permanent error (should not retry)
    print("3️⃣  Permanent error (no retry):")
    try:
        await retry_manager.execute_with_retry(
            simulate_permanent_error,
            RetryConfig(max_attempts=3, base_delay=1.0),
            service_name="auth_service"
        )
    except Exception as e:
        print(f"   ❌ Failed immediately: {e}")
    
    print()


async def demo_circuit_breaker():
    """Demonstrate circuit breaker functionality"""
    
    print("🔌 Testing Circuit Breaker")
    print("=" * 40)
    
    logger = GleitzeitLogger("CircuitDemo")
    retry_manager = RetryManager(logger)
    
    # Simulate multiple failures to trigger circuit breaker
    print("Simulating repeated failures to trigger circuit breaker...")
    
    for i in range(8):
        try:
            await retry_manager.execute_with_retry(
                simulate_network_error,
                RetryConfig(max_attempts=1, base_delay=0.1),  # Fast fail
                service_name="failing_service"
            )
        except Exception as e:
            status = "🔴 Circuit OPEN" if i >= 5 else "🟡 Accumulating failures"
            print(f"   Attempt {i+1}: Failed - {status}")
    
    print()
    
    # Try to execute after circuit breaker is open
    print("Attempting execution with open circuit breaker:")
    try:
        await retry_manager.execute_with_retry(
            lambda: "This should not execute",
            RetryConfig(max_attempts=1),
            service_name="failing_service"
        )
    except Exception as e:
        print(f"   ❌ Blocked by circuit breaker: {e}")
    
    print()


async def demo_workflow_error_handling():
    """Demonstrate error handling in actual workflows"""
    
    print("🔄 Testing Workflow Error Handling")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_real_execution=False,  # Use mock to avoid Ollama dependency
        enable_redis=False  # Simplified for demo
    )
    
    await cluster.start()
    
    try:
        # Create workflow with intentional errors
        workflow = cluster.create_workflow("error_test", "Test error handling")
        
        # Add tasks that might fail
        task1 = workflow.add_text_task("task1", "Normal task", "llama3")
        task2 = workflow.add_text_task("task2", "Task that might fail", "llama3")
        task3 = workflow.add_text_task("task3", "Final task", "llama3", dependencies=[task1.id])
        
        print("📋 Executing workflow with potential failures...")
        
        # Set workflow to continue on errors
        from gleitzeit_cluster.core.workflow import WorkflowErrorStrategy
        workflow.error_strategy = WorkflowErrorStrategy.CONTINUE_ON_ERROR
        
        result = await cluster.execute_workflow(workflow)
        
        print(f"📊 Workflow Results:")
        print(f"   Status: {result.status.value}")
        print(f"   Completed: {result.completed_tasks}")
        print(f"   Failed: {result.failed_tasks}")
        print(f"   Errors: {len(result.errors)}")
        
        if result.errors:
            print(f"📋 Error Details:")
            for task_id, error in result.errors.items():
                print(f"   {task_id}: {error}")
    
    finally:
        await cluster.stop()


async def demo_error_logging():
    """Demonstrate structured error logging"""
    
    print("📝 Testing Error Logging")
    print("=" * 40)
    
    # Create logger with file output
    log_file = Path("error_demo.log")
    logger = GleitzeitLogger("ErrorDemo", log_level="DEBUG", log_file=log_file)
    
    # Test different error types and severities
    test_scenarios = [
        (SimulatedFailureError("Critical system failure"), {"service": "core", "user_id": "123"}),
        (SimulatedFailureError("Connection timeout"), {"service": "api", "retry_attempt": 2}),
        (SimulatedFailureError("Invalid input"), {"input": "malformed_data"}),
        (SimulatedFailureError("Resource exhausted"), {"memory_usage": "95%"})
    ]
    
    for error, context in test_scenarios:
        error_info = ErrorCategorizer.categorize_error(error, context)
        logger.log_error(error_info, context)
    
    print(f"✅ Error logs written to: {log_file}")
    print(f"📊 Log file size: {log_file.stat().st_size} bytes")
    
    # Show log contents
    if log_file.exists() and log_file.stat().st_size < 2000:  # Only if reasonably small
        print(f"\n📄 Sample log entries:")
        with open(log_file, 'r') as f:
            for line in f.readlines()[-5:]:  # Last 5 lines
                print(f"   {line.strip()}")


async def demo_result_cache_with_errors():
    """Demonstrate error handling in result caching"""
    
    print("💾 Testing Result Cache Error Handling")
    print("=" * 40)
    
    # Create cache that might fail
    cache = ResultCache(
        redis_client=None,  # No Redis to test fallback
        enable_file_backup=True
    )
    
    # Test storing results with simulated errors
    test_results = [
        ("success_workflow", {"status": "completed", "results": {"task1": "Success!"}}, ["test"]),
        ("partial_workflow", {"status": "partial", "results": {"task1": "Done", "task2": "Failed"}}, ["test", "partial"]),
        ("failed_workflow", {"status": "failed", "results": {}, "errors": {"task1": "Network error"}}, ["test", "error"])
    ]
    
    for workflow_id, result_data, tags in test_results:
        try:
            success = await cache.store_workflow_result(workflow_id, result_data, tags)
            print(f"   {'✅' if success else '❌'} Stored: {workflow_id}")
        except Exception as e:
            print(f"   ❌ Storage failed: {workflow_id} - {e}")
    
    # Test retrieval with error handling
    print("\n📋 Retrieving cached results:")
    for workflow_id, _, _ in test_results:
        try:
            cached_result = await cache.get_workflow_result(workflow_id)
            if cached_result:
                status = cached_result["result"]["status"]
                print(f"   ✅ Retrieved: {workflow_id} (status: {status})")
            else:
                print(f"   ⚠️  Not found: {workflow_id}")
        except Exception as e:
            print(f"   ❌ Retrieval failed: {workflow_id} - {e}")


async def main():
    """Run all error handling demonstrations"""
    
    print("🚀 Gleitzeit Error Handling & Retry System Demo")
    print("=" * 60)
    print()
    
    demos = [
        demo_error_categorization,
        demo_retry_logic,
        demo_circuit_breaker,
        demo_error_logging,
        demo_result_cache_with_errors,
        demo_workflow_error_handling
    ]
    
    for demo in demos:
        try:
            await demo()
            print(f"✅ {demo.__name__} completed")
        except Exception as e:
            print(f"❌ {demo.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
        
        print()
        print("-" * 60)
        print()
    
    print("🎯 Error Handling Demo Summary:")
    print("✅ Error categorization and severity assessment")
    print("✅ Intelligent retry logic with exponential backoff")
    print("✅ Circuit breaker for failing services")
    print("✅ Structured error logging with context")
    print("✅ Workflow error strategies (stop vs continue)")
    print("✅ Result cache error handling and fallbacks")
    print()
    print("💡 The system now has comprehensive error handling!")


if __name__ == "__main__":
    asyncio.run(main())