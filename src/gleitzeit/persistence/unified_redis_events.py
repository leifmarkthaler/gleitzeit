"""
Enhanced Redis Persistence Adapter with Event-Driven Architecture

Extends the base Redis adapter with full event support for real-time coordination.
"""

import json
import logging
import asyncio
import uuid
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import Task, TaskStatus, Workflow, WorkflowStatus, TaskResult
from gleitzeit.core.events import (
    GleitzeitEvent, EventType, EventSeverity,
    create_task_started_event, create_task_completed_event,
    create_task_failed_event, create_workflow_completed_event
)

logger = logging.getLogger(__name__)


class UnifiedRedisEventsAdapter(UnifiedRedisAdapter):
    """
    Redis adapter with full event-driven architecture support.
    
    Features:
    - Event publishing via Redis pub/sub
    - Event subscription and handling
    - Atomic workflow completion checking
    - Distributed locking for coordination
    """
    
    def __init__(self, *args, event_bus=None, **kwargs):
        """
        Initialize with event support.
        
        Args:
            event_bus: Optional EventBus for local event distribution
            *args, **kwargs: Passed to parent UnifiedRedisAdapter
        """
        super().__init__(*args, **kwargs)
        self.event_bus = event_bus
        self._event_listeners = {}
        self._subscription_task = None
        self._event_handlers: Dict[str, List[Callable]] = {}
        
        # Enable pub/sub for events
        self.enable_pubsub = True
    
    # =========================================================================
    # Event Publishing
    # =========================================================================
    
    async def emit_event(self, event: GleitzeitEvent) -> None:
        """
        Emit an event via Redis pub/sub and local event bus.
        
        Args:
            event: The event to emit
        """
        if not self._initialized:
            logger.warning("Redis adapter not initialized, cannot emit event")
            return
        
        try:
            # Get the string representation of event type
            if hasattr(event.event_type, 'value'):
                event_type_str = event.event_type.value
            elif isinstance(event.event_type, str):
                event_type_str = event.event_type
            else:
                event_type_str = str(event.event_type).replace('EventType.', '')
            
            # Prepare event data
            event_data = {
                'event_type': event_type_str,
                'severity': str(event.severity.value if hasattr(event.severity, 'value') else event.severity),
                'data': event.data,
                'source': event.source,
                'tags': event.tags,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Publish to Redis channel  
            channel = self._key("events", event_type_str)
            result = await self.redis.publish(channel, json.dumps(event_data))
            
            logger.info(f"Published {event_data['event_type']} event to Redis channel {channel} ({result} subscribers)")
            
            # Also emit to local event bus if available
            if self.event_bus:
                await self.event_bus.emit(event)
                
        except Exception as e:
            logger.error(f"Failed to emit event {event.event_type}: {e}")
    
    # =========================================================================
    # Enhanced Task Operations with Events
    # =========================================================================
    
    async def save_task(self, task: Task) -> None:
        """Save task and emit appropriate events"""
        # Get previous status for event decisions
        existing_task = await self.get_task(task.id)
        old_status = existing_task.status if existing_task else None
        
        # Save using parent method
        await super().save_task(task)
        
        # Emit events based on status changes
        if old_status != task.status:
            if task.status == TaskStatus.EXECUTING:
                event = create_task_started_event(
                    task_id=task.id,
                    task_name=task.name,
                    protocol=task.protocol,
                    method=task.method,
                    workflow_id=task.workflow_id,
                    source="redis_persistence"
                )
                await self.emit_event(event)
                
            elif task.status == TaskStatus.COMPLETED:
                event = create_task_completed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    duration=(task.completed_at - task.started_at).total_seconds() if task.started_at and task.completed_at else 0,
                    source="redis_persistence"
                )
                await self.emit_event(event)
                
            elif task.status == TaskStatus.FAILED:
                event = create_task_failed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    error=task.error_message,
                    source="redis_persistence"
                )
                await self.emit_event(event)
    
    async def save_task_result(self, result: TaskResult) -> None:
        """Save task result and emit completion event"""
        # Save using parent method
        await super().save_task_result(result)
        
        # Emit task completed event with result
        event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            severity=EventSeverity.INFO,
            data={
                'task_id': result.task_id,
                'workflow_id': result.workflow_id,
                'status': str(result.status.value if hasattr(result.status, 'value') else result.status),
                'result': result.result,
                'error': result.error,
                'has_result': True
            },
            source="redis_persistence",
            tags={'component': 'persistence', 'with_result': 'true'}
        )
        await self.emit_event(event)
    
    # =========================================================================
    # Atomic Workflow Completion
    # =========================================================================
    
    async def check_and_complete_workflow(self, workflow_id: str) -> bool:
        """
        Atomically check if workflow is complete and emit event if so.
        
        Uses Lua script for atomic operation to prevent race conditions.
        
        Args:
            workflow_id: The workflow to check
            
        Returns:
            True if workflow was completed, False otherwise
        """
        if not self._initialized:
            return False
        
        # Lua script for atomic workflow completion check
        lua_script = """
        local workflow_key = KEYS[1]
        local tasks_index_key = KEYS[2]
        local events_channel = KEYS[3]
        local current_time = ARGV[1]
        
        -- Check if workflow exists
        local workflow_data = redis.call('HGETALL', workflow_key)
        if #workflow_data == 0 then
            return 0
        end
        
        -- Convert to table for easier access
        local workflow = {}
        for i = 1, #workflow_data, 2 do
            workflow[workflow_data[i]] = workflow_data[i + 1]
        end
        
        -- Check if already completed
        if workflow['status'] == 'completed' or workflow['status'] == 'failed' then
            return 0
        end
        
        -- Get all task IDs for this workflow
        local task_ids = redis.call('SMEMBERS', tasks_index_key)
        if #task_ids == 0 then
            return 0
        end
        
        -- Check status of all tasks
        local completed_count = 0
        local failed_count = 0
        local pending_count = 0
        local task_results = {}
        
        for _, task_id in ipairs(task_ids) do
            local task_key = 'gleitzeit:task:' .. task_id
            local task_status = redis.call('HGET', task_key, 'status')
            
            if task_status == 'completed' then
                completed_count = completed_count + 1
                
                -- Get task result if available
                local result_key = 'gleitzeit:task_result:' .. task_id
                local result_data = redis.call('HGETALL', result_key)
                if #result_data > 0 then
                    table.insert(task_results, task_id)
                end
            elseif task_status == 'failed' then
                failed_count = failed_count + 1
            elseif task_status ~= 'cancelled' then
                pending_count = pending_count + 1
            end
        end
        
        -- Check if workflow is complete
        if pending_count > 0 then
            return 0  -- Still have pending tasks
        end
        
        -- Workflow is complete - update status
        local final_status = 'completed'
        if failed_count > 0 then
            final_status = 'failed'
        end
        
        -- Update workflow status atomically
        redis.call('HSET', workflow_key, 'status', final_status)
        redis.call('HSET', workflow_key, 'completed_at', current_time)
        redis.call('HSET', workflow_key, 'completed_tasks', completed_count)
        redis.call('HSET', workflow_key, 'failed_tasks', failed_count)
        
        -- Return completion info
        return {final_status, completed_count, failed_count, #task_ids}
        """
        
        try:
            # Execute Lua script
            result = await self.redis.eval(
                lua_script,
                3,  # Number of keys
                self._workflow_key(workflow_id),  # KEYS[1]
                self._workflow_index_key(workflow_id),  # KEYS[2]
                self._key("events", "WORKFLOW_COMPLETED"),  # KEYS[3]
                datetime.utcnow().isoformat()  # ARGV[1]
            )
            
            if result and result != 0:
                # Workflow completed - emit event
                status, completed_count, failed_count, total_count = result
                
                # Get workflow details for event
                workflow = await self.get_workflow(workflow_id)
                if workflow:
                    # Collect task results
                    task_results = {}
                    for task in workflow.tasks:
                        task_result = await self.get_task_result(task.id)
                        if task_result:
                            task_results[task.id] = {
                                'status': 'completed' if task_result.status == TaskStatus.COMPLETED else 'failed',
                                'result': task_result.result,
                                'error': task_result.error
                            }
                    
                    # Emit workflow completed event
                    event = GleitzeitEvent(
                        event_type=EventType.WORKFLOW_COMPLETED,
                        severity=EventSeverity.INFO,
                        data={
                            'workflow_id': workflow_id,
                            'workflow_name': workflow.name,
                            'status': status,
                            'completed_tasks': completed_count,
                            'failed_tasks': failed_count,
                            'total_tasks': total_count,
                            'task_results': task_results,
                            'duration': (workflow.completed_at - workflow.started_at).total_seconds() if workflow.started_at and workflow.completed_at else 0
                        },
                        source="redis_persistence",
                        tags={'component': 'persistence', 'atomic': 'true'}
                    )
                    await self.emit_event(event)
                    
                    logger.info(f"Workflow {workflow_id} completed with status {status}")
                    return True
                    
        except Exception as e:
            logger.error(f"Failed to check workflow completion for {workflow_id}: {e}")
            
        return False
    
    # =========================================================================
    # Event Subscription and Handling
    # =========================================================================
    
    async def start_event_subscription(self, event_types: List[str] = None) -> None:
        """
        Start subscribing to Redis event channels.
        
        Args:
            event_types: List of event types to subscribe to (None = all)
        """
        if not self._initialized:
            await self.initialize()
        
        if self._subscription_task and not self._subscription_task.done():
            logger.warning("Event subscription already running")
            return
        
        # Default to all event types
        if event_types is None:
            event_types = [
                'TASK_STARTED', 'TASK_COMPLETED', 'TASK_FAILED',
                'WORKFLOW_STARTED', 'WORKFLOW_COMPLETED', 'WORKFLOW_FAILED'
            ]
        
        # Start subscription task
        self._subscription_task = asyncio.create_task(
            self._event_subscription_loop(event_types)
        )
        logger.info(f"Started event subscription for {len(event_types)} event types")
    
    async def _event_subscription_loop(self, event_types: List[str]) -> None:
        """
        Main event subscription loop.
        
        Args:
            event_types: Event types to subscribe to
        """
        try:
            # Create pubsub instance
            pubsub = self.redis.pubsub()
            
            # Subscribe to channels
            channels = [self._key("events", event_type) for event_type in event_types]
            await pubsub.subscribe(*channels)
            
            logger.info(f"Subscribed to {len(channels)} Redis event channels")
            
            # Process messages
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        # Parse event data
                        event_data = json.loads(message['data'])
                        event_type = event_data.get('event_type')
                        
                        # Call registered handlers
                        if event_type in self._event_handlers:
                            for handler in self._event_handlers[event_type]:
                                try:
                                    await handler(event_data)
                                except Exception as e:
                                    logger.error(f"Event handler error for {event_type}: {e}")
                                    
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse event message: {e}")
                    except Exception as e:
                        logger.error(f"Error processing event message: {e}")
                        
        except asyncio.CancelledError:
            logger.info("Event subscription cancelled")
            raise
        except Exception as e:
            logger.error(f"Event subscription loop error: {e}")
        finally:
            if pubsub:
                await pubsub.close()
    
    def register_event_handler(self, event_type: str, handler: Callable) -> None:
        """
        Register a handler for an event type.
        
        Args:
            event_type: The event type to handle
            handler: Async function to handle the event
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.debug(f"Registered handler for {event_type}")
    
    async def stop_event_subscription(self) -> None:
        """Stop event subscription"""
        if self._subscription_task and not self._subscription_task.done():
            self._subscription_task.cancel()
            try:
                await self._subscription_task
            except asyncio.CancelledError:
                pass
            self._subscription_task = None
            logger.info("Stopped event subscription")
    
    # =========================================================================
    # Distributed Locking
    # =========================================================================
    
    async def acquire_lock(self, resource_id: str, timeout_ms: int = 5000) -> Optional[str]:
        """
        Acquire a distributed lock using Redis SET NX.
        
        Args:
            resource_id: Resource to lock
            timeout_ms: Lock timeout in milliseconds
            
        Returns:
            Lock token if acquired, None otherwise
        """
        if not self._initialized:
            return None
        
        lock_key = self._lock_key(resource_id)
        lock_token = str(uuid.uuid4())
        
        try:
            # Try to acquire lock with timeout
            acquired = await self.redis.set(
                lock_key,
                lock_token,
                nx=True,  # Only set if not exists
                px=timeout_ms  # Expire after timeout
            )
            
            if acquired:
                logger.debug(f"Acquired lock for {resource_id}")
                return lock_token
            else:
                logger.debug(f"Failed to acquire lock for {resource_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error acquiring lock for {resource_id}: {e}")
            return None
    
    async def release_lock(self, resource_id: str, lock_token: str) -> bool:
        """
        Release a distributed lock if we own it.
        
        Args:
            resource_id: Resource to unlock
            lock_token: Token received when lock was acquired
            
        Returns:
            True if lock was released, False otherwise
        """
        if not self._initialized:
            return False
        
        lock_key = self._lock_key(resource_id)
        
        # Lua script to atomically check and delete
        lua_script = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        else
            return 0
        end
        """
        
        try:
            result = await self.redis.eval(lua_script, 1, lock_key, lock_token)
            
            if result == 1:
                logger.debug(f"Released lock for {resource_id}")
                return True
            else:
                logger.debug(f"Failed to release lock for {resource_id} (not owner)")
                return False
                
        except Exception as e:
            logger.error(f"Error releasing lock for {resource_id}: {e}")
            return False
    
    # =========================================================================
    # Lifecycle Override
    # =========================================================================
    
    async def shutdown(self) -> None:
        """Shutdown with event cleanup"""
        # Stop event subscription
        await self.stop_event_subscription()
        
        # Call parent shutdown
        await super().shutdown()