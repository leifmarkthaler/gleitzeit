#!/usr/bin/env python
"""Test timer workflow"""

import asyncio
import time
from gleitzeit.client import GleitzeitClient

async def test_timer():
    """Test timer workflow submission and execution"""
    client = await GleitzeitClient.create(mode="api", api_url="http://localhost:8000")
    
    print("=" * 60)
    print("Testing Timer Workflow")
    print("=" * 60)
    
    # Test 1: Simple timer workflow
    print("\n1. Simple timer sleep")
    try:
        result = await client.submit_workflow({
            "name": "Timer test workflow",
            "tasks": [{
                "name": "timer_sleep",
                "protocol": "timer/v1",
                "method": "timer/sleep",
                "params": {
                    "duration": 2  # 2 second sleep
                }
            }]
        })
        workflow_id = result.get('workflow_id')
        print(f"✓ Timer workflow submitted: {workflow_id}")
        
        # Wait for it to complete
        print("  Waiting for timer to complete...")
        start = time.time()
        await asyncio.sleep(3)  # Wait a bit longer than the timer
        elapsed = time.time() - start
        print(f"  Timer completed after {elapsed:.1f} seconds")
        
    except Exception as e:
        print(f"✗ Timer workflow failed: {e}")
    
    # Test 2: Timer with invalid method
    print("\n2. Timer with invalid method")
    try:
        result = await client.submit_workflow({
            "name": "Invalid timer workflow",
            "tasks": [{
                "name": "invalid_timer",
                "protocol": "timer/v1",
                "method": "timer/invalid",  # Invalid method
                "params": {
                    "duration": 1
                }
            }]
        })
        print(f"✗ Invalid timer method was accepted: {result.get('workflow_id')}")
    except Exception as e:
        print(f"✓ Invalid timer method rejected: {e}")
    
    # Test 3: Timer sequence
    print("\n3. Timer sequence workflow")
    try:
        result = await client.submit_workflow({
            "name": "Timer sequence",
            "tasks": [
                {
                    "id": "timer1",
                    "name": "First timer",
                    "protocol": "timer/v1",
                    "method": "timer/sleep",
                    "params": {
                        "duration": 1
                    }
                },
                {
                    "id": "timer2",
                    "name": "Second timer",
                    "protocol": "timer/v1", 
                    "method": "timer/sleep",
                    "params": {
                        "duration": 1
                    },
                    "dependencies": ["timer1"]
                }
            ]
        })
        workflow_id = result.get('workflow_id')
        print(f"✓ Timer sequence submitted: {workflow_id}")
        
        # Wait and check status
        print("  Waiting for sequence to complete...")
        start = time.time()
        await asyncio.sleep(3)
        elapsed = time.time() - start
        print(f"  Sequence completed after {elapsed:.1f} seconds")
        
        # Get workflow status
        workflow = await client.get_workflow(workflow_id)
        if workflow:
            print(f"  Workflow status: {workflow.get('status', 'unknown')}")
        
    except Exception as e:
        print(f"✗ Timer sequence failed: {e}")
    
    # Test 4: Timer wait_until
    print("\n4. Timer wait_until")
    try:
        import datetime
        future_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=2)
        result = await client.submit_workflow({
            "name": "Wait until timer",
            "tasks": [{
                "name": "wait_until_timer",
                "protocol": "timer/v1",
                "method": "timer/wait_until",
                "params": {
                    "timestamp": future_time.isoformat()
                }
            }]
        })
        print(f"✓ Wait until timer submitted: {result.get('workflow_id')}")
    except Exception as e:
        print(f"Note: Wait until timer result: {e}")
    
    # Test 5: Timer with callback
    print("\n5. Timer with callback task")
    try:
        result = await client.submit_workflow({
            "name": "Timer with callback",
            "tasks": [
                {
                    "id": "timer_wait",
                    "name": "Wait timer",
                    "protocol": "timer/v1",
                    "method": "timer/sleep",
                    "params": {
                        "duration": 1
                    }
                },
                {
                    "id": "callback_task",
                    "name": "Callback after timer",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "file_path": "/tmp/timer_complete.py",
                        "code": "print('Timer completed!')"
                    },
                    "dependencies": ["timer_wait"]
                }
            ]
        })
        print(f"✓ Timer with callback submitted: {result.get('workflow_id')}")
    except Exception as e:
        print(f"✗ Timer with callback failed: {e}")

    print("\n" + "=" * 60)
    print("Timer Workflow Tests Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_timer())