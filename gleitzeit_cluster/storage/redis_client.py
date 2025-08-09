"""
Redis client for distributed workflow storage and coordination
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError, TimeoutError

from ..core.task import Task, TaskStatus, TaskType
from ..core.workflow import Workflow, WorkflowStatus
from ..core.node import ExecutorNode
from ..core.error_handling import RetryManager, RetryConfig, GleitzeitLogger


class RedisConnectionError(Exception):
    """Redis connection related errors"""
    pass


class RedisOperationError(Exception):
    """Redis operation failures"""
    pass


class RedisClient:
    """
    Async Redis client for Gleitzeit cluster coordination
    
    Provides persistent storage for workflows, tasks, and coordination data
    with atomic operations and event streaming capabilities.
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        db: int = 0,
        max_connections: int = 20,
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
        workflow_ttl: int = 604800,  # 7 days
        heartbeat_ttl: int = 60      # 60 seconds
    ):
        """
        Initialize Redis client
        
        Args:
            redis_url: Redis connection URL
            db: Redis database number
            max_connections: Maximum connection pool size
            retry_attempts: Number of retry attempts for failed operations
            retry_delay: Delay between retries in seconds
            workflow_ttl: Workflow data TTL in seconds
            heartbeat_ttl: Node heartbeat TTL in seconds
        """
        self.redis_url = redis_url
        self.db = db
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.workflow_ttl = workflow_ttl
        self.heartbeat_ttl = heartbeat_ttl
        
        # Connection pool
        self.pool = redis.ConnectionPool.from_url(
            redis_url,
            db=db,
            max_connections=max_connections,
            decode_responses=True
        )
        self.redis = Redis(connection_pool=self.pool)
        
        # Cluster configuration
        self.cluster_id = str(uuid.uuid4())
        self._is_connected = False
        
        # Error handling and retry
        self.logger = GleitzeitLogger("RedisClient")
        self.retry_manager = RetryManager(self.logger)
    
    async def connect(self) -> None:
        """Initialize Redis connection and verify connectivity with retry"""
        retry_config = RetryConfig(
            max_attempts=self.retry_attempts,
            base_delay=self.retry_delay,
            max_delay=30.0
        )
        
        async def _connect():
            await self.redis.ping()
            self._is_connected = True
            
            # Initialize cluster configuration
            await self._initialize_cluster_config()
            
            print(f"✅ Redis connected: {self.redis_url}")
            return True
        
        try:
            return await self.retry_manager.execute_with_retry(
                _connect, 
                retry_config, 
                service_name="redis_connection"
            )
        except Exception as e:
            self._is_connected = False
            raise RedisConnectionError(f"Failed to connect to Redis after retries: {e}")
    
    async def disconnect(self) -> None:
        """Close Redis connections"""
        if self.redis:
            await self.redis.close()
        if self.pool:
            await self.pool.disconnect()
        self._is_connected = False
        print("🔌 Redis disconnected")
    
    async def _initialize_cluster_config(self) -> None:
        """Initialize cluster configuration in Redis"""
        config = {
            "cluster_id": self.cluster_id,
            "max_workflow_ttl": self.workflow_ttl,
            "heartbeat_interval": self.heartbeat_ttl,
            "initialized_at": datetime.utcnow().isoformat(),
            "version": "1.0.0"
        }
        
        # Only set if not exists (preserve existing cluster config)
        for key, value in config.items():
            await self.redis.hsetnx("config:cluster", key, str(value))
    
    async def _execute_with_retry(self, operation, operation_name: str, context: Dict[str, Any] = None):
        """Execute Redis operation with retry logic"""
        retry_config = RetryConfig(
            max_attempts=self.retry_attempts,
            base_delay=self.retry_delay,
            max_delay=10.0
        )
        
        return await self.retry_manager.execute_with_retry(
            operation,
            retry_config,
            service_name=f"redis_{operation_name}",
            context=context or {}
        )
    
    @asynccontextmanager
    async def transaction(self):
        """Context manager for Redis transactions"""
        pipe = self.redis.pipeline(transaction=True)
        try:
            yield pipe
            await pipe.execute()
        except Exception as e:
            await pipe.reset()
            raise RedisOperationError(f"Transaction failed: {e}")
    
    # ========================
    # Workflow Operations
    # ========================
    
    async def store_workflow(self, workflow: Workflow) -> None:
        """Store workflow with atomic operation and retry"""
        workflow_key = f"workflow:{workflow.id}"
        tasks_key = f"workflow:{workflow.id}:tasks"
        
        async def _store_workflow():
            async with self.transaction() as pipe:
                # Store workflow data
                workflow_data = {
                    "id": workflow.id,
                    "name": workflow.name,
                    "description": workflow.description or "",
                    "status": workflow.status.value,
                    "error_strategy": workflow.error_strategy.value,
                    "created_at": workflow.created_at.isoformat(),
                    "total_tasks": len(workflow.tasks),
                    "completed_tasks": 0,
                    "failed_tasks": 0,
                    "metadata": json.dumps(workflow.metadata)
                }
                
                pipe.hset(workflow_key, mapping=workflow_data)
                pipe.expire(workflow_key, self.workflow_ttl)
                
                # Store task order
                if workflow.task_order:
                    pipe.lpush(tasks_key, *workflow.task_order)
                    pipe.expire(tasks_key, self.workflow_ttl)
                
                # Add to active workflows
                pipe.sadd("workflows:active", workflow.id)
                
                # Store individual tasks
                for task in workflow.tasks.values():
                    await self._store_task_in_pipe(pipe, task)
                
                # Publish event
                event = {
                    "type": "workflow_created",
                    "workflow_id": workflow.id,
                    "name": workflow.name,
                    "timestamp": datetime.utcnow().isoformat()
                }
                pipe.publish("notifications:global", json.dumps(event))
        
        try:
            await self._execute_with_retry(
                _store_workflow, 
                "store_workflow",
                {"workflow_id": workflow.id, "workflow_name": workflow.name}
            )
        except Exception as e:
            raise RedisOperationError(f"Failed to store workflow {workflow.id}: {e}")
    
    async def _store_task_in_pipe(self, pipe, task: Task) -> None:
        """Store task data in pipeline"""
        task_key = f"task:{task.id}"
        
        task_data = {
            "id": task.id,
            "workflow_id": task.workflow_id,
            "name": task.name,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "priority": task.priority.value,
            "parameters": json.dumps(task.parameters.model_dump()),
            "requirements": json.dumps(task.requirements.model_dump()),
            "dependencies": json.dumps(task.dependencies),
            "max_retries": task.max_retries,
            "retry_count": task.retry_count,
            "created_at": task.created_at.isoformat(),
            "metadata": json.dumps(task.metadata)
        }
        
        pipe.hset(task_key, mapping=task_data)
        pipe.expire(task_key, self.workflow_ttl)
        
        # Add to priority queue
        priority_queue = f"queue:tasks:{task.priority.value}"
        timestamp = time.time()
        pipe.zadd(priority_queue, {task.id: timestamp})
        
        # Store dependencies
        if task.dependencies:
            deps_key = f"task:{task.id}:dependencies"
            pipe.sadd(deps_key, *task.dependencies)
            pipe.expire(deps_key, self.workflow_ttl)
    
    async def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve workflow data with retry"""
        async def _get_workflow():
            workflow_key = f"workflow:{workflow_id}"
            data = await self.redis.hgetall(workflow_key)
            
            if not data:
                return None
                
            return data
        
        try:
            return await self._execute_with_retry(
                _get_workflow,
                "get_workflow", 
                {"workflow_id": workflow_id}
            )
        except Exception as e:
            raise RedisOperationError(f"Failed to get workflow {workflow_id}: {e}")
    
    async def update_workflow_status(
        self, 
        workflow_id: str, 
        status: WorkflowStatus,
        completed_tasks: Optional[int] = None,
        failed_tasks: Optional[int] = None
    ) -> None:
        """Update workflow status atomically"""
        try:
            async with self.transaction() as pipe:
                workflow_key = f"workflow:{workflow_id}"
                
                updates = {"status": status.value}
                
                if status == WorkflowStatus.RUNNING:
                    updates["started_at"] = datetime.utcnow().isoformat()
                elif status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]:
                    updates["completed_at"] = datetime.utcnow().isoformat()
                    # Move from active to completed
                    pipe.srem("workflows:active", workflow_id)
                    pipe.zadd("workflows:completed", {workflow_id: time.time()})
                
                if completed_tasks is not None:
                    updates["completed_tasks"] = completed_tasks
                    
                if failed_tasks is not None:
                    updates["failed_tasks"] = failed_tasks
                
                pipe.hset(workflow_key, mapping=updates)
                
                # Publish status change event
                event = {
                    "type": "workflow_status_changed",
                    "workflow_id": workflow_id,
                    "status": status.value,
                    "timestamp": datetime.utcnow().isoformat()
                }
                pipe.publish(f"notifications:workflow:{workflow_id}", json.dumps(event))
                pipe.publish("notifications:global", json.dumps(event))
                
        except Exception as e:
            raise RedisOperationError(f"Failed to update workflow {workflow_id}: {e}")
    
    async def store_workflow_result(self, workflow_id: str, task_id: str, result: Any) -> None:
        """Store task result for workflow"""
        try:
            results_key = f"workflow:{workflow_id}:results"
            result_json = json.dumps(result) if result is not None else ""
            
            await self.redis.hset(results_key, task_id, result_json)
            await self.redis.expire(results_key, self.workflow_ttl)
            
        except Exception as e:
            raise RedisOperationError(f"Failed to store result for {workflow_id}/{task_id}: {e}")
    
    async def store_workflow_error(self, workflow_id: str, task_id: str, error: str) -> None:
        """Store task error for workflow"""
        try:
            errors_key = f"workflow:{workflow_id}:errors"
            
            await self.redis.hset(errors_key, task_id, error)
            await self.redis.expire(errors_key, self.workflow_ttl)
            
        except Exception as e:
            raise RedisOperationError(f"Failed to store error for {workflow_id}/{task_id}: {e}")
    
    async def get_workflow_results(self, workflow_id: str) -> Dict[str, Any]:
        """Get all results for a workflow"""
        try:
            results_key = f"workflow:{workflow_id}:results"
            results_data = await self.redis.hgetall(results_key)
            
            # Parse JSON results
            results = {}
            for task_id, result_json in results_data.items():
                try:
                    results[task_id] = json.loads(result_json) if result_json else None
                except json.JSONDecodeError:
                    results[task_id] = result_json
                    
            return results
            
        except Exception as e:
            raise RedisOperationError(f"Failed to get results for {workflow_id}: {e}")
    
    async def get_workflow_errors(self, workflow_id: str) -> Dict[str, str]:
        """Get all errors for a workflow"""
        try:
            errors_key = f"workflow:{workflow_id}:errors"
            return await self.redis.hgetall(errors_key)
            
        except Exception as e:
            raise RedisOperationError(f"Failed to get errors for {workflow_id}: {e}")
    
    # ========================
    # Task Queue Operations
    # ========================
    
    async def pop_task_from_queue(self, priority: str = "normal") -> Optional[str]:
        """Pop highest priority task from queue"""
        try:
            queue_key = f"queue:tasks:{priority}"
            
            # Pop lowest score (earliest timestamp)
            result = await self.redis.zpopmin(queue_key, 1)
            
            if result:
                task_id = result[0][0]  # (member, score) tuple
                return task_id
                
            return None
            
        except Exception as e:
            raise RedisOperationError(f"Failed to pop task from queue: {e}")
    
    async def assign_task_to_node(self, task_id: str, node_id: str) -> None:
        """Assign task to executor node atomically"""
        try:
            async with self.transaction() as pipe:
                # Update task assignment
                task_key = f"task:{task_id}"
                pipe.hset(task_key, mapping={
                    "assigned_node_id": node_id,
                    "status": TaskStatus.ASSIGNED.value,
                    "assigned_at": datetime.utcnow().isoformat()
                })
                
                # Track assignment
                pipe.sadd(f"node:{node_id}:tasks", task_id)
                pipe.hset("queue:assigned", task_id, node_id)
                pipe.zadd("queue:processing", {task_id: time.time()})
                
                # Publish assignment event
                event = {
                    "type": "task_assigned",
                    "task_id": task_id,
                    "node_id": node_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                pipe.publish(f"notifications:node:{node_id}", json.dumps(event))
                
        except Exception as e:
            raise RedisOperationError(f"Failed to assign task {task_id} to {node_id}: {e}")
    
    async def complete_task(
        self, 
        task_id: str, 
        result: Any = None, 
        error: Optional[str] = None
    ) -> None:
        """Mark task as completed atomically"""
        try:
            async with self.transaction() as pipe:
                # Get task data for workflow update
                task_key = f"task:{task_id}"
                task_data = await self.redis.hgetall(task_key)
                
                if not task_data:
                    raise RedisOperationError(f"Task {task_id} not found")
                
                workflow_id = task_data["workflow_id"]
                node_id = task_data.get("assigned_node_id")
                
                # Update task status
                status = TaskStatus.FAILED if error else TaskStatus.COMPLETED
                updates = {
                    "status": status.value,
                    "completed_at": datetime.utcnow().isoformat()
                }
                
                if result is not None:
                    updates["result"] = json.dumps(result)
                if error:
                    updates["error"] = error
                
                pipe.hset(task_key, mapping=updates)
                
                # Clean up assignments
                if node_id:
                    pipe.srem(f"node:{node_id}:tasks", task_id)
                    pipe.lpush(f"node:{node_id}:history", task_id)
                    pipe.ltrim(f"node:{node_id}:history", 0, 99)  # Keep last 100
                
                pipe.hdel("queue:assigned", task_id)
                pipe.zrem("queue:processing", task_id)
                
                # Store workflow result/error
                if result is not None:
                    pipe.hset(f"workflow:{workflow_id}:results", task_id, json.dumps(result))
                if error:
                    pipe.hset(f"workflow:{workflow_id}:errors", task_id, error)
                
                # Update workflow counters
                if error:
                    pipe.hincrby(f"workflow:{workflow_id}", "failed_tasks", 1)
                else:
                    pipe.hincrby(f"workflow:{workflow_id}", "completed_tasks", 1)
                
                # Publish completion event
                event = {
                    "type": "task_completed" if not error else "task_failed",
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                pipe.publish(f"notifications:workflow:{workflow_id}", json.dumps(event))
                
        except Exception as e:
            raise RedisOperationError(f"Failed to complete task {task_id}: {e}")
    
    # ========================
    # Node Management
    # ========================
    
    async def register_node(self, node: ExecutorNode) -> None:
        """Register executor node"""
        try:
            node_key = f"node:{node.id}"
            
            node_data = {
                "id": node.id,
                "name": node.name,
                "host": node.host,
                "status": node.status.value,
                "capabilities": json.dumps(node.capabilities.model_dump()),
                "last_heartbeat": datetime.utcnow().isoformat(),
                "total_tasks_completed": 0,
                "total_tasks_failed": 0,
                "metadata": json.dumps(node.metadata)
            }
            
            async with self.transaction() as pipe:
                pipe.hset(node_key, mapping=node_data)
                pipe.expire(node_key, self.heartbeat_ttl)
                pipe.sadd("nodes:active", node.id)
                
                # Add to capability indexes
                if node.capabilities.has_gpu:
                    pipe.sadd("nodes:by_capability:gpu", node.id)
                
                for task_type in node.capabilities.supported_task_types:
                    pipe.sadd(f"nodes:by_capability:{task_type.value}", node.id)
                
                # Publish registration event
                event = {
                    "type": "node_registered",
                    "node_id": node.id,
                    "name": node.name,
                    "timestamp": datetime.utcnow().isoformat()
                }
                pipe.publish("notifications:global", json.dumps(event))
                
        except Exception as e:
            raise RedisOperationError(f"Failed to register node {node.id}: {e}")
    
    async def update_node_heartbeat(self, node_id: str) -> None:
        """Update node heartbeat"""
        try:
            node_key = f"node:{node_id}"
            
            await self.redis.hset(node_key, "last_heartbeat", datetime.utcnow().isoformat())
            await self.redis.expire(node_key, self.heartbeat_ttl)
            await self.redis.sadd("nodes:active", node_id)
            
        except Exception as e:
            raise RedisOperationError(f"Failed to update heartbeat for {node_id}: {e}")
    
    async def get_active_nodes(self) -> List[str]:
        """Get list of active node IDs"""
        try:
            return await self.redis.smembers("nodes:active")
        except Exception as e:
            raise RedisOperationError(f"Failed to get active nodes: {e}")
    
    async def get_active_workflows(self) -> List[str]:
        """Get list of active workflow IDs"""
        try:
            return await self.redis.smembers("workflows:active")
        except Exception as e:
            raise RedisOperationError(f"Failed to get active workflows: {e}")
    
    async def get_resumable_workflows(self) -> List[Dict[str, Any]]:
        """Get workflows that can be resumed after cluster restart"""
        try:
            active_workflow_ids = await self.get_active_workflows()
            resumable = []
            
            for workflow_id in active_workflow_ids:
                workflow_data = await self.get_workflow(workflow_id)
                if workflow_data:
                    # Check if workflow was interrupted (status is RUNNING but no recent activity)
                    status = workflow_data.get('status')
                    if status in ['running', 'pending']:
                        # Get task-level recovery information
                        incomplete_tasks = await self.get_incomplete_tasks(workflow_id)
                        
                        resumable.append({
                            'id': workflow_id,
                            'name': workflow_data.get('name'),
                            'status': status,
                            'total_tasks': int(workflow_data.get('total_tasks', 0)),
                            'completed_tasks': int(workflow_data.get('completed_tasks', 0)),
                            'failed_tasks': int(workflow_data.get('failed_tasks', 0)),
                            'incomplete_tasks': len(incomplete_tasks),
                            'recoverable_tasks': [t for t in incomplete_tasks if t['can_resume']],
                            'created_at': workflow_data.get('created_at'),
                            'started_at': workflow_data.get('started_at')
                        })
            
            return resumable
        except Exception as e:
            raise RedisOperationError(f"Failed to get resumable workflows: {e}")
    
    async def get_incomplete_tasks(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get tasks that were not completed for a workflow"""
        try:
            # Get list of task IDs from workflow
            tasks_key = f"workflow:{workflow_id}:tasks"
            task_ids = await self.redis.lrange(tasks_key, 0, -1)
            
            incomplete_tasks = []
            completed_task_ids = set()
            
            # Get completed and failed task results to identify incomplete ones
            results = await self.get_workflow_results(workflow_id)
            errors = await self.get_workflow_errors(workflow_id)
            completed_task_ids.update(results.keys())
            completed_task_ids.update(errors.keys())
            
            for task_id in task_ids:
                if task_id not in completed_task_ids:
                    # Get task data
                    task_data = await self.redis.hgetall(f"task:{task_id}")
                    if task_data:
                        # Check if task dependencies are satisfied
                        can_resume = await self._can_task_resume(task_id, completed_task_ids)
                        
                        incomplete_tasks.append({
                            'id': task_id,
                            'name': task_data.get('name'),
                            'task_type': task_data.get('task_type'),
                            'status': task_data.get('status', 'pending'),
                            'priority': task_data.get('priority', 'normal'),
                            'dependencies': json.loads(task_data.get('dependencies', '[]')),
                            'retry_count': int(task_data.get('retry_count', 0)),
                            'max_retries': int(task_data.get('max_retries', 3)),
                            'can_resume': can_resume,
                            'created_at': task_data.get('created_at')
                        })
            
            return incomplete_tasks
        except Exception as e:
            raise RedisOperationError(f"Failed to get incomplete tasks for {workflow_id}: {e}")
    
    async def _can_task_resume(self, task_id: str, completed_task_ids: Set[str]) -> bool:
        """Check if a task can be resumed (all dependencies satisfied)"""
        try:
            deps_key = f"task:{task_id}:dependencies"
            dependencies = await self.redis.smembers(deps_key)
            
            # Task can resume if all its dependencies are completed
            for dep_id in dependencies:
                if dep_id not in completed_task_ids:
                    return False
            
            return True
        except Exception as e:
            # If we can't check dependencies, assume task can resume
            return True
    
    async def restore_workflow_tasks(self, workflow_id: str) -> Dict[str, Any]:
        """Restore incomplete tasks back to the queue for execution"""
        try:
            # Get incomplete tasks that can be resumed
            incomplete_tasks = await self.get_incomplete_tasks(workflow_id)
            resumable_tasks = [t for t in incomplete_tasks if t['can_resume']]
            
            restored_count = 0
            skipped_count = 0
            
            async with self.transaction() as pipe:
                for task_info in resumable_tasks:
                    task_id = task_info['id']
                    priority = task_info['priority']
                    
                    # Reset task status to pending
                    pipe.hset(f"task:{task_id}", mapping={
                        "status": "pending",
                        "assigned_node_id": "",
                        "assigned_at": "",
                        "resumed_at": datetime.utcnow().isoformat()
                    })
                    
                    # Add back to priority queue (remove first to avoid duplicates)
                    priority_queue = f"queue:tasks:{priority}"
                    pipe.zrem(priority_queue, task_id)
                    pipe.zadd(priority_queue, {task_id: time.time()})
                    
                    # Clean up any stale assignments
                    pipe.hdel("queue:assigned", task_id)
                    pipe.zrem("queue:processing", task_id)
                    
                    restored_count += 1
                
                # Update workflow status to running if it was interrupted
                pipe.hset(f"workflow:{workflow_id}", mapping={
                    "status": "running",
                    "resumed_at": datetime.utcnow().isoformat()
                })
                
                # Publish workflow resumed event
                event = {
                    "type": "workflow_resumed",
                    "workflow_id": workflow_id,
                    "restored_tasks": restored_count,
                    "timestamp": datetime.utcnow().isoformat()
                }
                pipe.publish(f"notifications:workflow:{workflow_id}", json.dumps(event))
                pipe.publish("notifications:global", json.dumps(event))
            
            return {
                "workflow_id": workflow_id,
                "total_incomplete": len(incomplete_tasks),
                "restored_tasks": restored_count,
                "skipped_tasks": len(incomplete_tasks) - restored_count,
                "ready_for_execution": restored_count > 0
            }
            
        except Exception as e:
            raise RedisOperationError(f"Failed to restore tasks for workflow {workflow_id}: {e}")
    
    async def get_nodes_by_capability(self, capability: str) -> List[str]:
        """Get nodes with specific capability"""
        try:
            return await self.redis.smembers(f"nodes:by_capability:{capability}")
        except Exception as e:
            raise RedisOperationError(f"Failed to get nodes by capability {capability}: {e}")
    
    # ========================
    # Utility Operations  
    # ========================
    
    async def cleanup_expired_workflows(self) -> int:
        """Clean up expired workflow data"""
        try:
            cutoff_time = time.time() - self.workflow_ttl
            
            # Get old completed workflows
            expired = await self.redis.zrangebyscore(
                "workflows:completed", 
                "-inf", 
                cutoff_time
            )
            
            if not expired:
                return 0
            
            # Remove expired workflows
            async with self.transaction() as pipe:
                for workflow_id in expired:
                    # Remove workflow data
                    pipe.delete(f"workflow:{workflow_id}")
                    pipe.delete(f"workflow:{workflow_id}:tasks")
                    pipe.delete(f"workflow:{workflow_id}:results")
                    pipe.delete(f"workflow:{workflow_id}:errors")
                    
                    # Remove from completed set
                    pipe.zrem("workflows:completed", workflow_id)
                    
                    # Remove associated tasks
                    task_ids = await self.redis.lrange(f"workflow:{workflow_id}:tasks", 0, -1)
                    for task_id in task_ids:
                        pipe.delete(f"task:{task_id}")
                        pipe.delete(f"task:{task_id}:dependencies")
            
            print(f"🧹 Cleaned up {len(expired)} expired workflows")
            return len(expired)
            
        except Exception as e:
            raise RedisOperationError(f"Failed to cleanup expired workflows: {e}")
    
    async def get_cluster_stats(self) -> Dict[str, Any]:
        """Get cluster statistics"""
        try:
            # Get basic counts
            stats = {
                "active_workflows": await self.redis.scard("workflows:active"),
                "completed_workflows": await self.redis.zcard("workflows:completed"),
                "active_nodes": await self.redis.scard("nodes:active"),
                "queued_tasks": 0,
                "processing_tasks": await self.redis.zcard("queue:processing"),
                "assigned_tasks": await self.redis.hlen("queue:assigned")
            }
            
            # Count queued tasks across all priorities
            for priority in ["urgent", "high", "normal", "low"]:
                count = await self.redis.zcard(f"queue:tasks:{priority}")
                stats["queued_tasks"] += count
            
            # Get system info
            config = await self.redis.hgetall("config:cluster")
            stats["cluster_config"] = config
            
            return stats
            
        except Exception as e:
            raise RedisOperationError(f"Failed to get cluster stats: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Redis health"""
        try:
            start_time = time.time()
            await self.redis.ping()
            ping_time = (time.time() - start_time) * 1000
            
            info = await self.redis.info()
            
            return {
                "connected": True,
                "ping_ms": round(ping_time, 2),
                "redis_version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "uptime_seconds": info.get("uptime_in_seconds")
            }
            
        except Exception as e:
            return {
                "connected": False,
                "error": str(e)
            }
    
    def __str__(self) -> str:
        return f"RedisClient(url={self.redis_url}, connected={self._is_connected})"