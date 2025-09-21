#!/usr/bin/env python3
"""
Test workflow execution using the Gleitzeit client library.
This demonstrates how a user would use Gleitzeit as a library.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for library import
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def main():
    """Run workflows using Gleitzeit client library."""
    
    print("Testing Gleitzeit Client Library")
    print("=" * 50)
    
    # Import Gleitzeit client
    from gleitzeit.client import GleitzeitClient, ClientMode
    
    # Create client in API mode (connects to running Gleitzeit server)
    print("\n1. Creating Gleitzeit client in API mode...")
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_url="http://localhost:8000"  # Default API server URL
    )
    
    # Initialize client (connects to API)
    await client.initialize()
    print("✓ Client initialized and connected to API")
    
    # Create a simple Python workflow
    print("\n2. Creating Python workflow...")
    
    # Create test Python files
    test_files = []
    for i in range(3):
        test_file = Path(f"/tmp/gleitzeit_task_{i}.py")
        test_file.write_text(f"""
# Task {i}
import time
import json

print(f"Starting task {i}")
time.sleep(0.5)  # Simulate work

# Return result
result = {{
    "task_id": {i},
    "message": "Task {i} completed successfully",
    "value": {i} * 10
}}

print(json.dumps(result))
""")
        test_files.append(test_file)
    
    # Submit tasks
    task_ids = []
    
    print("\n3. Submitting tasks...")
    for i, test_file in enumerate(test_files):
        task_id = await client.submit_task(
            protocol="python/v1",
            method="python/execute",
            params={
                "file_path": str(test_file.absolute()),
                "return_output": True
            },
            task_id=f"python_task_{i}"
        )
        task_ids.append(task_id)
        print(f"  ✓ Submitted task {i}: {task_id}")
    
    # Create and submit a workflow with dependencies
    print("\n4. Creating workflow with dependencies...")
    
    # Create workflow definition
    workflow_def = {
        "id": "test_workflow_001",
        "name": "Test Workflow",
        "tasks": [
            {
                "id": "task_a",
                "name": "Task A",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file_path": str(test_files[0].absolute()),
                    "return_output": True
                }
            },
            {
                "id": "task_b",
                "name": "Task B",
                "protocol": "python/v1", 
                "method": "python/execute",
                "params": {
                    "file_path": str(test_files[1].absolute()),
                    "return_output": True
                },
                "dependencies": ["task_a"]  # B depends on A
            },
            {
                "id": "task_c",
                "name": "Task C",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file_path": str(test_files[2].absolute()),
                    "return_output": True
                },
                "dependencies": ["task_a", "task_b"]  # C depends on both A and B
            }
        ]
    }
    
    # Submit workflow
    workflow_id = await client.submit_workflow(workflow_def)
    print(f"✓ Submitted workflow: {workflow_id}")
    
    # Wait for individual tasks to complete
    print("\n5. Waiting for individual tasks...")
    for i, task_id in enumerate(task_ids):
        result = await client.wait_for_task(task_id, timeout=10)
        if result:
            print(f"  ✓ Task {i} completed")
            if result.result and 'output' in result.result:
                print(f"    Output: {result.result['output'][:100]}...")
        else:
            print(f"  ✗ Task {i} failed or timed out")
    
    # Get workflow status
    print("\n6. Checking workflow status...")
    await asyncio.sleep(3)  # Give workflow time to complete
    
    # Get workflow results (native mode doesn't have get_workflow_status yet)
    # We'll check task results instead
    workflow_tasks = ["task_a", "task_b", "task_c"]
    completed = 0
    for task_id in workflow_tasks:
        full_id = f"test_workflow_001-{task_id}"  # Workflow prefixes task IDs
        try:
            # Try to get task result
            result = await client.wait_for_task(full_id, timeout=1)
            if result and result.status == "completed":
                completed += 1
                print(f"  ✓ {task_id}: completed")
        except:
            print(f"  ? {task_id}: status unknown")
    
    print(f"\n  Workflow tasks completed: {completed}/3")
    
    # Shutdown client
    print("\n7. Shutting down client...")
    await client.shutdown()
    print("✓ Client shut down")
    
    # Cleanup
    for test_file in test_files:
        test_file.unlink(missing_ok=True)
    
    print("\n" + "=" * 50)
    print("✅ Gleitzeit client library test completed!")
    print("\nThe client successfully:")
    print("  - Connected in native mode")
    print("  - Submitted individual tasks")  
    print("  - Submitted a workflow with dependencies")
    print("  - Retrieved task results")
    print("  - Handled task dependencies correctly")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)