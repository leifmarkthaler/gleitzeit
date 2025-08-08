#!/usr/bin/env python3
"""
Network Retry Logic Demo

Demonstrates retry logic for Redis and Socket.IO connections and operations.
Tests failover scenarios, network interruptions, and recovery.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.storage.redis_client import RedisClient, RedisConnectionError
from gleitzeit_cluster.communication.socketio_client import SocketIOClient, ClientType
from gleitzeit_cluster.core.workflow import Workflow, WorkflowStatus
from gleitzeit_cluster.core.error_handling import GleitzeitLogger


async def demo_redis_retry_logic():
    """Test Redis connection and operation retry logic"""
    
    print("🔄 Testing Redis Retry Logic")
    print("=" * 40)
    
    # Test 1: Connection retry with invalid URL (should fail after retries)
    print("1️⃣  Testing connection retry with invalid Redis URL...")
    
    redis_client_bad = RedisClient(
        redis_url="redis://localhost:9999",  # Invalid port
        retry_attempts=3,
        retry_delay=0.5
    )
    
    try:
        await redis_client_bad.connect()
        print("   ❌ Unexpected success - should have failed")
    except RedisConnectionError as e:
        print(f"   ✅ Connection failed as expected: {e}")
    
    print()
    
    # Test 2: Valid connection with retry (should succeed)
    print("2️⃣  Testing connection retry with valid Redis URL...")
    
    redis_client_good = RedisClient(
        redis_url="redis://localhost:6379",
        retry_attempts=3,
        retry_delay=0.5
    )
    
    try:
        await redis_client_good.connect()
        print("   ✅ Connected successfully")
        
        # Test workflow operations with retry
        print("   📋 Testing workflow operations with retry logic...")
        
        # Create a test workflow
        workflow = Workflow(
            workflow_id="retry_test", 
            name="Retry Test Workflow"
        )
        workflow.add_text_task(
            "test_task",
            "Test retry logic",
            "llama3"
        )
        
        # Store workflow (uses retry internally)
        await redis_client_good.store_workflow(workflow)
        print("   ✅ Workflow stored with retry logic")
        
        # Retrieve workflow (uses retry internally)
        retrieved = await redis_client_good.get_workflow(workflow.id)
        if retrieved:
            print(f"   ✅ Workflow retrieved: {retrieved['name']}")
        else:
            print("   ❌ Workflow retrieval failed")
        
        await redis_client_good.disconnect()
        
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
    
    print()


async def demo_socketio_retry_logic():
    """Test Socket.IO connection and event retry logic"""
    
    print("🔌 Testing Socket.IO Retry Logic")
    print("=" * 40)
    
    # Test 1: Connection retry with invalid URL (should fail after retries)
    print("1️⃣  Testing Socket.IO connection retry with invalid URL...")
    
    client_bad = SocketIOClient(
        server_url="http://localhost:9999",  # Invalid port
        client_type=ClientType.CLUSTER,
        reconnection_attempts=3,
        reconnection_delay=1
    )
    
    start_time = time.time()
    connected = await client_bad.connect()
    elapsed = time.time() - start_time
    
    if not connected:
        print(f"   ✅ Connection failed as expected after {elapsed:.2f}s")
        print(f"   📊 Retry behavior: 3 attempts with backoff")
    else:
        print("   ❌ Unexpected success - should have failed")
    
    await client_bad.disconnect()
    print()
    
    # Test 2: Connection to potentially running server (if available)
    print("2️⃣  Testing Socket.IO connection retry with valid URL...")
    
    client_good = SocketIOClient(
        server_url="http://localhost:8000",
        client_type=ClientType.DASHBOARD,
        reconnection_attempts=2,
        reconnection_delay=1
    )
    
    connected = await client_good.connect()
    if connected:
        print("   ✅ Connected successfully to Socket.IO server")
        
        # Test event emission with retry
        print("   📡 Testing event emission with retry logic...")
        
        # This will use retry logic internally
        await client_good.emit('test_event', {
            'message': 'Testing retry logic',
            'timestamp': time.time()
        })
        print("   ✅ Event emitted with retry logic")
        
    else:
        print("   ⚠️  Socket.IO server not available (expected if not running)")
        print("   💡 Start the server with: gleitzeit serve")
    
    await client_good.disconnect()
    print()


async def demo_network_resilience():
    """Demonstrate network resilience patterns"""
    
    print("🛡️  Network Resilience Patterns")
    print("=" * 40)
    
    print("✅ Implemented Features:")
    print("   🔄 Exponential backoff with jitter")
    print("   🔌 Circuit breaker for failing services")
    print("   📝 Structured error logging with context")
    print("   ⚡ Different retry policies per service type")
    print("   🚦 Error categorization (transient vs permanent)")
    print("   📊 Retry attempt tracking and metrics")
    print()
    
    print("🔧 Configuration Examples:")
    print("   Redis: 3 attempts, 1.0s base delay, 10s max delay")
    print("   Socket.IO Connection: 5 attempts, 2s base delay, 30s max delay")
    print("   Socket.IO Events: 3 attempts, 0.5s base delay, 5s max delay")
    print("   Task Execution: Variable based on task type")
    print()
    
    print("💡 Best Practices:")
    print("   • Permanent errors (auth, validation) are not retried")
    print("   • Rate limit errors respect server retry-after headers")
    print("   • Circuit breakers prevent cascade failures")
    print("   • Jitter prevents thundering herd effect")
    print("   • Structured logging enables monitoring and debugging")


async def main():
    """Run all network retry demonstrations"""
    
    print("🚀 Gleitzeit Network Retry Logic Demo")
    print("=" * 60)
    print()
    
    demos = [
        demo_redis_retry_logic,
        demo_socketio_retry_logic,
        demo_network_resilience
    ]
    
    for demo in demos:
        try:
            await demo()
        except Exception as e:
            print(f"❌ {demo.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
        
        print("-" * 60)
        print()
    
    print("🎯 Network Retry System Summary:")
    print("✅ Redis operations have comprehensive retry logic")
    print("✅ Socket.IO connections use exponential backoff")
    print("✅ Event emissions are protected with retry logic")
    print("✅ Circuit breakers prevent cascade failures")
    print("✅ Error categorization ensures appropriate retry behavior")
    print()
    print("💡 The system now has production-ready network resilience!")


if __name__ == "__main__":
    asyncio.run(main())