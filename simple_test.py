"""
Simple test to verify signal system works.
"""

import asyncio
import redis.asyncio as redis
import json
import time

async def test_signal_system():
    """Test that the signal system components work."""
    
    # Connect to Redis
    redis_client = redis.from_url("redis://localhost:6379")
    
    print("🔧 Testing Signal System Components...")
    
    try:
        # Test 1: Can we import signal components?
        from src.gleitzeit.signals import SignalTaskHandler, SignalMonitorService
        print("✅ Signal components import successfully")
        
        # Test 2: Can we create signal handler?
        handler = SignalTaskHandler(redis_client)
        print("✅ SignalTaskHandler created")
        
        # Test 3: Test basic signal send 
        result = await handler.handle_send(
            "sender_workflow",
            "sender_task", 
            {
                "target_workflow": "test_workflow_123",
                "signal": "test_signal", 
                "payload": {"message": "hello"}
            }
        )
        print(f"✅ Signal sent: {result}")
        
        # Test 4: Check if signal stream was created
        streams = []
        async for key in redis_client.scan_iter("workflow:signals:*"):
            streams.append(key.decode() if isinstance(key, bytes) else key)
        
        print(f"✅ Signal streams created: {streams}")
        
        # Test 5: Try to wait for a signal
        try:
            wait_result = await handler.handle_wait(
                "test_workflow_123", 
                "test_task", 
                {"signal": "nonexistent_signal", "timeout": 1}
            )
            print(f"✅ Signal wait registered: {wait_result}")
        except Exception as e:
            print(f"⚠️ Signal wait error (expected): {e}")
        
        print("🎉 Basic signal system functionality works!")
        return True
        
    except Exception as e:
        print(f"❌ Signal system test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        await redis_client.close()

if __name__ == "__main__":
    result = asyncio.run(test_signal_system())
    exit(0 if result else 1)