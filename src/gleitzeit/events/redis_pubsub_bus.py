"""
Redis Pub/Sub based event bus for truly stateless event handling.

This implementation uses Redis Pub/Sub which requires no handler registration.
Workers simply subscribe to channels and receive events in real-time.
"""

import asyncio
import logging
import json
from typing import Dict, Set, Callable, Optional, Any
from datetime import datetime

from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class RedisPubSubBus:
    """
    Redis Pub/Sub based event bus for stateless operation.
    
    Key advantages:
    - No handler registration needed in persistence
    - Real-time event delivery
    - Multiple workers can subscribe to same events
    - Truly stateless - workers can come and go
    """
    
    def __init__(self, redis_client):
        """
        Initialize Redis Pub/Sub event bus.
        
        Args:
            redis_client: Redis client instance
        """
        self.redis = redis_client
        self._subscribers: Dict[str, asyncio.Task] = {}
        self._handlers: Dict[str, Set[Callable]] = {}
        self._running = False
        
        logger.info("Initialized RedisPubSubBus")
    
    async def start(self):
        """Start the event bus."""
        self._running = True
        logger.info("RedisPubSubBus started")
    
    async def stop(self):
        """Stop the event bus and all subscribers."""
        self._running = False
        
        # Cancel all subscriber tasks
        for task in self._subscribers.values():
            task.cancel()
        
        # Wait for tasks to complete
        if self._subscribers:
            await asyncio.gather(*self._subscribers.values(), return_exceptions=True)
        
        self._subscribers.clear()
        logger.info("RedisPubSubBus stopped")
    
    async def emit(self, event: GleitzeitEvent) -> None:
        """
        Emit an event to Redis Pub/Sub channel.
        
        Args:
            event: Event to emit
        """
        # Convert event type to channel name
        channel = self._get_channel_name(event.event_type)
        
        # Serialize event data
        message = json.dumps({
            'event_type': str(event.event_type.value if hasattr(event.event_type, 'value') else event.event_type),
            'data': event.data,
            'timestamp': datetime.utcnow().isoformat(),
            'source': getattr(event, 'source', 'unknown')
        })
        
        # Publish to Redis channel
        subscribers = await self.redis.publish(channel, message)
        logger.debug(f"Published {event.event_type} to {subscribers} subscribers")
    
    async def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """
        Subscribe to an event type.
        
        Args:
            event_type: Event type to subscribe to
            handler: Handler function to call
        """
        channel = self._get_channel_name(event_type)
        
        # Store handler locally
        if channel not in self._handlers:
            self._handlers[channel] = set()
        self._handlers[channel].add(handler)
        
        # Start subscriber task if not already running
        if channel not in self._subscribers:
            self._subscribers[channel] = asyncio.create_task(
                self._subscribe_channel(channel)
            )
        
        logger.info(f"Subscribed to {event_type} events")
    
    async def _subscribe_channel(self, channel: str):
        """
        Subscribe to a Redis channel and process messages.
        
        Args:
            channel: Channel name to subscribe to
        """
        # Create pubsub instance
        pubsub = self.redis.pubsub()
        
        try:
            # Subscribe to channel
            await pubsub.subscribe(channel)
            logger.info(f"Listening on channel: {channel}")
            
            # Process messages
            while self._running:
                try:
                    # Get message with timeout
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0
                    )
                    
                    if message and message['type'] == 'message':
                        await self._process_message(channel, message['data'])
                        
                except asyncio.TimeoutError:
                    continue  # Normal timeout, check if still running
                except Exception as e:
                    logger.error(f"Error processing message on {channel}: {e}")
                    
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            logger.info(f"Unsubscribed from channel: {channel}")
    
    async def _process_message(self, channel: str, data: bytes):
        """
        Process a message from Redis Pub/Sub.
        
        Args:
            channel: Channel the message came from
            data: Message data
        """
        try:
            # Decode message
            message = json.loads(data)
            
            # Reconstruct event
            event = GleitzeitEvent(
                event_type=message['event_type'],
                data=message['data']
            )
            
            # Call local handlers
            handlers = self._handlers.get(channel, set())
            for handler in handlers:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Error in handler for {channel}: {e}")
                    
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message on {channel}: {e}")
        except Exception as e:
            logger.error(f"Error processing message on {channel}: {e}")
    
    def _get_channel_name(self, event_type: EventType) -> str:
        """
        Convert event type to channel name.
        
        Args:
            event_type: Event type
            
        Returns:
            Channel name for Redis Pub/Sub
        """
        if hasattr(event_type, 'value'):
            return f"gleitzeit:events:{event_type.value}"
        else:
            return f"gleitzeit:events:{event_type}"


