#!/usr/bin/env python3
"""
Real-Time Monitoring Demo for Gleitzeit

Demonstrates the Socket.IO-based real-time monitoring system:
1. Live executor health metrics
2. Task execution streaming
3. Workflow progress monitoring 
4. System performance tracking
"""

import asyncio
import sys
from pathlib import Path

# Add the parent directory to the path so we can import gleitzeit_cluster
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster, Workflow


async def demo_monitoring():
    """Demonstrate real-time monitoring capabilities"""
    
    print("📡 Real-Time Monitoring Demo")
    print("=" * 50)
    
    # Create cluster with full monitoring enabled
    cluster = GleitzeitCluster(
        enable_redis=True,
        enable_real_execution=True,
        enable_socketio=True,
        auto_start_socketio_server=True,
        socketio_host="0.0.0.0",
        socketio_port=8000,
        auto_start_services=True,
        auto_recovery=True
    )
    
    try:
        print("\\n🚀 Starting cluster with monitoring...")
        await cluster.start()
        
        print("\\n📊 Monitoring Features Available:")
        print("   ✅ Socket.IO Server: http://localhost:8000")
        print("   ✅ Real-time metrics broadcasting every 2 seconds")
        print("   ✅ Live executor health monitoring")
        print("   ✅ Task execution streaming")
        print("   ✅ Workflow progress tracking")
        print("   ✅ System performance metrics")
        print("   ✅ 30-minute historical data retention")
        
        print("\\n🔍 How to Monitor:")
        print("   1. Open new terminal:")
        print("      python gleitzeit_cluster/cli_monitor_live.py")
        print("   2. Or connect any Socket.IO client to ws://localhost:8000/cluster")
        print("   3. Subscribe to events: monitor:subscribe")
        
        # Create a complex workflow to demonstrate monitoring
        print("\\n📋 Creating demo workflow for monitoring...")
        
        workflow = cluster.create_workflow(
            name="Monitoring Demo Workflow",
            description="Multi-step workflow to showcase real-time monitoring"
        )
        
        # Task 1: Data generation
        task1 = workflow.add_python_task(
            name="Generate Data", 
            function_name="fibonacci",
            kwargs={"n": 15}
        )
        
        # Task 2: Process data (depends on Task 1)
        task2 = workflow.add_python_task(
            name="Analyze Data",
            function_name="analyze_numbers", 
            kwargs={"numbers": "{{Generate Data.result}}"},
            dependencies=["Generate Data"]
        )
        
        # Task 3: Text processing (parallel)
        task3 = workflow.add_python_task(
            name="Process Text",
            function_name="count_words",
            kwargs={"text": "Real-time monitoring with Socket.IO provides excellent visibility into distributed workflow execution"}
        )
        
        # Task 4: LLM analysis (depends on Task 2 and 3)
        task4 = workflow.add_text_task(
            name="AI Analysis",
            prompt="Analyze this data: {{Analyze Data.result}} and word count: {{Process Text.result}}. Provide insights.",
            model="llama3",
            dependencies=["Analyze Data", "Process Text"]
        )
        
        # Task 5: Final report
        task5 = workflow.add_text_task(
            name="Generate Report", 
            prompt="Create a comprehensive report based on: {{AI Analysis.result}}",
            model="llama3",
            dependencies=["AI Analysis"]
        )
        
        print(f"   ✅ Created workflow with {len(workflow.tasks)} tasks")
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"   📤 Submitted workflow: {workflow_id[:12]}...")
        
        print("\\n📡 Real-Time Events You Can Monitor:")
        print("   • workflow:started - Workflow begins execution")
        print("   • task:progress - Task execution progress updates") 
        print("   • task:completed - Individual task completions")
        print("   • task:failed - Task failures with error details")
        print("   • workflow:completed - Workflow completion")
        print("   • monitor:metrics_update - Live system metrics every 2s")
        print("   • node:heartbeat - Executor health updates every 30s")
        
        print("\\n📊 Available Metrics:")
        print("   • Cluster: connected clients, executor nodes, active workflows")
        print("   • Nodes: CPU/memory/GPU usage, active tasks, uptime")
        print("   • Queues: task queue depths by priority") 
        print("   • Tasks: completion rates, execution times, success rates")
        print("   • System: server resource utilization")
        
        print("\\n⏰ Keeping cluster running for 2 minutes to show monitoring...")
        print("   Start the monitoring client to see real-time updates!")
        
        # Keep running for 2 minutes to allow monitoring
        await asyncio.sleep(120)
        
        # Show final stats
        if cluster.redis_client:
            print("\\n📈 Final Statistics:")
            try:
                stats = await cluster.get_cluster_stats()
                print(f"   Workflows processed: {stats.get('workflows', 0)}")
                print(f"   Nodes registered: {stats.get('nodes', 0)}")
                
                redis_stats = stats.get('redis_stats', {})
                if redis_stats:
                    print(f"   Redis health: {redis_stats.get('status', 'unknown')}")
                    
            except Exception as e:
                print(f"   Stats unavailable: {e}")
        
        print("\\n✅ Monitoring demo completed!")
        print("\\n💡 Pro Tips:")
        print("   • Use multiple monitoring clients for different views")
        print("   • Subscribe to specific event types for focused monitoring")
        print("   • Historical metrics available for up to 30 minutes")
        print("   • Monitor node health to detect performance issues")
        print("   • Watch queue depths to identify bottlenecks")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\\n🛑 Shutting down cluster...")
        await cluster.stop()


if __name__ == "__main__":
    print("🚀 Make sure to run the monitoring client in another terminal:")
    print("   python gleitzeit_cluster/cli_monitor_live.py")
    print("\\nPress Enter to start demo...")
    input()
    
    asyncio.run(demo_monitoring())