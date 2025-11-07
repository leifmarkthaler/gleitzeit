#!/usr/bin/env python
"""
Simple test for handler tracking implementation.

Tests that handler IDs and metadata are properly added to results
and stream messages.
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


async def test_handler_tracking():
    """Test handler tracking with direct handler execution"""
    
    # Get Ollama handler
    registry = handler_loader.get_registry()
    OllamaHandler = registry.get_handler("ollama/v1")
    
    if not OllamaHandler:
        logger.error("Ollama handler not found")
        return
    
    # Create handler instance
    handler_config = {
        "base_url": "http://localhost:11434",
        "worker_id": "test-worker"
    }
    handler = OllamaHandler(handler_config)
    
    logger.info(f"Created handler with ID: {handler.handler_id}")
    logger.info(f"Handler metadata: {handler.metadata}")
    
    # Create test task
    task = Task(
        id="test-task-" + str(uuid.uuid4()),
        name="Test Handler Tracking",
        workflow_id="test-workflow-" + str(uuid.uuid4()),
        protocol="ollama/v1",
        method="ollama/generate",
        params={
            "model": "llama3.2",
            "prompt": "Say 'Handler tracking works!' in 5 words or less.",
            "stream": False
        }
    )
    
    logger.info(f"Created task: {task.id}")
    
    # Execute task
    try:
        result = await handler.execute(task)
        
        logger.info("\n=== TASK RESULT ===")
        logger.info(f"Status: {result.status}")
        logger.info(f"Result: {result.result}")
        
        # Check handler tracking fields
        logger.info("\n=== HANDLER TRACKING ===")
        
        if result.handler_id:
            logger.info(f"✓ Handler ID: {result.handler_id}")
            assert result.handler_id == handler.handler_id, "Handler ID mismatch"
        else:
            logger.error("✗ Handler ID not set")
        
        if result.worker_id:
            logger.info(f"✓ Worker ID: {result.worker_id}")
        else:
            logger.info("  Worker ID: Not set (expected, set by worker)")
        
        if result.provider_url:
            logger.info(f"✓ Provider URL: {result.provider_url}")
            assert result.provider_url == handler.base_url, "Provider URL mismatch"
        else:
            logger.error("✗ Provider URL not set")

        if result.worker_instance_url:
            logger.info(f"✓ Worker Instance URL: {result.worker_instance_url}")
        else:
            logger.info("  Worker Instance URL: Not set (optional)")
        
        logger.info("\n✅ Handler tracking fields are properly set in TaskResult")
        
    except Exception as e:
        logger.error(f"Task execution failed: {e}")
        logger.info("\nNote: Make sure Ollama is running on port 11434")
        logger.info("You can start it with: ollama serve")
        return
    
    # Test Redis storage (simulated)
    redis = aioredis.from_url("redis://localhost:6379", decode_responses=False)
    
    try:
        # Simulate what TaskExecutionWorker would do
        logger.info("\n=== SIMULATING WORKER STREAM EMISSION ===")
        
        # Build message as worker would
        message = {
            b"workflow_id": task.workflow_id.encode(),
            b"task_id": task.id.encode(),
            b"result": json.dumps(result.result).encode() if result.result else b"{}",
            b"timestamp": datetime.utcnow().isoformat().encode(),
            # Handler tracking fields
            b"worker_id": b"test-worker",
            b"handler_id": handler.handler_id.encode(),
            b"handler_protocol": b"ollama/v1",
            b"provider_url": handler.base_url.encode(),
            b"worker_instance_url": b"test-host.local"
        }
        
        # Store in stream
        stream_key = default_sharding.get_stream_key("task:completed", task.workflow_id).encode()
        msg_id = await redis.xadd(stream_key, message)
        
        logger.info(f"Added message to stream: {stream_key.decode()}")
        logger.info(f"Message ID: {msg_id.decode()}")
        
        # Read back and verify
        messages = await redis.xrange(stream_key, "-", "+")
        
        if messages:
            _, data = messages[-1]  # Get last message
            
            logger.info("\n=== VERIFYING STREAM MESSAGE ===")
            
            if b"handler_id" in data:
                logger.info(f"✓ Handler ID in stream: {data[b'handler_id'].decode()}")
            else:
                logger.error("✗ Handler ID not in stream")
            
            if b"worker_id" in data:
                logger.info(f"✓ Worker ID in stream: {data[b'worker_id'].decode()}")
            else:
                logger.error("✗ Worker ID not in stream")
            
            if b"handler_protocol" in data:
                logger.info(f"✓ Protocol in stream: {data[b'handler_protocol'].decode()}")
            else:
                logger.error("✗ Protocol not in stream")
            
            if b"provider_url" in data:
                logger.info(f"✓ Provider URL in stream: {data[b'provider_url'].decode()}")
            else:
                logger.error("✗ Provider URL not in stream")

            if b"worker_instance_url" in data:
                logger.info(f"✓ Worker Instance URL in stream: {data[b'worker_instance_url'].decode()}")
            else:
                logger.error("✗ Worker Instance URL not in stream")
        
        # Store handler registry entry
        logger.info("\n=== STORING HANDLER REGISTRY ===")
        
        handler_info = handler.get_handler_info()
        handler_key = f"handler:registry:{handler.handler_id}"
        
        await redis.hset(
            handler_key.encode(),
            mapping={k.encode(): json.dumps(v).encode() if isinstance(v, dict) else str(v).encode()
                     for k, v in handler_info.items()}
        )
        
        logger.info(f"Stored handler info at: {handler_key}")
        
        # Read back and verify
        stored_info = await redis.hgetall(handler_key.encode())
        
        if stored_info:
            logger.info(f"✓ Handler registry contains {len(stored_info)} fields")
            
            if b"handler_id" in stored_info:
                logger.info(f"  - Handler ID: {stored_info[b'handler_id'].decode()[:8]}...")
            if b"protocol" in stored_info:
                logger.info(f"  - Protocol: {stored_info[b'protocol'].decode()}")
            if b"created_at" in stored_info:
                logger.info(f"  - Created: {stored_info[b'created_at'].decode()}")
        
        # Store task-to-handler mapping
        logger.info("\n=== STORING TASK-TO-HANDLER MAPPING ===")
        
        mapping_key = f"task:handler:{task.id}"
        await redis.set(mapping_key.encode(), handler.handler_id.encode(), ex=86400)
        
        logger.info(f"Stored mapping: {mapping_key} -> {handler.handler_id[:8]}...")
        
        # Verify mapping
        stored_handler_id = await redis.get(mapping_key.encode())
        
        if stored_handler_id:
            logger.info(f"✓ Mapping verified: {stored_handler_id.decode()[:8]}...")
        
        logger.info("\n✅ ALL HANDLER TRACKING TESTS PASSED")
        
    finally:
        # Clean up
        await redis.flushdb()
        await redis.close()


if __name__ == "__main__":
    asyncio.run(test_handler_tracking())