#!/usr/bin/env python3
"""Test that workflow status properly reflects failed tasks"""

import asyncio
import httpx
import yaml
import time

async def test_workflow_failure():
    """Submit a workflow with invalid model and verify it fails properly"""
    
    # Load the test workflow with invalid model (llama5)
    with open("test_workflow.yaml", "r") as f:
        workflow = yaml.safe_load(f)
    
    print(f"📋 Submitting workflow: {workflow['name']}")
    print(f"   Tasks: {[t['id'] for t in workflow['tasks']]}")
    
    # Submit workflow via API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8001/api/workflows",
            json=workflow,
            timeout=30.0
        )
        
        if response.status_code != 200:
            print(f"❌ Failed to submit: {response.status_code} - {response.text}")
            return
        
        workflow_id = response.json()["workflow_id"]
        print(f"✅ Workflow submitted: {workflow_id}\n")
        
        # Monitor workflow and task status
        print("⏳ Monitoring workflow execution...")
        print("-" * 60)
        
        last_status = None
        for i in range(60):  # Monitor for up to 60 seconds
            # Get workflow status
            status_response = await client.get(
                f"http://localhost:8001/api/workflows/{workflow_id}/status"
            )
            
            if status_response.status_code == 200:
                status = status_response.json()
                
                # Only print if status changed
                if status != last_status:
                    print(f"\nIteration {i+1}:")
                    print(f"  Workflow Status: {status.get('status', 'unknown')}")
                    
                    # Show task summary if available
                    if 'task_summary' in status:
                        summary = status['task_summary']
                        print(f"  Task Summary: {summary}")
                    
                    # Show individual task statuses
                    if 'tasks' in status:
                        for task_id, task_info in status['tasks'].items():
                            task_status = task_info.get('status', 'unknown')
                            retry_info = ""
                            if 'retry_attempt' in task_info:
                                retry_info = f" (retry {task_info['retry_attempt']})"
                            print(f"    - {task_id}: {task_status}{retry_info}")
                    
                    last_status = status
                
                # Check if workflow is complete
                workflow_status = status.get('status', '').lower()
                if workflow_status in ['completed', 'failed', 'error', 'cancelled']:
                    print("\n" + "=" * 60)
                    print(f"🏁 Workflow finished with status: {workflow_status.upper()}")
                    
                    # Final summary
                    if 'task_summary' in status:
                        print(f"📊 Final Task Summary: {status['task_summary']}")
                    
                    # Verify the expected behavior
                    if workflow_status == 'failed':
                        print("\n✅ TEST PASSED: Workflow correctly marked as FAILED when tasks fail!")
                    else:
                        print(f"\n❌ TEST FAILED: Expected workflow status FAILED, got {workflow_status.upper()}")
                    
                    return
            
            await asyncio.sleep(1)
        
        print("\n⚠️ Timeout: Workflow didn't complete within 60 seconds")
        print("Final status:", last_status)

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Workflow Status with Failed Tasks")
    print("=" * 60)
    asyncio.run(test_workflow_failure())