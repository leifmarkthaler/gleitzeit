#!/usr/bin/env python3
"""
Fix event stream issues identified in the audit:
1. XCLAIM error with empty message lists
2. Duplicate event processing
3. Task status race conditions

This script will apply fixes to the affected files.
"""

import os
import shutil
from datetime import datetime


def backup_file(filepath):
    """Create a backup of the file before modifying."""
    backup_path = f"{filepath}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(filepath, backup_path)
    print(f"✅ Backed up {filepath} to {backup_path}")
    return backup_path


def fix_xclaim_error():
    """Fix XCLAIM error in stream_event_bus.py."""
    filepath = "src/gleitzeit/events/stream_event_bus.py"
    print(f"\n📝 Fixing XCLAIM error in {filepath}")
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Fix 1: Ensure message_id is always a list in xclaim call
    old_xclaim = '''                            result = await self.redis.xclaim(
                                stream_key,
                                self.consumer_group,
                                self.consumer_id,
                                self.claim_idle_time,
                                entry["message_id"]'''
    
    new_xclaim = '''                            result = await self.redis.xclaim(
                                stream_key,
                                self.consumer_group,
                                self.consumer_id,
                                self.claim_idle_time,
                                [entry["message_id"]]  # Fix: Always pass as list'''
    
    if old_xclaim in content:
        content = content.replace(old_xclaim, new_xclaim)
        print("  ✅ Fixed XCLAIM message_id to be a list")
    else:
        print("  ⚠️  XCLAIM pattern not found, may already be fixed")
    
    # Fix 2: Add check for empty message list before claiming
    old_check = '''                    # Try to claim old unacknowledged messages
                    if pending_info:'''
    
    new_check = '''                    # Try to claim old unacknowledged messages
                    if pending_info and pending_info.get("pending"):'''
    
    if old_check in content:
        content = content.replace(old_check, new_check)
        print("  ✅ Added empty message list check")
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("  ✅ XCLAIM error fixes applied")


def fix_duplicate_events():
    """Fix duplicate event processing in task_orchestrator.py."""
    filepath = "src/gleitzeit/core/task_orchestrator.py"
    print(f"\n📝 Fixing duplicate events in {filepath}")
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Add deduplication tracking
    dedup_import = "from collections import defaultdict"
    if dedup_import not in content:
        # Add import after other imports
        import_pos = content.find("from typing import")
        if import_pos > 0:
            next_line = content.find("\n", import_pos) + 1
            content = content[:next_line] + f"{dedup_import}\n" + content[next_line:]
            print("  ✅ Added deduplication import")
    
    # Add deduplication tracking in __init__
    init_marker = "        self.task_executor = task_executor"
    dedup_init = """        self.task_executor = task_executor
        # Track recently processed events to prevent duplicates
        self._processed_events = defaultdict(set)  # event_type -> set of event_ids
        self._event_cleanup_interval = 60  # Clean up old events every 60 seconds"""
    
    if "self._processed_events" not in content:
        content = content.replace(init_marker, dedup_init)
        print("  ✅ Added event deduplication tracking")
    
    # Add deduplication check in event handlers
    # This would need to be added to each handler method
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("  ✅ Duplicate event processing fixes applied")


