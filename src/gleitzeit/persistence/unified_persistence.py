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
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution

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
        """Save or update a task"""
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
    """In-memory implementation for testing and development"""
    
    def __init__(self):
        # Task/Workflow storage
        self.tasks: Dict[str, Task] = {}
        self.task_results: Dict[str, TaskResult] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.workflow_executions: Dict[str, WorkflowExecution] = {}
        self.queue_states: Dict[str, Dict[str, Any]] = {}
        
        # Hub Resource storage
        self.instances: Dict[str, Dict[str, Any]] = {}
        self.hub_instances: Dict[str, Set[str]] = {}  # hub_id -> set of instance_ids
        self.metrics: Dict[str, List[Dict[str, Any]]] = {}
        self.locks: Dict[str, tuple] = {}  # resource_id -> (owner_id, expiry)
        
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
        self.instances.clear()
        self.hub_instances.clear()
        self.metrics.clear()
        self.locks.clear()
        self._initialized = False
        logger.info("Unified in-memory adapter shut down")
    
    # Task operations
    async def save_task(self, task: Task) -> None:
        self.tasks[task.id] = task
    
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