#!/usr/bin/env python3
"""
Sequential Tasks Example - Task Dependencies

This example demonstrates how to chain tasks together where each task
depends on the output of the previous task.

IMPORTANT: Use 'inputs' to access dependency results, not 'dependencies'
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def main():
    """Sequential task execution with dependencies"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Define workflow with sequential tasks
        workflow = {
            'name': 'Data Processing Pipeline',
            'tasks': [
                {
                    'id': 'fetch_data',
                    'type': 'python',
                    'params': {
                        'code': '''
# Step 1: Fetch data
data = [1, 2, 3, 4, 5]
result = {
    "data": data,
    "count": len(data)
}
print(f"Fetched {len(data)} items")
'''
                    }
                },
                {
                    'id': 'process_data',
                    'type': 'python',
                    'depends_on': ['fetch_data'],  # Wait for fetch_data to complete
                    'params': {
                        'code': '''
# Step 2: Process data
# Access previous task result via 'inputs'
fetch_result = inputs.get("fetch_data", {})
data = fetch_result.get("data", [])

# Double all values
processed = [x * 2 for x in data]
result = {
    "processed": processed,
    "sum": sum(processed),
    "count": len(processed)
}
print(f"Processed {len(processed)} items, sum: {sum(processed)}")
'''
                    }
                },
                {
                    'id': 'save_results',
                    'type': 'python',
                    'depends_on': ['process_data'],  # Wait for process_data to complete
                    'params': {
                        'code': '''
# Step 3: Save results
# Access process_data result via 'inputs'
process_result = inputs.get("process_data", {})
print(f"Saving results: {process_result}")

result = {
    "status": "saved",
    "data": process_result
}
'''
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted pipeline: {response.workflow_id}")

        # Wait for completion
        status = await client.wait_for_workflow(response.workflow_id, timeout=60)
        print(f"✓ Pipeline completed: {status.status}")

        # Show results
        print(f"\n📊 Pipeline Results:")
        print(f"   Status: {status.status}")
        print(f"   Workflow ID: {response.workflow_id}")


if __name__ == "__main__":
    print("=" * 60)
    print("Sequential Tasks Example")
    print("=" * 60)
    asyncio.run(main())
