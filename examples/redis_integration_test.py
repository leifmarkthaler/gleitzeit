#!/usr/bin/env python3
"""
Redis Integration Test for Gleitzeit Cluster

This example demonstrates the Redis integration capabilities including:
- Persistent workflow storage
- Distributed task queues
- Result and error persistence
- Cluster statistics
- Workflow recovery after restart

Requirements:
- Redis server running on localhost:6379
- Ollama server (optional) for real task execution
"""

import asyncio
import sys
import time
from pathlib import Path

# Add package to path for import
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.storage.redis_client import RedisClient


async def test_redis_connection():
    """Test basic Redis connectivity"""
    print("🧪 Test 1: Redis Connection")
    print("=" * 50)
    
    redis_client = RedisClient(redis_url="redis://localhost:6379")
    
    try:
        await redis_client.connect()
        
        # Check health
        health = await redis_client.health_check()
        print(f"✅ Redis connected successfully")
        print(f"   Version: {health.get('redis_version')}")
        print(f"   Ping: {health.get('ping_ms')}ms")
        print(f"   Memory: {health.get('used_memory')}")
        
        await redis_client.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False


async def test_workflow_persistence():
    """Test workflow storage and retrieval from Redis"""
    print("\n🧪 Test 2: Workflow Persistence")
    print("=" * 50)
    
    cluster = GleitzeitCluster(
        enable_real_execution=False,  # Use mock execution for testing
        enable_redis=True
    )
    
    try:
        await cluster.start()
        
        # Create and submit workflow
        workflow = cluster.create_workflow("test_persistence", "Test Redis persistence")
        task1 = workflow.add_text_task("analyze", "Test prompt 1")
        task2 = workflow.add_text_task("summarize", "Test prompt 2", dependencies=[task1.id])
        
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"📋 Submitted workflow: {workflow_id}")
        
        # Check workflow status from Redis
        status = await cluster.get_workflow_status(workflow_id)
        print(f"📊 Workflow status from Redis:")
        print(f"   Name: {status['name']}")
        print(f"   Status: {status['status']}")
        print(f"   Total tasks: {status['total_tasks']}")
        
        # Execute workflow
        result = await cluster.execute_workflow(workflow)
        print(f"✅ Workflow executed: {result.status.value}")
        
        # Check final status from Redis
        final_status = await cluster.get_workflow_status(workflow_id)
        print(f"📊 Final status from Redis:")
        print(f"   Completed tasks: {final_status['completed_tasks']}")
        print(f"   Failed tasks: {final_status['failed_tasks']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
        
    finally:
        await cluster.stop()


async def test_workflow_recovery():
    """Test workflow recovery after cluster restart"""
    print("\n🧪 Test 3: Workflow Recovery")
    print("=" * 50)
    
    workflow_id = None
    
    # Phase 1: Create and submit workflow
    print("📝 Phase 1: Submit workflow")
    cluster1 = GleitzeitCluster(enable_real_execution=False, enable_redis=True)
    
    try:
        await cluster1.start()
        
        workflow = cluster1.create_workflow("test_recovery", "Test workflow recovery")
        workflow.add_text_task("task1", "First task")
        workflow.add_text_task("task2", "Second task")
        
        workflow_id = await cluster1.submit_workflow(workflow)
        print(f"   Submitted workflow: {workflow_id}")
        
        await cluster1.stop()
        print("   Cluster stopped")
        
    except Exception as e:
        print(f"❌ Phase 1 failed: {e}")
        await cluster1.stop()
        return False
    
    # Simulate restart delay
    await asyncio.sleep(1)
    
    # Phase 2: Recover workflow from Redis
    print("\n📝 Phase 2: Recover workflow after restart")
    cluster2 = GleitzeitCluster(enable_real_execution=False, enable_redis=True)
    
    try:
        await cluster2.start()
        
        # Try to get workflow status (should load from Redis)
        status = await cluster2.get_workflow_status(workflow_id)
        
        if status:
            print(f"✅ Workflow recovered from Redis!")
            print(f"   Name: {status['name']}")
            print(f"   Status: {status['status']}")
            print(f"   Tasks: {status['total_tasks']}")
            return True
        else:
            print(f"❌ Workflow not found in Redis")
            return False
            
    except Exception as e:
        print(f"❌ Phase 2 failed: {e}")
        return False
        
    finally:
        await cluster2.stop()


async def test_cluster_statistics():
    """Test cluster statistics with Redis"""
    print("\n🧪 Test 4: Cluster Statistics")
    print("=" * 50)
    
    cluster = GleitzeitCluster(enable_real_execution=False, enable_redis=True)
    
    try:
        await cluster.start()
        
        # Create some workflows
        for i in range(3):
            workflow = cluster.create_workflow(f"stats_test_{i}", f"Test workflow {i}")
            workflow.add_text_task(f"task_{i}", f"Test task {i}")
            await cluster.submit_workflow(workflow)
        
        # Get cluster stats
        stats = await cluster.get_cluster_stats()
        
        print(f"📊 Cluster Statistics:")
        print(f"   Started: {stats['is_started']}")
        print(f"   Redis enabled: {stats['redis_enabled']}")
        
        if "redis_stats" in stats:
            redis_stats = stats["redis_stats"]
            print(f"\n📊 Redis Statistics:")
            print(f"   Active workflows: {redis_stats.get('active_workflows', 0)}")
            print(f"   Queued tasks: {redis_stats.get('queued_tasks', 0)}")
            print(f"   Processing tasks: {redis_stats.get('processing_tasks', 0)}")
        
        if "redis_health" in stats:
            redis_health = stats["redis_health"]
            print(f"\n💚 Redis Health:")
            print(f"   Connected: {redis_health.get('connected')}")
            print(f"   Ping: {redis_health.get('ping_ms')}ms")
            print(f"   Clients: {redis_health.get('connected_clients')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
        
    finally:
        await cluster.stop()


async def test_error_handling_with_redis():
    """Test error handling and persistence in Redis"""
    print("\n🧪 Test 5: Error Handling with Redis")
    print("=" * 50)
    
    cluster = GleitzeitCluster(
        enable_real_execution=True,  # Use real execution to test errors
        enable_redis=True
    )
    
    try:
        await cluster.start()
        
        # Create workflow with intentional error
        workflow = cluster.create_workflow("error_test", "Test error handling")
        
        # This will fail if model doesn't exist
        task1 = workflow.add_text_task(
            "fail_task",
            "This will fail",
            model="nonexistent_model_xyz"
        )
        
        # This should still work
        task2 = workflow.add_text_task(
            "success_task",
            "This should work",
            model="llama3"
        )
        
        # Execute workflow
        result = await cluster.execute_workflow(workflow)
        
        print(f"📊 Workflow Result:")
        print(f"   Status: {result.status.value}")
        print(f"   Failed tasks: {result.failed_tasks}")
        
        # Check errors in Redis
        workflow_status = await cluster.get_workflow_status(workflow.id)
        if workflow_status and "errors" in workflow_status:
            print(f"\n⚠️  Errors from Redis:")
            for task_id, error in workflow_status["errors"].items():
                print(f"   {task_id[:8]}: {error[:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
        
    finally:
        await cluster.stop()


async def test_cleanup():
    """Test Redis cleanup operations"""
    print("\n🧪 Test 6: Redis Cleanup")
    print("=" * 50)
    
    redis_client = RedisClient(redis_url="redis://localhost:6379")
    
    try:
        await redis_client.connect()
        
        # Get initial stats
        initial_stats = await redis_client.get_cluster_stats()
        print(f"📊 Initial state:")
        print(f"   Active workflows: {initial_stats.get('active_workflows', 0)}")
        print(f"   Completed workflows: {initial_stats.get('completed_workflows', 0)}")
        
        # Clean up expired workflows
        cleaned = await redis_client.cleanup_expired_workflows()
        print(f"\n🧹 Cleaned up {cleaned} expired workflows")
        
        # Get final stats
        final_stats = await redis_client.get_cluster_stats()
        print(f"\n📊 Final state:")
        print(f"   Active workflows: {final_stats.get('active_workflows', 0)}")
        print(f"   Completed workflows: {final_stats.get('completed_workflows', 0)}")
        
        await redis_client.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


async def main():
    """Run all Redis integration tests"""
    print("🚀 Gleitzeit Cluster - Redis Integration Tests")
    print("=" * 60)
    print()
    
    tests = [
        ("Redis Connection", test_redis_connection),
        ("Workflow Persistence", test_workflow_persistence),
        ("Workflow Recovery", test_workflow_recovery),
        ("Cluster Statistics", test_cluster_statistics),
        ("Error Handling", test_error_handling_with_redis),
        ("Redis Cleanup", test_cleanup)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            print(f"\n🔄 Running: {test_name}")
            result = await test_func()
            results.append((test_name, result))
            
            if result:
                print(f"✅ {test_name} passed!")
            else:
                print(f"❌ {test_name} failed!")
                
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 30)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {test_name}")
    
    print(f"\n✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    
    if passed == total:
        print("\n🎉 All Redis integration tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} tests failed.")
        print("\nTroubleshooting:")
        print("1. Ensure Redis is running: redis-server")
        print("2. Check Redis connection: redis-cli ping")
        print("3. Verify Redis URL: redis://localhost:6379")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)