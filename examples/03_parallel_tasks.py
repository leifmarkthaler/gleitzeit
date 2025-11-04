#!/usr/bin/env python3
"""
Parallel Tasks Example - Concurrent Execution with Aggregation

This example demonstrates how to run multiple tasks in parallel and
then combine their results in a final aggregation task.
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def main():
    """Parallel task execution with result aggregation"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Define workflow with parallel tasks
        workflow = {
            'name': 'Parallel Processing',
            'tasks': [
                # These three tasks run in parallel
                {
                    'id': 'task_a',
                    'type': 'python',
                    'params': {
                        'code': '''
import time
time.sleep(1)  # Simulate work
result = {"name": "Task A", "value": 10}
print(f"Task A completed: {result}")
'''
                    }
                },
                {
                    'id': 'task_b',
                    'type': 'python',
                    'params': {
                        'code': '''
import time
time.sleep(1)  # Simulate work
result = {"name": "Task B", "value": 20}
print(f"Task B completed: {result}")
'''
                    }
                },
                {
                    'id': 'task_c',
                    'type': 'python',
                    'params': {
                        'code': '''
import time
time.sleep(1)  # Simulate work
result = {"name": "Task C", "value": 30}
print(f"Task C completed: {result}")
'''
                    }
                },
                # This task waits for all three to complete
                {
                    'id': 'combine',
                    'type': 'python',
                    'depends_on': ['task_a', 'task_b', 'task_c'],
                    'params': {
                        'code': '''
# Combine results from all three parallel tasks
# Access results via 'inputs'
result_a = inputs.get("task_a", {})
result_b = inputs.get("task_b", {})
result_c = inputs.get("task_c", {})

# Calculate total
total = (
    result_a.get("value", 0) +
    result_b.get("value", 0) +
    result_c.get("value", 0)
)

result = {
    "all_tasks": [result_a, result_b, result_c],
    "total": total,
    "average": total / 3
}
print(f"Combined results - Total: {total}, Average: {total/3}")
'''
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted parallel workflow: {response.workflow_id}")

        # Wait for completion
        status = await client.wait_for_workflow(response.workflow_id, timeout=60)
        print(f"✓ Workflow completed: {status.status}")

        # Get final result
        tasks = await client.get_workflow_tasks(response.workflow_id)
        combine_task = next((t for t in tasks if 'combine' in str(t)), None)
        if combine_task:
            task_id = combine_task.get('task_id') if isinstance(combine_task, dict) else combine_task.task_id
            result = await client.get_task_result(task_id, response.workflow_id)
            print(f"\n📊 Final Result:")
            print(f"   Total: {result.get('total')}")
            print(f"   Average: {result.get('average')}")


if __name__ == "__main__":
    print("=" * 60)
    print("Parallel Tasks Example")
    print("=" * 60)
    asyncio.run(main())
