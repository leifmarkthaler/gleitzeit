#!/usr/bin/env python3
"""
Full Cluster Demo with Executor Nodes

This demo shows the complete Gleitzeit system:
1. Starts the cluster with Socket.IO server  
2. Starts executor nodes
3. Submits workflows
4. Shows real-time execution
5. Web dashboard monitoring

Usage:
    python examples/full_cluster_demo.py
    
Then open http://localhost:8000 to see the dashboard
"""

import asyncio
import sys
import time
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.execution.executor_node import GleitzeitExecutorNode
from gleitzeit_cluster.core.node import NodeCapabilities
from gleitzeit_cluster.core.task import TaskType


async def start_executor_nodes():
    """Start multiple executor nodes"""
    
    print("🖥️  Starting executor nodes...")
    
    # Node 1: General purpose
    executor1 = GleitzeitExecutorNode(
        name="worker-1",
        cluster_url="http://localhost:8000",
        capabilities=NodeCapabilities(
            supported_task_types={TaskType.TEXT_PROMPT, TaskType.PYTHON_FUNCTION},
            available_models=["llama3", "codellama"],
            max_concurrent_tasks=2,
            has_gpu=False,
            cpu_cores=4,
            memory_gb=8.0
        ),
        max_concurrent_tasks=2
    )
    
    # Node 2: GPU-enabled
    executor2 = GleitzeitExecutorNode(
        name="gpu-worker-1", 
        cluster_url="http://localhost:8000",
        capabilities=NodeCapabilities(
            supported_task_types={TaskType.TEXT_PROMPT, TaskType.VISION_TASK},
            available_models=["llama3", "llava"],
            max_concurrent_tasks=1,
            has_gpu=True,
            cpu_cores=8,
            memory_gb=16.0
        ),
        max_concurrent_tasks=1
    )
    
    # Start both nodes
    print("   Starting worker-1 (CPU)...")
    task1 = asyncio.create_task(executor1.start())
    
    print("   Starting gpu-worker-1 (GPU)...")  
    task2 = asyncio.create_task(executor2.start())
    
    # Let them connect
    await asyncio.sleep(3)
    
    return task1, task2, executor1, executor2


async def submit_demo_workflows(cluster: GleitzeitCluster):
    """Submit demo workflows to show execution"""
    
    print("\n📋 Submitting demo workflows...")
    
    workflows_submitted = []
    
    # Workflow 1: Simple text analysis
    print("   📝 Creating text analysis workflow...")
    workflow1 = cluster.create_workflow("text_analysis", "Analyze document content")
    
    task1 = workflow1.add_text_task("extract", "Extract key points from research paper", "llama3")
    task2 = workflow1.add_text_task("summarize", "Create executive summary", "llama3", dependencies=[task1.id])
    task3 = workflow1.add_text_task("keywords", "Extract keywords", "llama3", dependencies=[task1.id])
    
    workflows_submitted.append(workflow1)
    
    # Workflow 2: Vision + text
    print("   🖼️  Creating vision analysis workflow...")
    workflow2 = cluster.create_workflow("vision_analysis", "Analyze charts and documents")
    
    task4 = workflow2.add_vision_task("describe", "Describe the chart content", "llava")
    task5 = workflow2.add_text_task("insights", "Generate insights from description", "llama3", dependencies=[task4.id])
    
    workflows_submitted.append(workflow2)
    
    # Workflow 3: Complex pipeline
    print("   🔄 Creating complex workflow...")
    workflow3 = cluster.create_workflow("data_pipeline", "Complete data processing pipeline") 
    
    task6 = workflow3.add_text_task("query", "Process data query", "llama3")
    task7 = workflow3.add_text_task("analyze", "Analyze results", "llama3", dependencies=[task6.id])
    task8 = workflow3.add_text_task("report", "Generate report", "llama3", dependencies=[task7.id])
    
    workflows_submitted.append(workflow3)
    
    return workflows_submitted


async def monitor_execution(cluster: GleitzeitCluster, workflows: list):
    """Monitor workflow execution"""
    
    print("\n⚡ Executing workflows...")
    print("   Watch progress in dashboard: http://localhost:8000")
    print()
    
    results = []
    
    for i, workflow in enumerate(workflows, 1):
        print(f"🚀 Executing workflow {i}/{len(workflows)}: {workflow.name}")
        
        try:
            result = await cluster.execute_workflow(workflow)
            
            print(f"✅ Workflow {i} completed: {result.status.value}")
            print(f"   Completed: {result.completed_tasks}/{result.total_tasks}")
            print(f"   Duration: {result.execution_time:.2f}s")
            
            results.append(result)
            
        except Exception as e:
            print(f"❌ Workflow {i} failed: {e}")
        
        print()
    
    return results


