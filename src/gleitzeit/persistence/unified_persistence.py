"""
Unified Persistence Layer for Gleitzeit

This module provides a unified persistence interface that handles both:
1. Task/Workflow persistence (tasks, workflows, execution state, queue state)
2. Hub Resource persistence (resource instances, metrics, distributed locks)

Supports multiple backends: SQLAlchemy (default SQLite), Redis, and In-Memory.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
import logging

# Task/Workflow models
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution, TaskStatus

# Hub Resource models
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType

logger = logging.getLogger(__name__)


class UnifiedPersistenceAdapter(ABC):
    """
    Unified persistence interface for both task and hub resource management.
    
    This combines:
    - PersistenceBackend functionality (tasks, workflows, queues)
    - HubPersistenceAdapter functionality (resources, metrics, locks)
    """
    
    # =========================================================================
    # Lifecycle Methods
    # =========================================================================
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the persistence backend"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the persistence backend and cleanup resources"""
        pass
    
    # =========================================================================
    # Task/Workflow Operations (from PersistenceBackend)
    # =========================================================================
    
    @abstractmethod
    async def save_task(self, task: Task) -> None:
        """
        Save or update a task
        
        REQUIREMENT: Every task MUST have a workflow_id.
        Raises ValueError if task has no workflow_id.
        """
        if not task.workflow_id:
            error_msg = (
                f"Task {task.id} ({task.name}) cannot be saved without a workflow_id. "
                "Every task must belong to a workflow. "
                "Use ExecutionEngine.submit_task() which auto-creates workflows for single tasks."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        pass
    
    @abstractmethod
    async def update_task(self, task_data: Any) -> None:
        """
        Update an existing task - used by reconciliation service.
        
        Args:
            task_data: Task object or dict with task updates
        """
        pass
    
    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        pass
    
    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        pass
    
    @abstractmethod
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get all tasks with a specific status"""
        pass
    
    @abstractmethod
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        pass
    
    @abstractmethod
    async def save_task_result(self, task_result: TaskResult) -> None:
        """Save a task result"""
        pass
    
    @abstractmethod
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result by task ID"""
        pass
    
    @abstractmethod
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save or update a workflow"""
        pass
    
    @abstractmethod
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID"""
        pass
    
    @abstractmethod
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow and all its associated tasks"""
        pass
    
    @abstractmethod
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Save workflow execution state"""
        pass
    
    @abstractmethod
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution by ID"""
        pass
    
    @abstractmethod
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        """Save queue state for recovery"""
        pass
    
    @abstractmethod
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Get saved queue state"""
        pass
    
    @abstractmethod
    async def delete_queue_state(self, queue_name: str) -> bool:
        """Delete queue state"""
        pass
    
    @abstractmethod
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        """Save multiple tasks in a single operation"""
        pass
    
    async def acquire_next_queued_task(self, check_dependencies: bool = True) -> Optional[Task]:
        """
        Atomically acquire the next queued task and mark it as EXECUTING.
        
        This method prevents race conditions by atomically checking and updating
        task status in a single operation. Different backends implement this
        differently:
        - Redis: Uses Lua scripts or WATCH/MULTI/EXEC
        - SQL: Uses SELECT FOR UPDATE or similar row locking
        - Memory: Uses asyncio locks
        
        Args:
            check_dependencies: Whether to check task dependencies
            
        Returns:
            The acquired task with status already set to EXECUTING, or None
        """
        # Default implementation for backwards compatibility
        # Backends should override this with atomic implementations
        return None
    
    @abstractmethod
    async def get_all_queued_tasks(self) -> List[Task]:
        """Get all tasks that should be in queues on startup"""
        pass
    
    @abstractmethod
    async def get_task_count_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        pass
    
    @abstractmethod
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        """Remove old completed tasks and results before cutoff date"""
        pass
    
    async def clean_queue_state_for_tasks(self, task_ids: List[str]) -> None:
        """
        Clean queue state by removing references to deleted tasks.
        This is a helper method used by delete_workflow.
        """
        # Default implementation - can be overridden by adapters
        pass
    
    # List operations for UI/API
    @abstractmethod
    async def list_workflows(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List all workflows with optional filtering and pagination"""
        pass
    
    @abstractmethod
    async def list_tasks(self, workflow_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List all tasks with optional filtering and pagination"""
        pass
    
    # =========================================================================
    # Hub Resource Operations (from HubPersistenceAdapter)
    # =========================================================================
    
    @abstractmethod
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        pass
    
    @abstractmethod
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        pass
    
    @abstractmethod
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        """List all instances for a hub"""
        pass
    
    @abstractmethod
    async def delete_instance(self, instance_id: str) -> None:
        """Remove instance from storage"""
        pass
    
    @abstractmethod
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Store metrics snapshot"""
        pass
    
    @abstractmethod
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Retrieve historical metrics"""
        pass
    
    @abstractmethod
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock for resource allocation"""
        pass
    
    @abstractmethod
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release distributed lock"""
        pass
    
    @abstractmethod
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock timeout"""
        pass
    
    @abstractmethod
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get current lock owner"""
        pass
    
    # =========================================================================
    # Cross-Domain Operations (linking tasks and resources)
    # =========================================================================
    
    async def get_tasks_for_resource(self, resource_id: str) -> List[Task]:
        """Get all tasks assigned to a specific resource"""
        # Default implementation using existing methods
        all_tasks = await self.get_tasks_by_status("executing")
        return [t for t in all_tasks if t.assigned_provider == resource_id]
    
    async def get_resource_for_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the resource instance assigned to a task"""
        task = await self.get_task(task_id)
        if task and task.assigned_provider:
            return await self.load_instance(task.assigned_provider)
        return None
    
    async def get_resource_utilization(self, hub_id: str) -> Dict[str, Any]:
        """Get resource utilization statistics for a hub"""
        instances = await self.list_instances(hub_id)
        total = len(instances)
        
        # Count instances by status
        status_counts = {}
        for instance in instances:
            status = instance.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Get active tasks per instance
        utilization = []
        for instance in instances:
            tasks = await self.get_tasks_for_resource(instance['id'])
            utilization.append({
                'instance_id': instance['id'],
                'active_tasks': len(tasks),
                'status': instance.get('status')
            })
        
        return {
            'total_instances': total,
            'status_distribution': status_counts,
            'instance_utilization': utilization
        }


# ============================================================================
# Adapter Implementations
# ============================================================================

class UnifiedInMemoryAdapter(UnifiedPersistenceAdapter):
    """In-memory implementation for testing and development with thread-safety"""
    
    def supports_atomic_operations(self) -> bool:
        """In-memory adapter supports thread-local atomic operations via asyncio.Lock."""
        return True  # We now support atomic operations through locks
    
    def __init__(self):
        import asyncio
        from collections import deque
        
        # Thread safety lock for atomic operations
        self._lock = asyncio.Lock()
        self._task_locks: Dict[str, asyncio.Lock] = {}  # Per-task locks
        
        # Task/Workflow storage
        self.tasks: Dict[str, Task] = {}
        self.task_results: Dict[str, TaskResult] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.workflow_executions: Dict[str, WorkflowExecution] = {}
        self.queue_states: Dict[str, Dict[str, Any]] = {}
        
        # Event storage - using deques with maxlen for automatic trimming
        self.events_global = deque(maxlen=10000)  # Global event stream
        self.events_by_workflow: Dict[str, deque] = {}  # Per-workflow streams
        self.events_by_task: Dict[str, deque] = {}  # Per-task streams
        
        # Hub Resource storage
        self.instances: Dict[str, Dict[str, Any]] = {}
        self.hub_instances: Dict[str, Set[str]] = {}  # hub_id -> set of instance_ids
        self.metrics: Dict[str, List[Dict[str, Any]]] = {}
        self.locks: Dict[str, tuple] = {}  # resource_id -> (owner_id, expiry)
        
        # Redis-like storage structures for StatelessEventBus
        self._hashes: Dict[str, Dict[str, str]] = {}  # For hset/hget operations
        self._sorted_sets: Dict[str, List[tuple]] = {}  # For zadd/zrange operations  
        self._sets: Dict[str, set] = {}  # For sadd/smembers operations
        self._lists: Dict[str, list] = {}  # For lpush/lrange operations
        self._keys_ttl: Dict[str, float] = {}  # For expire operations
        
        # Create a mock Redis client for atomic operations
        self.redis = MockRedisClient(self)
        
        self._initialized = False
    
    async def initialize(self) -> None:
        """No initialization needed for in-memory"""
        self._initialized = True
        logger.info("Unified in-memory adapter initialized")
    
    async def shutdown(self) -> None:
        """Clear all data"""
        self.tasks.clear()
        self.task_results.clear()
        self.workflows.clear()
        self.workflow_executions.clear()
        self.queue_states.clear()
        self.events_global.clear()
        self.events_by_workflow.clear()
        self.events_by_task.clear()
        self.instances.clear()
        self.hub_instances.clear()
        self.metrics.clear()
        self.locks.clear()
        self._initialized = False
        logger.info("Unified in-memory adapter shut down")
    
    # Task operations
    async def save_task(self, task: Task) -> None:
        # Validate workflow_id requirement
        if not task.workflow_id:
            error_msg = (
                f"Task {task.id} ({task.name}) cannot be saved without a workflow_id. "
                "Every task must belong to a workflow. "
                "Use ExecutionEngine.submit_task() which auto-creates workflows for single tasks."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        async with self._lock:
            self.tasks[task.id] = task
    
    async def update_task(self, task_data: Any) -> None:
        """Update an existing task - used by reconciliation service"""
        from typing import Union
        
        async with self._lock:
            if isinstance(task_data, dict):
                # Handle dict format
                task_id = task_data.get('task_id') or task_data.get('id')
                if not task_id or task_id not in self.tasks:
                    return
                
                task = self.tasks[task_id]
                
                # Update task fields from dict
                if 'status' in task_data:
                    task.status = TaskStatus(task_data['status'])
                if 'result' in task_data:
                    task.result = task_data['result']
                if 'error' in task_data:
                    task.error = task_data['error']
                if 'metadata' in task_data:
                    if task.metadata:
                        task.metadata.update(task_data['metadata'])
                    else:
                        task.metadata = task_data['metadata']
            elif isinstance(task_data, Task):
                # Handle Task object
                if task_data.id in self.tasks:
                    self.tasks[task_data.id] = task_data
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)
    
    async def delete_task(self, task_id: str) -> bool:
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        return [task for task in self.tasks.values() if task.status == status]
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        return [task for task in self.tasks.values() if task.workflow_id == workflow_id]
    
    async def save_task_result(self, task_result: TaskResult) -> None:
        self.task_results[task_result.task_id] = task_result
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        return self.task_results.get(task_id)
    
    async def save_workflow(self, workflow: Workflow) -> None:
        self.workflows[workflow.id] = workflow
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self.workflows.get(workflow_id)
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow and all its associated tasks"""
        # Check for tasks associated with this workflow (they might exist even without a workflow record)
        tasks_to_delete = [
            task_id for task_id, task in self.tasks.items() 
            if task.workflow_id == workflow_id
        ]
        
        # If neither workflow nor tasks exist, return False
        if workflow_id not in self.workflows and not tasks_to_delete:
            return False
        
        # Delete all tasks and their results
        for task_id in tasks_to_delete:
            del self.tasks[task_id]
            # Also delete task results if they exist
            self.task_results.pop(task_id, None)
        
        # Delete the workflow itself if it exists
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
        
        # Delete workflow execution if exists
        self.workflow_executions = {
            exec_id: exec_data 
            for exec_id, exec_data in self.workflow_executions.items()
            if exec_data.workflow_id != workflow_id
        }
        
        # Clean queue state references
        await self.clean_queue_state_for_tasks(tasks_to_delete)
        
        return True
    
    async def clean_queue_state_for_tasks(self, task_ids: List[str]) -> None:
        """Clean queue state by removing references to deleted tasks"""
        if not task_ids:
            return
        
        task_id_set = set(task_ids)
        
        # Clean all queue states
        for queue_name, queue_state in self.queue_states.items():
            if 'completed_tasks' in queue_state:
                queue_state['completed_tasks'] = [
                    task_id for task_id in queue_state['completed_tasks']
                    if task_id not in task_id_set
                ]
            
            if 'failed_tasks' in queue_state:
                queue_state['failed_tasks'] = [
                    task_id for task_id in queue_state['failed_tasks']
                    if task_id not in task_id_set
                ]
    
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        self.workflow_executions[execution.execution_id] = execution
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        return self.workflow_executions.get(execution_id)
    
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        self.queue_states[queue_name] = state
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        return self.queue_states.get(queue_name)
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        if queue_name in self.queue_states:
            del self.queue_states[queue_name]
            return True
        return False
    
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
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
        
        for task in tasks:
            self.tasks[task.id] = task
    
    async def get_all_queued_tasks(self) -> List[Task]:
        return [
            task for task in self.tasks.values() 
            if task.status in ["queued", "retry_pending", "executing"]
        ]
    
    async def get_task_count_by_status(self) -> Dict[str, int]:
        counts = {}
        for task in self.tasks.values():
            counts[task.status] = counts.get(task.status, 0) + 1
        return counts
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        old_tasks = [
            task_id for task_id, task in self.tasks.items()
            if task.status in ["completed", "failed"] and 
               task.completed_at and task.completed_at < cutoff_date
        ]
        
        for task_id in old_tasks:
            del self.tasks[task_id]
            self.task_results.pop(task_id, None)
        
        return len(old_tasks)
    
    # List operations for UI/API
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        return [task for task in self.tasks.values() if task.workflow_id == workflow_id]
    
    async def list_workflows(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List all workflows with optional filtering and pagination"""
        workflows = list(self.workflows.values())
        
        # Filter by status if provided
        if status:
            workflows = [w for w in workflows if hasattr(w, 'status') and w.status == status]
        
        # Sort by created_at (newest first)
        workflows.sort(key=lambda w: getattr(w, 'created_at', datetime.min), reverse=True)
        
        # Apply pagination
        total = len(workflows)
        workflows = workflows[offset:offset + limit]
        
        # Convert to dictionaries for consistent output
        workflow_dicts = []
        for w in workflows:
            workflow_dict = {
                "id": w.id,
                "name": w.name,
                "description": getattr(w, 'description', ''),
                "status": getattr(w, 'status', 'unknown'),
                "created_at": w.created_at.isoformat() if hasattr(w, 'created_at') and w.created_at else '',
                "tasks_total": len(w.tasks) if hasattr(w, 'tasks') else 0,
                "tasks_completed": getattr(w, 'tasks_completed', 0),
                "tasks_failed": getattr(w, 'tasks_failed', 0)
            }
            workflow_dicts.append(workflow_dict)
        
        return {
            "workflows": workflow_dicts,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    
    async def list_tasks(self, workflow_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List all tasks with optional filtering and pagination"""
        tasks = list(self.tasks.values())
        
        # Filter by workflow_id if provided
        if workflow_id:
            tasks = [t for t in tasks if t.workflow_id == workflow_id]
        
        # Filter by status if provided
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        # Sort by created_at (newest first)
        tasks.sort(key=lambda t: getattr(t, 'created_at', datetime.min), reverse=True)
        
        # Apply pagination
        total = len(tasks)
        tasks = tasks[offset:offset + limit]
        
        return {
            "tasks": tasks,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    
    # Hub Resource operations
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        instance_data = {
            'id': instance.id,
            'hub_id': hub_id,
            'name': instance.name,
            'type': instance.type.value if isinstance(instance.type, ResourceType) else instance.type,
            'endpoint': instance.endpoint,
            'status': instance.status.value if isinstance(instance.status, ResourceStatus) else instance.status,
            'metadata': instance.metadata,
            'tags': list(instance.tags),
            'capabilities': list(instance.capabilities),
            'health_checks_failed': instance.health_checks_failed,
            'last_health_check': instance.last_health_check.isoformat() if instance.last_health_check else None,
            'created_at': instance.created_at.isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        self.instances[instance.id] = instance_data
        
        if hub_id not in self.hub_instances:
            self.hub_instances[hub_id] = set()
        self.hub_instances[hub_id].add(instance.id)
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return self.instances.get(instance_id)
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        instance_ids = self.hub_instances.get(hub_id, set())
        return [self.instances[iid] for iid in instance_ids if iid in self.instances]
    
    async def delete_instance(self, instance_id: str) -> None:
        if instance_id in self.instances:
            instance = self.instances[instance_id]
            hub_id = instance.get('hub_id')
            del self.instances[instance_id]
            
            if hub_id and hub_id in self.hub_instances:
                self.hub_instances[hub_id].discard(instance_id)
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        if instance_id not in self.metrics:
            self.metrics[instance_id] = []
        
        metrics_data = metrics.to_dict()
        metrics_data['timestamp'] = datetime.utcnow().isoformat()
        self.metrics[instance_id].append(metrics_data)
        
        # Keep only last 100 entries
        self.metrics[instance_id] = self.metrics[instance_id][-100:]
    
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        if instance_id not in self.metrics:
            return []
        
        result = []
        for m in self.metrics[instance_id]:
            if 'timestamp' in m:
                ts = datetime.fromisoformat(m['timestamp'])
                if start_time <= ts <= end_time:
                    result.append(m)
        return result
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        from datetime import timedelta
        now = datetime.utcnow()
        
        # Check if lock exists and is not expired
        if resource_id in self.locks:
            current_owner, expiry = self.locks[resource_id]
            if expiry > now:
                return False  # Lock held by someone
        
        # Acquire lock
        self.locks[resource_id] = (owner_id, now + timedelta(seconds=timeout))
        return True
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        if resource_id in self.locks:
            current_owner, _ = self.locks[resource_id]
            if current_owner == owner_id:
                del self.locks[resource_id]
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        from datetime import timedelta
        if resource_id in self.locks:
            current_owner, _ = self.locks[resource_id]
            if current_owner == owner_id:
                self.locks[resource_id] = (owner_id, datetime.utcnow() + timedelta(seconds=timeout))
                return True
        return False
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        if resource_id in self.locks:
            owner, expiry = self.locks[resource_id]
            if expiry > datetime.utcnow():
                return owner
            else:
                # Lock expired
                del self.locks[resource_id]
        return None
    
    # Event persistence methods
    async def save_event(self, event_data: Dict[str, Any]) -> None:
        """
        Save an event to in-memory storage.
        
        Args:
            event_data: Event dictionary with event_id, event_type, timestamp, etc.
        """
        from collections import deque
        
        # Add timestamp if not present
        if 'timestamp' not in event_data:
            event_data['timestamp'] = datetime.utcnow().isoformat()
        
        # Add to global stream
        self.events_global.append(event_data)
        
        # Add to workflow-specific stream if workflow_id present
        if 'workflow_id' in event_data and event_data['workflow_id']:
            if event_data['workflow_id'] not in self.events_by_workflow:
                self.events_by_workflow[event_data['workflow_id']] = deque(maxlen=1000)
            self.events_by_workflow[event_data['workflow_id']].append(event_data)
        
        # Add to task-specific stream if task_id present
        if 'task_id' in event_data and event_data['task_id']:
            if event_data['task_id'] not in self.events_by_task:
                self.events_by_task[event_data['task_id']] = deque(maxlen=100)
            self.events_by_task[event_data['task_id']].append(event_data)
    
    async def get_events(self,
                         workflow_id: Optional[str] = None,
                         task_id: Optional[str] = None,
                         event_type: Optional[str] = None,
                         since: Optional[datetime] = None,
                         until: Optional[datetime] = None,
                         limit: int = 1000) -> List[Dict[str, Any]]:
        """
        Retrieve events from in-memory storage with filters.
        
        Args:
            workflow_id: Filter by workflow ID
            task_id: Filter by task ID
            event_type: Filter by event type
            since: Events after this time
            until: Events before this time
            limit: Maximum number of events
            
        Returns:
            List of event dictionaries
        """
        # Determine which stream to use
        if task_id and task_id in self.events_by_task:
            events = list(self.events_by_task[task_id])
        elif workflow_id and workflow_id in self.events_by_workflow:
            events = list(self.events_by_workflow[workflow_id])
        else:
            events = list(self.events_global)
        
        # Apply filters
        filtered_events = []
        for event in events:
            # Filter by event type
            if event_type and event.get('event_type') != event_type:
                continue
            
            # Filter by time range
            if 'timestamp' in event:
                try:
                    event_time = datetime.fromisoformat(event['timestamp'])
                    if since and event_time < since:
                        continue
                    if until and event_time > until:
                        continue
                except:
                    pass  # Skip events with invalid timestamps
            
            filtered_events.append(event)
            
            if len(filtered_events) >= limit:
                break
        
        return filtered_events
    
    async def delete_old_events(self, days: int = 30) -> int:
        """
        Delete events older than specified days.
        Note: In-memory backend with deque automatically limits size,
        so this is a no-op but provided for interface compatibility.
        
        Args:
            days: Number of days to retain
            
        Returns:
            Always returns 0 (automatic trimming handles cleanup)
        """
        # Deques with maxlen automatically trim old events
        # This method exists for interface compatibility
        return 0

    # =========================================================================
    # Redis Compatibility Methods for StatelessEventBus
    # =========================================================================
        
    # Hash operations
    async def hset(self, key: str, *args, mapping=None, **kwargs) -> int:
        """Set hash field values"""
        if key not in self._hashes:
            self._hashes[key] = {}
            
        count = 0
        # Handle positional args (field, value, field, value, ...)
        if args:
            if len(args) % 2 != 0:
                raise ValueError("hset requires an even number of field/value pairs")
            for i in range(0, len(args), 2):
                field, value = args[i], args[i + 1]
                if field not in self._hashes[key] or self._hashes[key][field] != str(value):
                    self._hashes[key][field] = str(value)
                    count += 1
        
        # Handle mapping dict
        if mapping:
            for field, value in mapping.items():
                if field not in self._hashes[key] or self._hashes[key][field] != str(value):
                    self._hashes[key][field] = str(value)
                    count += 1
                    
        # Handle keyword args
        for field, value in kwargs.items():
            if field not in self._hashes[key] or self._hashes[key][field] != str(value):
                self._hashes[key][field] = str(value)
                count += 1
                
        return count
    
    async def hgetall(self, key: str) -> Dict[str, str]:
        """Get all hash fields and values"""
        return self._hashes.get(key, {})
    
    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        """Increment hash field by amount"""
        if key not in self._hashes:
            self._hashes[key] = {}
        current = int(self._hashes[key].get(field, 0))
        new_value = current + amount
        self._hashes[key][field] = str(new_value)
        return new_value
    
    # Sorted set operations
    async def zadd(self, key: str, mapping: Dict[str, float]) -> int:
        """Add members to sorted set"""
        if key not in self._sorted_sets:
            self._sorted_sets[key] = []
            
        count = 0
        for member, score in mapping.items():
            # Remove existing member if present
            self._sorted_sets[key] = [
                (m, s) for m, s in self._sorted_sets[key] if m != member
            ]
            # Add with new score
            self._sorted_sets[key].append((member, score))
            count += 1
            
        # Keep sorted by score
        self._sorted_sets[key].sort(key=lambda x: x[1])
        return count
    
    async def zrange(self, key: str, start: int, stop: int) -> List[str]:
        """Get range of members from sorted set"""
        if key not in self._sorted_sets:
            return []
        items = self._sorted_sets[key]
        if stop == -1:
            stop = len(items)
        else:
            stop = min(stop + 1, len(items))
        start = max(0, start)
        return [item[0] for item in items[start:stop]]
    
    async def zrem(self, key: str, *members) -> int:
        """Remove members from sorted set"""
        if key not in self._sorted_sets:
            return 0
        count = 0
        for member in members:
            original_len = len(self._sorted_sets[key])
            self._sorted_sets[key] = [
                (m, s) for m, s in self._sorted_sets[key] if m != member
            ]
            if len(self._sorted_sets[key]) < original_len:
                count += 1
        return count
    
    # Set operations
    async def sadd(self, key: str, *values) -> int:
        """Add members to set"""
        if key not in self._sets:
            self._sets[key] = set()
        original_size = len(self._sets[key])
        self._sets[key].update(values)
        return len(self._sets[key]) - original_size
    
    async def srem(self, key: str, *values) -> int:
        """Remove members from set"""
        if key not in self._sets:
            return 0
        count = 0
        for value in values:
            if value in self._sets[key]:
                self._sets[key].remove(value)
                count += 1
        return count
    
    async def smembers(self, key: str) -> set:
        """Get all members of set"""
        return self._sets.get(key, set()).copy()
    
    # List operations
    async def lpush(self, key: str, *values) -> int:
        """Push values to front of list"""
        if key not in self._lists:
            self._lists[key] = []
        for value in reversed(values):  # Insert in reverse to maintain order
            self._lists[key].insert(0, value)
        return len(self._lists[key])
    
    async def lrange(self, key: str, start: int, stop: int) -> List[str]:
        """Get range of elements from list"""
        if key not in self._lists:
            return []
        items = self._lists[key]
        if stop == -1:
            stop = len(items)
        else:
            stop = min(stop + 1, len(items))
        start = max(0, start)
        return items[start:stop]
    
    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        """Trim list to specified range"""
        if key not in self._lists:
            return True
        items = self._lists[key]
        if stop == -1:
            stop = len(items) - 1
        start = max(0, start)
        stop = min(stop, len(items) - 1)
        self._lists[key] = items[start:stop + 1]
        return True
    
    # Key management
    async def delete(self, *keys) -> int:
        """Delete keys"""
        count = 0
        for key in keys:
            if (key in self._hashes or key in self._sorted_sets or 
                key in self._sets or key in self._lists):
                self._hashes.pop(key, None)
                self._sorted_sets.pop(key, None)  
                self._sets.pop(key, None)
                self._lists.pop(key, None)
                self._keys_ttl.pop(key, None)
                count += 1
        return count
    
    # Simple key-value operations (for rate limiting and other uses)
    async def get(self, key: str) -> Optional[Any]:
        """Get value by key (Redis GET)"""
        import json
        
        # Store simple values in _hashes with a special field
        if key in self._hashes and "__value__" in self._hashes[key]:
            value = self._hashes[key]["__value__"]
            # Try to parse as JSON if it looks like JSON
            if value and value.startswith('{'):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    pass
            return value
        return None
    
    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """Set key-value pair (Redis SET)"""
        import json
        
        # Handle different value types
        if isinstance(value, dict):
            # Store as JSON string for dict values
            value_str = json.dumps(value, default=str)
        elif isinstance(value, str):
            value_str = value
        else:
            value_str = str(value)
        
        if key not in self._hashes:
            self._hashes[key] = {}
        self._hashes[key]["__value__"] = value_str
        
        # Handle expiry if provided
        if ex:
            await self.expire(key, ex)
        return True
    
    async def incr(self, key: str) -> int:
        """Increment value by 1 (Redis INCR)"""
        current = await self.get(key)
        new_value = int(current) + 1 if current else 1
        await self.set(key, str(new_value))
        return new_value
    
    async def incrby(self, key: str, amount: int) -> int:
        """Increment value by amount (Redis INCRBY)"""
        current = await self.get(key)
        new_value = int(current) + amount if current else amount
        await self.set(key, str(new_value))
        return new_value
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set key expiration (simplified - no actual expiry logic)"""
        # For testing, we just track that expire was called
        # Real implementation would need background cleanup
        import time
        self._keys_ttl[key] = time.time() + seconds
        return True
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys matching pattern (Redis KEYS)"""
        import fnmatch
        all_keys = set()
        
        # Collect keys from all storage types
        all_keys.update(self._hashes.keys())
        all_keys.update(self._sorted_sets.keys())
        all_keys.update(self._sets.keys())
        all_keys.update(self._lists.keys())
        
        # Filter by pattern
        if pattern == "*":
            return list(all_keys)
        else:
            return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]
    
    async def scan(self, cursor: int = 0, match: str = None, count: int = 10):
        """Scan keys (simplified implementation)"""
        all_keys = set()
        all_keys.update(self._hashes.keys())
        all_keys.update(self._sorted_sets.keys())
        all_keys.update(self._sets.keys())
        all_keys.update(self._lists.keys())
        
        keys_list = list(all_keys)
        if match:
            # Simple glob matching
            import fnmatch
            keys_list = [k for k in keys_list if fnmatch.fnmatch(k, match)]
        
        # Simple pagination
        start = cursor
        end = min(cursor + count, len(keys_list))
        next_cursor = end if end < len(keys_list) else 0
        
        return next_cursor, [key.encode() for key in keys_list[start:end]]


# ============================================================================
# Backward Compatibility Wrappers
# ============================================================================

class PersistenceBackendWrapper(UnifiedPersistenceAdapter):
    """
    Wrapper that makes UnifiedPersistenceAdapter compatible with PersistenceBackend interface.
    Only exposes task/workflow operations.
    """
    
    def __init__(self, unified_adapter: UnifiedPersistenceAdapter):
        self._adapter = unified_adapter
    
    # Delegate all task/workflow operations
    async def initialize(self) -> None:
        return await self._adapter.initialize()
    
    async def shutdown(self) -> None:
        return await self._adapter.shutdown()
    
    async def save_task(self, task: Task) -> None:
        return await self._adapter.save_task(task)
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        return await self._adapter.get_task(task_id)
    
    async def delete_task(self, task_id: str) -> bool:
        return await self._adapter.delete_task(task_id)
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        return await self._adapter.get_tasks_by_status(status)
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        return await self._adapter.get_tasks_by_workflow(workflow_id)
    
    async def save_task_result(self, task_result: TaskResult) -> None:
        return await self._adapter.save_task_result(task_result)
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        return await self._adapter.get_task_result(task_id)
    
    async def save_workflow(self, workflow: Workflow) -> None:
        return await self._adapter.save_workflow(workflow)
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return await self._adapter.get_workflow(workflow_id)
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        return await self._adapter.delete_workflow(workflow_id)
    
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        return await self._adapter.save_workflow_execution(execution)
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        return await self._adapter.get_workflow_execution(execution_id)
    
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        return await self._adapter.save_queue_state(queue_name, state)
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        return await self._adapter.get_queue_state(queue_name)
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        return await self._adapter.delete_queue_state(queue_name)
    
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        return await self._adapter.save_tasks_batch(tasks)
    
    async def get_all_queued_tasks(self) -> List[Task]:
        return await self._adapter.get_all_queued_tasks()
    
    async def get_task_count_by_status(self) -> Dict[str, int]:
        return await self._adapter.get_task_count_by_status()
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        return await self._adapter.cleanup_old_data(cutoff_date)
    
    async def list_workflows(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return await self._adapter.list_workflows(status=status, limit=limit, offset=offset)
    
    async def list_tasks(self, workflow_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return await self._adapter.list_tasks(workflow_id=workflow_id, status=status, limit=limit, offset=offset)


class HubPersistenceAdapterWrapper(UnifiedPersistenceAdapter):
    """
    Wrapper that makes UnifiedPersistenceAdapter compatible with HubPersistenceAdapter interface.
    Only exposes hub resource operations.
    """
    
    def __init__(self, unified_adapter: UnifiedPersistenceAdapter):
        self._adapter = unified_adapter
    
    # Delegate all hub resource operations
    async def initialize(self) -> None:
        return await self._adapter.initialize()
    
    async def shutdown(self) -> None:
        return await self._adapter.shutdown()
    
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        return await self._adapter.save_instance(hub_id, instance)
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return await self._adapter.load_instance(instance_id)
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        return await self._adapter.list_instances(hub_id)
    
    async def delete_instance(self, instance_id: str) -> None:
        return await self._adapter.delete_instance(instance_id)
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        return await self._adapter.save_metrics(instance_id, metrics)
    
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        return await self._adapter.get_metrics_history(instance_id, start_time, end_time)
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        return await self._adapter.acquire_lock(resource_id, owner_id, timeout)
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        return await self._adapter.release_lock(resource_id, owner_id)
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        return await self._adapter.extend_lock(resource_id, owner_id, timeout)
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        return await self._adapter.get_lock_owner(resource_id)


class MockRedisClient:
    """
    Mock Redis client for in-memory adapter to support atomic operations.
    Provides Redis-like operations that work with the in-memory adapter's lock.
    """
    
    def __init__(self, adapter: 'UnifiedInMemoryAdapter'):
        self.adapter = adapter
        import asyncio
        self._script_lock = asyncio.Lock()
    
    async def eval(self, script: str, numkeys: int, *args):
        """
        Mock implementation of Redis EVAL for atomic operations.
        Used by AtomicPersistenceOperations for task claiming, status transitions, etc.
        """
        async with self._script_lock:
            # Parse the script to determine operation type
            if "task:status" in script and "HGET" in script:
                # Task status transition or claim operation
                task_key = args[0] if args else None
                if not task_key:
                    return 0
                
                task_id = task_key.decode() if isinstance(task_key, bytes) else task_key
                task_id = task_id.replace("task:status:", "")
                
                # Check if this is a claim operation
                if "executing" in script.lower() or "claim" in script.lower():
                    # Try to claim the task
                    task = self.adapter.tasks.get(task_id)
                    if task and task.status in ["pending", "ready"]:
                        task.status = TaskStatus.EXECUTING
                        self.adapter.tasks[task_id] = task
                        return 1  # Success
                    return 0  # Failed to claim
                
                # Regular status transition
                if len(args) >= 3:
                    new_status = args[2].decode() if isinstance(args[2], bytes) else args[2]
                    task = self.adapter.tasks.get(task_id)
                    if task:
                        task.status = new_status
                        self.adapter.tasks[task_id] = task
                        return 1
                return 0
                
            elif "workflow:lock" in script:
                # Workflow locking operation
                lock_key = args[0] if args else None
                if not lock_key:
                    return 0
                    
                lock_id = args[1] if len(args) > 1 else None
                timeout = int(args[2]) if len(args) > 2 else 30
                
                # Acquire lock
                from datetime import datetime, timedelta
                lock_key_str = lock_key.decode() if isinstance(lock_key, bytes) else lock_key
                
                if lock_key_str in self.adapter.locks:
                    _, expiry = self.adapter.locks[lock_key_str]
                    if expiry > datetime.utcnow():
                        return 0  # Lock held
                
                self.adapter.locks[lock_key_str] = (lock_id, datetime.utcnow() + timedelta(seconds=timeout))
                return 1  # Lock acquired
                
            # Default: operation succeeded
            return 1
    
    async def hget(self, key: str, field: str):
        """Mock HGET operation."""
        if key in self.adapter._hashes:
            return self.adapter._hashes[key].get(field)
        return None
    
    async def hset(self, key: str, field: str, value: str):
        """Mock HSET operation."""
        if key not in self.adapter._hashes:
            self.adapter._hashes[key] = {}
        self.adapter._hashes[key][field] = value
        return 1
    
    async def expire(self, key: str, seconds: int):
        """Mock EXPIRE operation."""
        from datetime import datetime, timedelta
        self.adapter._keys_ttl[key] = datetime.utcnow() + timedelta(seconds=seconds)
        return 1