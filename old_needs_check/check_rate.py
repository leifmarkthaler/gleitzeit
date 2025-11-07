#!/usr/bin/env python3
import redis
import time
import subprocess

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

print("Monitoring workflow execution rate...")
print("Time    | Queue  | Done    | Rate/5s | Avg/s | Workers")
print("--------|--------|---------|---------|-------|--------")

start_time = time.time()
prev_completed = 0

for i in range(60):  # Monitor for up to 5 minutes
    # Count queue size
    queue_size = sum(r.xlen(f"{{shard:{s}}}:workflow:load") for s in range(16))

    # Count completed
    completed = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match="workflow:status:*", count=1000)
        for key in keys:
            if r.hget(key, "status") == "completed":
                completed += 1
        if cursor == 0:
            break

    # Count workers
    result = subprocess.run("ps aux | grep -E 'workflow_loader-[0-9]+' | grep -v grep | wc -l",
                          shell=True, capture_output=True, text=True)
    workers = int(result.stdout.strip())

    # Calculate rates
    elapsed = time.time() - start_time
    rate_5s = completed - prev_completed
    avg_rate = completed / elapsed if elapsed > 0 else 0

    print(f"{time.strftime('%H:%M:%S')} | {queue_size:6d} | {completed:6d} | {rate_5s:7d} | {avg_rate:5.0f} | {workers:7d}")

    prev_completed = completed

    if completed >= 100000:
        print(f"\n=== ALL 100K COMPLETED in {elapsed:.0f} seconds! ===")
        print(f"Overall rate: {100000/elapsed:.0f} workflows/sec")
        break

    time.sleep(5)