class PubSubWorker:
    """
    Worker that subscribes to events and processes tasks.
    """
    
    def __init__(self, worker_id: str, redis_client, persistence):
        """
        Initialize worker.
        
        Args:
            worker_id: Unique worker ID
            redis_client: Redis client
            persistence: Persistence adapter
        """
        self.worker_id = worker_id
        self.bus = RedisPubSubBus(redis_client)
        self.persistence = persistence
        
        logger.info(f"Initialized PubSubWorker: {worker_id}")
    
    async def start(self):
        """Start the worker and subscribe to events."""
        await self.bus.start()
        
        # Subscribe to workflow submitted events
        await self.bus.subscribe(
            EventType.WORKFLOW_SUBMITTED,
            self._on_workflow_submitted
        )
        
        # Subscribe to task completed events
        await self.bus.subscribe(
            EventType.TASK_COMPLETED,
            self._on_task_completed
        )
        
        logger.info(f"Worker {self.worker_id} started and subscribed to events")
    
    async def stop(self):
        """Stop the worker."""
        await self.bus.stop()
        logger.info(f"Worker {self.worker_id} stopped")
    
    async def _on_workflow_submitted(self, event: GleitzeitEvent):
        """Handle workflow submission - execute ready tasks."""
        workflow_id = event.data.get('workflow_id')
        if not workflow_id:
            return
        
        logger.info(f"Worker {self.worker_id} processing workflow {workflow_id}")
        
        # Get workflow
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return
        
        # Find and execute tasks with no dependencies
        for task in workflow.tasks:
            if not task.dependencies:
                await self._execute_task(task)
    
    async def _on_task_completed(self, event: GleitzeitEvent):
        """Handle task completion - check for newly ready tasks."""
        task_id = event.data.get('task_id')
        workflow_id = event.data.get('workflow_id')
        
        if not task_id or not workflow_id:
            return
        
        logger.info(f"Task {task_id} completed, checking for ready tasks")
        
        # Get all tasks for workflow
        tasks = await self.persistence.get_tasks_by_workflow(workflow_id)
        
        for task in tasks:
            # Skip if not pending
            status = task.status.value if hasattr(task.status, 'value') else task.status
            if status != 'pending':
                continue
            
            # Check if dependencies are complete
            if task_id in task.dependencies:
                all_complete = True
                for dep_id in task.dependencies:
                    dep_task = await self.persistence.get_task(dep_id)
                    if not dep_task:
                        all_complete = False
                        break
                    dep_status = dep_task.status.value if hasattr(dep_task.status, 'value') else dep_task.status
                    if dep_status != 'completed':
                        all_complete = False
                        break
                
                if all_complete:
                    await self._execute_task(task)
    
    async def _execute_task(self, task):
        """Execute a task."""
        from gleitzeit.core.models import TaskStatus
        
        logger.info(f"Worker {self.worker_id} executing task {task.id}")
        
        try:
            # Update status to executing
            task.status = TaskStatus.EXECUTING
            await self.persistence.save_task(task)
        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return
        
        # Simulate execution
        await asyncio.sleep(1)
        
        # Mark as completed
        task.status = TaskStatus.COMPLETED
        await self.persistence.save_task(task)
        
        # Emit completion event
        await self.bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={
                'task_id': task.id,
                'workflow_id': task.workflow_id or 'unknown'
            }
        ))
        
        logger.info(f"Task {task.id} completed")