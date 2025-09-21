#!/usr/bin/env python3
"""
Force event consumption by manually triggering handler processing.
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def force_consume_events():
    """Force the consumption of pending events."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    
    logger.info("=== Forcing Event Consumption ===")
    
    # Get SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    # Wait for initialization
    await asyncio.sleep(2)
    
    # Get the event bus
    event_bus = system_manager.event_bus
    redis = system_manager.persistence.redis
    
    # Check for unconsumed messages in task:submitted stream
    stream_key = "gleitzeit:events:stream:task:submitted"
    
    # Read last few messages directly
    messages = await redis.xread({stream_key: '0'}, count=10)
    
    if messages:
        logger.info(f"Found {len(messages[0][1])} messages in {stream_key}")
        
        # Get the QueueManager's handler
        if hasattr(system_manager, 'queue_manager'):
            qm = system_manager.queue_manager
            
            # Process each message manually
            for msg_id, data in messages[0][1]:
                # Decode data
                decoded = {}
                for k, v in data.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v
                    decoded[key] = val
                
                if 'data' in decoded:
                    import json
                    event_data = json.loads(decoded['data'])
                    task_id = event_data.get('task_id')
                    
                    if task_id:
                        logger.info(f"Processing task {task_id}")
                        
                        # Get the task
                        task = await system_manager.persistence.get_task(task_id)
                        if task and task.status == TaskStatus.PENDING:
                            logger.info(f"Task {task_id} is PENDING, forcing to QUEUED")
                            
                            # Force enqueue
                            from gleitzeit.core.events import EventType, GleitzeitEvent
                            
                            # Update status
                            task.status = TaskStatus.QUEUED
                            await system_manager.persistence.save_task(task)
                            
                            # Emit TASK_READY
                            ready_event = GleitzeitEvent(
                                event_type=EventType.TASK_READY,
                                data={
                                    'task_id': task_id,
                                    'workflow_id': task.workflow_id,
                                    'protocol': task.protocol,
                                    'method': task.method
                                },
                                source="force_consume"
                            )
                            await event_bus.emit(ready_event)
                            logger.info(f"Emitted TASK_READY for {task_id}")
    
    # Now check if TaskOrchestrator picks up TASK_READY
    await asyncio.sleep(3)
    
    # Check for TASK_READY messages
    ready_stream = "gleitzeit:events:stream:task:ready"
    ready_messages = await redis.xread({ready_stream: '0'}, count=10)
    
    if ready_messages:
        logger.info(f"Found {len(ready_messages[0][1])} TASK_READY messages")
        
        # Check if orchestrator has these handlers
        if 'task:ready' in event_bus._handlers:
            handlers = event_bus._handlers['task:ready']
            logger.info(f"Found {len(handlers)} handlers for task:ready")
            
            # Try calling handler directly
            if handlers and ready_messages[0][1]:
                msg_id, data = ready_messages[0][1][-1]  # Get last message
                
                # Create event manually
                from gleitzeit.core.events import GleitzeitEvent
                decoded = {}
                for k, v in data.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v
                    decoded[key] = val
                
                if 'data' in decoded:
                    import json
                    event_data = json.loads(decoded['data'])
                    
                    event = GleitzeitEvent(
                        event_type="task:ready",
                        data=event_data,
                        source=decoded.get('source', '')
                    )
                    
                    # Call handler directly
                    logger.info(f"Manually calling task:ready handler for task {event_data.get('task_id')}")
                    for handler in handlers:
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(event)
                            else:
                                handler(event)
                            logger.info("Handler called successfully")
                        except Exception as e:
                            logger.error(f"Handler error: {e}")
    
    # Final check
    await asyncio.sleep(5)
    
    # Check all pending tasks
    tasks = await redis.keys("task:*")
    for task_key in tasks[:5]:  # Check first 5
        if isinstance(task_key, bytes):
            task_key = task_key.decode()
        if ':result:' not in task_key:  # Skip result keys
            task_data = await redis.hgetall(task_key)
            if task_data:
                status = task_data.get(b'status', b'').decode() if b'status' in task_data else ''
                task_id = task_key.replace('task:', '')
                logger.info(f"Task {task_id}: {status}")
    
    logger.info("=== Force Consumption Complete ===")

if __name__ == "__main__":
    asyncio.run(force_consume_events())