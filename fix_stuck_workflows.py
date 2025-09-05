#!/usr/bin/env python3
"""Fix stuck workflows that have all tasks completed but workflow still shows as running."""

import redis
import json

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Find all workflows
workflow_keys = r.keys("gleitzeit:workflow:*")
fixed_count = 0

for workflow_key in workflow_keys:
    workflow_id = workflow_key.split(":")[2]
    workflow_status = r.hget(workflow_key, "status")
    
    if workflow_status == "running":
        # Get all tasks for this workflow
        task_ids = r.smembers(f"gleitzeit:idx:workflow_tasks:{workflow_id}")
        
        if task_ids:
            all_completed = True
            has_failed = False
            
            for task_id in task_ids:
                task_status = r.hget(f"gleitzeit:task:{task_id}", "status")
                if task_status == "failed":
                    has_failed = True
                elif task_status != "completed":
                    all_completed = False
                    break
            
            # If all tasks are completed or failed, update workflow status
            if all_completed:
                new_status = "failed" if has_failed else "completed"
                r.hset(workflow_key, "status", new_status)
                print(f"Fixed workflow {workflow_id}: running -> {new_status}")
                fixed_count += 1
        else:
            # Workflow has no tasks but is stuck in running - mark as completed
            r.hset(workflow_key, "status", "completed")
            print(f"Fixed empty workflow {workflow_id}: running -> completed")
            fixed_count += 1

print(f"\nFixed {fixed_count} stuck workflows")