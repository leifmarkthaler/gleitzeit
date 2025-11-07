#!/usr/bin/env python
"""
Test timer accuracy - verify timers fire at the correct time
"""

import asyncio
import time
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import redis.asyncio as aioredis
from gleitzeit.timers.stateless_timer_manager import StatelessTimerManager


async def test_timer_accuracy():
    """Test that timers respect the requested duration accurately"""
    print("\n=== Testing Timer Accuracy ===\n")

    redis = await aioredis.from_url('redis://localhost:6379')

    try:
        # Clean up any existing timers
        await redis.delete(StatelessTimerManager.PENDING_TIMERS_KEY)

        # Test 1: Using duration_seconds (old API - backward compatibility)
        print("Test 1: Using duration_seconds parameter (backward compatible)")
        start_time = time.time()
        requested_duration = 2.0  # 2 seconds

        timer_id_1 = await StatelessTimerManager.create_timer(
            redis=redis,
            workflow_id="test-wf-1",
            duration_seconds=requested_duration,
            task_id="test-task-1",
            timer_type="sleep"
        )

        # Check when it's scheduled
        timer_data = await StatelessTimerManager.get_timer_status(redis, timer_id_1)
        scheduled_timestamp = float(timer_data['scheduled_timestamp'])
        expected_wake = start_time + requested_duration
        drift_old_api = scheduled_timestamp - expected_wake

        print(f"  Requested duration: {requested_duration}s")
        print(f"  Expected wake time: {expected_wake:.3f}")
        print(f"  Actual scheduled time: {scheduled_timestamp:.3f}")
        print(f"  Drift: {drift_old_api*1000:.1f}ms")
        print(f"  Status: {'✅ PASS' if abs(drift_old_api) < 0.1 else '❌ FAIL'}")

        # Test 2: Using wake_time (new API - more accurate)
        print("\nTest 2: Using wake_time parameter (new API)")
        start_time = time.time()
        requested_duration = 2.0
        exact_wake_time = start_time + requested_duration

        # Simulate processing delay
        await asyncio.sleep(0.1)  # 100ms delay

        timer_id_2 = await StatelessTimerManager.create_timer(
            redis=redis,
            workflow_id="test-wf-2",
            wake_time=exact_wake_time,  # Use absolute time
            task_id="test-task-2",
            timer_type="sleep"
        )

        # Check when it's scheduled
        timer_data = await StatelessTimerManager.get_timer_status(redis, timer_id_2)
        scheduled_timestamp = float(timer_data['scheduled_timestamp'])
        drift_new_api = scheduled_timestamp - exact_wake_time

        print(f"  Requested duration: {requested_duration}s")
        print(f"  Processing delay: 100ms")
        print(f"  Expected wake time: {exact_wake_time:.3f}")
        print(f"  Actual scheduled time: {scheduled_timestamp:.3f}")
        print(f"  Drift: {drift_new_api*1000:.1f}ms")
        print(f"  Status: {'✅ PASS' if abs(drift_new_api) < 0.01 else '❌ FAIL'}")

        # Test 3: Verify timers fire correctly
        print("\nTest 3: Verify timers actually fire at the right time")
        start_time = time.time()
        wake_time = start_time + 1.0  # 1 second

        timer_id_3 = await StatelessTimerManager.create_timer(
            redis=redis,
            workflow_id="test-wf-3",
            wake_time=wake_time,
            task_id="test-task-3",
            timer_type="sleep"
        )

        print(f"  Created timer to fire in 1.0s")
        print(f"  Waiting for timer to expire...")

        # Wait for timer to become due
        await asyncio.sleep(1.1)

        # Process due timers
        processed, fired_timers = await StatelessTimerManager.process_due_timers(redis)

        if fired_timers:
            fired_timer = fired_timers[0]
            fire_time = time.time()
            actual_duration = fire_time - start_time
            error = actual_duration - 1.0

            print(f"  Timer fired after: {actual_duration:.3f}s")
            print(f"  Error: {error*1000:.1f}ms")
            print(f"  Status: {'✅ PASS' if abs(error) < 0.2 else '❌ FAIL'}")
        else:
            print(f"  ❌ FAIL: Timer did not fire")

        # Summary
        print("\n" + "="*50)
        if abs(drift_old_api) < 0.1 and abs(drift_new_api) < 0.01:
            print("✅ ALL TESTS PASSED")
            print(f"   Old API drift: {drift_old_api*1000:.1f}ms (acceptable)")
            print(f"   New API drift: {drift_new_api*1000:.1f}ms (excellent)")
        else:
            print("❌ SOME TESTS FAILED")
        print("="*50 + "\n")

        # Cleanup
        await redis.delete(StatelessTimerManager.PENDING_TIMERS_KEY)

    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(test_timer_accuracy())
