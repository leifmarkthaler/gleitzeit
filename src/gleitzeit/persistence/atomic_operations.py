"""
Atomic persistence operations for race-condition-free stateless operation.

This module provides atomic operations using Redis primitives and
database row-level locking to prevent race conditions in distributed systems.
"""

import asyncio
import logging
import json
from typing import Any, Optional, Dict, Set, List, Callable
from datetime import datetime, timedelta
from uuid import uuid4
from enum import Enum

from gleitzeit.core.models import TaskStatus, WorkflowStatus

logger = logging.getLogger(__name__)


class LockResult(Enum):
    """Result of lock acquisition attempt."""
    ACQUIRED = "acquired"
    ALREADY_LOCKED = "already_locked"
    EXPIRED = "expired"
    ERROR = "error"


class AtomicPersistenceOperations:
    """
    Atomic operations for distributed stateless systems.
    
    Provides:
    - Distributed locking with TTL
    - Compare-and-set operations
    - Atomic task assignment
    - State machine transitions
    - Idempotency guarantees
    """
    
    def __init__(self, redis_client, base_persistence=None):
        """
        Initialize atomic operations.
        
        Args:
            redis_client: Redis client for atomic operations
            base_persistence: Optional base persistence for non-atomic ops
        """
        self.redis = redis_client
        self.base = base_persistence
        
        # Lua scripts for atomic operations
        self._init_lua_scripts()
        
        logger.info("Initialized AtomicPersistenceOperations")
    
    def _init_lua_scripts(self):
        """Initialize Lua scripts for atomic operations."""
        
        # Compare-and-set script
        self.cas_script = """
        local key = KEYS[1]
        local old_value = ARGV[1]
        local new_value = ARGV[2]
        
        local current = redis.call('GET', key)
        if current == old_value then
            redis.call('SET', key, new_value)
            return 1
        else
            return 0
        end
        """
        
        # Atomic task assignment script
        self.assign_task_script = """
        local task_key = KEYS[1]
        local assignment_key = KEYS[2]
        local worker_id = ARGV[1]
        local ttl = ARGV[2]
        
        -- Check if task is already assigned
        local existing = redis.call('GET', assignment_key)
        if existing then
            return 0  -- Already assigned
        end
        
        -- Check task status is PENDING (tasks stored as Redis hashes)
        local task_status = redis.call('HGET', task_key, 'status')
        if not task_status then
            return -1  -- Task not found
        end
        
        if task_status ~= 'pending' then
            return -2  -- Task not pending
        end
        
        -- Atomically assign and update status
        redis.call('SETEX', assignment_key, ttl, worker_id)
        redis.call('HSET', task_key, 'status', 'executing')
        redis.call('HSET', task_key, 'assigned_to', worker_id)
        redis.call('HSET', task_key, 'assigned_at', ARGV[3])
        
        return 1  -- Success
        """
        
        # Workflow completion check script
        self.check_workflow_complete_script = """
        local workflow_key = KEYS[1]
        local workflow_task_index_key = KEYS[2]
        
        -- Get all task IDs for workflow from the index
        local task_ids = redis.call('SMEMBERS', workflow_task_index_key)
        
        local all_complete = true
        local task_count = 0
        local completed_count = 0
        
        for _, task_id in ipairs(task_ids) do
            local task_key = 'gleitzeit:task:' .. task_id
            local task_status = redis.call('HGET', task_key, 'status')
            if task_status then
                task_count = task_count + 1
                if task_status == 'completed' then
                    completed_count = completed_count + 1
                elseif task_status ~= 'cancelled' then
                    all_complete = false
                end
            end
        end
        
        if all_complete and task_count > 0 then
            -- Update workflow status atomically
            local workflow_status = redis.call('HGET', workflow_key, 'status')
            if workflow_status and workflow_status == 'running' then
                redis.call('HSET', workflow_key, 'status', 'completed')
                redis.call('HSET', workflow_key, 'completed_at', ARGV[1])
                return 1
            end
        end
        
        return 0
        """
    
    # Distributed Locking
    
    async def acquire_lock(
        self, 
        resource: str, 
        lock_id: str, 
        ttl: int = 30
    ) -> bool:
        """
        Acquire distributed lock with TTL.
        
        Args:
            resource: Resource identifier to lock
            lock_id: Unique identifier for this lock holder
            ttl: Time-to-live in seconds
            
        Returns:
            True if lock acquired, False otherwise
        """
        key = f"lock:{resource}"
        
        # Use SET NX EX for atomic lock acquisition
        result = await self.redis.set(
            key, 
            lock_id, 
            nx=True,  # Only set if not exists
            ex=ttl    # Expire after TTL
        )
        
        if result:
            logger.debug(f"Acquired lock for {resource} with ID {lock_id}")
        
        return bool(result)
    
    async def release_lock(self, resource: str, lock_id: str) -> bool:
        """
        Release distributed lock if we still own it.
        
        Args:
            resource: Resource identifier
            lock_id: Our lock identifier
            
        Returns:
            True if released, False if not owned by us
        """
        key = f"lock:{resource}"
        
        # Lua script to only delete if we own it
        lua = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        else
            return 0
        end
        """
        
        result = await self.redis.eval(lua, 1, key, lock_id)
        
        if result:
            logger.debug(f"Released lock for {resource}")
        
        return bool(result)
    
    async def extend_lock(self, resource: str, lock_id: str, ttl: int) -> bool:
        """
        Extend lock TTL if we still own it.
        
        Args:
            resource: Resource identifier
            lock_id: Our lock identifier
            ttl: New TTL in seconds
            
        Returns:
            True if extended, False if not owned by us
        """
        key = f"lock:{resource}"
        
        lua = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('EXPIRE', KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        
        result = await self.redis.eval(lua, 1, key, lock_id, ttl)
        return bool(result)
    
    # Atomic Task Operations
    
    async def claim_task(
        self, 
        task_id: str, 
        worker_id: str, 
        lease_ttl: int = 300
    ) -> bool:
        """
        Atomically claim a task for execution.
        
        Args:
            task_id: Task to claim
            worker_id: Worker claiming the task
            lease_ttl: Lease time in seconds
            
        Returns:
            True if claimed, False if already claimed or not ready
        """
        task_key = f"gleitzeit:task:{task_id}"
        assignment_key = f"gleitzeit:task_assignment:{task_id}"
        
        result = await self.redis.eval(
            self.assign_task_script,
            2,
            task_key,
            assignment_key,
            worker_id,
            str(lease_ttl),
            datetime.utcnow().isoformat()
        )
        
        if result == 1:
            logger.info(f"Worker {worker_id} claimed task {task_id}")
            return True
        elif result == 0:
            logger.debug(f"Task {task_id} already assigned")
        elif result == -1:
            logger.warning(f"Task {task_id} not found")
        elif result == -2:
            logger.debug(f"Task {task_id} not in PENDING state")
        
        return False
    
    async def release_task(self, task_id: str, worker_id: str) -> bool:
        """
        Release task assignment (for retry/failure cases).
        
        Args:
            task_id: Task to release
            worker_id: Worker releasing (must be owner)
            
        Returns:
            True if released, False otherwise
        """
        assignment_key = f"gleitzeit:task_assignment:{task_id}"
        
        # Only release if we own it
        lua = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            redis.call('DEL', KEYS[1])
            -- Also reset task status to PENDING (tasks stored as Redis hashes)
            local task_key = ARGV[2]
            local task_exists = redis.call('EXISTS', task_key)
            if task_exists == 1 then
                redis.call('HSET', task_key, 'status', 'pending')
                redis.call('HDEL', task_key, 'assigned_to')
            end
            return 1
        end
        return 0
        """
        
        result = await self.redis.eval(
            lua, 
            1, 
            assignment_key, 
            worker_id,
            f"gleitzeit:task:{task_id}"
        )
        
        return bool(result)
    
    async def atomic_task_status_transition(
        self,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        worker_id: Optional[str] = None
    ) -> bool:
        """
        Atomically transition task status with validation.
        
        Args:
            task_id: Task ID
            from_status: Expected current status
            to_status: New status
            worker_id: Optional worker ID for ownership check
            
        Returns:
            True if transitioned, False otherwise
        """
        task_key = f"gleitzeit:task:{task_id}"
        
        lua = """
        local task_exists = redis.call('EXISTS', KEYS[1])
        if task_exists == 0 then
            return -1  -- Not found
        end
        
        -- Check current status (tasks stored as Redis hashes)
        local current_status = redis.call('HGET', KEYS[1], 'status')
        if current_status ~= ARGV[1] then
            return -2  -- Wrong status
        end
        
        -- Check ownership if worker_id provided
        if ARGV[3] ~= '' then
            local assigned_to = redis.call('HGET', KEYS[1], 'assigned_to')
            if assigned_to ~= ARGV[3] then
                return -3  -- Not owner
            end
        end
        
        -- Update status
        redis.call('HSET', KEYS[1], 'status', ARGV[2])
        redis.call('HSET', KEYS[1], 'updated_at', ARGV[4])
        
        -- Clear assignment if completing/failing
        if ARGV[2] == 'completed' or ARGV[2] == 'failed' then
            redis.call('HDEL', KEYS[1], 'assigned_to')
            -- Also delete assignment key (need task ID from hash)
            local task_id = redis.call('HGET', KEYS[1], 'id')
            if task_id then
                redis.call('DEL', 'gleitzeit:task_assignment:' .. task_id)
            end
        end
        
        return 1
        """
        
        result = await self.redis.eval(
            lua,
            1,
            task_key,
            from_status.value if hasattr(from_status, 'value') else from_status,
            to_status.value if hasattr(to_status, 'value') else to_status,
            worker_id or '',
            datetime.utcnow().isoformat()
        )
        
        if result == 1:
            logger.info(f"Task {task_id} transitioned from {from_status} to {to_status}")
            return True
        elif result == -1:
            logger.error(f"Task {task_id} not found")
        elif result == -2:
            logger.warning(f"Task {task_id} not in expected status {from_status}")
        elif result == -3:
            logger.warning(f"Worker {worker_id} does not own task {task_id}")
        
        return False
    
    # Atomic Workflow Operations
    
    async def check_and_complete_workflow(
        self, 
        workflow_id: str
    ) -> bool:
        """
        Atomically check if workflow is complete and update status.
        
        Args:
            workflow_id: Workflow to check
            
        Returns:
            True if workflow was completed, False otherwise
        """
        workflow_key = f"gleitzeit:workflow:{workflow_id}"
        workflow_task_index_key = f"gleitzeit:idx:workflow_tasks:{workflow_id}"
        
        result = await self.redis.eval(
            self.check_workflow_complete_script,
            2,
            workflow_key,
            workflow_task_index_key,
            datetime.utcnow().isoformat()
        )
        
        if result == 1:
            logger.info(f"Workflow {workflow_id} marked complete")
            return True
        
        return False
    
    # Compare-and-Set Operations
    
    async def compare_and_set(
        self,
        key: str,
        old_value: Any,
        new_value: Any
    ) -> bool:
        """
        Compare and set value atomically.
        
        Args:
            key: Key to update
            old_value: Expected current value
            new_value: New value to set
            
        Returns:
            True if updated, False if current value doesn't match
        """
        # Serialize values to JSON for comparison
        old_json = json.dumps(old_value, sort_keys=True)
        new_json = json.dumps(new_value, sort_keys=True)
        
        result = await self.redis.eval(
            self.cas_script,
            1,
            key,
            old_json,
            new_json
        )
        
        return bool(result)
    
    # Idempotency Support
    
    async def execute_once(
        self,
        idempotency_key: str,
        operation: Callable,
        ttl: int = 3600
    ) -> Any:
        """
        Execute operation with idempotency guarantee.
        
        Args:
            idempotency_key: Unique key for this operation
            operation: Async callable to execute
            ttl: Result cache TTL in seconds
            
        Returns:
            Operation result (cached or fresh)
        """
        result_key = f"idempotent:{idempotency_key}"
        
        # Check if already executed
        cached = await self.redis.get(result_key)
        if cached:
            return json.loads(cached)
        
        # Acquire lock for execution
        lock_id = uuid4().hex
        lock_acquired = await self.acquire_lock(
            f"idempotent_lock:{idempotency_key}",
            lock_id,
            ttl=60
        )
        
        if not lock_acquired:
            # Someone else is executing, wait and retry
            await asyncio.sleep(0.5)
            cached = await self.redis.get(result_key)
            if cached:
                return json.loads(cached)
            raise Exception(f"Failed to acquire lock for {idempotency_key}")
        
        try:
            # Execute operation
            result = await operation()
            
            # Cache result
            await self.redis.setex(
                result_key,
                ttl,
                json.dumps(result)
            )
            
            return result
            
        finally:
            # Release lock
            await self.release_lock(
                f"idempotent_lock:{idempotency_key}",
                lock_id
            )
    
    # Batch Operations
    
    async def claim_tasks_batch(
        self,
        task_ids: List[str],
        worker_id: str,
        max_claims: int = 1
    ) -> List[str]:
        """
        Try to claim multiple tasks, returning those successfully claimed.
        
        Args:
            task_ids: Tasks to try claiming
            worker_id: Worker ID
            max_claims: Maximum tasks to claim
            
        Returns:
            List of successfully claimed task IDs
        """
        claimed = []
        
        for task_id in task_ids:
            if len(claimed) >= max_claims:
                break
                
            if await self.claim_task(task_id, worker_id):
                claimed.append(task_id)
        
        return claimed
    
    # Version-based Operations
    
    async def update_with_version(
        self,
        key: str,
        update_fn: Callable,
        max_retries: int = 3
    ) -> Any:
        """
        Update value with automatic version conflict resolution.
        
        Args:
            key: Key to update
            update_fn: Function that takes current value and returns new value
            max_retries: Maximum retry attempts
            
        Returns:
            Updated value
            
        Raises:
            Exception if max retries exceeded
        """
        for attempt in range(max_retries):
            # Get current value and version
            current_data = await self.redis.get(key)
            if current_data:
                current = json.loads(current_data)
                version = current.get('__version__', 0)
            else:
                current = {}
                version = 0
            
            # Apply update
            updated = update_fn(current)
            updated['__version__'] = version + 1
            
            # Try to save with version check
            lua = """
            local current = redis.call('GET', KEYS[1])
            if not current then
                -- New key
                if tonumber(ARGV[2]) == 0 then
                    redis.call('SET', KEYS[1], ARGV[1])
                    return 1
                end
                return 0
            end
            
            local data = cjson.decode(current)
            if data.__version__ == tonumber(ARGV[2]) then
                redis.call('SET', KEYS[1], ARGV[1])
                return 1
            end
            return 0
            """
            
            result = await self.redis.eval(
                lua,
                1,
                key,
                json.dumps(updated),
                str(version)
            )
            
            if result == 1:
                return updated
            
            # Retry with exponential backoff
            await asyncio.sleep(0.1 * (2 ** attempt))
        
        raise Exception(f"Failed to update {key} after {max_retries} retries")