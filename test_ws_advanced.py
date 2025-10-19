#!/usr/bin/env python3
"""Test advanced WebSocket methods."""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient

async def test_connection_stats():
    """Test WebSocket connection health."""
    print("=== Testing Connection Stats ===\n")
    
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        stats = await client.get_connection_stats()
        print(f"Status: {stats['status']}")
        print(f"Latency: {stats.get('latency_ms')}ms")
        print(f"Connect Time: {stats.get('connect_time_ms')}ms")
        print(f"Connected: {stats['connected']}\n")

async def test_watch_multiple():
    """Test watching multiple workflows."""
    print("=== Testing Multiple Workflow Monitoring ===\n")
    
    with open("test_python_workflow.yaml", "r") as f:
        workflow = yaml.safe_load(f)
    
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit 3 workflows
        print("Submitting 3 workflows...")
        ids = []
        for i in range(3):
            response = await client.submit_workflow(workflow)
            ids.append(response.workflow_id)
            print(f"  {i+1}. {response.workflow_id[:8]}...")
        
        print("\nMonitoring all workflows...")
        
        # Watch all at once
        summary = await client.watch_multiple_workflows(
            ids,
            on_workflow_complete=lambda wid, e: print(f"  ✓ {wid[:8]} completed"),
            on_all_complete=lambda s: print(f"\n  All workflows done! {s['completed']}/{s['total']}"),
            timeout=60
        )
        
        print(f"\nSummary:")
        print(f"  Total: {summary['total']}")
        print(f"  Completed: {summary['completed']}")
        print(f"  Failed: {summary['failed']}")
        print(f"  Timeout: {summary['timeout']}\n")

async def test_wait_for_task():
    """Test waiting for specific task."""
    print("=== Testing Task-Level Monitoring ===\n")
    
    with open("test_python_workflow.yaml", "r") as f:
        workflow = yaml.safe_load(f)
    
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit workflow
        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id
        print(f"Submitted workflow: {workflow_id[:8]}...\n")
        
        # Get tasks to find task IDs
        await asyncio.sleep(1)  # Let workflow start
        tasks_list = await client.get_workflow_tasks(workflow_id)
        
        if tasks_list:
            first_task_id = tasks_list[0].get('id')
            print(f"Monitoring task: {first_task_id[:8]}...\n")
            
            # Wait for specific task
            task_event = await client.wait_for_task(
                first_task_id,
                workflow_id,
                on_complete=lambda e: print(f"  ✓ Task completed!"),
                timeout=30
            )
            
            print(f"\nTask result: {task_event.get('data', {}).get('result')}\n")

async def main():
    """Run all tests."""
    try:
        await test_connection_stats()
        await test_watch_multiple()
        await test_wait_for_task()
        print("✓ All tests completed!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
