#!/usr/bin/env python3
"""
Socket.IO Integration Test for Gleitzeit Cluster

This example demonstrates the Socket.IO real-time communication capabilities:
- Server and client coordination
- Real-time workflow events
- Live task progress updates
- Node registration and heartbeat
- Dashboard monitoring

Requirements:
- Redis server running on localhost:6379
- Socket.IO server running on localhost:8000

Usage:
    # Terminal 1: Start Socket.IO server
    python examples/socketio_server_standalone.py
    
    # Terminal 2: Run integration tests
    python examples/socketio_integration_test.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

# Add package to path for import
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.core.node import ExecutorNode, NodeCapabilities, NodeStatus
from gleitzeit_cluster.core.task import TaskType
from gleitzeit_cluster.communication.socketio_server import SocketIOServer
from gleitzeit_cluster.communication.socketio_client import (
    ExecutorSocketClient, DashboardSocketClient
)


async def test_server_startup():
    """Test Socket.IO server startup and health"""
    print("🧪 Test 1: Server Startup")
    print("=" * 50)
    
    server = SocketIOServer(port=8001)  # Use different port for test
    
    try:
        await server.start()
        
        # Check server stats
        stats = await server.get_server_stats()
        print(f"✅ Server started successfully")
        print(f"   Connected clients: {stats['connected_clients']}")
        print(f"   Executor nodes: {stats['executor_nodes']}")
        
        await server.stop()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


async def test_cluster_connection():
    """Test cluster connection to Socket.IO server"""
    print("\n🧪 Test 2: Cluster Connection")
    print("=" * 50)
    
    cluster = GleitzeitCluster(
        enable_real_execution=False,
        enable_redis=False,  # Disable Redis for this test
        enable_socketio=True
    )
    
    try:
        await cluster.start()
        
        if cluster.socketio_client and cluster.socketio_client.is_connected:
            print("✅ Cluster connected to Socket.IO successfully")
            print(f"   Client ID: {cluster.socketio_client.client_id}")
            
            await cluster.stop()
            return True
        else:
            print("❌ Socket.IO connection failed")
            await cluster.stop()
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


async def test_executor_node_coordination():
    """Test executor node registration and coordination"""
    print("\n🧪 Test 3: Executor Node Coordination")
    print("=" * 50)
    
    # Create mock executor node
    node = ExecutorNode(
        name="test-executor-1",
        host="localhost",
        capabilities=NodeCapabilities(
            supported_task_types={TaskType.TEXT_PROMPT},
            available_models=["llama3"],
            has_gpu=False,
            cpu_cores=4,
            memory_gb=8
        )
    )
    
    # Mock task handler
    async def mock_task_handler(task_data):
        await asyncio.sleep(1)  # Simulate work
        return {"result": f"Mock result for task {task_data.get('task_id')}"}
    
    executor_client = ExecutorSocketClient(
        node=node,
        task_handler=mock_task_handler,
        server_url="http://localhost:8000"
    )
    
    try:
        # Connect executor
        connected = await executor_client.connect()
        if not connected:
            print("❌ Executor failed to connect")
            return False
        
        # Register node
        await executor_client.register_node()
        print(f"✅ Executor node registered: {node.name}")
        
        # Wait a moment for registration to propagate
        await asyncio.sleep(2)
        
        await executor_client.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


async def test_workflow_real_time_events():
    """Test real-time workflow events via Socket.IO"""
    print("\n🧪 Test 4: Real-time Workflow Events")
    print("=" * 50)
    
    # Track received events
    events_received = []
    
    # Create dashboard client to monitor events
    dashboard = DashboardSocketClient(server_url="http://localhost:8000")
    
    # Override event handlers to track events
    original_workflow_handler = dashboard._handle_workflow_update
    original_node_handler = dashboard._handle_node_update
    
    async def track_workflow_events(data):
        events_received.append(('workflow', data))
        print(f"📡 Workflow event: {data.get('workflow_id', 'unknown')} - {list(data.keys())}")
        await original_workflow_handler(data)
    
    async def track_node_events(data):
        events_received.append(('node', data))
        print(f"📡 Node event: {data.get('node_id', 'unknown')} - {list(data.keys())}")
        await original_node_handler(data)
    
    dashboard._handle_workflow_update = track_workflow_events
    dashboard._handle_node_update = track_node_events
    
    try:
        # Connect dashboard
        connected = await dashboard.connect()
        if not connected:
            print("❌ Dashboard failed to connect")
            return False
        
        print("📊 Dashboard connected, monitoring events...")
        
        # Create cluster and submit workflow
        cluster = GleitzeitCluster(
            enable_real_execution=False,
            enable_redis=False,
            enable_socketio=True
        )
        
        await cluster.start()
        
        # Create and submit workflow
        workflow = cluster.create_workflow("socketio_test", "Test real-time events")
        workflow.add_text_task("test_task", "Test prompt", "llama3")
        
        await cluster.submit_workflow(workflow)
        print(f"📋 Workflow submitted: {workflow.id}")
        
        # Wait for events
        await asyncio.sleep(3)
        
        # Check if events were received
        if events_received:
            print(f"✅ Received {len(events_received)} real-time events")
            for event_type, data in events_received:
                print(f"   - {event_type}: {data.get('workflow_id') or data.get('node_id', 'unknown')}")
        else:
            print("⚠️  No events received")
        
        await cluster.stop()
        await dashboard.disconnect()
        
        return len(events_received) > 0
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


async def test_end_to_end_coordination():
    """Test complete end-to-end Socket.IO coordination"""
    print("\n🧪 Test 5: End-to-End Coordination")
    print("=" * 50)
    
    results = {}
    
    # Create executor node
    node = ExecutorNode(
        name="e2e-executor",
        host="localhost",
        capabilities=NodeCapabilities(
            supported_task_types={TaskType.TEXT_PROMPT},
            available_models=["llama3"],
            has_gpu=False
        )
    )
    
    async def task_handler(task_data):
        task_id = task_data.get('task_id')
        print(f"🔄 Executing task: {task_id}")
        await asyncio.sleep(0.5)  # Simulate work
        result = f"Completed task {task_id}"
        print(f"✅ Task completed: {task_id}")
        return result
    
    executor = ExecutorSocketClient(
        node=node,
        task_handler=task_handler,
        server_url="http://localhost:8000"
    )
    
    dashboard = DashboardSocketClient(server_url="http://localhost:8000")
    
    # Track workflow completion
    workflow_completed = asyncio.Event()
    
    async def on_workflow_complete(data):
        if data.get('status') == 'completed':
            results['workflow_result'] = data
            workflow_completed.set()
    
    dashboard.on('workflow:completed', on_workflow_complete)
    
    try:
        # Connect all components
        await executor.connect()
        await executor.register_node()
        
        await dashboard.connect()
        
        cluster = GleitzeitCluster(
            enable_real_execution=False,
            enable_redis=False,
            enable_socketio=True
        )
        await cluster.start()
        
        # Submit workflow
        workflow = cluster.create_workflow("e2e_test", "End-to-end test")
        task1 = workflow.add_text_task("task1", "Test task 1")
        task2 = workflow.add_text_task("task2", "Test task 2", dependencies=[task1.id])
        
        await cluster.submit_workflow(workflow)
        print(f"📋 E2E workflow submitted with {len(workflow.tasks)} tasks")
        
        # Wait for workflow completion or timeout
        try:
            await asyncio.wait_for(workflow_completed.wait(), timeout=10.0)
            print("✅ E2E workflow completed successfully!")
            return True
        except asyncio.TimeoutError:
            print("⏱️  E2E test timed out")
            return False
    
    except Exception as e:
        print(f"❌ E2E test failed: {e}")
        return False
    
    finally:
        await executor.disconnect()
        await dashboard.disconnect()
        await cluster.stop()


async def main():
    """Run all Socket.IO integration tests"""
    print("🚀 Gleitzeit Cluster - Socket.IO Integration Tests")
    print("=" * 60)
    print("\n⚠️  Note: This test requires a running Socket.IO server")
    print("   Start the server with: python examples/socketio_server_standalone.py")
    print()
    
    # Check if Socket.IO server is running
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8000/health", timeout=2.0)
            if response.status_code != 200:
                print("❌ Socket.IO server health check failed")
                return 1
    except Exception:
        print("❌ Socket.IO server not reachable at http://localhost:8000")
        print("\n💡 Start the server first:")
        print("   python examples/socketio_server_standalone.py")
        return 1
    
    print("✅ Socket.IO server is running\n")
    
    tests = [
        ("Server Startup", test_server_startup),
        ("Cluster Connection", test_cluster_connection),
        ("Executor Coordination", test_executor_node_coordination),
        ("Real-time Events", test_workflow_real_time_events),
        ("End-to-End Coordination", test_end_to_end_coordination)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"💥 {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Socket.IO Integration Test Summary")
    print("=" * 35)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {test_name}")
    
    print(f"\n✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    
    if passed == total:
        print("\n🎉 All Socket.IO integration tests passed!")
        print("\n🚀 Real-time coordination is working!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} tests failed.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)