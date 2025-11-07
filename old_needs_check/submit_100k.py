#!/usr/bin/env python3
"""
Submit 100k workflows from test_100k directory
"""
import asyncio
import time
import yaml
import sys
import os
from pathlib import Path

sys.path.insert(0, 'src')
from gleitzeit.client.client import GleitzeitClient

async def submit_100k_workflows():
    """Submit 100k workflows"""
    client = GleitzeitClient("http://localhost:8000")

    print("🚀 Starting 100k workflow submission...")
    print(f"⏰ Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    start_time = time.time()

    workflow_dir = Path("test_100k")
    workflow_files = sorted(workflow_dir.glob("wf_*.yaml"))

    total_workflows = len(workflow_files)
    print(f"📁 Found {total_workflows} workflow files")

    submitted = 0
    errors = 0
    batch_size = 1000

    # Submit in batches for progress reporting
    for i in range(0, total_workflows, batch_size):
        batch = workflow_files[i:i+batch_size]
        batch_start = time.time()

        for wf_file in batch:
            try:
                # Load workflow from YAML
                with open(wf_file, 'r') as f:
                    workflow_data = yaml.safe_load(f)

                # Submit workflow
                await client.submit_workflow(workflow_data)
                submitted += 1

            except Exception as e:
                errors += 1
                if errors < 10:  # Only print first 10 errors
                    print(f"❌ Error submitting {wf_file.name}: {e}")

        batch_time = time.time() - batch_start
        elapsed = time.time() - start_time
        rate = submitted / elapsed if elapsed > 0 else 0

        print(f"Progress: {submitted:6d}/{total_workflows} ({submitted*100//total_workflows:2d}%) | "
              f"Rate: {rate:6.0f}/s | Batch: {batch_time:.1f}s | Errors: {errors}")

    total_time = time.time() - start_time

    print(f"\n{'='*80}")
    print(f"📊 Submission Complete!")
    print(f"  ✅ Submitted: {submitted:,} workflows")
    print(f"  ❌ Errors: {errors}")
    print(f"  ⏱️  Total time: {total_time:.2f}s")
    print(f"  📈 Average rate: {submitted/total_time:.0f} workflows/sec")
    print(f"{'='*80}")

    print(f"\n💡 Now run 'python3 monitor_performance.py' to track execution")

if __name__ == "__main__":
    asyncio.run(submit_100k_workflows())
