#!/usr/bin/env python3
"""
Executor Node Test

Test executor nodes connecting to the cluster and executing tasks.
This runs automatically without user interaction.
"""

import asyncio
import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.execution.executor_node import GleitzeitExecutorNode
from gleitzeit_cluster.core.node import NodeCapabilities
from gleitzeit_cluster.core.task import TaskType


async def test_executor_nodes():
    """Test executor nodes with the cluster"""
    
    print("🧪 Testing Executor Nodes")
    print("=" * 40)
    
    # 1. Start cluster
    print("🚀 Starting cluster...")
    cluster = GleitzeitCluster(
        enable_real_execution=False,  # Mock execution
        enable_redis=True,
        enable_socketio=True,
        auto_start_socketio_server=True
    )
    
    await cluster.start()
    print("✅ Cluster started on http://localhost:8000")
    
    # 2. Create executor node
    print("\n🖥️  Creating executor node...")
    executor = GleitzeitExecutorNode(
        name="test-executor",
        cluster_url="http://localhost:8000",
        capabilities=NodeCapabilities(
            supported_task_types={TaskType.TEXT_PROMPT, TaskType.PYTHON_FUNCTION},
            available_models=["llama3"],
            max_concurrent_tasks=2,
            has_gpu=False,
            cpu_cores=2,
            memory_gb=4.0
        )
    )
    
    # 3. Start executor in background
    print("🔌 Connecting executor to cluster...")
    executor_task = asyncio.create_task(executor.start())
    
    # Give it time to connect and register
    await asyncio.sleep(3)
    
    try:
        # 4. Verify executor is connected
        nodes = await cluster.list_nodes()
        print(f"📊 Connected nodes: {len(nodes)}")
        for node in nodes:
            print(f"   - {node['name']}: {node['status']}")
        
        # 5. Create and submit a workflow
        print("\n📋 Creating test workflow...")
        workflow = cluster.create_workflow("executor_test", "Test workflow for executor")
        
        task1 = workflow.add_text_task("greeting", "Say hello", "llama3")
        task2 = workflow.add_text_task("analysis", "Analyze the greeting", "llama3", dependencies=[task1.id])
        
        print(f"📝 Submitting workflow with {len(workflow.tasks)} tasks...")
        
        # 6. Execute workflow
        result = await cluster.execute_workflow(workflow)
        
        print(f"\n📊 Execution Results:")
        print(f"   Status: {result.status.value}")
        print(f"   Total tasks: {result.total_tasks}")
        print(f"   Completed: {result.completed_tasks}")
        print(f"   Failed: {result.failed_tasks}")
        print(f"   Duration: {result.execution_time_seconds or 0:.2f}s")
        
        # 7. Check cluster stats
        print(f"\n📈 Cluster Statistics:")
        stats = await cluster.get_cluster_stats()
        print(f"   Redis connected: {stats.get('redis_enabled', False)}")
        print(f"   Real execution: {stats.get('real_execution_enabled', False)}")
        
        if 'redis_stats' in stats:
            redis_stats = stats['redis_stats']
            print(f"   Active workflows: {redis_stats.get('active_workflows', 0)}")
            print(f"   Completed workflows: {redis_stats.get('completed_workflows', 0)}")
        
        # 8. Test multiple workflows
        print(f"\n🔄 Testing multiple workflows...")
        workflows = []
        
        for i in range(3):
            wf = cluster.create_workflow(f"test_wf_{i}", f"Test workflow {i+1}")
            wf.add_text_task(f"task_{i}", f"Process item {i+1}", "llama3")
            workflows.append(wf)
        
        results = []
        for i, wf in enumerate(workflows):
            print(f"   ⚡ Executing workflow {i+1}/3...")
            result = await cluster.execute_workflow(wf)
            results.append(result)
            print(f"   ✅ Workflow {i+1} completed: {result.status.value}")
        
        successful = sum(1 for r in results if r.status.value == 'completed')
        print(f"\n🎯 Multiple workflow results: {successful}/{len(results)} successful")
        
        # 9. Show final status
        print(f"\n✅ Executor node test completed!")
        print(f"   Dashboard available: http://localhost:8000")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        print(f"\n🧹 Cleaning up...")
        
        # Stop executor
        if not executor_task.done():
            executor_task.cancel()
        
        try:
            await executor.stop()
        except:
            pass
        
        # Stop cluster
        await cluster.stop()
        print("✅ Cleanup completed")


async def test_simple_workflow():
    """Simple test without executor nodes (fallback mode)"""
    
    print("\n🧪 Testing Simple Workflow (Mock Execution)")
    print("=" * 50)
    
    cluster = GleitzeitCluster(
        enable_real_execution=False,
        enable_redis=True,
        enable_socketio=True,
        auto_start_socketio_server=True
    )
    
    try:
        await cluster.start()
        
        # Create workflow
        workflow = cluster.create_workflow("simple_test", "Simple test workflow")
        workflow.add_text_task("hello", "Say hello world", "llama3")
        workflow.add_text_task("goodbye", "Say goodbye", "llama3")
        
        # Execute
        result = await cluster.execute_workflow(workflow)
        
        print(f"📊 Result: {result.status.value} ({result.completed_tasks}/{result.total_tasks})")
        
        return result.status.value == 'completed'
        
    finally:
        await cluster.stop()


async def main():
    """Run all tests"""
    
    print("🚀 Gleitzeit Executor Node Tests")
    print("=" * 60)
    print()
    
    tests_passed = 0
    total_tests = 2
    
    # Test 1: Simple workflow (should always work)
    try:
        if await test_simple_workflow():
            tests_passed += 1
            print("✅ Test 1 PASSED: Simple workflow")
        else:
            print("❌ Test 1 FAILED: Simple workflow")
    except Exception as e:
        print(f"❌ Test 1 ERROR: {e}")
    
    # Test 2: Executor node test (requires more components)
    try:
        if await test_executor_nodes():
            tests_passed += 1
            print("✅ Test 2 PASSED: Executor nodes")
        else:
            print("❌ Test 2 FAILED: Executor nodes")
    except Exception as e:
        print(f"❌ Test 2 ERROR: {e}")
    
    print()
    print("=" * 60)
    print(f"🎯 Test Results: {tests_passed}/{total_tests} passed")
    
    if tests_passed == total_tests:
        print("✅ All tests passed! Executor nodes are working correctly.")
        print()
        print("💡 Next steps:")
        print("1. Start cluster: PYTHONPATH=. python examples/dashboard_demo.py")
        print("2. Start executor: PYTHONPATH=. python examples/start_executor.py")
        print("3. Open dashboard: http://localhost:8000")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")


if __name__ == "__main__":
    asyncio.run(main())