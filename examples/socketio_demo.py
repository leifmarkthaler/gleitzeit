#!/usr/bin/env python3
"""
Socket.IO Integration Demo for Gleitzeit Cluster

This example demonstrates how Socket.IO integration works with the cluster,
showing both success and fallback scenarios.

Requirements:
- Redis server running on localhost:6379
- Optional: Socket.IO server running on localhost:8000

Usage:
    # Without Socket.IO server (shows fallback)
    python examples/socketio_demo.py
    
    # With Socket.IO server (shows real-time coordination)
    # Terminal 1: python examples/socketio_server_standalone.py
    # Terminal 2: python examples/socketio_demo.py
"""

import asyncio
import sys
from pathlib import Path

# Add package to path for import
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster


async def demo_with_socketio():
    """Demo with Socket.IO enabled (will fallback if server unavailable)"""
    print("🧪 Demo: Socket.IO Integration")
    print("=" * 50)
    
    cluster = GleitzeitCluster(
        enable_real_execution=False,  # Use mock execution for demo
        enable_redis=True,
        enable_socketio=True,  # Enable Socket.IO
        auto_start_socketio_server=True  # Automatically start Socket.IO server!
    )
    
    try:
        await cluster.start()
        
        # Show connection status
        socketio_status = "✅ Connected" if (
            cluster.socketio_client and cluster.socketio_client.is_connected
        ) else "❌ Not connected (fallback mode)"
        
        print(f"📊 Connection Status:")
        print(f"   Redis: {'✅ Connected' if cluster.redis_client else '❌ Disabled'}")
        print(f"   Socket.IO: {socketio_status}")
        print()
        
        # Create and submit workflow
        workflow = cluster.create_workflow("socketio_demo", "Demo real-time events")
        task1 = workflow.add_text_task("greeting", "Say hello", "llama3")
        task2 = workflow.add_text_task("summary", "Summarize the greeting", "llama3", dependencies=[task1.id])
        
        print(f"🔄 Submitting workflow with {len(workflow.tasks)} tasks...")
        
        # This will submit to both Redis and Socket.IO (if available)
        result = await cluster.execute_workflow(workflow)
        
        print(f"📊 Workflow Results:")
        print(f"   Status: {result.status.value}")
        print(f"   Completed: {result.completed_tasks}")
        print(f"   Failed: {result.failed_tasks}")
        
        if cluster.socketio_client and cluster.socketio_client.is_connected:
            print(f"\n💡 Socket.IO Features Available:")
            print(f"   ✅ Real-time workflow events")
            print(f"   ✅ Live task progress updates")
            print(f"   ✅ Node coordination")
            print(f"   ✅ Dashboard monitoring")
        else:
            print(f"\n💡 Socket.IO Server Not Running:")
            print(f"   ⚠️  Using fallback execution")
            print(f"   ⚠️  No real-time events")
            print(f"   💡 Start server: python examples/socketio_server_standalone.py")
        
        return True
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        return False
        
    finally:
        await cluster.stop()


async def demo_cluster_stats():
    """Demo cluster statistics with Socket.IO integration"""
    print("\n🧪 Demo: Cluster Statistics")
    print("=" * 50)
    
    cluster = GleitzeitCluster(
        enable_real_execution=False,
        enable_redis=True,
        enable_socketio=True
    )
    
    try:
        await cluster.start()
        
        # Get cluster stats
        stats = await cluster.get_cluster_stats()
        
        print(f"📊 Cluster Statistics:")
        print(f"   Started: {stats['is_started']}")
        print(f"   Real execution: {stats['real_execution_enabled']}")
        print(f"   Redis enabled: {stats['redis_enabled']}")
        
        if "redis_stats" in stats:
            redis_stats = stats["redis_stats"]
            print(f"\n📊 Redis Statistics:")
            print(f"   Active workflows: {redis_stats.get('active_workflows', 0)}")
            print(f"   Completed workflows: {redis_stats.get('completed_workflows', 0)}")
            print(f"   Active nodes: {redis_stats.get('active_nodes', 0)}")
        
        if "redis_health" in stats:
            redis_health = stats["redis_health"]
            print(f"\n💚 Redis Health:")
            print(f"   Connected: {redis_health.get('connected')}")
            print(f"   Ping: {redis_health.get('ping_ms')}ms")
        
        return True
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        return False
        
    finally:
        await cluster.stop()


async def main():
    """Run Socket.IO integration demos"""
    print("🚀 Gleitzeit Cluster - Socket.IO Integration Demo")
    print("=" * 60)
    print()
    
    demos = [
        demo_with_socketio,
        demo_cluster_stats
    ]
    
    for demo in demos:
        try:
            await demo()
        except Exception as e:
            print(f"💥 Demo crashed: {e}")
        
        print()  # Add spacing between demos
    
    print("=" * 60)
    print("✅ Socket.IO Integration Demo Complete!")
    print()
    print("💡 Next Steps:")
    print("1. Start Socket.IO server: python examples/socketio_server_standalone.py")
    print("2. Run integration tests: python examples/socketio_integration_test.py")
    print("3. Build a web dashboard for real-time monitoring")
    print("4. Deploy distributed executor nodes")


if __name__ == "__main__":
    asyncio.run(main())