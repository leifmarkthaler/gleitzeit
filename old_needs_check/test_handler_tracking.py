#!/usr/bin/env python
"""
Test handler tracking implementation.

Verifies that handler IDs and metadata are properly tracked
when tasks are executed.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime

import redis.asyncio as aioredis

from gleitzeit.core.models import Workflow, Task, TaskStatus
from gleitzeit.workers import TaskExecutionWorker, WorkerConfig, DependencyWorker, WorkflowLoaderWorker
from gleitzeit.core.sharding import default_sharding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_handler_tracking():
    """Test that handler tracking is properly added to stream messages"""
    redis = aioredis.from_url("redis://localhost:6379", decode_responses=False)
    
    # Clear any existing data
    await redis.flushdb()
    logger.info("Cleared Redis")
    
    # Create workflow with Ollama task
    workflow_id = str(uuid.uuid4())
    
    workflow = Workflow(
        id=workflow_id,
        name="Handler Tracking Test",
        tasks=[
            Task(
                id="intro",
                name="Generate Intro",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Tell me about handler tracking in one sentence.",
                    "stream": False
                }
            )
        ]
    )
    
    # Submit workflow directly to Redis
    shard = default_sharding.get_shard(workflow_id)
    workflow_json = json.dumps(workflow.model_dump())
    
    await redis.hset(
        default_sharding.get_workflow_key("data", workflow_id).encode(),
        mapping={
            b"workflow": workflow_json.encode(),
            b"status": TaskStatus.PENDING.encode(),
            b"submitted_at": datetime.utcnow().isoformat().encode()
        }
    )
    
    # Submit to orchestration stream
    await redis.xadd(
        default_sharding.get_stream_key("workflow:submitted", workflow_id).encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"workflow": workflow_json.encode()
        }
    )
    
    logger.info(f"Submitted workflow {workflow_id}")
    
    # Start workers
    workers = []
    
    # Workflow loader worker
    loader_config = WorkerConfig(
        worker_id="test-loader",
        worker_type="WorkflowLoaderWorker",
        consumer_group="test-group",
        redis_url="redis://localhost:6379"
    )
    loader_worker = WorkflowLoaderWorker(loader_config)
    workers.append(loader_worker)

    # Dependency worker
    dep_config = WorkerConfig(
        worker_id="test-dep",
        worker_type="DependencyWorker",
        consumer_group="test-group",
        redis_url="redis://localhost:6379"
    )
    dep_worker = DependencyWorker(dep_config)
    workers.append(dep_worker)

    # Task execution worker with Ollama handler
    exec_config = WorkerConfig(
        worker_id="test-exec",
        worker_type="TaskExecutionWorker",
        consumer_group="test-group",
        redis_url="redis://localhost:6379"
    )
    # Add handler configs after creation
    exec_config.enabled_task_types = ["ollama", "llm"]
    exec_config.handler_configs = {
        "ollama/v1": {
            "base_url": "http://localhost:11434"
        }
    }
    exec_worker = TaskExecutionWorker(exec_config)
    workers.append(exec_worker)
    
    logger.info("Starting workers...")
    
    # Start workers in background
    worker_tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.start())
        worker_tasks.append(task)
    
    # Wait for workflow to complete (or timeout)
    logger.info("Waiting for workflow to complete...")
    timeout = 30
    start_time = asyncio.get_event_loop().time()
    
    while True:
        # Check workflow status
        status = await redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"status"
        )
        
        if status and status.decode() == "completed":
            logger.info("✓ Workflow completed")
            break
        elif status and status.decode() == "failed":
            logger.error("✗ Workflow failed")
            break
        
        if asyncio.get_event_loop().time() - start_time > timeout:
            logger.error(f"✗ Workflow timed out after {timeout}s")
            break
        
        await asyncio.sleep(1)
    
    # Stop workers
    for worker in workers:
        await worker.stop()
    
    # Cancel worker tasks
    for task in worker_tasks:
        task.cancel()
    
    # Check if handler tracking was added to stream
    logger.info("\nChecking handler tracking in stream messages...")
    
    # Read from task:completed stream
    stream_key = default_sharding.get_stream_key("task:completed", workflow_id).encode()
    messages = await redis.xrange(stream_key, "-", "+")
    
    if messages:
        logger.info(f"Found {len(messages)} messages in task:completed stream")
        
        for msg_id, data in messages:
            logger.info(f"\nMessage ID: {msg_id.decode()}")
            
            # Check for handler tracking fields
            handler_id = data.get(b"handler_id")
            worker_id = data.get(b"worker_id")
            handler_protocol = data.get(b"handler_protocol")
            provider_url = data.get(b"provider_url")
            worker_instance_url = data.get(b"worker_instance_url")
            
            if handler_id:
                logger.info(f"✓ Handler ID: {handler_id.decode()}")
            else:
                logger.warning("✗ Handler ID not found")
            
            if worker_id:
                logger.info(f"✓ Worker ID: {worker_id.decode()}")
            else:
                logger.warning("✗ Worker ID not found")
            
            if handler_protocol:
                logger.info(f"✓ Handler Protocol: {handler_protocol.decode()}")
            else:
                logger.warning("✗ Handler Protocol not found")
            
            if provider_url:
                logger.info(f"✓ Provider URL: {provider_url.decode()}")
            else:
                logger.info("  Provider URL: Not set (optional)")

            if worker_instance_url:
                logger.info(f"✓ Worker Instance URL: {worker_instance_url.decode()}")
            else:
                logger.info("  Instance URL: Not set (optional)")
    else:
        logger.warning("No messages found in task:completed stream")
    
    # Check handler registry
    logger.info("\nChecking handler registry...")
    handler_keys = await redis.keys(b"handler:registry:*")
    
    if handler_keys:
        logger.info(f"Found {len(handler_keys)} handlers in registry")
        
        for key in handler_keys:
            handler_data = await redis.hgetall(key)
            handler_id = key.decode().split(":")[-1]
            logger.info(f"\nHandler: {handler_id[:8]}...")
            
            if b"protocol" in handler_data:
                logger.info(f"  Protocol: {handler_data[b'protocol'].decode()}")
            if b"worker_id" in handler_data:
                logger.info(f"  Worker: {handler_data[b'worker_id'].decode()}")
            if b"created_at" in handler_data:
                logger.info(f"  Created: {handler_data[b'created_at'].decode()}")
    else:
        logger.warning("No handlers found in registry")
    
    # Check task-to-handler mapping
    logger.info("\nChecking task-to-handler mappings...")
    mapping_keys = await redis.keys(b"task:handler:*")
    
    if mapping_keys:
        logger.info(f"Found {len(mapping_keys)} task-to-handler mappings")
        
        for key in mapping_keys:
            handler_id = await redis.get(key)
            task_id = key.decode().split(":")[-1]
            logger.info(f"  Task {task_id} → Handler {handler_id.decode()[:8]}...")
    else:
        logger.warning("No task-to-handler mappings found")
    
    # Clean up
    await redis.close()
    logger.info("\n✅ Handler tracking test complete")


if __name__ == "__main__":
    asyncio.run(test_handler_tracking())