#!/usr/bin/env python3
"""
Submit 10k workflows for stress test
"""
import asyncio
import time
import yaml
import sys
from pathlib import Path

sys.path.insert(0, 'src')
from gleitzeit.client.client import GleitzeitClient

async def submit_10k_workflows():
    """Submit 10k workflows"""
    client = GleitzeitClient("http://localhost:8000")

    print("🚀 Starting 10k workflow submission...")
    start_time = time.time()

    workflow_dir = Path("test_100k")
    total = 10000

    # Load first workflow as template
    with open(workflow_dir / "wf_000001.yaml", 'r') as f:
        template = yaml.safe_load(f)

    submitted = 0
    errors = 0

    # Submit workflows
    for i in range(1, total + 1):
        try:
            # Modify template
            workflow = template.copy()
            workflow['name'] = f"Stress Test {i}"

            # Submit
            await client.submit_workflow(workflow)
            submitted += 1

            # Progress every 1000
            if submitted % 1000 == 0:
                elapsed = time.time() - start_time
                rate = submitted / elapsed
                print(f"{submitted:5d}/{total} | Rate: {rate:6.0f}/s | Elapsed: {elapsed:5.1f}s")

        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"❌ Error: {e}")

    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"✅ Submitted: {submitted:,} workflows")
    print(f"⏱️  Total time: {total_time:.2f}s")
    print(f"📈 Rate: {submitted/total_time:.0f} workflows/sec")
    print(f"❌ Errors: {errors}")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(submit_10k_workflows())
