"""
Redis persistence backend for Gleitzeit V4

High-performance distributed storage with pub/sub capabilities.
Ideal for multi-node deployments and real-time coordination.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import redis.asyncio as redis

from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.core.errors import (
    ErrorCode, PersistenceError, PersistenceConnectionError,
    SystemError
)

logger = logging.getLogger(__name__)


class RedisBackend(PersistenceBackend):
    """Redis-based persistence backend with pub/sub support"""
    
    def __init__(self, 
                 host: str = "localhost", 
                 port: int = 6379, 
                 db: int = 0,
                 password: Optional[str] = None,
                 key_prefix: str = "gleitzeit:"):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.key_prefix = key_prefix
        self.redis_client: Optional[redis.Redis] = None
        self._initialized = False
    
    def _key(self, suffix: str) -> str:
        """Generate prefixed Redis key"""
        return f"{self.key_prefix}{suffix}"
    
    async def initialize(self) -> None:
        """Initialize Redis connection"""
        if self._initialized:
            return
        
        self.redis_client = redis.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password,
            decode_responses=True
        )
        
        # Test connection
        try:
            await self.redis_client.ping()
            logger.info(f"Redis backend initialized: {self.host}:{self.port}/{self.db}")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise PersistenceConnectionError(
                backend="Redis",
                connection_string=f"redis://{self.host}:{self.port}/{self.db}",
                cause=e
            )
    
    async def shutdown(self) -> None:
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
            self.redis_client = None
        self._initialized = False
    
    # Task operations
    async def save_task(self, task: Task) -> None:
        """Save or update a task"""
        # Get existing task to handle status changes
        existing_task = await self.get_task(task.id)
        
        task_data = task.dict()
        
        # Convert datetime objects to ISO strings
        for field in ['created_at', 'started_at', 'completed_at']:
            if task_data.get(field):
                task_data[field] = task_data[field].isoformat()
        
        # Save task data
        await self.redis_client.hset(
            self._key(f"task:{task.id}"),
            mapping={"data": json.dumps(task_data)}
        )
        
        # Handle status index updates with event-driven approach
        current_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
        
        if existing_task and str(existing_task.status) != str(task.status):
            # Remove from old status index
            old_status = existing_task.status.value if hasattr(existing_task.status, 'value') else str(existing_task.status)
            await self.redis_client.srem(
                self._key(f"tasks:status:{old_status}"),
                task.id
            )
        
        # Add to current status index
        await self.redis_client.sadd(
            self._key(f"tasks:status:{current_status}"),
            task.id
        )
        
        # Add to workflow index if applicable
        if task.workflow_id:
            await self.redis_client.sadd(
                self._key(f"workflow:{task.workflow_id}:tasks"),
                task.id
            )
        
        # Set TTL for completed/failed tasks (optional cleanup)
        if current_status in ["completed", "failed"]:
            await self.redis_client.expire(
                self._key(f"task:{task.id}"),
                int(timedelta(days=7).total_seconds())  # Keep for 7 days
            )
        
        # Publish task state change event for event-driven coordination
        if existing_task and str(existing_task.status) != str(task.status):
            await self.publish_task_event(
                f"task:status_changed",
                task.id,
                {
                    "old_status": str(existing_task.status),
                    "new_status": current_status,
                    "workflow_id": task.workflow_id,
                    "retry_attempt": getattr(task, 'attempt_count', 0),
                    "event_source": "persistence"
                }
            )
        elif not existing_task:
            # New task created
            await self.publish_task_event(
                f"task:created", 
                task.id,
                {
                    "status": current_status,
                    "workflow_id": task.workflow_id,
                    "protocol": task.protocol,
                    "method": task.method,
                    "priority": str(task.priority),
                    "event_source": "persistence"
                }
            )
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        data = await self.redis_client.hget(
            self._key(f"task:{task_id}"), "data"
        )
        
        if not data:
            return None
        
        task_data = json.loads(data)
        return self._dict_to_task(task_data)
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        # Get task first to remove from indexes
        task = await self.get_task(task_id)
        if not task:
            return False
        
        # Remove from status index
        status_key = task.status.value if hasattr(task.status, 'value') else str(task.status)
        await self.redis_client.srem(
            self._key(f"tasks:status:{status_key}"),
            task_id
        )
        
        # Remove from workflow index
        if task.workflow_id:
            await self.redis_client.srem(
                self._key(f"workflow:{task.workflow_id}:tasks"),
                task_id
            )
        
        # Delete task data
        result = await self.redis_client.delete(self._key(f"task:{task_id}"))
        return result > 0
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get all tasks with a specific status"""
        task_ids = await self.redis_client.smembers(
            self._key(f"tasks:status:{status}")
        )
        
        tasks = []
        for task_id in task_ids:
            task = await self.get_task(task_id)
            if task:
                tasks.append(task)
        
        return sorted(tasks, key=lambda t: t.created_at)
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        task_ids = await self.redis_client.smembers(
            self._key(f"workflow:{workflow_id}:tasks")
        )
        
        tasks = []
        for task_id in task_ids:
            task = await self.get_task(task_id)
            if task:
                tasks.append(task)
        
        return sorted(tasks, key=lambda t: t.created_at)
    
    def _dict_to_task(self, task_data: Dict[str, Any]) -> Task:
        """Convert dict to Task object"""
        from gleitzeit.core.models import RetryConfig
        
        # Convert ISO strings back to datetime objects
        for field in ['created_at', 'started_at', 'completed_at']:
            if task_data.get(field):
                task_data[field] = datetime.fromisoformat(task_data[field])
        
        # Handle retry_config
        if task_data.get('retry_config'):
            task_data['retry_config'] = RetryConfig(**task_data['retry_config'])
        
        return Task(**task_data)
    
    # Task results
    async def save_task_result(self, task_result: TaskResult) -> None:
        """Save a task result"""
        result_data = task_result.dict()
        # Convert datetime fields to ISO format for JSON serialization
        if result_data.get('started_at'):
            result_data['started_at'] = result_data['started_at'].isoformat()
        if result_data.get('completed_at'):
            result_data['completed_at'] = result_data['completed_at'].isoformat()
        
        await self.redis_client.hset(
            self._key(f"result:{task_result.task_id}"),
            mapping={"data": json.dumps(result_data)}
        )
        
        # Set TTL for cleanup
        await self.redis_client.expire(
            self._key(f"result:{task_result.task_id}"),
            int(timedelta(days=30).total_seconds())  # Keep results longer
        )
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result by task ID"""
        data = await self.redis_client.hget(
            self._key(f"result:{task_id}"), "data"
        )
        
        if not data:
            return None
        
        result_data = json.loads(data)
        # Convert ISO format strings back to datetime objects
        if result_data.get('started_at'):
            result_data['started_at'] = datetime.fromisoformat(result_data['started_at'])
        if result_data.get('completed_at'):
            result_data['completed_at'] = datetime.fromisoformat(result_data['completed_at'])
        
        return TaskResult(**result_data)
    
    # Workflow operations
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save or update a workflow"""
        # Use json() method which handles datetime serialization properly
        workflow_json = workflow.json()
        
        await self.redis_client.hset(
            self._key(f"workflow:{workflow.id}"),
            mapping={"data": workflow_json}
        )
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID"""
        data = await self.redis_client.hget(
            self._key(f"workflow:{workflow_id}"), "data"
        )
        
        if not data:
            return None
        
        # Parse JSON directly into Workflow object (handles datetime parsing)
        return Workflow.parse_raw(data)
    
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Save workflow execution state"""
        execution_data = execution.dict()
        execution_data['started_at'] = execution_data['started_at'].isoformat()
        if execution_data.get('completed_at'):
            execution_data['completed_at'] = execution_data['completed_at'].isoformat()
        
        await self.redis_client.hset(
            self._key(f"execution:{execution.execution_id}"),
            mapping={"data": json.dumps(execution_data)}
        )
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution by ID"""
        data = await self.redis_client.hget(
            self._key(f"execution:{execution_id}"), "data"
        )
        
        if not data:
            return None
        
        execution_data = json.loads(data)
        execution_data['started_at'] = datetime.fromisoformat(execution_data['started_at'])
        if execution_data.get('completed_at'):
            execution_data['completed_at'] = datetime.fromisoformat(execution_data['completed_at'])
        
        return WorkflowExecution(**execution_data)
    
    # Queue state operations
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        """Save queue state for recovery"""
        state_data = {
            "state": json.dumps(state),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        await self.redis_client.hset(
            self._key(f"queue:{queue_name}"),
            mapping=state_data
        )
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Get saved queue state"""
        data = await self.redis_client.hget(
            self._key(f"queue:{queue_name}"), "state"
        )
        
        if not data:
            return None
        
        return json.loads(data)
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        """Delete queue state"""
        result = await self.redis_client.delete(self._key(f"queue:{queue_name}"))
        return result > 0
    
    # Bulk operations
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        """Save multiple tasks efficiently using pipeline"""
        if not tasks:
            return
        
        pipe = self.redis_client.pipeline()
        
        for task in tasks:
            task_data = task.dict()
            
            # Convert datetime objects
            for field in ['created_at', 'started_at', 'completed_at']:
                if task_data.get(field):
                    task_data[field] = task_data[field].isoformat()
            
            # Save task
            pipe.hset(
                self._key(f"task:{task.id}"),
                mapping={"data": json.dumps(task_data)}
            )
            
            # Add to status index
            pipe.sadd(self._key(f"tasks:status:{task.status.value}"), task.id)
            
            # Add to workflow index
            if task.workflow_id:
                pipe.sadd(
                    self._key(f"workflow:{task.workflow_id}:tasks"),
                    task.id
                )
        
        await pipe.execute()
    
    async def get_all_queued_tasks(self) -> List[Task]:
        """Get all tasks that should be in queues on startup"""
        statuses = ["queued", "retry_pending", "executing"]
        all_tasks = []
        
        for status in statuses:
            tasks = await self.get_tasks_by_status(status)
            all_tasks.extend(tasks)
        
        return sorted(all_tasks, key=lambda t: t.created_at)
    
    # Statistics
    async def get_task_count_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        counts = {}
        
        # Get all status keys
        status_keys = await self.redis_client.keys(self._key("tasks:status:*"))
        
        for key in status_keys:
            status = key.split(":")[-1]  # Extract status from key
            count = await self.redis_client.scard(key)
            counts[status] = count
        
        return counts
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        """Remove old completed tasks and results before cutoff date"""
        deleted_count = 0
        
        # Get completed and failed tasks
        for status in ["completed", "failed"]:
            tasks = await self.get_tasks_by_status(status)
            
            for task in tasks:
                if task.completed_at and task.completed_at < cutoff_date:
                    await self.delete_task(task.id)
                    
                    # Delete result too
                    await self.redis_client.delete(self._key(f"result:{task.id}"))
                    deleted_count += 1
        
        return deleted_count
    
    # Redis-specific features
    async def publish_task_event(self, event_type: str, task_id: str, data: Dict[str, Any]) -> None:
        """Publish task event for real-time updates"""
        event_data = {
            "event_type": event_type,
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            **data
        }
        
        await self.redis_client.publish(
            self._key("events:tasks"),
            json.dumps(event_data)
        )
    
    async def subscribe_to_task_events(self) -> redis.client.PubSub:
        """Subscribe to task events for real-time updates"""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(self._key("events:tasks"))
        return pubsub
    
    async def get_queue_size(self, queue_name: str) -> int:
        """Get current size of a queue from Redis"""
        return await self.redis_client.scard(self._key(f"queue:{queue_name}:tasks"))
    
    async def add_to_retry_queue(self, task_id: str, retry_at: datetime) -> None:
        """Add task to retry queue with timestamp (event-driven integration)"""
        await self.redis_client.zadd(
            self._key("retry_queue"),
            {task_id: retry_at.timestamp()}
        )
        
        # Publish retry scheduled event for coordination
        await self.publish_task_event(
            "task:retry_scheduled",
            task_id,
            {
                "retry_at": retry_at.isoformat(),
                "scheduled_timestamp": retry_at.timestamp(),
                "event_source": "persistence"
            }
        )
    
    async def get_ready_retry_tasks(self) -> List[str]:
        """Get tasks ready for retry (event-driven approach)"""
        now = datetime.utcnow().timestamp()
        
        # Get tasks with score <= now
        task_ids = await self.redis_client.zrangebyscore(
            self._key("retry_queue"),
            0, now
        )
        
        # Remove from retry queue and publish events
        if task_ids:
            await self.redis_client.zrem(
                self._key("retry_queue"),
                *task_ids
            )
            
            # Publish retry ready events
            for task_id in task_ids:
                await self.publish_task_event(
                    "task:retry_ready",
                    task_id,
                    {
                        "ready_at": datetime.utcnow().isoformat(),
                        "event_source": "persistence"
                    }
                )
        
        return task_ids
    
    async def remove_from_retry_queue(self, task_id: str) -> bool:
        """Remove task from retry queue (for cancellation)"""
        result = await self.redis_client.zrem(self._key("retry_queue"), task_id)
        
        if result > 0:
            await self.publish_task_event(
                "task:retry_cancelled",
                task_id,
                {"event_source": "persistence"}
            )
        
        return result > 0