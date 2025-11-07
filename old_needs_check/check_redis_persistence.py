#!/usr/bin/env python
"""Check Redis for persisted workflow and task results"""

import asyncio
import json
import redis.asyncio as aioredis
from datetime import datetime


async def check_persistence():
    """Check what's persisted in Redis from our Ollama workflow tests"""

    print("=" * 70)
    print("Redis Persistence Check")
    print("=" * 70)

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379', decode_responses=True)

    try:
        # Check connection
        await redis.ping()
        print("✅ Connected to Redis\n")

        # 1. Check for workflow keys
        print("📋 Checking for Workflow Keys:")
        print("-" * 40)

        # Look for workflow status keys
        workflow_keys = await redis.keys("*workflow:status:*")
        print(f"Found {len(workflow_keys)} workflow status keys")

        for key in workflow_keys[:5]:  # Show first 5
            status_data = await redis.hgetall(key)
            workflow_id = key.split(":")[-1]
            print(f"\n  Workflow: {workflow_id}")

            # Show key fields
            for field, value in status_data.items():
                if field == 'definition':
                    # Parse and show summary of definition
                    try:
                        definition = json.loads(value)
                        task_count = len(definition.get('tasks', []))
                        print(f"    {field}: {task_count} tasks defined")
                    except:
                        print(f"    {field}: <parsing error>")
                elif field in ['created_at', 'completed_at']:
                    print(f"    {field}: {value}")
                elif field == 'status':
                    print(f"    {field}: {value}")
                else:
                    preview = str(value)[:100] + '...' if len(str(value)) > 100 else value
                    print(f"    {field}: {preview}")

        # 2. Check for task status keys
        print("\n\n📝 Checking for Task Status Keys:")
        print("-" * 40)

        task_keys = await redis.keys("*task:status:*")
        print(f"Found {len(task_keys)} task status keys")

        # Group by workflow
        tasks_by_workflow = {}
        for key in task_keys:
            task_data = await redis.hgetall(key)
            workflow_id = task_data.get('workflow_id', 'unknown')
            task_id = key.split(":")[-1]

            if workflow_id not in tasks_by_workflow:
                tasks_by_workflow[workflow_id] = []

            tasks_by_workflow[workflow_id].append({
                'id': task_id,
                'data': task_data
            })

        # Show tasks grouped by workflow
        for workflow_id, tasks in list(tasks_by_workflow.items())[:3]:  # Show first 3 workflows
            print(f"\n  Workflow: {workflow_id}")
            for task in tasks[:5]:  # Show first 5 tasks per workflow
                print(f"    Task: {task['id']}")
                data = task['data']

                # Show status
                status = data.get('status', 'unknown')
                print(f"      status: {status}")

                # Show result if completed
                if status == 'completed' and 'result' in data:
                    try:
                        result = json.loads(data['result'])

                        # Handle different result types
                        if isinstance(result, dict):
                            # Handle Ollama responses
                            if 'response' in result:
                                preview = result['response'][:80] + '...' if len(result['response']) > 80 else result['response']
                                print(f"      response: {preview}")
                            elif 'message' in result and isinstance(result['message'], dict):
                                content = result['message'].get('content', '')
                                preview = content[:80] + '...' if len(content) > 80 else content
                                print(f"      message: {preview}")
                            else:
                                # Show first key-value pair
                                for k, v in list(result.items())[:2]:
                                    preview = str(v)[:80] + '...' if len(str(v)) > 80 else str(v)
                                    print(f"      {k}: {preview}")
                        else:
                            # Result is not a dict (maybe string or other)
                            preview = str(result)[:80] + '...' if len(str(result)) > 80 else str(result)
                            print(f"      result: {preview}")
                    except json.JSONDecodeError:
                        print(f"      result: <invalid JSON>")

                # Show error if failed
                if status == 'failed' and 'error' in data:
                    error = data['error'][:100] + '...' if len(data['error']) > 100 else data['error']
                    print(f"      error: {error}")

                # Show timing
                if 'completed_at' in data:
                    print(f"      completed_at: {data['completed_at']}")

        # 3. Check for stream keys (queues)
        print("\n\n📊 Checking Stream Keys (Queues):")
        print("-" * 40)

        stream_patterns = [
            "*:workflow:load",
            "*:task:ready",
            "*:task:completed",
            "*:dependency:check"
        ]

        for pattern in stream_patterns:
            stream_keys = await redis.keys(pattern)
            if stream_keys:
                print(f"\n  Pattern: {pattern}")
                for key in stream_keys[:3]:
                    # Get stream length
                    try:
                        stream_info = await redis.xinfo_stream(key)
                        length = stream_info.get('length', 0)
                        first_entry = stream_info.get('first-entry')
                        last_entry = stream_info.get('last-entry')

                        print(f"    {key}:")
                        print(f"      Length: {length} messages")
                        if first_entry:
                            print(f"      First: {first_entry[0]}")
                        if last_entry:
                            print(f"      Last: {last_entry[0]}")
                    except:
                        print(f"    {key}: <error reading stream>")

        # 4. Check for other relevant keys
        print("\n\n🔍 Other Relevant Keys:")
        print("-" * 40)

        # Check for handler-related keys
        handler_keys = await redis.keys("*handler*")
        print(f"Handler-related keys: {len(handler_keys)}")

        # Check for cache keys
        cache_keys = await redis.keys("*cache*")
        print(f"Cache keys: {len(cache_keys)}")

        # Check for leader election keys
        leader_keys = await redis.keys("*leader*")
        print(f"Leader election keys: {len(leader_keys)}")

        # 5. Database statistics
        print("\n\n📈 Database Statistics:")
        print("-" * 40)

        db_info = await redis.info('keyspace')
        for line in db_info.split('\n'):
            if line.startswith('db'):
                print(f"  {line}")

        # Memory usage
        memory_info = await redis.info('memory')
        for line in memory_info.split('\n'):
            if 'used_memory_human' in line:
                print(f"  {line}")

        # 6. Check specific workflows from our tests
        print("\n\n🎯 Checking Recent Test Workflows:")
        print("-" * 40)

        test_patterns = [
            "*workflow_*",  # Our test workflow IDs
            "*ollama*"      # Ollama-specific keys
        ]

        for pattern in test_patterns:
            keys = await redis.keys(pattern)
            if keys:
                print(f"\n  Pattern: {pattern} ({len(keys)} keys)")
                for key in keys[:5]:
                    key_type = await redis.type(key)
                    print(f"    {key} (type: {key_type})")

                    # Show content based on type
                    if key_type == 'hash':
                        size = await redis.hlen(key)
                        print(f"      → {size} fields")
                    elif key_type == 'stream':
                        try:
                            length = await redis.xlen(key)
                            print(f"      → {length} messages")
                        except:
                            print(f"      → <error reading>")
                    elif key_type == 'string':
                        value = await redis.get(key)
                        preview = value[:50] + '...' if len(value) > 50 else value
                        print(f"      → {preview}")

        print("\n" + "=" * 70)
        print("✅ Persistence check complete!")

        # Summary
        print("\n📊 Summary:")
        print(f"  - Total keys in database: {await redis.dbsize()}")
        print(f"  - Workflow statuses found: {len(workflow_keys)}")
        print(f"  - Task statuses found: {len(task_keys)}")

        # Check if our recent tests are there
        recent_workflows = [k for k in workflow_keys if 'ollama' in k.lower() or 'd382411bb6e0' in k or 'a6c8b1a64aae' in k]
        if recent_workflows:
            print(f"  - Recent Ollama test workflows: {len(recent_workflows)}")
            for wf in recent_workflows:
                print(f"    → {wf}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(check_persistence())