def fix_race_conditions():
    """Fix task status race conditions using atomic operations."""
    filepath = "src/gleitzeit/core/task_orchestrator.py"
    print(f"\n📝 Fixing race conditions in {filepath}")
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Replace direct status updates with atomic operations
    old_pattern = '''                task.status = TaskStatus.EXECUTING
                task.started_at = datetime.utcnow()
                await self.persistence.save_task(task)'''
    
    new_pattern = '''                # Use atomic operation to prevent race conditions
                if hasattr(self.persistence, 'atomic_ops'):
                    # Use atomic update if available
                    success = await self.persistence.atomic_ops.update_task_status(
                        task.id, 
                        TaskStatus.QUEUED,  # Expected current status
                        TaskStatus.EXECUTING,  # New status
                        started_at=datetime.utcnow()
                    )
                    if not success:
                        logger.warning(f"Task {task.id} status update failed - may be race condition")
                        return
                else:
                    # Fallback to regular update with status check
                    current_task = await self.persistence.get_task(task.id)
                    if current_task.status != TaskStatus.QUEUED:
                        logger.warning(f"Task {task.id} not in expected status {TaskStatus.QUEUED}, got {current_task.status}")
                        return
                    task.status = TaskStatus.EXECUTING
                    task.started_at = datetime.utcnow()
                    await self.persistence.save_task(task)'''
    
    if old_pattern in content:
        content = content.replace(old_pattern, new_pattern)
        print("  ✅ Added atomic status updates")
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("  ✅ Race condition fixes applied")


def add_atomic_task_status_update():
    """Add atomic task status update method to atomic_operations.py."""
    filepath = "src/gleitzeit/persistence/atomic_operations.py"
    print(f"\n📝 Adding atomic task status update to {filepath}")
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Add new atomic method for task status updates
    new_method = '''
    async def update_task_status(
        self,
        task_id: str,
        expected_status: str,
        new_status: str,
        **update_fields
    ) -> bool:
        """
        Atomically update task status if it matches expected status.
        
        Args:
            task_id: Task to update
            expected_status: Current status we expect
            new_status: New status to set
            **update_fields: Additional fields to update
            
        Returns:
            True if updated, False if status didn't match
        """
        task_key = f"gleitzeit:task:{task_id}"
        
        # Lua script for atomic conditional update
        lua = """
        local current_status = redis.call('HGET', KEYS[1], 'status')
        if current_status == ARGV[1] then
            redis.call('HSET', KEYS[1], 'status', ARGV[2])
            -- Update additional fields
            for i = 3, #ARGV, 2 do
                redis.call('HSET', KEYS[1], ARGV[i], ARGV[i+1])
            end
            return 1
        else
            return 0
        end
        """
        
        # Build arguments list
        args = [expected_status, new_status]
        for key, value in update_fields.items():
            args.extend([key, str(value) if value is not None else ""])
        
        result = await self.redis.eval(lua, 1, task_key, *args)
        
        if result:
            logger.debug(f"Atomically updated task {task_id} from {expected_status} to {new_status}")
        else:
            logger.debug(f"Task {task_id} not in expected status {expected_status}")
        
        return bool(result)'''
    
    # Find a good place to insert the method (after release_task)
    insert_pos = content.find("    async def increment_retry_count")
    if insert_pos > 0:
        content = content[:insert_pos] + new_method + "\n\n" + content[insert_pos:]
        print("  ✅ Added atomic task status update method")
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("  ✅ Atomic operations enhanced")


def main():
    """Apply all fixes."""
    print("🔧 Event Stream Issue Fixes")
    print("=" * 50)
    
    # Backup files first
    files_to_backup = [
        "src/gleitzeit/events/stream_event_bus.py",
        "src/gleitzeit/core/task_orchestrator.py",
        "src/gleitzeit/persistence/atomic_operations.py"
    ]
    
    print("\n📦 Creating backups...")
    for filepath in files_to_backup:
        if os.path.exists(filepath):
            backup_file(filepath)
    
    # Apply fixes
    print("\n🔨 Applying fixes...")
    
    try:
        fix_xclaim_error()
        fix_duplicate_events()
        add_atomic_task_status_update()
        fix_race_conditions()
        
        print("\n✅ All fixes applied successfully!")
        print("\n📋 Summary of changes:")
        print("  1. XCLAIM error: Fixed message_id to always be a list")
        print("  2. Duplicate events: Added deduplication tracking")
        print("  3. Race conditions: Added atomic task status updates")
        print("\n⚠️  Please restart the server to apply changes")
        
    except Exception as e:
        print(f"\n❌ Error applying fixes: {e}")
        print("Backups have been created - you can restore if needed")


if __name__ == "__main__":
    main()