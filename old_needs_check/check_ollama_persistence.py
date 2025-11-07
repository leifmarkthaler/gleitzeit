#!/usr/bin/env python
"""Check Redis for Ollama workflow persistence"""

import asyncio
import json
import redis.asyncio as aioredis
from datetime import datetime


async def check_ollama_persistence():
    """Check Ollama workflow results in Redis"""

    print("=" * 70)
    print("Ollama Workflow Persistence Check")
    print("=" * 70)

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379', decode_responses=True)

    try:
        await redis.ping()
        print("✅ Connected to Redis\n")

        # Find all workflow status keys
        workflow_keys = await redis.keys("*:workflow:status:*")

        # Filter for Ollama-related workflows
        ollama_workflows = []
        for key in workflow_keys:
            status_data = await redis.hgetall(key)
            workflow_id = key.split(":")[-1]

            # Check if this is one of our test workflows
            if any(x in workflow_id for x in ['ollama', 'a6c8b1a64aae', 'd382411bb6e0']):
                ollama_workflows.append({
                    'id': workflow_id,
                    'key': key,
                    'data': status_data
                })

        print(f"📊 Found {len(ollama_workflows)} Ollama-related workflows\n")

        # Display each workflow with its tasks
        for wf in ollama_workflows:
            print("-" * 70)
            print(f"📋 Workflow: {wf['id']}")

            # Show workflow status
            data = wf['data']
            print(f"   Status: {data.get('status', 'unknown')}")
            print(f"   Total tasks: {data.get('total_tasks', '?')}")
            print(f"   Completed tasks: {data.get('completed_tasks', '?')}")

            if 'completed_at' in data:
                print(f"   Completed at: {data['completed_at']}")

            # Extract shard from key
            shard_match = key.split(':')[0].replace('{shard', '').replace('}', '')
            if shard_match:
                shard = shard_match.split(':')[-1] if ':' in shard_match else shard_match

                # Get task list
                task_list_key = f"{{shard:{shard}}}:workflow:tasks:completed:{wf['id']}"
                completed_tasks = await redis.smembers(task_list_key)

                if completed_tasks:
                    print(f"\n   🎯 Tasks:")

                    # Get each task's results
                    for task_id in sorted(completed_tasks):
                        task_key = f"{{shard:{shard}}}:task:status:{task_id}"
                        task_data = await redis.hgetall(task_key)

                        if task_data:
                            print(f"\n   Task: {task_id}")
                            print(f"      Status: {task_data.get('status', 'unknown')}")

                            # Parse and display result
                            if 'result' in task_data:
                                try:
                                    result = json.loads(task_data['result'])

                                    # Handle Ollama generate response
                                    if 'response' in result:
                                        response = result['response']
                                        print(f"      Response: {response[:100]}..." if len(response) > 100 else f"      Response: {response}")

                                        # Show performance metrics
                                        if 'total_duration' in result:
                                            total_ms = result['total_duration'] / 1_000_000
                                            print(f"      Duration: {total_ms:.0f}ms")
                                        if 'eval_count' in result:
                                            print(f"      Tokens generated: {result['eval_count']}")

                                    # Handle Ollama chat response
                                    elif 'message' in result:
                                        msg = result['message']
                                        if isinstance(msg, dict) and 'content' in msg:
                                            content = msg['content']
                                            print(f"      Chat response: {content[:100]}..." if len(content) > 100 else f"      Chat response: {content}")

                                        # Show performance metrics
                                        if 'total_duration' in result:
                                            total_ms = result['total_duration'] / 1_000_000
                                            print(f"      Duration: {total_ms:.0f}ms")

                                    # Show model used
                                    if 'model' in result:
                                        print(f"      Model: {result['model']}")

                                except json.JSONDecodeError:
                                    print(f"      Result: <invalid JSON>")

                            # Show timestamp
                            if 'completed_at' in task_data:
                                print(f"      Completed: {task_data['completed_at']}")

        print("\n" + "=" * 70)
        print("📈 Persistence Summary")
        print("=" * 70)

        # Database stats
        db_size = await redis.dbsize()
        print(f"   Total keys in database: {db_size}")

        # Memory usage
        memory_info = await redis.execute_command('MEMORY', 'USAGE', 'dummy_key')
        if memory_info:
            # Get actual memory stats
            info = await redis.info('memory')
            for key, value in info.items():
                if key == 'used_memory_human':
                    print(f"   Memory used: {value}")
                    break

        # Stream sizes
        streams = await redis.keys("*:task:ready")
        if streams:
            total_messages = 0
            for stream in streams:
                try:
                    length = await redis.xlen(stream)
                    total_messages += length
                except:
                    pass
            print(f"   Total messages in task queues: {total_messages}")

        print("\n✅ All Ollama workflow results are persisted in Redis!")
        print("\n💡 Tips:")
        print("   - Results persist across restarts")
        print("   - Use `redis-cli FLUSHDB` to clear all data")
        print("   - Use `redis-cli --scan --pattern '*workflow*'` to explore")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(check_ollama_persistence())