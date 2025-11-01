#!/usr/bin/env python3
"""Monitor workflow completion rate in real-time"""

import asyncio
import redis.asyncio as aioredis
from datetime import datetime

async def monitor_workflows(duration_seconds=60):
    """Monitor workflow completion for specified duration"""
    redis_client = await aioredis.from_url("redis://localhost:6379")

    # Get initial count
    initial_pending = 0
    for shard in range(16):
        count = await redis_client.llen(f"{{shard:{shard}}}:workflows:pending")
        initial_pending += count

    print(f"🔍 Monitoring workflow completion for {duration_seconds} seconds...")
    print(f"Initial pending workflows: {initial_pending:,}")
    print("-" * 60)

    start_time = datetime.now()
    last_count = initial_pending

    for i in range(duration_seconds):
        await asyncio.sleep(1)

        # Count current pending
        current_pending = 0
        for shard in range(16):
            count = await redis_client.llen(f"{{shard:{shard}}}:workflows:pending")
            current_pending += count

        # Calculate completion rate
        completed_this_second = last_count - current_pending
        elapsed = i + 1
        total_completed = initial_pending - current_pending
        avg_rate = total_completed / elapsed if elapsed > 0 else 0

        if i % 5 == 0 or completed_this_second > 0:  # Print every 5 seconds or when there's activity
            print(f"[{elapsed:3d}s] Pending: {current_pending:,} | "
                  f"Completed this sec: {completed_this_second:,} | "
                  f"Avg rate: {avg_rate:.1f}/sec")

        last_count = current_pending

        # Early exit if all processed
        if current_pending == 0:
            print(f"\n✅ All workflows completed in {elapsed} seconds!")
            break

    final_time = datetime.now()
    duration = (final_time - start_time).total_seconds()
    final_pending = current_pending
    total_completed = initial_pending - final_pending

    print("-" * 60)
    print(f"\n📊 Summary:")
    print(f"  Duration: {duration:.1f}s")
    print(f"  Initial: {initial_pending:,} workflows")
    print(f"  Completed: {total_completed:,} workflows")
    print(f"  Remaining: {final_pending:,} workflows")
    print(f"  Average rate: {total_completed / duration:.1f} workflows/sec")

    await redis_client.close()

if __name__ == "__main__":
    asyncio.run(monitor_workflows(duration_seconds=60))
