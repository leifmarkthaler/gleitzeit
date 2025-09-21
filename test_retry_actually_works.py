#!/usr/bin/env python3
"""
Test that the retry system actually works with the easy client.
"""

import asyncio
import json
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


async def test_retry_system():
    """Test that retries actually happen when tasks fail."""
    print("=== Testing Actual Retry System ===\n")
    
    # Clean up any previous attempt file
    import os
    attempt_file = "/tmp/gleitzeit_retry_attempt.txt"
    if os.path.exists(attempt_file):
        os.remove(attempt_file)
    
    # Create a task that will fail first 2 times, succeed on 3rd
    retry_task = (
        t("retry_test", "python/v1:python/execute")
        .with_(file="test_tasks/failing_task.py")
        .with_retry(max_attempts=3, delay=1.0)  # Will retry up to 3 times
    )
    
    # Create workflow
    workflow = (
        w(retry_task)
        .name("retry_test_workflow")
        .version("1.0.0")
        .description("Test that retry actually works")
    )
    
    # Validate
    errors = workflow.validate()
    if errors:
        print(f"❌ Validation errors: {errors}")
        return
    
    print("✅ Workflow validation passed!")
    
    # Show workflow structure
    workflow_dict = workflow.to_dict()
    print("\nWorkflow structure:")
    print(json.dumps(workflow_dict, indent=2))
    
    # Submit to server
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()
    
    try:
        print("\nSubmitting workflow...")
        result = await client.submit_workflow(workflow_dict)
        workflow_id = result.get("workflow_id")
        print(f"✅ Workflow submitted: {workflow_id}")
        
        # Wait for completion
        print("\nWaiting for workflow to complete (retries should happen)...")
        max_wait = 30  # 30 seconds max
        for i in range(max_wait):
            await asyncio.sleep(1)
            workflow_obj = await client.get_workflow(workflow_id)
            print(f"  Status after {i+1}s: {workflow_obj.status}")
            
            if workflow_obj.status in ["completed", "failed"]:
                break
        
        # Check final status
        final_workflow = await client.get_workflow(workflow_id)
        print(f"\n=== Final Result ===")
        print(f"Status: {final_workflow.status}")
        
        if final_workflow.status == "completed":
            print("✅ Workflow completed successfully after retries!")
        else:
            print("❌ Workflow failed despite retries")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main test function."""
    print("=" * 60)
    print("TESTING RETRY SYSTEM WITH EASY CLIENT")
    print("=" * 60)
    print()
    
    await test_retry_system()
    
    print("\n" + "=" * 60)
    print("RETRY SYSTEM TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
