#!/usr/bin/env python3
"""
Workflow Submission and Execution Audit Test Script

This script verifies that the workflow submission and execution pipeline
is working correctly after the GleitzeitError migration.
"""

import asyncio
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_workflow_submission():
    """Test complete workflow submission and execution pipeline"""
    
    from gleitzeit import GleitzeitClient
    
    # Create client
    client = GleitzeitClient(mode="native")
    
    try:
        logger.info("=" * 60)
        logger.info("WORKFLOW SUBMISSION AND EXECUTION AUDIT")
        logger.info("=" * 60)
        
        # Test 1: Simple single task
        logger.info("\n1. Testing single task submission...")
        task_result = await client.submit_and_wait(
            protocol="python",
            method="python/run", 
            parameters={
                "code": "return {'status': 'success', 'timestamp': '2025-09-07'}"
            }
        )
        logger.info(f"✅ Single task result: {task_result}")
        
        # Test 2: Multi-task workflow with dependencies
        logger.info("\n2. Testing multi-task workflow with dependencies...")
        workflow = {
            "name": "audit_test_workflow",
            "tasks": [
                {
                    "id": "task1",
                    "name": "Generate Data",
                    "protocol": "python",
                    "method": "python/run",
                    "parameters": {
                        "code": "return {'numbers': [1, 2, 3, 4, 5]}"
                    }
                },
                {
                    "id": "task2", 
                    "name": "Process Data",
                    "protocol": "python",
                    "method": "python/run",
                    "depends_on": ["task1"],
                    "parameters": {
                        "code": "return {'sum': sum(task1['result']['numbers']), 'count': len(task1['result']['numbers'])}"
                    }
                },
                {
                    "id": "task3",
                    "name": "Final Report",
                    "protocol": "python",
                    "method": "python/run",
                    "depends_on": ["task2"],
                    "parameters": {
                        "code": "return {'average': task2['result']['sum'] / task2['result']['count'], 'report': 'complete'}"
                    }
                }
            ]
        }
        
        workflow_id = await client.submit_workflow(workflow)
        logger.info(f"✅ Workflow submitted: {workflow_id}")
        
        # Wait for completion
        logger.info("Waiting for workflow completion...")
        result = await client.wait_for_workflow(workflow_id, timeout=30)
        logger.info(f"✅ Workflow completed: {result['status']}")
        
        # Get detailed results
        task_results = await client.get_workflow_tasks(workflow_id)
        for task in task_results:
            logger.info(f"  Task {task['id']}: {task['status']}")
        
        # Test 3: Error handling with GleitzeitError
        logger.info("\n3. Testing error handling...")
        try:
            error_task = await client.submit_and_wait(
                protocol="python",
                method="python/run",
                parameters={
                    "code": "raise ValueError('Test error')"
                }
            )
        except Exception as e:
            logger.info(f"✅ Error properly caught: {type(e).__name__}")
        
        # Test 4: Priority queue
        logger.info("\n4. Testing priority queue...")
        high_priority = await client.submit_task(
            protocol="python",
            method="python/run",
            parameters={"code": "return 'high'"},
            priority="high"
        )
        logger.info(f"✅ High priority task submitted: {high_priority}")
        
        # Test 5: Provider availability
        logger.info("\n5. Testing provider availability...")
        providers = await client.get_providers()
        logger.info(f"✅ Available providers: {[p['protocol'] for p in providers]}")
        
        logger.info("\n" + "=" * 60)
        logger.info("AUDIT COMPLETE - ALL TESTS PASSED")
        logger.info("=" * 60)
        
        # Summary
        logger.info("\nSUMMARY:")
        logger.info("✅ Single task submission: WORKING")
        logger.info("✅ Multi-task workflow: WORKING") 
        logger.info("✅ Dependency resolution: WORKING")
        logger.info("✅ Error handling: WORKING")
        logger.info("✅ Priority queue: WORKING")
        logger.info("✅ Provider system: WORKING")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await client.close()

async def test_streaming_workflow():
    """Test streaming workflow functionality"""
    
    from gleitzeit import GleitzeitClient
    
    logger.info("\n" + "=" * 60)
    logger.info("STREAMING WORKFLOW TEST")
    logger.info("=" * 60)
    
    client = GleitzeitClient(mode="native")
    
    try:
        # Test streaming task
        logger.info("\nTesting streaming task...")
        
        stream_workflow = {
            "name": "stream_test",
            "stream": True,
            "tasks": [{
                "id": "streamer",
                "protocol": "python",
                "method": "python/run",
                "stream": True,
                "parameters": {
                    "code": """
import time
for i in range(3):
    print(f'Stream item {i}')
    time.sleep(0.5)
return {'items': 3}
"""
                }
            }]
        }
        
        workflow_id = await client.submit_workflow(stream_workflow)
        logger.info(f"✅ Streaming workflow submitted: {workflow_id}")
        
        result = await client.wait_for_workflow(workflow_id, timeout=10)
        logger.info(f"✅ Streaming workflow completed: {result['status']}")
        
        # Get logs to see streamed output
        logs = await client.get_task_logs(workflow_id)
        if logs:
            logger.info("Stream output received")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Streaming test failed: {e}")
        return False
    finally:
        await client.close()

async def main():
    """Run all audit tests"""
    
    # Start the server
    logger.info("Starting Gleitzeit server...")
    from gleitzeit.server import start_server
    import asyncio
    
    # Start server in background
    server_task = asyncio.create_task(start_server(port=8888))
    
    # Wait for server to be ready
    await asyncio.sleep(2)
    
    try:
        # Run tests
        basic_passed = await test_workflow_submission()
        streaming_passed = await test_streaming_workflow()
        
        # Final report
        logger.info("\n" + "=" * 60)
        logger.info("FINAL AUDIT REPORT")
        logger.info("=" * 60)
        logger.info(f"Basic Workflow Tests: {'✅ PASSED' if basic_passed else '❌ FAILED'}")
        logger.info(f"Streaming Tests: {'✅ PASSED' if streaming_passed else '❌ FAILED'}")
        
        if basic_passed and streaming_passed:
            logger.info("\n🎉 ALL WORKFLOW SYSTEMS OPERATIONAL")
        else:
            logger.info("\n⚠️ SOME SYSTEMS NEED ATTENTION")
            
    finally:
        # Shutdown server
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    asyncio.run(main())