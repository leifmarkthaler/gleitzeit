#!/usr/bin/env python
"""
Check if handler tracking data persists in Redis.
"""

import asyncio
import json
import redis.asyncio as aioredis


async def check_persistence():
    """Check what handler tracking data is in Redis"""
    redis = aioredis.from_url("redis://localhost:6379", decode_responses=False)
    
    print("\n=== CHECKING HANDLER TRACKING PERSISTENCE IN REDIS ===")
    
    # Check handler registry
    print("\n1. Handler Registry:")
    handler_keys = await redis.keys(b"handler:registry:*")
    
    if handler_keys:
        print(f"   Found {len(handler_keys)} handlers in registry:")
        
        for key in handler_keys:
            handler_data = await redis.hgetall(key)
            handler_id = key.decode().split(":")[-1]
            print(f"\n   Handler: {handler_id[:8]}...")
            
            if b"protocol" in handler_data:
                print(f"   - Protocol: {handler_data[b'protocol'].decode()}")
            if b"worker_id" in handler_data:
                print(f"   - Worker: {handler_data[b'worker_id'].decode()}")
            if b"created_at" in handler_data:
                print(f"   - Created: {handler_data[b'created_at'].decode()}")
            if b"handler_class" in handler_data:
                print(f"   - Class: {handler_data[b'handler_class'].decode()}")
            
            # Check TTL
            ttl = await redis.ttl(key)
            if ttl > 0:
                print(f"   - TTL: {ttl} seconds ({ttl/3600:.1f} hours)")
            else:
                print(f"   - TTL: No expiry set")
    else:
        print("   No handlers found in registry")
    
    # Check task-to-handler mappings
    print("\n2. Task-to-Handler Mappings:")
    mapping_keys = await redis.keys(b"task:handler:*")
    
    if mapping_keys:
        print(f"   Found {len(mapping_keys)} task-to-handler mappings:")
        
        for i, key in enumerate(mapping_keys[:5]):  # Show first 5
            handler_id = await redis.get(key)
            task_id = key.decode().split(":")[-1]
            ttl = await redis.ttl(key)
            print(f"   - Task {task_id[:16]}... → Handler {handler_id.decode()[:8]}... (TTL: {ttl}s)")
        
        if len(mapping_keys) > 5:
            print(f"   ... and {len(mapping_keys) - 5} more")
    else:
        print("   No task-to-handler mappings found")
    
    # Check task:completed streams for handler data
    print("\n3. Task:Completed Streams with Handler Data:")
    
    # Get all sharded streams
    stream_keys = await redis.keys(b"*:task:completed")
    
    if stream_keys:
        print(f"   Found {len(stream_keys)} task:completed streams")
        
        total_messages = 0
        messages_with_handler = 0
        
        for stream_key in stream_keys:
            messages = await redis.xrange(stream_key, "-", "+", count=10)
            
            for msg_id, data in messages:
                total_messages += 1
                
                # Check if message has handler tracking
                if b"handler_id" in data:
                    messages_with_handler += 1
                    
                    if messages_with_handler <= 3:  # Show first 3
                        print(f"\n   Message {msg_id.decode()}:")
                        print(f"   - Task ID: {data.get(b'task_id', b'').decode()[:16]}...")
                        print(f"   - Handler ID: {data.get(b'handler_id', b'').decode()[:8]}...")
                        print(f"   - Worker ID: {data.get(b'worker_id', b'').decode()}")
                        if b"provider_url" in data:
                            print(f"   - Provider URL: {data.get(b'provider_url', b'').decode()}")
                        if b"worker_instance_url" in data:
                            print(f"   - Worker Instance URL: {data.get(b'worker_instance_url', b'').decode()}")
                        if b"handler_protocol" in data:
                            print(f"   - Protocol: {data.get(b'handler_protocol', b'').decode()}")
        
        print(f"\n   Summary: {messages_with_handler}/{total_messages} messages have handler tracking")
    else:
        print("   No task:completed streams found")
    
    # Check task data in hashes
    print("\n4. Task Data with Handler Info:")
    task_keys = await redis.keys(b"task:*")
    task_keys = [k for k in task_keys if not k.startswith(b"task:handler:")]  # Exclude mappings
    
    if task_keys:
        tasks_with_handler = 0
        
        for key in task_keys[:10]:  # Check first 10
            task_data = await redis.hgetall(key)
            
            if b"handler_id" in task_data:
                tasks_with_handler += 1
                
                if tasks_with_handler <= 3:  # Show first 3
                    print(f"\n   Task {key.decode()}:")
                    print(f"   - Status: {task_data.get(b'status', b'').decode()}")
                    print(f"   - Handler ID: {task_data.get(b'handler_id', b'').decode()[:8]}...")
                    if b"worker_id" in task_data:
                        print(f"   - Worker ID: {task_data.get(b'worker_id', b'').decode()}")
        
        print(f"\n   Found {tasks_with_handler} tasks with handler info out of {len(task_keys)} checked")
    else:
        print("   No task data found")
    
    # Database info
    print("\n5. Redis Database Info:")
    info = await redis.info("keyspace")
    if 'db0' in info:
        db_info = info['db0']
        print(f"   Keys: {db_info.get('keys', 0)}")
        print(f"   Expires: {db_info.get('expires', 0)}")
    
    await redis.close()
    print("\n✅ Persistence check complete")


if __name__ == "__main__":
    asyncio.run(check_persistence())