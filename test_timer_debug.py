#!/usr/bin/env python
"""Debug timer workflow to see the flow"""

import asyncio
import redis.asyncio as aioredis
import json

async def check_timer_flow():
    redis = await aioredis.from_url('redis://localhost:6379')

    print("\n🔍 Checking timer flow in Redis...\n")

    # Check timer:schedule streams
    print("📋 Timer Schedule Streams:")
    for shard in range(16):
        stream_key = f"timer:schedule:{shard}".encode()
        try:
            messages = await redis.xrange(stream_key, count=5)
            if messages:
                print(f"  Shard {shard}: {len(messages)} messages")
                for msg_id, data in messages[:2]:
                    print(f"    - {msg_id.decode()}: {data}")
        except:
            pass

    # Check timer tasks in task:status
    print("\n📋 Timer Task Status:")
    cursor = b'0'
    while True:
        cursor, keys = await redis.scan(cursor, match=b'task:status:*wait*', count=100)
        for key in keys:
            status = await redis.hgetall(key)
            if status.get(b'timer_type'):
                print(f"  {key.decode()}:")
                for k, v in status.items():
                    print(f"    {k.decode()}: {v.decode()}")
        if cursor == b'0':
            break

    # Check pending timers
    print("\n📋 Pending Timers (sorted set):")
    timers = await redis.zrange(b"timers:pending", 0, -1, withscores=True)
    for timer_id, score in timers[:5]:
        print(f"  {timer_id.decode()}: fires at {score}")
        # Get timer metadata
        meta = await redis.hgetall(f"timers:meta:{timer_id.decode()}".encode())
        if meta:
            print(f"    Metadata: {meta}")

    # Check if timer worker is leader
    leader = await redis.get(b"timer:leader")
    if leader:
        print(f"\n👑 Timer Leader: {leader.decode()}")
    else:
        print("\n⚠️  No timer leader elected")

    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(check_timer_flow())