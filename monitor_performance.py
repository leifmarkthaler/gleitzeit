#!/usr/bin/env python3
import redis
import time
import subprocess
from datetime import datetime

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

start_time = time.time()
print(f"=== PERFORMANCE TEST STARTED at {datetime.now()} ===")
print("Time    | Queue  | Done     | Workers | Rate    | Elapsed")
print("--------|--------|----------|---------|---------|--------")

while True:
    # Count queue size across all shards
    queue_size = 0
    for shard in range(16):
        queue_size += r.xlen(f"{{shard:{shard}}}:workflow:load")

    # Count completed workflows
    completed = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match="workflow:status:*", count=1000)
        for key in keys:
            status = r.hget(key, "status")
            if status == "completed":
                completed += 1
        if cursor == 0:
            break

    # Count worker processes
    result = subprocess.run("ps aux | grep -E 'workflow_loader-[0-9]+' | grep -v grep | wc -l",
                          shell=True, capture_output=True, text=True)
    workers = int(result.stdout.strip())

    # Calculate metrics
    elapsed = int(time.time() - start_time)
    rate = completed / elapsed if elapsed > 0 else 0

    # Print status
    print(f"{datetime.now().strftime('%H:%M:%S')} | {queue_size:6d} | {completed:6d}/100k | {workers:7d} | {rate:6.0f}/s | {elapsed:6d}s")

    # Check completion
    if completed >= 100000:
        print(f"\n=== ALL 100K WORKFLOWS COMPLETED in {elapsed} seconds! ===")
        print(f"Average throughput: {100000 / elapsed:.0f} workflows/sec")
        break

    time.sleep(5)