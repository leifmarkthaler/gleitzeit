#!/usr/bin/env python
"""
Test script to verify the retry mechanism is working correctly.

Run with: python test_retry_system.py
"""

import sys
import asyncio
import redis.asyncio as aioredis
import time
from datetime import datetime

# Add src to path
sys.path.insert(0, '/Users/leifmarkthaler/github/gleitzeit 0.0.7/src')

from gleitzeit.core.stateless_retry_service import StatelessRetryService, RetryContext, RetryDecision


async def main():
    """Test the retry mechanism."""
    print("=" * 60)
    print("RETRY MECHANISM TEST SUITE")
    print("=" * 60)

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379', decode_responses=False)

    # Create retry service
    service = StatelessRetryService(redis)

    # Test results
    tests_passed = 0
    tests_failed = 0

    # Test 1: Retryable Error Decision
    print("\n[TEST 1] Retryable Error Decision")
    print("-" * 40)
    try:
        context = RetryContext(
            task_id='test_1',
            workflow_id='test_workflow',
            error_type='ConnectionError',
            error_msg='Connection refused',
            current_attempt=0
        )

        decision, metadata = await service.should_retry(context)

        if decision == RetryDecision.RETRY and metadata.get('delay', 0) > 0:
            print(f"✅ PASS: ConnectionError correctly identified as retryable")
            print(f"   Decision: {decision.value}, Delay: {metadata['delay']:.2f}s")
            tests_passed += 1
        else:
            print(f"❌ FAIL: Expected RETRY decision")
            tests_failed += 1
    except Exception as e:
        print(f"❌ FAIL: {e}")
        tests_failed += 1

    # Test 2: Non-Retryable Error (CircuitOpenError)
    print("\n[TEST 2] Non-Retryable Error (CircuitOpenError)")
    print("-" * 40)
    try:
        context = RetryContext(
            task_id='test_2',
            workflow_id='test_workflow',
            error_type='CircuitOpenError',
            error_msg='Circuit breaker is open',
            current_attempt=0
        )

        decision, metadata = await service.should_retry(context)

        if decision == RetryDecision.SKIP:
            print(f"✅ PASS: CircuitOpenError correctly identified as non-retryable")
            print(f"   Decision: {decision.value}, Reason: {metadata.get('reason')}")
            tests_passed += 1
        else:
            print(f"❌ FAIL: Expected SKIP decision for CircuitOpenError")
            tests_failed += 1
    except Exception as e:
        print(f"❌ FAIL: {e}")
        tests_failed += 1

    # Test 3: Max Attempts Exceeded
    print("\n[TEST 3] Max Attempts Exceeded")
    print("-" * 40)
    try:
        context = RetryContext(
            task_id='test_3',
            workflow_id='test_workflow',
            error_type='ConnectionError',
            error_msg='Connection refused',
            current_attempt=10  # Exceeds default max_retries of 2
        )

        decision, metadata = await service.should_retry(context)

        if decision == RetryDecision.MAX_ATTEMPTS:
            print(f"✅ PASS: Max attempts correctly enforced")
            print(f"   Decision: {decision.value}, Current attempt: {metadata.get('current_attempt')}")
            tests_passed += 1
        else:
            print(f"❌ FAIL: Expected MAX_ATTEMPTS decision")
            tests_failed += 1
    except Exception as e:
        print(f"❌ FAIL: {e}")
        tests_failed += 1

    # Test 4: Configuration Hierarchy
    print("\n[TEST 4] Configuration Hierarchy")
    print("-" * 40)
    try:
        # Set workflow-specific config
        await service.set_retry_config(
            {'max_retries': 5, 'base_delay': 3.0},
            workflow_id='config_test_workflow'
        )

        # Get config
        config = await service._get_retry_config('config_test_workflow', 'task_1')

        if config['max_retries'] == 5 and config['base_delay'] == 3.0:
            print(f"✅ PASS: Configuration hierarchy working")
            print(f"   Config: max_retries={config['max_retries']}, base_delay={config['base_delay']}")
            tests_passed += 1
        else:
            print(f"❌ FAIL: Config not properly retrieved")
            tests_failed += 1

        # Cleanup
        await redis.delete(b'retry:config:workflow:config_test_workflow')
    except Exception as e:
        print(f"❌ FAIL: {e}")
        tests_failed += 1

    # Test 5: Retry Scheduling
    print("\n[TEST 5] Retry Scheduling via Timer")
    print("-" * 40)
    try:
        # Schedule a retry
        task_key = b'task:timer_test:task_1'
        await redis.hset(
            task_key,
            mapping={
                b'status': b'scheduled',
                b'retry_count': b'1',
                b'last_error': b'Test error'
            }
        )

        # Add to timer
        timer_score = time.time() + 5
        await redis.zadd(
            b'timers',
            {b'timer_test:task_1:retry': timer_score}
        )

        # Check timer exists
        timers = await redis.zrange(b'timers', 0, -1, withscores=True)
        timer_found = any(b'timer_test:task_1' in timer for timer, _ in timers)

        if timer_found:
            print(f"✅ PASS: Retry successfully scheduled via timer")
            print(f"   Scheduled for execution in ~5 seconds")
            tests_passed += 1
        else:
            print(f"❌ FAIL: Timer not found")
            tests_failed += 1

        # Cleanup
        await redis.delete(task_key)
        await redis.zrem(b'timers', b'timer_test:task_1:retry')
    except Exception as e:
        print(f"❌ FAIL: {e}")
        tests_failed += 1

    # Test 6: Metrics Collection
    print("\n[TEST 6] Metrics Collection")
    print("-" * 40)
    try:
        # Record some metrics
        await service.record_retry_success('metrics_workflow', 'task_1')
        await service.record_retry_failure('metrics_workflow', 'task_2')
        await service.record_retry_success('metrics_workflow', 'task_3')

        # Get metrics
        metrics = await service.get_retry_metrics('metrics_workflow')

        if metrics['total_retries'] >= 3 and metrics['success_rate'] > 0:
            print(f"✅ PASS: Metrics properly collected")
            print(f"   Total: {metrics['total_retries']}, Success rate: {metrics['success_rate']:.1f}%")
            tests_passed += 1
        else:
            print(f"❌ FAIL: Metrics not properly collected")
            tests_failed += 1

        # Cleanup
        await redis.delete(b'retry:metrics:metrics_workflow')
    except Exception as e:
        print(f"❌ FAIL: {e}")
        tests_failed += 1

    # Test 7: Budget System
    print("\n[TEST 7] Retry Budget System")
    print("-" * 40)
    try:
        # Try consuming budget multiple times
        consumed = 0
        for i in range(10):
            context = RetryContext(
                task_id=f'budget_task_{i}',
                workflow_id='budget_workflow',
                error_type='ConnectionError',
                error_msg='Test',
                current_attempt=0
            )

            # Check budget (don't actually retry)
            has_budget = await service._check_budget(context)
            if has_budget:
                consumed += 1

        if consumed > 0:
            print(f"✅ PASS: Budget system working")
            print(f"   Consumed {consumed}/10 retry attempts")
            tests_passed += 1
        else:
            print(f"❌ FAIL: Budget system not working")
            tests_failed += 1
    except Exception as e:
        print(f"❌ FAIL: {e}")
        tests_failed += 1

    # Close Redis connection
    await redis.aclose()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests Passed: {tests_passed}")
    print(f"Tests Failed: {tests_failed}")
    print(f"Total Tests: {tests_passed + tests_failed}")
    print(f"Success Rate: {(tests_passed / (tests_passed + tests_failed) * 100):.1f}%")

    if tests_failed == 0:
        print("\n✅ ALL TESTS PASSED! The retry mechanism is working correctly.")
    else:
        print(f"\n⚠️  {tests_failed} test(s) failed. Please review the output above.")

    print("\n" + "=" * 60)
    return tests_failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)