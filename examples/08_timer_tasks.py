#!/usr/bin/env python3
"""
Timer Tasks Example
===================
This example demonstrates using timer tasks to introduce delays in workflows.

Timer tasks are useful for:
- Rate limiting
- Scheduled delays
- Retry backoff patterns
- Time-based orchestration

Prerequisites:
- Gleitzeit server running: gleitzeit serve --dev-mode
"""

import asyncio
import time
from gleitzeit.client import GleitzeitClient


async def main():
    """Run timer task example"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Workflow with timer task
        workflow = {
            'name': 'timer-example',
            'tasks': [
                {
                    'id': 'init_task',
                    'type': 'python',
                    'params': {
                        'code': '''
import time
print(f"Init task started at {time.time()}")
result = {"start_time": time.time()}
'''
                    }
                },
                {
                    'id': 'timer_task',
                    'type': 'timer',
                    'depends_on': ['init_task'],
                    'params': {
                        'duration': 3  # Wait for 3 seconds
                    }
                },
                {
                    'id': 'final_task',
                    'type': 'python',
                    'depends_on': ['timer_task'],
                    'params': {
                        'code': '''
import time
print(f"Final task started at {time.time()}")
result = {"end_time": time.time()}
'''
                    }
                }
            ]
        }

        # Submit workflow
        start_time = time.time()
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted timer workflow: {response.workflow_id}")

        # Wait for completion
        print("\n⏳ Workflow running with 3-second timer delay...")
        status = await client.wait_for_workflow(response.workflow_id, timeout=30)

        elapsed = time.time() - start_time
        print(f"\n✓ Timer workflow completed: {status.status}")
        print(f"   Total time: {elapsed:.1f}s (should be ~3+ seconds)")


if __name__ == "__main__":
    print("=" * 60)
    print("Timer Tasks Example")
    print("=" * 60)
    print()

    asyncio.run(main())
