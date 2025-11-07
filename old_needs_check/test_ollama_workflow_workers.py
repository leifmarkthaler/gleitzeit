#!/usr/bin/env python
"""Test Ollama workflow execution using Gleitzeit workers"""

import asyncio
import logging
import sys
from pathlib import Path
import json
import time
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.sharding import default_sharding
import redis.asyncio as aioredis

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def submit_ollama_workflow(redis):
    """Submit a workflow with Ollama tasks"""
    import uuid
    workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"

    # Workflow with Ollama tasks and dependencies
    workflow = {
        'name': 'ollama-story-test',
        'tasks': [
            {
                'id': 'intro',
                'protocol': 'ollama/v1',
                'method': 'ollama/generate',
                'params': {
                    'model': 'llama3.2',
                    'prompt': 'Write the opening line of a science fiction story. One sentence only.',
                    'options': {
                        'temperature': 0.8,
                        'num_predict': 30
                    }
                }
            },
            {
                'id': 'expand',
                'protocol': 'ollama/v1',
                'method': 'ollama/generate',
                'params': {
                    'model': 'llama3.2',
                    'prompt': 'Continue this story: ${intro.response}. Add one more sentence.',
                    'options': {
                        'temperature': 0.8,
                        'num_predict': 30
                    }
                },
                'dependencies': ['intro']
            },
            {
                'id': 'analyze',
                'protocol': 'ollama/v1',
                'method': 'ollama/chat',
                'params': {
                    'model': 'llama3.2',
                    'messages': [
                        {'role': 'system', 'content': 'You are a literary critic. Be brief.'},
                        {'role': 'user', 'content': 'What genre is this story? Story: ${intro.response} ${expand.response}'}
                    ],
                    'options': {
                        'temperature': 0.5,
                        'num_predict': 20
                    }
                },
                'dependencies': ['intro', 'expand']
            }
        ]
    }

    shard = default_sharding.get_shard(workflow_id)

    # Submit workflow using cluster-aware key format
    await redis.xadd(
        f"{{shard:{shard}}}:workflow:load".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": json.dumps(workflow).encode(),
            b"format": b"inline"
        }
    )

    print(f"✅ Submitted Ollama workflow {workflow_id} to shard {shard}")
    return workflow_id, shard

async def check_workflow_status(redis, workflow_id):
    """Check the status of a workflow"""
    shard = default_sharding.get_shard(workflow_id)
    status_data = await redis.hgetall(f"{{shard:{shard}}}:workflow:status:{workflow_id}".encode())

    if status_data:
        print(f"\n📊 Workflow Status for {workflow_id}:")
        for key, value in status_data.items():
            print(f"  {key.decode()}: {value.decode()}")

        # Check task statuses
        print("\n📋 Task Status:")
        for task_id in ['intro', 'expand', 'analyze']:
            task_status = await redis.hgetall(f"{{shard:{shard}}}:task:status:{task_id}".encode())
            if task_status:
                status = task_status.get(b"status", b"unknown").decode()
                if status == "completed":
                    print(f"  {task_id}: ✅ {status}")
                    # Show result preview for Ollama tasks
                    result_str = task_status.get(b"result", b"").decode()
                    if result_str:
                        try:
                            result = json.loads(result_str)
                            if 'response' in result:
                                preview = result['response'][:100] + '...' if len(result['response']) > 100 else result['response']
                                print(f"    → {preview}")
                            elif 'message' in result:
                                content = result['message'].get('content', '')
                                preview = content[:100] + '...' if len(content) > 100 else content
                                print(f"    → {preview}")
                        except json.JSONDecodeError:
                            pass
                elif status == "failed":
                    error = task_status.get(b"error", b"").decode()
                    print(f"  {task_id}: ❌ {status} - {error[:100]}")
                else:
                    print(f"  {task_id}: ⏳ {status}")
            else:
                print(f"  {task_id}: No status")
    else:
        print(f"No status found for workflow {workflow_id}")

