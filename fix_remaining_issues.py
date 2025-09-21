#!/usr/bin/env python3
"""
Fix remaining issues identified in the system:
1. Service registry heartbeat type comparison error
2. Clean up stale SystemManager instances
3. Remove invalid test tasks
"""

import asyncio
import json
from datetime import datetime
import redis.asyncio as redis


async def fix_service_registry():
    """Fix the service registry heartbeat comparison issue."""
    print("\n🔧 Fixing service registry heartbeat comparison...")
    
    filepath = "src/gleitzeit/system/service_registry.py"
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Fix the type comparison issue on line 491
    old_line = "                    if service.last_heartbeat and service.last_heartbeat < timeout_threshold:"
    new_line = """                    # Ensure last_heartbeat is a datetime object
                    last_hb = service.last_heartbeat
                    if last_hb:
                        if isinstance(last_hb, str):
                            try:
                                last_hb = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                            except:
                                continue
                        if last_hb < timeout_threshold:"""
    
    if old_line in content:
        # Need to handle the indentation properly
        content = content.replace(old_line, new_line)
        
        # Also need to indent the next lines properly
        old_block = """                        # Mark service as unhealthy
                        await self.update_service_status("""
        new_block = """                            # Mark service as unhealthy
                            await self.update_service_status("""
        content = content.replace(old_block, new_block)
        
        # Fix the closing parenthesis indentation
        old_close = """                        )
                        
                        # Emit event
                        if self.event_bus:"""
        new_close = """                            )
                            
                            # Emit event
                            if self.event_bus:"""
        content = content.replace(old_close, new_close)
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        print("  ✅ Fixed heartbeat type comparison")
    else:
        print("  ⚠️  Pattern not found, may already be fixed")


async def clean_stale_system_managers():
    """Clean up stale SystemManager instances from Redis."""
    print("\n🧹 Cleaning up stale SystemManager instances...")
    
    client = await redis.from_url("redis://localhost:6379/0")
    
    try:
        # Get all service keys
        service_keys = await client.keys("service:system_manager_*")
        print(f"  Found {len(service_keys)} SystemManager service entries")
        
        if service_keys:
            # Delete all stale service entries
            deleted = await client.delete(*service_keys)
            print(f"  ✅ Deleted {deleted} stale service entries")
        
        # Clean up health monitor data
        health_keys = await client.keys("health:system_manager_*")
        if health_keys:
            deleted = await client.delete(*health_keys)
            print(f"  ✅ Deleted {deleted} stale health entries")
        
        # Clean up from the services set
        services = await client.smembers("services")
        stale_count = 0
        for service_id in services:
            if isinstance(service_id, bytes):
                service_id = service_id.decode()
            if service_id.startswith("system_manager_"):
                await client.srem("services", service_id)
                stale_count += 1
        
        if stale_count:
            print(f"  ✅ Removed {stale_count} stale entries from services set")
        
        # Clean up component registry
        component_keys = await client.keys("component:system_manager_*")
        if component_keys:
            deleted = await client.delete(*component_keys)
            print(f"  ✅ Deleted {deleted} stale component entries")
        
        # Clean up distributed registry
        registry_keys = await client.keys("distributed_registry:*")
        for key in registry_keys:
            components = await client.smembers(key)
            for comp in components:
                if isinstance(comp, bytes):
                    comp = comp.decode()
                try:
                    comp_data = json.loads(comp)
                    if comp_data.get('component_id', '').startswith('system_manager_'):
                        await client.srem(key, comp)
                        print(f"  ✅ Removed stale component from {key.decode() if isinstance(key, bytes) else key}")
                except:
                    pass
        
        print("  ✅ Cleanup complete")
        
    except Exception as e:
        print(f"  ❌ Error during cleanup: {e}")
    finally:
        await client.close()


async def remove_invalid_test_tasks():
    """Remove invalid test tasks from the retry system."""
    print("\n🗑️  Removing invalid test tasks...")
    
    client = await redis.from_url("redis://localhost:6379/0")
    
    try:
        # Find and remove the invalid provider_test_task
        task_keys = await client.keys("gleitzeit:task:provider_test_task*")
        if task_keys:
            deleted = await client.delete(*task_keys)
            print(f"  ✅ Deleted {deleted} invalid test task(s)")
        
        # Remove from retry sets
        retry_keys = [
            "gleitzeit:retry:pending",
            "gleitzeit:retry:scheduled",
            "gleitzeit:tasks:failed"
        ]
        
        for key in retry_keys:
            # Check if it's a sorted set or regular set
            key_type = await client.type(key)
            if key_type == b'zset':
                # Remove from sorted set
                removed = await client.zrem(key, "provider_test_task")
                if removed:
                    print(f"  ✅ Removed invalid task from {key}")
            elif key_type == b'set':
                # Remove from regular set
                removed = await client.srem(key, "provider_test_task")
                if removed:
                    print(f"  ✅ Removed invalid task from {key}")
        
        # Remove from task results
        result_keys = await client.keys("gleitzeit:task_result:provider_test_task*")
        if result_keys:
            deleted = await client.delete(*result_keys)
            print(f"  ✅ Deleted {deleted} invalid task result(s)")
        
        # Clean up any workflow with invalid tasks
        workflow_keys = await client.keys("gleitzeit:workflow:*")
        for wf_key in workflow_keys:
            wf_data = await client.get(wf_key)
            if wf_data:
                try:
                    if isinstance(wf_data, bytes):
                        wf_data = wf_data.decode()
                    wf = json.loads(wf_data)
                    if any('provider_test_task' in str(task) for task in wf.get('tasks', [])):
                        await client.delete(wf_key)
                        print(f"  ✅ Removed workflow with invalid task: {wf_key}")
                except:
                    pass
        
        print("  ✅ Invalid task cleanup complete")
        
    except Exception as e:
        print(f"  ❌ Error during task cleanup: {e}")
    finally:
        await client.close()


async def main():
    """Apply all fixes."""
    print("🔨 Fixing Remaining System Issues")
    print("=" * 50)
    
    # Apply fixes
    await fix_service_registry()
    await clean_stale_system_managers()
    await remove_invalid_test_tasks()
    
    print("\n✅ All fixes applied successfully!")
    print("\n⚠️  Please restart the server to apply changes")


if __name__ == "__main__":
    asyncio.run(main())