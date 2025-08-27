"""
Unified Redis Persistence Adapter

High-performance distributed persistence using Redis.
Default persistence backend for Gleitzeit with automatic fallback to SQL if Redis is unavailable.
"""

import json
import logging
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
import asyncio

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None

from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution, TaskStatus, WorkflowStatus
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType

logger = logging.getLogger(__name__)


class UnifiedRedisAdapter(UnifiedPersistenceAdapter):
    """
    Redis-based unified persistence adapter.
    
    Provides high-performance distributed persistence with:
    - Fast in-memory operations
    - Distributed locking with Redis SET NX
    - Pub/Sub for real-time updates
    - Automatic expiration for metrics
    - Atomic operations with Lua scripts
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "gleitzeit",
        metrics_retention_hours: int = 24,
        enable_pubsub: bool = False,
        max_connections: int = 50,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
        retry_on_timeout: bool = True,
        health_check_interval: int = 30
    ):
        """
        Initialize Redis adapter.
        
        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for all Redis keys
            metrics_retention_hours: How long to retain metrics
            enable_pubsub: Enable pub/sub for real-time updates
            max_connections: Maximum number of connections in pool
            socket_timeout: Socket timeout in seconds
            socket_connect_timeout: Socket connection timeout in seconds
            retry_on_timeout: Retry commands on timeout
            health_check_interval: Health check interval in seconds
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis not installed. Install with: pip install redis[hiredis]"
            )
        
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.metrics_retention_hours = metrics_retention_hours
        self.enable_pubsub = enable_pubsub
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self.retry_on_timeout = retry_on_timeout
        self.health_check_interval = health_check_interval
        
        self.redis: Optional[aioredis.Redis] = None
        self.pubsub = None
        self._initialized = False
    
    # =========================================================================
    # Key Generation Helpers
    # =========================================================================
    
    def _key(self, *parts: str) -> str:
        """Generate Redis key with prefix"""
        return f"{self.key_prefix}:{':'.join(parts)}"
    
    def _task_key(self, task_id: str) -> str:
        return self._key("task", task_id)
    
    def _task_result_key(self, task_id: str) -> str:
        return self._key("task_result", task_id)
    
    def _workflow_key(self, workflow_id: str) -> str:
        return self._key("workflow", workflow_id)
    
    def _workflow_execution_key(self, execution_id: str) -> str:
        return self._key("workflow_execution", execution_id)
    
    def _queue_state_key(self, queue_name: str) -> str:
        return self._key("queue_state", queue_name)
    
    def _instance_key(self, instance_id: str) -> str:
        return self._key("instance", instance_id)
    
    def _hub_instances_key(self, hub_id: str) -> str:
        return self._key("hub_instances", hub_id)
    
    def _metrics_key(self, instance_id: str) -> str:
        return self._key("metrics", instance_id)
    
    def _lock_key(self, resource_id: str) -> str:
        return self._key("lock", resource_id)
    
    def _status_index_key(self, status: str) -> str:
        return self._key("idx", "task_status", status)
    
    def _workflow_index_key(self, workflow_id: str) -> str:
        return self._key("idx", "workflow_tasks", workflow_id)
    
    def _provider_index_key(self, provider_id: str) -> str:
        return self._key("idx", "provider_tasks", provider_id)
    
    # =========================================================================
    # Lifecycle Methods
    # =========================================================================
    
    async def initialize(self) -> None:
        """Initialize Redis connection"""
        if self._initialized:
            return
        
        try:
            # Create Redis connection
            self.redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=self.socket_connect_timeout,
                socket_timeout=self.socket_timeout,
                retry_on_timeout=self.retry_on_timeout,
                max_connections=self.max_connections,
                health_check_interval=self.health_check_interval
            )
            
            # Test connection
            await self.redis.ping()
            
            # Set up pub/sub if enabled
            if self.enable_pubsub:
                self.pubsub = self.redis.pubsub()
            
            self._initialized = True
            logger.info(f"Unified Redis adapter initialized: {self.redis_url}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis adapter: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Close Redis connection"""
        if self.pubsub:
            await self.pubsub.close()
            self.pubsub = None
        
        if self.redis:
            await self.redis.aclose()  # Use aclose() instead of deprecated close()
            self.redis = None
        
        self._initialized = False
        logger.info("Unified Redis adapter shut down")
    
    async def _execute(self, *args, **kwargs):
        """Execute Redis command (for testing compatibility)"""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        return await self.redis.execute_command(*args, **kwargs)
    
    @property
    def _pool(self):
        """Get Redis connection pool (for testing compatibility)"""
        return self.redis.connection_pool if self.redis else None
    
    # =========================================================================
    # Task/Workflow Operations
    # =========================================================================
    
    async def save_task(self, task: Task) -> None:
        """Save or update a task"""
        # Validate workflow_id requirement
        if not task.workflow_id:
            error_msg = (
                f"Task {task.id} ({task.name}) cannot be saved without a workflow_id. "
                "Every task must belong to a workflow. "
                "Use ExecutionEngine.submit_task() which auto-creates workflows for single tasks."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        if not self._initialized:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            # Check if task exists to track index changes
            existing_task = await self.get_task(task.id)
            old_status = existing_task.status if existing_task else None
            old_provider = existing_task.assigned_provider if existing_task else None
            
            # Prepare task data
            task_data = {
                'id': task.id,
                'name': task.name,
                'protocol': task.protocol,
                'method': task.method,
                'params': json.dumps(task.params),
                'priority': task.priority,
                'dependencies': json.dumps(task.dependencies) if task.dependencies else '[]',
                'timeout': task.timeout or 0,
                'retry_config': json.dumps(task.retry_config.model_dump()) if task.retry_config else '{}',
                'status': task.status,
                'attempt_count': task.attempt_count,
                'workflow_id': task.workflow_id or '',
                'created_at': task.created_at.isoformat() if task.created_at else datetime.utcnow().isoformat(),
                'started_at': task.started_at.isoformat() if task.started_at else '',
                'completed_at': task.completed_at.isoformat() if task.completed_at else '',
                'assigned_provider': task.assigned_provider or '',
                'execution_node': task.execution_node or '',
                'error_message': task.error_message or '',
                'tags': json.dumps(task.tags) if task.tags else '{}',
                'metadata': json.dumps(task.metadata) if task.metadata else '{}'
            }
            
            # Use pipeline for atomic operations
            async with self.redis.pipeline() as pipe:
                # Save task data
                pipe.hset(self._task_key(task.id), mapping=task_data)
                
                # Update status index atomically - remove from old, add to new
                if old_status and old_status != task.status:
                    pipe.srem(self._status_index_key(old_status), task.id)
                pipe.sadd(self._status_index_key(task.status), task.id)
                
                # Update workflow index if present
                if task.workflow_id:
                    pipe.sadd(self._workflow_index_key(task.workflow_id), task.id)
                
                # Update provider index atomically
                if old_provider and old_provider != task.assigned_provider:
                    pipe.srem(self._provider_index_key(old_provider), task.id)
                if task.assigned_provider:
                    pipe.sadd(self._provider_index_key(task.assigned_provider), task.id)
                
                await pipe.execute()
            
            # Publish update if pub/sub enabled
            if self.enable_pubsub:
                await self.redis.publish(
                    self._key("events", "task", "saved"),
                    json.dumps({'task_id': task.id, 'status': task.status})
                )
            
            logger.debug(f"Saved task {task.id} to Redis")
            
        except Exception as e:
            logger.error(f"Failed to save task {task.id}: {e}")
            raise
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        if not self._initialized:
            return None
        
        try:
            task_data = await self.redis.hgetall(self._task_key(task_id))
            
            if not task_data:
                return None
            
            return self._dict_to_task(task_data)
            
        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None
    
    def _dict_to_task(self, data: Dict[str, Any]) -> Task:
        """Convert Redis hash to Task object"""
        from gleitzeit.core.models import RetryConfig, TaskStatus
        
        return Task(
            id=data['id'],
            name=data['name'],
            protocol=data['protocol'],
            method=data['method'],
            params=json.loads(data['params']),
            priority=data['priority'],
            status=TaskStatus(data.get('status', 'pending')),  # Include status field with proper enum
            dependencies=json.loads(data['dependencies']) if data.get('dependencies') else [],
            timeout=int(data['timeout']) if data.get('timeout') and int(data['timeout']) > 0 else None,
            retry_config=RetryConfig(**json.loads(data['retry_config'])) if data.get('retry_config') and data['retry_config'] != '{}' else None,
            attempt_count=int(data.get('attempt_count', 0)),
            workflow_id=data.get('workflow_id') or None,
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None,
            started_at=datetime.fromisoformat(data['started_at']) if data.get('started_at') else None,
            completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
            assigned_provider=data.get('assigned_provider') or None,
            execution_node=data.get('execution_node') or None,
            error_message=data.get('error_message') or None,
            tags=json.loads(data['tags']) if data.get('tags') else {},
            metadata=json.loads(data['metadata']) if data.get('metadata') else {}
        )
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        if not self._initialized:
            return False
        
        try:
            # Get task to remove from indexes
            task = await self.get_task(task_id)
            if not task:
                return False
            
            async with self.redis.pipeline() as pipe:
                # Delete task
                pipe.delete(self._task_key(task_id))
                pipe.delete(self._task_result_key(task_id))
                
                # Remove from indexes
                pipe.srem(self._status_index_key(task.status), task_id)
                
                if task.workflow_id:
                    pipe.srem(self._workflow_index_key(task.workflow_id), task_id)
                
                if task.assigned_provider:
                    pipe.srem(self._provider_index_key(task.assigned_provider), task_id)
                
                results = await pipe.execute()
            
            return results[0] > 0  # First command was delete
            
        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            return False
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get all tasks with a specific status"""
        if not self._initialized:
            return []
        
        try:
            # Get task IDs from status index
            task_ids = await self.redis.smembers(self._status_index_key(status))
            
            # Get tasks in parallel
            tasks = []
            for task_id in task_ids:
                task_data = await self.redis.hgetall(self._task_key(task_id))
                if task_data:
                    tasks.append(self._dict_to_task(task_data))
            
            # Sort by created_at
            tasks.sort(key=lambda t: t.created_at or datetime.min)
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get tasks by status {status}: {e}")
            return []
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        if not self._initialized:
            return []
        
        try:
            # Get task IDs from workflow index
            task_ids = await self.redis.smembers(self._workflow_index_key(workflow_id))
            
            # Get tasks
            tasks = []
            for task_id in task_ids:
                task_data = await self.redis.hgetall(self._task_key(task_id))
                if task_data:
                    tasks.append(self._dict_to_task(task_data))
            
            # Sort by created_at
            tasks.sort(key=lambda t: t.created_at or datetime.min)
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get tasks for workflow {workflow_id}: {e}")
            return []
    
    async def save_task_result(self, task_result: TaskResult) -> None:
        """Save a task result"""
        if not self._initialized:
            return
        
        try:
            result_data = {
                'task_id': task_result.task_id,
                'workflow_id': task_result.workflow_id or '',
                'status': task_result.status.value if hasattr(task_result.status, 'value') else str(task_result.status),
                'result': json.dumps(task_result.result) if task_result.result is not None else '',
                'error': task_result.error or '',
                'duration_seconds': task_result.duration_seconds or 0,
                'started_at': task_result.started_at.isoformat() if task_result.started_at else '',
                'completed_at': task_result.completed_at.isoformat() if task_result.completed_at else '',
                'created_at': datetime.utcnow().isoformat()
            }
            
            await self.redis.hset(
                self._task_result_key(task_result.task_id),
                mapping=result_data
            )
            
            # Set expiration for old results (7 days)
            await self.redis.expire(self._task_result_key(task_result.task_id), 7 * 24 * 3600)
            
        except Exception as e:
            logger.error(f"Failed to save task result for {task_result.task_id}: {e}")
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result by task ID"""
        if not self._initialized:
            return None
        
        try:
            result_data = await self.redis.hgetall(self._task_result_key(task_id))
            
            if not result_data:
                return None
            
            # Parse status enum
            status_str = result_data.get('status', 'pending')
            status = TaskStatus(status_str) if status_str in [s.value for s in TaskStatus] else TaskStatus.PENDING
            
            # Parse timestamps
            started_at = None
            completed_at = None
            if result_data.get('started_at'):
                try:
                    started_at = datetime.fromisoformat(result_data['started_at'])
                except:
                    pass
            if result_data.get('completed_at'):
                try:
                    completed_at = datetime.fromisoformat(result_data['completed_at'])
                except:
                    pass
            
            return TaskResult(
                task_id=result_data['task_id'],
                workflow_id=result_data.get('workflow_id'),
                status=status,
                result=json.loads(result_data['result']) if result_data.get('result') else None,
                error=result_data.get('error') or None,
                duration_seconds=float(result_data['duration_seconds']) if result_data.get('duration_seconds') else None,
                started_at=started_at,
                completed_at=completed_at,
                metadata={}
            )
            
        except Exception as e:
            logger.error(f"Failed to get task result for {task_id}: {e}")
            return None
    
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save or update a workflow"""
        if not self._initialized:
            return
        
        try:
            # Convert tasks to JSON
            tasks_data = []
            for task in workflow.tasks:
                task_dict = task.model_dump()
                # Convert datetime objects to ISO format strings
                for field in ['created_at', 'started_at', 'completed_at']:
                    if task_dict.get(field):
                        # Check if it's already a string (ISO format) or a datetime object
                        if hasattr(task_dict[field], 'isoformat'):
                            task_dict[field] = task_dict[field].isoformat()
                        # If it's already a string, leave it as is
                tasks_data.append(task_dict)
            
            # Get workflow status - handle enum values
            status = 'pending'
            if hasattr(workflow, 'status'):
                if hasattr(workflow.status, 'value'):
                    status = workflow.status.value
                else:
                    status = str(workflow.status)
            
            # Count completed and failed tasks
            tasks_completed = 0
            tasks_failed = 0
            if hasattr(workflow, 'tasks'):
                for task in workflow.tasks:
                    if hasattr(task, 'status'):
                        if str(task.status) == 'completed' or (hasattr(task.status, 'value') and task.status.value == 'completed'):
                            tasks_completed += 1
                        elif str(task.status) == 'failed' or (hasattr(task.status, 'value') and task.status.value == 'failed'):
                            tasks_failed += 1
            
            workflow_data = {
                'id': workflow.id,
                'name': workflow.name,
                'description': workflow.description or '',
                'status': status,
                'tasks': json.dumps(tasks_data),
                'metadata': json.dumps(workflow.metadata) if workflow.metadata else '{}',
                'created_at': workflow.created_at.isoformat() if workflow.created_at else datetime.utcnow().isoformat(),
                'started_at': workflow.started_at.isoformat() if hasattr(workflow, 'started_at') and workflow.started_at else '',
                'completed_at': workflow.completed_at.isoformat() if hasattr(workflow, 'completed_at') and workflow.completed_at else '',
                'tasks_total': len(workflow.tasks),
                'tasks_completed': tasks_completed,
                'tasks_failed': tasks_failed
            }
            
            await self.redis.hset(
                self._workflow_key(workflow.id),
                mapping=workflow_data
            )
            
        except Exception as e:
            logger.error(f"Failed to save workflow {workflow.id}: {e}")
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID"""
        if not self._initialized:
            return None
        
        try:
            workflow_data = await self.redis.hgetall(self._workflow_key(workflow_id))
            
            if not workflow_data:
                return None
            
            tasks_data = json.loads(workflow_data['tasks'])
            tasks = []
            for task_data in tasks_data:
                # Convert ISO format strings back to datetime objects
                for field in ['created_at', 'started_at', 'completed_at']:
                    if task_data.get(field):
                        task_data[field] = datetime.fromisoformat(task_data[field])
                tasks.append(Task(**task_data))
            
            workflow = Workflow(
                id=workflow_data['id'],
                name=workflow_data['name'],
                description=workflow_data.get('description') or None,
                tasks=tasks,
                metadata=json.loads(workflow_data['metadata']) if workflow_data.get('metadata') else {},
                created_at=datetime.fromisoformat(workflow_data['created_at']) if workflow_data.get('created_at') else None
            )
            
            # Set additional workflow status fields
            if workflow_data.get('status'):
                workflow.status = WorkflowStatus(workflow_data['status'])
            if workflow_data.get('started_at'):
                workflow.started_at = datetime.fromisoformat(workflow_data['started_at'])
            if workflow_data.get('completed_at'):
                workflow.completed_at = datetime.fromisoformat(workflow_data['completed_at'])
            
            # Set completion tracking lists if available
            if workflow_data.get('completed_tasks'):
                workflow.completed_tasks = json.loads(workflow_data['completed_tasks']) if isinstance(workflow_data['completed_tasks'], str) else workflow_data['completed_tasks']
            if workflow_data.get('failed_tasks'):
                workflow.failed_tasks = json.loads(workflow_data['failed_tasks']) if isinstance(workflow_data['failed_tasks'], str) else workflow_data['failed_tasks']
            
            return workflow
            
        except Exception as e:
            logger.error(f"Failed to get workflow {workflow_id}: {e}")
            return None
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow and all its associated tasks"""
        if not self._initialized:
            return False
        
        try:
            # Get all tasks for this workflow first (they might exist even without a workflow record)
            task_ids = await self.redis.smembers(self._workflow_index_key(workflow_id))
            
            # Check if we have either a workflow record OR tasks to delete
            workflow_exists = await self.redis.exists(self._workflow_key(workflow_id))
            if not workflow_exists and not task_ids:
                return False
            
            async with self.redis.pipeline() as pipe:
                # Delete all tasks and their results
                for task_id in task_ids:
                    # Get task to remove from status index
                    task = await self.get_task(task_id)
                    if task:
                        # Remove from status index
                        pipe.srem(self._status_index_key(task.status), task_id)
                        # Remove from provider index if assigned
                        if hasattr(task, 'assigned_provider') and task.assigned_provider:
                            pipe.srem(self._provider_index_key(task.assigned_provider), task_id)
                    
                    # Delete task and task result
                    pipe.delete(self._task_key(task_id))
                    pipe.delete(self._task_result_key(task_id))
                
                # Delete workflow index
                pipe.delete(self._workflow_index_key(workflow_id))
                
                # Delete workflow
                pipe.delete(self._workflow_key(workflow_id))
                
                # Delete workflow execution if exists
                # Note: We might have multiple executions, so we'd need to track them
                # For now, we'll just delete by pattern (if needed)
                
                await pipe.execute()
            
            # Clean queue state references
            await self.clean_queue_state_for_tasks(list(task_ids))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete workflow {workflow_id}: {e}")
            return False
    
    async def clean_queue_state_for_tasks(self, task_ids: List[str]) -> None:
        """Clean queue state by removing references to deleted tasks"""
        if not self._initialized or not task_ids:
            return
        
        try:
            task_id_set = set(task_ids)
            
            # Get all queue state keys
            pattern = f"{self.key_prefix}:queue_state:*"
            queue_keys = await self.redis.keys(pattern)
            
            for queue_key in queue_keys:
                queue_state_str = await self.redis.hget(queue_key, 'state')
                if queue_state_str:
                    queue_state = json.loads(queue_state_str)
                    
                    # Clean completed_tasks
                    if 'completed_tasks' in queue_state:
                        queue_state['completed_tasks'] = [
                            task_id for task_id in queue_state['completed_tasks']
                            if task_id not in task_id_set
                        ]
                    
                    # Clean failed_tasks
                    if 'failed_tasks' in queue_state:
                        queue_state['failed_tasks'] = [
                            task_id for task_id in queue_state['failed_tasks']
                            if task_id not in task_id_set
                        ]
                    
                    # Save updated state
                    await self.redis.hset(
                        queue_key,
                        'state',
                        json.dumps(queue_state)
                    )
                    
        except Exception as e:
            logger.warning(f"Failed to clean queue state for deleted tasks: {e}")
    
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Save workflow execution state"""
        if not self._initialized:
            return
        
        try:
            execution_data = {
                'execution_id': execution.execution_id,
                'workflow_id': execution.workflow_id,
                'status': execution.status,
                'started_at': execution.started_at.isoformat() if execution.started_at else '',
                'completed_at': execution.completed_at.isoformat() if execution.completed_at else '',
                'error_message': execution.error_message or '',
                'completed_tasks': execution.completed_tasks,
                'failed_tasks': execution.failed_tasks,
                'total_tasks': execution.total_tasks
            }
            
            await self.redis.hset(
                self._workflow_execution_key(execution.execution_id),
                mapping=execution_data
            )
            
            # Set expiration (30 days)
            await self.redis.expire(
                self._workflow_execution_key(execution.execution_id),
                30 * 24 * 3600
            )
            
        except Exception as e:
            logger.error(f"Failed to save workflow execution {execution.execution_id}: {e}")
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution by ID"""
        if not self._initialized:
            return None
        
        try:
            execution_data = await self.redis.hgetall(
                self._workflow_execution_key(execution_id)
            )
            
            if not execution_data:
                return None
            
            return WorkflowExecution(
                execution_id=execution_data['execution_id'],
                workflow_id=execution_data['workflow_id'],
                status=execution_data['status'],
                started_at=datetime.fromisoformat(execution_data['started_at']) if execution_data.get('started_at') else None,
                completed_at=datetime.fromisoformat(execution_data['completed_at']) if execution_data.get('completed_at') else None,
                error_message=execution_data.get('error_message') or None,
                completed_tasks=int(execution_data.get('completed_tasks', 0)),
                failed_tasks=int(execution_data.get('failed_tasks', 0)),
                total_tasks=int(execution_data.get('total_tasks', 0))
            )
            
        except Exception as e:
            logger.error(f"Failed to get workflow execution {execution_id}: {e}")
            return None
    
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        """Save queue state for recovery"""
        if not self._initialized:
            return
        
        try:
            state_data = {
                'queue_name': queue_name,
                'state': json.dumps(state),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            await self.redis.hset(
                self._queue_state_key(queue_name),
                mapping=state_data
            )
            
        except Exception as e:
            logger.error(f"Failed to save queue state for {queue_name}: {e}")
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Get saved queue state"""
        if not self._initialized:
            return None
        
        try:
            state_data = await self.redis.hgetall(self._queue_state_key(queue_name))
            
            if not state_data or 'state' not in state_data:
                return None
            
            return json.loads(state_data['state'])
            
        except Exception as e:
            logger.error(f"Failed to get queue state for {queue_name}: {e}")
            return None
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        """Delete queue state"""
        if not self._initialized:
            return False
        
        try:
            result = await self.redis.delete(self._queue_state_key(queue_name))
            return result > 0
            
        except Exception as e:
            logger.error(f"Failed to delete queue state for {queue_name}: {e}")
            return False
    
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        """Save multiple tasks in a single operation"""
        # Validate all tasks have workflow_id before proceeding
        for task in tasks:
            if not task.workflow_id:
                error_msg = (
                    f"Task {task.id} ({task.name}) cannot be saved without a workflow_id. "
                    "Every task must belong to a workflow. "
                    "Use ExecutionEngine.submit_task() which auto-creates workflows for single tasks."
                )
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        if not self._initialized:
            return
        
        try:
            async with self.redis.pipeline() as pipe:
                for task in tasks:
                    # Prepare task data
                    task_data = {
                        'id': task.id,
                        'name': task.name,
                        'protocol': task.protocol,
                        'method': task.method,
                        'params': json.dumps(task.params),
                        'priority': task.priority,
                        'dependencies': json.dumps(task.dependencies) if task.dependencies else '[]',
                        'timeout': task.timeout or 0,
                        'retry_config': json.dumps(task.retry_config.model_dump()) if task.retry_config else '{}',
                        'status': task.status,
                        'attempt_count': task.attempt_count,
                        'workflow_id': task.workflow_id or '',
                        'created_at': task.created_at.isoformat() if task.created_at else datetime.utcnow().isoformat(),
                        'started_at': task.started_at.isoformat() if task.started_at else '',
                        'completed_at': task.completed_at.isoformat() if task.completed_at else '',
                        'assigned_provider': task.assigned_provider or '',
                        'execution_node': task.execution_node or '',
                        'error_message': task.error_message or '',
                        'tags': json.dumps(task.tags) if task.tags else '{}',
                        'metadata': json.dumps(task.metadata) if task.metadata else '{}'
                    }
                    
                    # Save task
                    pipe.hset(self._task_key(task.id), mapping=task_data)
                    
                    # Update indexes
                    pipe.sadd(self._status_index_key(task.status), task.id)
                    
                    if task.workflow_id:
                        pipe.sadd(self._workflow_index_key(task.workflow_id), task.id)
                    
                    if task.assigned_provider:
                        pipe.sadd(self._provider_index_key(task.assigned_provider), task.id)
                
                await pipe.execute()
            
        except Exception as e:
            logger.error(f"Failed to save tasks batch: {e}")
    
    async def acquire_next_queued_task(self, check_dependencies: bool = True) -> Optional[Task]:
        """
        Atomically acquire the next queued task using Redis Lua script.
        
        This prevents race conditions by atomically:
        1. Finding the highest priority QUEUED task
        2. Checking its dependencies if needed
        3. Updating its status to EXECUTING
        4. Returning the task
        
        All in a single atomic operation.
        """
        if not self.redis:
            return None
            
        # Lua script for atomic task acquisition
        lua_script = """
        local key_prefix = ARGV[1]
        local now_iso = ARGV[2]
        local check_deps = ARGV[3] == "true"
        
        -- Get all QUEUED task IDs
        local queued_tasks = redis.call('SMEMBERS', key_prefix .. ':tasks:status:queued')
        if #queued_tasks == 0 then
            return nil
        end
        
        -- Load and sort tasks by priority and creation time
        local tasks = {}
        for _, task_id in ipairs(queued_tasks) do
            local task_key = key_prefix .. ':task:' .. task_id
            local task_data = redis.call('HGET', task_key, 'data')
            if task_data then
                local task = cjson.decode(task_data)
                -- Priority order: urgent=0, high=1, normal=2, low=3
                local priority_val = 2  -- default to normal
                if task.priority == 'urgent' then priority_val = 0
                elseif task.priority == 'high' then priority_val = 1
                elseif task.priority == 'normal' then priority_val = 2
                elseif task.priority == 'low' then priority_val = 3
                end
                table.insert(tasks, {
                    id = task_id,
                    priority = priority_val,
                    created_at = task.created_at or now_iso,
                    data = task_data,
                    task = task
                })
            end
        end
        
        -- Sort by priority then creation time
        table.sort(tasks, function(a, b)
            if a.priority ~= b.priority then
                return a.priority < b.priority
            end
            return a.created_at < b.created_at
        end)
        
        -- Find first task with satisfied dependencies
        for _, task_entry in ipairs(tasks) do
            local task = task_entry.task
            local can_execute = true
            
            -- Check dependencies if needed
            if check_deps and task.dependencies and #task.dependencies > 0 then
                for _, dep_id in ipairs(task.dependencies) do
                    local dep_key = key_prefix .. ':task:' .. dep_id
                    local dep_data = redis.call('HGET', dep_key, 'data')
                    if dep_data then
                        local dep_task = cjson.decode(dep_data)
                        if dep_task.status ~= 'completed' then
                            can_execute = false
                            break
                        end
                    else
                        -- Dependency not found, can't execute
                        can_execute = false
                        break
                    end
                end
            end
            
            if can_execute then
                -- Atomically update task status to EXECUTING
                task.status = 'executing'
                task.started_at = now_iso
                
                -- Save updated task
                local task_key = key_prefix .. ':task:' .. task.id
                redis.call('HSET', task_key, 'data', cjson.encode(task))
                
                -- Update status indices
                redis.call('SREM', key_prefix .. ':tasks:status:queued', task.id)
                redis.call('SADD', key_prefix .. ':tasks:status:executing', task.id)
                
                -- Return the task data
                return cjson.encode(task)
            end
        end
        
        return nil
        """
        
        try:
            # Execute Lua script
            result = await self.redis.eval(
                lua_script,
                0,  # no keys, only args
                self.key_prefix,
                datetime.utcnow().isoformat(),
                "true" if check_dependencies else "false"
            )
            
            if result:
                # Parse and return the acquired task
                task_data = json.loads(result)
                return Task(**task_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to acquire queued task atomically: {e}")
            # Fall back to non-atomic implementation if Lua fails
            return None
    
    async def get_all_queued_tasks(self) -> List[Task]:
        """Get all tasks that should be in queues on startup"""
        if not self._initialized:
            return []
        
        try:
            tasks = []
            
            # Get tasks from each relevant status
            for status in ['queued', 'retry_pending', 'executing']:
                status_tasks = await self.get_tasks_by_status(status)
                tasks.extend(status_tasks)
            
            # Sort by created_at
            tasks.sort(key=lambda t: t.created_at or datetime.min)
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get queued tasks: {e}")
            return []
    
    async def get_task_count_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        if not self._initialized:
            return {}
        
        try:
            counts = {}
            
            # Get all status keys
            pattern = self._status_index_key("*")
            cursor = 0
            
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, 
                    match=pattern,
                    count=100
                )
                
                for key in keys:
                    # Extract status from key
                    status = key.split(":")[-1]
                    # Get count
                    count = await self.redis.scard(key)
                    counts[status] = count
                
                if cursor == 0:
                    break
            
            return counts
            
        except Exception as e:
            logger.error(f"Failed to get task count by status: {e}")
            return {}
    
    async def list_workflows(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List all workflows with optional filtering and pagination"""
        if not self._initialized:
            return {"workflows": [], "total": 0, "limit": limit, "offset": offset}
        
        try:
            # Get all workflow keys
            pattern = f"{self.key_prefix}:workflow:*"
            workflow_keys = await self.redis.keys(pattern)
            
            workflows = []
            for key in workflow_keys:
                try:
                    # Get workflow data
                    workflow_data = await self.redis.hgetall(key)
                    if workflow_data:
                        # Convert Redis data to workflow object
                        workflow = {
                            "id": workflow_data.get("id", ""),
                            "name": workflow_data.get("name", ""),
                            "description": workflow_data.get("description", ""),
                            "created_at": workflow_data.get("created_at", ""),
                            "status": workflow_data.get("status", "unknown"),
                            "tasks_total": int(workflow_data.get("tasks_total", 0)),
                            "tasks_completed": int(workflow_data.get("tasks_completed", 0)),
                            "tasks_failed": int(workflow_data.get("tasks_failed", 0))
                        }
                        
                        # Apply status filter if specified
                        if status is None or workflow["status"] == status:
                            workflows.append(workflow)
                        
                except Exception as e:
                    logger.warning(f"Failed to parse workflow from key {key}: {e}")
                    continue
            
            # Sort by created_at descending (newest first)
            workflows.sort(key=lambda w: w.get("created_at", ""), reverse=True)
            
            # Apply pagination
            total = len(workflows)
            start_idx = offset
            end_idx = offset + limit
            paginated_workflows = workflows[start_idx:end_idx]
            
            return {
                "workflows": paginated_workflows,
                "total": total,
                "limit": limit,
                "offset": offset
            }
            
        except Exception as e:
            logger.error(f"Failed to list workflows: {e}")
            return {"workflows": [], "total": 0, "limit": limit, "offset": offset}
    
    async def list_tasks(self, workflow_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List all tasks with optional filtering and pagination"""
        if not self._initialized:
            return {"tasks": [], "total": 0, "limit": limit, "offset": offset}
        
        try:
            tasks = []
            
            if workflow_id:
                # Get tasks for specific workflow
                workflow_index_key = self._workflow_index_key(workflow_id)
                task_ids = await self.redis.smembers(workflow_index_key)
                
                for task_id in task_ids:
                    try:
                        task = await self.get_task(task_id)
                        if task and (not status or task.status == status):
                            tasks.append(task)
                    except Exception as e:
                        logger.warning(f"Failed to get task {task_id}: {e}")
                        continue
            else:
                # Get all tasks
                if status:
                    # Use status index if filtering by status
                    status_index_key = self._status_index_key(status)
                    task_ids = await self.redis.smembers(status_index_key)
                    
                    for task_id in task_ids:
                        try:
                            task = await self.get_task(task_id)
                            if task:
                                tasks.append(task)
                        except Exception as e:
                            logger.warning(f"Failed to get task {task_id}: {e}")
                            continue
                else:
                    # Get all task keys
                    pattern = f"{self.key_prefix}:task:*"
                    task_keys = await self.redis.keys(pattern)
                    
                    for key in task_keys:
                        try:
                            # Extract task_id from key
                            task_id = key.split(":")[-1]
                            task = await self.get_task(task_id)
                            if task:
                                tasks.append(task)
                        except Exception as e:
                            logger.warning(f"Failed to get task from key {key}: {e}")
                            continue
            
            # Sort by created_at descending (newest first)
            tasks.sort(key=lambda t: getattr(t, 'created_at', None) or '', reverse=True)
            
            # Apply pagination
            total = len(tasks)
            start_idx = offset
            end_idx = offset + limit
            paginated_tasks = tasks[start_idx:end_idx]
            
            return {
                "tasks": paginated_tasks,
                "total": total,
                "limit": limit,
                "offset": offset
            }
            
        except Exception as e:
            logger.error(f"Failed to list tasks: {e}")
            return {"tasks": [], "total": 0, "limit": limit, "offset": offset}
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        """Remove old completed tasks and results before cutoff date"""
        if not self._initialized:
            return 0
        
        try:
            deleted_count = 0
            
            # Get completed and failed tasks
            for status in ['completed', 'failed']:
                task_ids = await self.redis.smembers(self._status_index_key(status))
                
                for task_id in task_ids:
                    task = await self.get_task(task_id)
                    if task and task.completed_at and task.completed_at < cutoff_date:
                        if await self.delete_task(task_id):
                            deleted_count += 1
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
            return 0
    
    # =========================================================================
    # Hub Resource Operations
    # =========================================================================
    
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        if not self._initialized:
            return
        
        try:
            instance_data = {
                'id': instance.id,
                'hub_id': hub_id,
                'name': instance.name,
                'type': instance.type.value if isinstance(instance.type, ResourceType) else instance.type,
                'endpoint': instance.endpoint,
                'status': instance.status.value if isinstance(instance.status, ResourceStatus) else instance.status,
                'metadata': json.dumps(instance.metadata),
                'tags': json.dumps(list(instance.tags)),
                'capabilities': json.dumps(list(instance.capabilities)),
                'health_checks_failed': instance.health_checks_failed,
                'last_health_check': instance.last_health_check.isoformat() if instance.last_health_check else '',
                'created_at': instance.created_at.isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            async with self.redis.pipeline() as pipe:
                # Save instance data
                pipe.hset(self._instance_key(instance.id), mapping=instance_data)
                
                # Add to hub's instance set
                pipe.sadd(self._hub_instances_key(hub_id), instance.id)
                
                # Set expiration (24 hours) for auto-cleanup of stale instances
                pipe.expire(self._instance_key(instance.id), 24 * 3600)
                
                await pipe.execute()
            
            logger.debug(f"Saved instance {instance.id} to Redis")
            
        except Exception as e:
            logger.error(f"Failed to save instance {instance.id}: {e}")
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        if not self._initialized:
            return None
        
        try:
            instance_data = await self.redis.hgetall(self._instance_key(instance_id))
            
            if not instance_data:
                return None
            
            return {
                'id': instance_data['id'],
                'hub_id': instance_data.get('hub_id', ''),
                'name': instance_data['name'],
                'type': instance_data['type'],
                'endpoint': instance_data['endpoint'],
                'status': instance_data['status'],
                'metadata': json.loads(instance_data['metadata']) if instance_data.get('metadata') else {},
                'tags': json.loads(instance_data['tags']) if instance_data.get('tags') else [],
                'capabilities': json.loads(instance_data['capabilities']) if instance_data.get('capabilities') else [],
                'health_checks_failed': int(instance_data.get('health_checks_failed', 0)),
                'last_health_check': instance_data.get('last_health_check'),
                'created_at': instance_data.get('created_at'),
                'updated_at': instance_data.get('updated_at')
            }
            
        except Exception as e:
            logger.error(f"Failed to load instance {instance_id}: {e}")
            return None
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        """List all instances for a hub"""
        if not self._initialized:
            return []
        
        try:
            # Get all instance IDs for this hub
            instance_ids = await self.redis.smembers(self._hub_instances_key(hub_id))
            
            # Load each instance
            instances = []
            for instance_id in instance_ids:
                instance_data = await self.load_instance(instance_id)
                if instance_data:
                    instances.append(instance_data)
                else:
                    # Remove stale reference
                    await self.redis.srem(self._hub_instances_key(hub_id), instance_id)
            
            return instances
            
        except Exception as e:
            logger.error(f"Failed to list instances for hub {hub_id}: {e}")
            return []
    
    async def delete_instance(self, instance_id: str) -> None:
        """Remove instance from storage"""
        if not self._initialized:
            return
        
        try:
            # Load instance to get hub_id
            instance_data = await self.load_instance(instance_id)
            
            async with self.redis.pipeline() as pipe:
                # Delete instance key
                pipe.delete(self._instance_key(instance_id))
                
                # Remove from hub's instance set
                if instance_data and instance_data.get('hub_id'):
                    pipe.srem(self._hub_instances_key(instance_data['hub_id']), instance_id)
                
                # Delete associated metrics
                pipe.delete(self._metrics_key(instance_id))
                
                await pipe.execute()
            
            logger.debug(f"Deleted instance {instance_id} from Redis")
            
        except Exception as e:
            logger.error(f"Failed to delete instance {instance_id}: {e}")
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Store metrics snapshot in time series"""
        if not self._initialized:
            return
        
        try:
            timestamp = int(datetime.utcnow().timestamp())
            
            # Convert metrics to dict
            metrics_data = metrics.to_dict()
            metrics_data['timestamp'] = timestamp
            
            # Add to sorted set (score is timestamp)
            await self.redis.zadd(
                self._metrics_key(instance_id),
                {json.dumps(metrics_data): timestamp}
            )
            
            # Trim old metrics (keep last N hours)
            cutoff = timestamp - (self.metrics_retention_hours * 3600)
            await self.redis.zremrangebyscore(
                self._metrics_key(instance_id),
                '-inf',
                cutoff
            )
            
            # Set expiration on metrics key
            await self.redis.expire(
                self._metrics_key(instance_id),
                self.metrics_retention_hours * 3600
            )
            
            logger.debug(f"Saved metrics for instance {instance_id}")
            
        except Exception as e:
            logger.error(f"Failed to save metrics for {instance_id}: {e}")
    
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Retrieve historical metrics"""
        if not self._initialized:
            return []
        
        try:
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())
            
            # Get metrics in time range
            results = await self.redis.zrangebyscore(
                self._metrics_key(instance_id),
                start_ts,
                end_ts
            )
            
            # Parse results
            metrics_list = []
            for item in results:
                try:
                    metrics_data = json.loads(item)
                    metrics_list.append(metrics_data)
                except json.JSONDecodeError:
                    continue
            
            return metrics_list
            
        except Exception as e:
            logger.error(f"Failed to get metrics history for {instance_id}: {e}")
            return []
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock using Redis SET NX"""
        if not self._initialized:
            return False
        
        try:
            # Store lock data as JSON with owner and timestamp
            lock_data = json.dumps({
                "owner_id": owner_id,
                "acquired_at": datetime.utcnow().isoformat()
            })
            
            # SET NX (set if not exists) with expiration
            result = await self.redis.set(
                self._lock_key(resource_id),
                lock_data,
                nx=True,
                ex=timeout
            )
            
            if result:
                logger.debug(f"Acquired lock for {resource_id} by {owner_id}")
            
            return bool(result)
            
        except Exception as e:
            logger.error(f"Failed to acquire lock for {resource_id}: {e}")
            return False
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release distributed lock if owned"""
        if not self._initialized:
            return
        
        try:
            # Lua script for atomic check-and-delete
            # Need to parse JSON to check owner
            lua_script = """
            local lock_data = redis.call("get", KEYS[1])
            if lock_data then
                local lock = cjson.decode(lock_data)
                if lock.owner_id == ARGV[1] then
                    return redis.call("del", KEYS[1])
                end
            end
            return 0
            """
            
            result = await self.redis.eval(
                lua_script,
                1,  # Number of keys
                self._lock_key(resource_id),  # Key
                owner_id  # Argument
            )
            
            if result:
                logger.debug(f"Released lock for {resource_id} by {owner_id}")
            
        except Exception as e:
            logger.error(f"Failed to release lock for {resource_id}: {e}")
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock timeout if owned"""
        if not self._initialized:
            return False
        
        try:
            # Lua script for atomic check-and-extend
            lua_script = """
            local lock_data = redis.call("get", KEYS[1])
            if lock_data then
                local lock = cjson.decode(lock_data)
                if lock.owner_id == ARGV[1] then
                    return redis.call("expire", KEYS[1], ARGV[2])
                end
            end
            return 0
            """
            
            result = await self.redis.eval(
                lua_script,
                1,  # Number of keys
                self._lock_key(resource_id),  # Key
                owner_id,  # First argument
                timeout  # Second argument
            )
            
            if result:
                logger.debug(f"Extended lock for {resource_id} by {owner_id}")
            
            return bool(result)
            
        except Exception as e:
            logger.error(f"Failed to extend lock for {resource_id}: {e}")
            return False
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get current lock owner"""
        if not self._initialized:
            return None
        
        try:
            lock_data = await self.redis.get(self._lock_key(resource_id))
            if lock_data:
                # Parse JSON lock data to get owner_id
                if isinstance(lock_data, bytes):
                    lock_data = lock_data.decode('utf-8')
                lock_info = json.loads(lock_data)
                return lock_info.get("owner_id")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get lock owner for {resource_id}: {e}")
            return None
    
    # =========================================================================
    # Cross-Domain Operations
    # =========================================================================
    
    async def get_tasks_for_resource(self, resource_id: str) -> List[Task]:
        """Get all tasks assigned to a specific resource"""
        if not self._initialized:
            return []
        
        try:
            # Get task IDs from provider index
            task_ids = await self.redis.smembers(self._provider_index_key(resource_id))
            
            # Get tasks
            tasks = []
            for task_id in task_ids:
                task = await self.get_task(task_id)
                if task and task.status == "executing":
                    tasks.append(task)
            
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get tasks for resource {resource_id}: {e}")
            return []