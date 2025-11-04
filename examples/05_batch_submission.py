#!/usr/bin/env python3
"""
Batch Submission Example - Submitting Multiple Workflows

This example demonstrates how to efficiently submit multiple workflows
using batch operations.
"""

import asyncio
import time
from gleitzeit.client import GleitzeitClient


async def main():
    """Batch workflow submission"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Create multiple workflows
        num_workflows = 50
        workflows = []

        for i in range(num_workflows):
            workflows.append({
                'name': f'Batch Workflow {i+1}',
                'tasks': [{
                    'id': 'calculate',
                    'type': 'python',
                    'params': {
                        'code': f'''
# Workflow {i+1}
import math
result = {{
    "workflow_number": {i+1},
    "value": {i * 10},
    "squared": {i * i},
    "sqrt": math.sqrt({i+1})
}}
'''
                    }
                }]
            })

        # Submit batch
        print(f"\n📤 Submitting {num_workflows} workflows...")
        start = time.time()

        responses = await client.submit_workflows_batch(
            workflows,
            max_concurrent=10  # Submit up to 10 at a time
        )

        elapsed = time.time() - start

        print(f"✓ Submitted {len(responses)} workflows in {elapsed:.2f}s")
        print(f"  Rate: {len(responses)/elapsed:.0f} workflows/second")

        # Wait for first few to complete
        print(f"\n⏳ Waiting for first 5 workflows to complete...")
        for i, response in enumerate(responses[:5]):
            status = await client.wait_for_workflow(
                response.workflow_id,
                timeout=30,
                poll_interval=1
            )
            print(f"  ✓ Workflow {i+1}: {status.status}")


if __name__ == "__main__":
    print("=" * 60)
    print("Batch Submission Example")
    print("=" * 60)
    asyncio.run(main())
