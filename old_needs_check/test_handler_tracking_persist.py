#!/usr/bin/env python
"""
Test handler tracking with persistence.
This test does NOT flush Redis at the end, so data persists.
"""

import asyncio
import json
import uuid
import logging
from datetime import datetime

import redis.asyncio as aioredis

from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.handlers import handler_loader
from gleitzeit.core.sharding import default_sharding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_and_persist():
    """Test handler tracking and persist data in Redis"""
    
    # Get Ollama handler
    registry = handler_loader.get_registry()
    OllamaHandler = registry.get_handler("ollama/v1")
    
    if not OllamaHandler:
        logger.error("Ollama handler not found")
        return
    
    # Create handler instance
    handler_config = {
        "base_url": "http://localhost:11434",
        "worker_id": "persistent-test-worker"
    }
    handler = OllamaHandler(handler_config)
    
    logger.info(f"Created handler with ID: {handler.handler_id}")
    
    # Create test task
    workflow_id = "persist-workflow-" + str(uuid.uuid4())
    task_id = "persist-task-" + str(uuid.uuid4())
    
    task = Task(
        id=task_id,
        name="Persistent Handler Test",
        workflow_id=workflow_id,
        protocol="ollama/v1",
        method="ollama/generate",
        params={
            "model": "llama3.2",
            "prompt": "Say 'Data persisted successfully' in exactly 3 words.",
            "stream": False
        }
    )
    
    logger.info(f"Created task: {task.id}")
    logger.info(f"Workflow: {workflow_id}")
    
    # Execute task
    try:
        result = await handler.execute(task)
        logger.info(f"Task executed: {result.status}")
        logger.info(f"Response: {result.result.get('response', 'No response')}")
        
    except Exception as e:
        logger.error(f"Task execution failed: {e}")
        logger.info("Make sure Ollama is running")
        return
    
    # Store in Redis
    redis = aioredis.from_url("redis://localhost:6379", decode_responses=False)
    
    try:
        # 1. Store handler registry with explicit TTL
        handler_info = handler.get_handler_info()
        handler_info['worker_id'] = handler_config['worker_id']
        handler_key = f"handler:registry:{handler.handler_id}"
        
        await redis.hset(
            handler_key.encode(),
            mapping={k.encode(): json.dumps(v).encode() if isinstance(v, dict) else str(v).encode()
                     for k, v in handler_info.items()}
        )
        # Set 24 hour TTL
        await redis.expire(handler_key.encode(), 86400)
        
        logger.info(f"\n✅ Stored handler registry: {handler_key}")
        
        # 2. Store task-to-handler mapping
        mapping_key = f"task:handler:{task.id}"
        await redis.set(mapping_key.encode(), handler.handler_id.encode(), ex=86400)
        
        logger.info(f"✅ Stored task mapping: {mapping_key[:30]}... -> {handler.handler_id[:8]}...")
        
        # 3. Store task data with handler info (as TaskExecutionWorker would)
        task_data_key = default_sharding.get_task_key(task_id, workflow_id)
        await redis.hset(
            task_data_key.encode(),
            mapping={
                b"task_id": task_id.encode(),
                b"workflow_id": workflow_id.encode(),
                b"status": TaskStatus.COMPLETED.encode(),
                b"result": json.dumps(result.result).encode(),
                b"handler_id": handler.handler_id.encode(),
                b"worker_id": handler_config['worker_id'].encode(),
                b"completed_at": datetime.utcnow().isoformat().encode()
            }
        )
        
        logger.info(f"✅ Stored task data: {task_data_key}")
        
        # 4. Add to task:completed stream with handler tracking
        message = {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"result": json.dumps(result.result).encode(),
            b"timestamp": datetime.utcnow().isoformat().encode(),
            # Handler tracking fields
            b"worker_id": handler_config['worker_id'].encode(),
            b"handler_id": handler.handler_id.encode(),
            b"handler_protocol": b"ollama/v1",
            b"provider_url": handler.base_url.encode(),
            b"worker_instance_url": b"test-persist-host"
        }
        
        stream_key = default_sharding.get_stream_key("task:completed", workflow_id)
        msg_id = await redis.xadd(stream_key.encode(), message)
        
        logger.info(f"✅ Added to stream: {stream_key} (msg: {msg_id.decode()})")
        
        # Summary
        logger.info("\n" + "="*50)
        logger.info("👾 DATA PERSISTED IN REDIS:")
        logger.info("="*50)
        logger.info(f"1. Handler Registry: handler:registry:{handler.handler_id[:8]}...")
        logger.info(f"2. Task Mapping: task:handler:{task_id[:16]}...")
        logger.info(f"3. Task Data: {task_data_key}")
        logger.info(f"4. Stream Entry: {stream_key}")
        logger.info("\nThis data will persist in Redis for 24 hours.")
        logger.info("Run 'python check_handler_persistence.py' to verify.")
        
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(test_and_persist())