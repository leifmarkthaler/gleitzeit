"""
Redis Client for Gleitzeit V2

Clean Redis interface for task and workflow persistence.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

import redis.asyncio as redis

from ..core.models import Task, Workflow, TaskStatus, WorkflowStatus

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Redis client for Gleitzeit V2 data persistence
    
    Features:
    - Task and workflow storage
    - Status tracking and updates
    - Result persistence
    - Clean key namespacing
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None
        
        # Key prefixes
        self.TASK_PREFIX = "gleitzeit:v2:task:"
        self.WORKFLOW_PREFIX = "gleitzeit:v2:workflow:"
        self.RESULT_PREFIX = "gleitzeit:v2:result:"
        self.STATUS_PREFIX = "gleitzeit:v2:status:"
        
        logger.info(f"RedisClient initialized: {redis_url}")
    
    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis = redis.from_url(self.redis_url)
            await self.redis.ping()
            logger.info("✅ Redis connected")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.aclose()
            logger.info("🔌 Redis disconnected")
    
    # ===================
    # Task Operations
    # ===================
    
    async def store_task(self, task: Task):
        """Store task in Redis"""
        key = f"{self.TASK_PREFIX}{task.id}"
        data = task.to_dict()
        
        await self.redis.hset(key, mapping={
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in data.items()
        })
        
        # Set expiration (30 days)
        await self.redis.expire(key, 30 * 24 * 60 * 60)
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task from Redis"""
        key = f"{self.TASK_PREFIX}{task_id}"
        data = await self.redis.hgetall(key)
        
        if not data:
            return None
        
        # Decode data
        decoded_data = {}
        for field, value in data.items():
            field_str = field.decode() if isinstance(field, bytes) else field
            value_str = value.decode() if isinstance(value, bytes) else value
            
            # Try to parse JSON for complex types
            try:
                decoded_data[field_str] = json.loads(value_str)
            except (json.JSONDecodeError, ValueError):
                decoded_data[field_str] = value_str
        
        return Task.from_dict(decoded_data)
    
    async def update_task_status(self, task_id: str, status: TaskStatus):
        """Update task status"""
        key = f"{self.TASK_PREFIX}{task_id}"
        await self.redis.hset(key, "status", status.value)
        
        # Also update in status tracking
        status_key = f"{self.STATUS_PREFIX}task:{task_id}"
        await self.redis.hset(status_key, mapping={
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat()
        })
        await self.redis.expire(status_key, 7 * 24 * 60 * 60)  # 7 days
    
    async def complete_task(self, task_id: str, result: Any = None, error: str = None):
        """Mark task as completed or failed"""
        key = f"{self.TASK_PREFIX}{task_id}"
        
        completion_data = {
            "completed_at": datetime.utcnow().isoformat(),
        }
        
        if error:
            completion_data.update({
                "status": TaskStatus.FAILED.value,
                "error": error
            })
        else:
            completion_data.update({
                "status": TaskStatus.COMPLETED.value,
                "result": json.dumps(result) if result is not None else ""
            })
        
        await self.redis.hset(key, mapping=completion_data)
        
        # Store result separately for easy access
        if result is not None:
            result_key = f"{self.RESULT_PREFIX}task:{task_id}"
            await self.redis.set(result_key, json.dumps(result))
            await self.redis.expire(result_key, 30 * 24 * 60 * 60)  # 30 days
    
    # ===================
    # Workflow Operations
    # ===================
    
    async def store_workflow(self, workflow: Workflow):
        """Store workflow in Redis"""
        key = f"{self.WORKFLOW_PREFIX}{workflow.id}"
        data = workflow.to_dict()
        
        await self.redis.hset(key, mapping={
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in data.items()
        })
        
        # Set expiration (90 days)
        await self.redis.expire(key, 90 * 24 * 60 * 60)
    
    async def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow from Redis"""
        key = f"{self.WORKFLOW_PREFIX}{workflow_id}"
        data = await self.redis.hgetall(key)
        
        if not data:
            return None
        
        # Decode data
        decoded_data = {}
        for field, value in data.items():
            field_str = field.decode() if isinstance(field, bytes) else field
            value_str = value.decode() if isinstance(value, bytes) else value
            
            # Try to parse JSON for complex types
            try:
                decoded_data[field_str] = json.loads(value_str)
            except (json.JSONDecodeError, ValueError):
                decoded_data[field_str] = value_str
        
        return decoded_data
    
    async def update_workflow_status(self, workflow_id: str, status: WorkflowStatus):
        """Update workflow status"""
        key = f"{self.WORKFLOW_PREFIX}{workflow_id}"
        await self.redis.hset(key, "status", status.value)
        
        if status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]:
            await self.redis.hset(key, "completed_at", datetime.utcnow().isoformat())
        
        # Also update in status tracking
        status_key = f"{self.STATUS_PREFIX}workflow:{workflow_id}"
        await self.redis.hset(status_key, mapping={
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat()
        })
        await self.redis.expire(status_key, 30 * 24 * 60 * 60)  # 30 days
    
    async def update_workflow_progress(self, workflow_id: str, progress: Dict):
        """Update workflow progress"""
        key = f"{self.WORKFLOW_PREFIX}{workflow_id}"
        await self.redis.hset(key, mapping={
            "completed_tasks": json.dumps(progress.get("completed", [])),
            "failed_tasks": json.dumps(progress.get("failed", [])),
            "task_results": json.dumps(progress.get("task_results", {}))
        })
    
    async def get_workflow_results(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow results"""
        key = f"{self.WORKFLOW_PREFIX}{workflow_id}"
        data = await self.redis.hgetall(key)
        
        if not data:
            return None
        
        # Extract results
        results = {}
        for field, value in data.items():
            field_str = field.decode() if isinstance(field, bytes) else field
            value_str = value.decode() if isinstance(value, bytes) else value
            
            if field_str == "task_results":
                try:
                    results = json.loads(value_str)
                except (json.JSONDecodeError, ValueError):
                    results = {}
                break
        
        return results
    
    # ===================
    # Query Operations
    # ===================
    
    async def list_workflows(self, status: Optional[WorkflowStatus] = None, limit: int = 100) -> List[Dict]:
        """List workflows with optional status filter"""
        pattern = f"{self.WORKFLOW_PREFIX}*"
        workflows = []
        
        async for key in self.redis.scan_iter(match=pattern, count=100):
            workflow_data = await self.get_workflow(key.decode().replace(self.WORKFLOW_PREFIX, ""))
            
            if workflow_data:
                if status is None or workflow_data.get("status") == status.value:
                    workflows.append(workflow_data)
                
                if len(workflows) >= limit:
                    break
        
        return workflows
    
    async def list_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        # This is a simplified version - in practice, you might want to store
        # workflow->task relationships more efficiently
        pattern = f"{self.TASK_PREFIX}*"
        tasks = []
        
        async for key in self.redis.scan_iter(match=pattern, count=100):
            task = await self.get_task(key.decode().replace(self.TASK_PREFIX, ""))
            
            if task and task.workflow_id == workflow_id:
                tasks.append(task)
        
        return tasks
    
    async def get_task_result(self, task_id: str) -> Optional[Any]:
        """Get task result"""
        result_key = f"{self.RESULT_PREFIX}task:{task_id}"
        data = await self.redis.get(result_key)
        
        if data:
            try:
                return json.loads(data.decode())
            except (json.JSONDecodeError, ValueError):
                return data.decode()
        
        return None
    
    # ===================
    # Utility Operations
    # ===================
    
    async def cleanup_expired(self):
        """Clean up expired entries (Redis handles this automatically with TTL)"""
        # Redis automatically handles TTL cleanup
        # This method can be used for manual cleanup if needed
        pass
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get Redis storage statistics"""
        info = await self.redis.info()
        
        # Count our keys
        task_count = 0
        workflow_count = 0
        
        async for key in self.redis.scan_iter(match=f"{self.TASK_PREFIX}*", count=100):
            task_count += 1
        
        async for key in self.redis.scan_iter(match=f"{self.WORKFLOW_PREFIX}*", count=100):
            workflow_count += 1
        
        return {
            "redis_info": {
                "connected_clients": info.get("connected_clients"),
                "used_memory": info.get("used_memory"),
                "used_memory_human": info.get("used_memory_human"),
                "total_commands_processed": info.get("total_commands_processed")
            },
            "gleitzeit_v2": {
                "tasks": task_count,
                "workflows": workflow_count
            }
        }