async def show_cluster_stats(cluster: GleitzeitCluster):
    """Show final cluster statistics"""
    
    print("📊 Final Cluster Statistics")
    print("=" * 40)
    
    stats = await cluster.get_cluster_stats()
    
    print(f"Cluster Status: {'✅ Running' if stats['is_started'] else '❌ Stopped'}")
    print(f"Real Execution: {'✅ Enabled' if stats['real_execution_enabled'] else '❌ Mock'}")
    print(f"Redis: {'✅ Connected' if stats.get('redis_enabled') else '❌ Disabled'}")
    
    if 'redis_stats' in stats:
        redis_stats = stats['redis_stats']
        print(f"\nRedis Statistics:")
        print(f"   Active workflows: {redis_stats.get('active_workflows', 0)}")
        print(f"   Completed workflows: {redis_stats.get('completed_workflows', 0)}")
        print(f"   Active nodes: {redis_stats.get('active_nodes', 0)}")
    
    # List nodes
    nodes = await cluster.list_nodes()
    if nodes:
        print(f"\nExecutor Nodes ({len(nodes)}):")
        for node in nodes:
            print(f"   {node['name']}: {node['status']}")
    
    # List workflows
    workflows = await cluster.list_workflows()
    if workflows:
        print(f"\nRecent Workflows ({len(workflows)}):")
        for workflow in workflows[-5:]:  # Last 5
            print(f"   {workflow['workflow_id'][:8]}: {workflow['status']}")


async def main():
    """Main demo orchestration"""
    
    print("🚀 Gleitzeit Full Cluster Demo")
    print("=" * 50)
    print()
    print("This demo will:")
    print("1. ✅ Start cluster with Socket.IO server")
    print("2. 🖥️  Start multiple executor nodes")  
    print("3. 📋 Submit various workflows")
    print("4. ⚡ Execute tasks on real executor nodes")
    print("5. 📊 Show real-time monitoring")
    print()
    print("🌐 Web dashboard will be available at: http://localhost:8000")
    print()
    
    input("Press Enter to start the demo...")
    print()
    
    # 1. Start cluster
    print("🚀 Starting Gleitzeit cluster...")
    cluster = GleitzeitCluster(
        enable_real_execution=False,  # Use mock execution for demo
        enable_redis=True,
        enable_socketio=True,
        auto_start_socketio_server=True
    )
    
    await cluster.start()
    print("✅ Cluster started with Socket.IO server")
    print("   Dashboard: http://localhost:8000")
    
    executor_tasks = None
    executors = []
    
    try:
        # 2. Start executor nodes  
        task1, task2, executor1, executor2 = await start_executor_nodes()
        executor_tasks = [task1, task2]
        executors = [executor1, executor2]
        
        print("✅ Executor nodes started and registered")
        
        # Wait for registration
        await asyncio.sleep(2)
        
        # 3. Submit workflows
        workflows = await submit_demo_workflows(cluster)
        
        # 4. Execute and monitor
        results = await monitor_execution(cluster, workflows)
        
        # 5. Show final stats
        await show_cluster_stats(cluster)
        
        print("\n🎯 Demo Results:")
        print(f"   Workflows executed: {len(results)}")
        print(f"   Successful: {sum(1 for r in results if r.status.value == 'completed')}")
        print(f"   Failed: {sum(1 for r in results if r.status.value != 'completed')}")
        
        print("\n💡 Keep the demo running to see the dashboard:")
        print("   Open http://localhost:8000")
        print("   The executor nodes will keep running")
        print("   Press Ctrl+C to stop everything")
        print()
        
        # Keep running for dashboard demo
        try:
            while True:
                await asyncio.sleep(10)
                
                # Show some activity
                print("💓 System running... (press Ctrl+C to stop)")
                
        except KeyboardInterrupt:
            print("\n🛑 Demo stopped by user")
    
    except Exception as e:
        print(f"💥 Demo failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        
        # Stop executors
        for executor in executors:
            try:
                await executor.stop()
            except Exception as e:
                print(f"⚠️  Error stopping executor: {e}")
        
        # Cancel executor tasks
        if executor_tasks:
            for task in executor_tasks:
                if not task.done():
                    task.cancel()
        
        # Stop cluster
        await cluster.stop()
        print("✅ Demo cleanup completed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Demo interrupted")
    except Exception as e:
        print(f"💥 Demo crashed: {e}")
        import traceback
        traceback.print_exc()