async def run_ollama_test():
    """Run Ollama workflow test"""
    print("\n🚀 Testing Ollama Workflow in Gleitzeit 0.0.7\n")

    # Check if Ollama is running
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('http://localhost:11434/api/tags', timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    models_data = await resp.json()
                    models = models_data.get('models', [])
                    print(f"✅ Ollama is running with {len(models)} model(s)")
                    if models:
                        print(f"   Available models: {', '.join([m['name'] for m in models[:3]])}")

                    # Check for llama3.2
                    has_llama32 = any('llama3.2' in m['name'] for m in models)
                    if not has_llama32:
                        print("⚠️  Warning: llama3.2 not found. Test may fail.")
                        print("   Run: ollama pull llama3.2")
                else:
                    print(f"⚠️  Ollama returned status {resp.status}")
    except Exception as e:
        print(f"❌ Cannot connect to Ollama: {e}")
        print("   Please start Ollama: ollama serve")
        return

    # Connect to Redis
    redis = await aioredis.from_url('redis://localhost:6379')

    # Submit workflow
    workflow_id, shard = await submit_ollama_workflow(redis)

    print(f"\n🔧 Starting workers for shard {shard}...")

    # Create workers
    workers = []

    # Workflow Loader
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="loader-ollama-test",
        consumer_group="loader-group-ollama",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    loader = WorkflowLoaderWorkerV2(loader_config)
    await loader.initialize()
    workers.append(loader)
    print("  ✅ WorkflowLoaderWorkerV2 ready")

    # Dependency Worker
    dep_config = WorkerConfig(
        worker_type="dependency",
        worker_id="dep-ollama-test",
        consumer_group="dep-group-ollama",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    dep = DependencyWorker(dep_config)
    await dep.initialize()
    workers.append(dep)
    print("  ✅ DependencyWorker ready")

    # Task Execution Worker
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="exec-ollama-test",
        consumer_group="exec-group-ollama",
        redis_url="redis://localhost:6379",
        assigned_shards=[shard],
        block_timeout=500
    )
    exec_worker = TaskExecutionWorker(exec_config)
    await exec_worker.initialize()
    workers.append(exec_worker)
    print("  ✅ TaskExecutionWorker ready")

    print(f"\n⏳ Processing Ollama workflow for up to 30 seconds...")

    # Create tasks for all workers
    tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.run())
        tasks.append(task)

    # Track progress
    start_time = time.time()
    max_wait = 30  # Maximum wait time in seconds

    workflow_complete = False
    for i in range(max_wait):
        await asyncio.sleep(1)

        # Check workflow status
        shard = default_sharding.get_shard(workflow_id)
        status_data = await redis.hgetall(f"{{shard:{shard}}}:workflow:status:{workflow_id}".encode())

        if status_data:
            status = status_data.get(b"status", b"").decode()
            if status == "completed":
                workflow_complete = True
                print(f"\n✅ Workflow completed!")
                break
            elif status == "failed":
                print(f"\n❌ Workflow failed!")
                break

        # Show progress every 3 seconds
        if i % 3 == 0:
            await check_workflow_status(redis, workflow_id)
            elapsed = time.time() - start_time
            print(f"\n⏱️  Elapsed: {elapsed:.1f}s")

    print("\n🛑 Stopping workers...")

    # Stop workers
    for worker in workers:
        worker._running = False

    await asyncio.sleep(1)

    # Cancel tasks
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Check final status
    print("\n" + "=" * 60)
    print("Final Results")
    print("=" * 60)
    await check_workflow_status(redis, workflow_id)

    print("\n📈 Worker Statistics:")
    for worker in workers:
        print(f"  {worker.config.worker_id}: {worker.messages_processed} processed, {worker.messages_failed} failed")

    # Get complete story if successful
    if workflow_complete:
        print("\n" + "=" * 60)
        print("📖 Generated Story")
        print("=" * 60)

        shard = default_sharding.get_shard(workflow_id)

        # Get all task results
        story_parts = []
        for task_id in ['intro', 'expand']:
            task_status = await redis.hgetall(f"{{shard:{shard}}}:task:status:{task_id}".encode())
            if task_status:
                result_str = task_status.get(b"result", b"").decode()
                if result_str:
                    try:
                        result = json.loads(result_str)
                        if 'response' in result:
                            story_parts.append(result['response'].strip())
                    except json.JSONDecodeError:
                        pass

        if story_parts:
            print("\n" + " ".join(story_parts))

        # Get analysis
        analyze_status = await redis.hgetall(f"{{shard:{shard}}}:task:status:analyze".encode())
        if analyze_status:
            result_str = analyze_status.get(b"result", b"").decode()
            if result_str:
                try:
                    result = json.loads(result_str)
                    if 'message' in result:
                        content = result['message'].get('content', '')
                        print(f"\n📊 Analysis: {content}")
                except json.JSONDecodeError:
                    pass

        print("\n🎉 SUCCESS! Ollama workflow with dependencies completed successfully!")
    else:
        print(f"\n⚠️  Workflow did not complete within {max_wait} seconds")

    await redis.aclose()
    print("\n✅ Test complete!")

if __name__ == "__main__":
    asyncio.run(run_ollama_test())