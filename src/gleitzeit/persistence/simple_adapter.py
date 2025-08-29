"""
Simple In-Memory Adapter with Optional SQL Backup

Lightning-fast in-memory operations with optional SQL persistence for single-node deployments.
Perfect for development, testing, and simple production use cases.
"""

import asyncio
import logging
import json
import threading
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.core.models import Task, TaskStatus, Workflow, WorkflowStatus, TaskResult
from gleitzeit.core.errors import PersistenceError

logger = logging.getLogger(__name__)


@dataclass
class InMemoryData:
    """In-memory data storage"""
    tasks: Dict[str, Task] = field(default_factory=dict)
    workflows: Dict[str, Workflow] = field(default_factory=dict)
    task_results: Dict[str, TaskResult] = field(default_factory=dict)
    
    # Indexes for efficient queries
    tasks_by_status: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    tasks_by_workflow: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    workflows_by_status: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    
    # Lock for thread safety
    _lock: threading.RLock = field(default_factory=threading.RLock)
    
    def export(self) -> Dict[str, Any]:
        """Export all data for backup"""
        with self._lock:
            return {
                'tasks': {
                    task_id: {
                        'id': task.id,
                        'workflow_id': task.workflow_id,
                        'name': task.name,
                        'method': task.method,
                        'status': task.status.value,
                        'priority': task.priority,
                        'params': task.params,
                        'dependencies': task.dependencies,
                        'created_at': task.created_at.isoformat(),
                        'updated_at': task.updated_at.isoformat() if task.updated_at else None
                    } for task_id, task in self.tasks.items()
                },
                'workflows': {
                    workflow_id: {
                        'id': workflow.id,
                        'name': workflow.name,
                        'status': workflow.status.value,
                        'created_at': workflow.created_at.isoformat(),
                        'updated_at': workflow.updated_at.isoformat() if workflow.updated_at else None
                    } for workflow_id, workflow in self.workflows.items()
                },
                'task_results': {
                    task_id: {
                        'task_id': result.task_id,
                        'success': result.success,
                        'result': result.result,
                        'error': result.error,
                        'created_at': result.created_at.isoformat()
                    } for task_id, result in self.task_results.items()
                }
            }
    
    def import_data(self, data: Dict[str, Any]) -> None:
        """Import data from backup"""
        with self._lock:
            # Clear existing data
            self.tasks.clear()
            self.workflows.clear()
            self.task_results.clear()
            self.tasks_by_status.clear()
            self.tasks_by_workflow.clear()
            self.workflows_by_status.clear()
            
            # Import tasks
            for task_id, task_data in data.get('tasks', {}).items():
                task = Task(
                    id=task_data['id'],
                    workflow_id=task_data['workflow_id'],
                    name=task_data['name'],
                    method=task_data['method'],
                    status=TaskStatus(task_data['status']),
                    priority=task_data['priority'],
                    params=task_data.get('params'),
                    dependencies=task_data.get('dependencies', []),
                    created_at=datetime.fromisoformat(task_data['created_at']),
                    updated_at=datetime.fromisoformat(task_data['updated_at']) if task_data.get('updated_at') else None
                )
                self.tasks[task_id] = task
                self.tasks_by_status[task.status.value].add(task_id)
                self.tasks_by_workflow[task.workflow_id].add(task_id)
            
            # Import workflows
            for workflow_id, workflow_data in data.get('workflows', {}).items():
                workflow = Workflow(
                    id=workflow_data['id'],
                    name=workflow_data['name'],
                    status=WorkflowStatus(workflow_data['status']),
                    created_at=datetime.fromisoformat(workflow_data['created_at']),
                    updated_at=datetime.fromisoformat(workflow_data['updated_at']) if workflow_data.get('updated_at') else None,
                    tasks=[]  # Tasks are linked via indexes
                )
                self.workflows[workflow_id] = workflow
                self.workflows_by_status[workflow.status.value].add(workflow_id)
            
            # Import task results
            for task_id, result_data in data.get('task_results', {}).items():
                result = TaskResult(
                    task_id=result_data['task_id'],
                    success=result_data['success'],
                    result=result_data.get('result'),
                    error=result_data.get('error'),
                    created_at=datetime.fromisoformat(result_data['created_at'])
                )
                self.task_results[task_id] = result


class SimpleAdapter(UnifiedPersistenceAdapter):
    """
    Lightning-fast in-memory adapter with optional SQL backup.
    
    Features:
    - Pure in-memory operations for maximum speed
    - Thread-safe with RLock protection
    - Optional SQL backup for durability
    - Perfect for single-node deployments
    - Zero external dependencies (without SQL backup)
    - Excellent for development and testing
    
    Perfect for:
    - Development environments
    - Testing scenarios
    - Single-node production deployments
    - Quick prototyping
    - CI/CD pipelines
    """
    
    def __init__(
        self,
        sql_backup: bool = False,
        sql_url: str = None,
        backup_interval: int = 300,  # 5 minutes
        auto_backup_on_shutdown: bool = True,
        max_tasks: int = 100000,
        max_workflows: int = 10000
    ):
        """
        Initialize simple adapter.
        
        Args:
            sql_backup: Enable SQL backup for durability
            sql_url: SQL connection URL for backup
            backup_interval: Automatic backup interval (seconds)
            auto_backup_on_shutdown: Backup on shutdown
            max_tasks: Maximum tasks to keep in memory
            max_workflows: Maximum workflows to keep in memory
        """
        self.sql_backup_enabled = sql_backup
        self.sql_url = sql_url
        self.backup_interval = backup_interval
        self.auto_backup_on_shutdown = auto_backup_on_shutdown
        self.max_tasks = max_tasks
        self.max_workflows = max_workflows
        
        # In-memory storage
        self.data = InMemoryData()
        
        # SQL adapter for backup (lazy loaded)
        self._sql_adapter = None
        self._backup_task = None
        self._initialized = False
        
        logger.info(f"Simple adapter initialized: sql_backup={sql_backup}, "
                   f"max_tasks={max_tasks}, max_workflows={max_workflows}")
    
    async def initialize(self) -> None:
        """Initialize adapter and optionally restore from SQL backup"""
        if self._initialized:
            return
        
        if self.sql_backup_enabled and self.sql_url:
            await self._initialize_sql_backup()
            await self._restore_from_sql_backup()
        
        # Start periodic backup
        if self.sql_backup_enabled and self.backup_interval > 0:
            self._backup_task = asyncio.create_task(
                self._periodic_backup()
            )
        
        self._initialized = True
        logger.info("Simple adapter initialized")
    
    async def shutdown(self) -> None:
        """Shutdown adapter with optional final backup"""
        if self._backup_task:
            self._backup_task.cancel()
            try:
                await self._backup_task
            except asyncio.CancelledError:
                pass
        
        if self.auto_backup_on_shutdown and self._sql_adapter:
            await self._backup_to_sql()
        
        if self._sql_adapter:
            await self._sql_adapter.shutdown()
        
        self._initialized = False
        logger.info("Simple adapter shutdown")
    
    async def _initialize_sql_backup(self) -> None:
        """Initialize SQL adapter for backup"""
        try:
            from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
            
            self._sql_adapter = UnifiedSQLAlchemyAdapter(
                connection_string=self.sql_url
            )
            await self._sql_adapter.initialize()
            logger.info(f"SQL backup adapter initialized: {self.sql_url}")
            
        except Exception as e:
            logger.error(f"Failed to initialize SQL backup: {e}")
            self.sql_backup_enabled = False
    
    async def _restore_from_sql_backup(self) -> None:
        """Restore data from SQL backup if available"""
        if not self._sql_adapter:
            return
        
        try:
            # Load all data from SQL
            workflows = await self._sql_adapter.list_workflows()
            tasks = await self._sql_adapter.list_tasks()
            
            with self.data._lock:
                # Load workflows
                for workflow in workflows:
                    self.data.workflows[workflow.id] = workflow
                    self.data.workflows_by_status[workflow.status.value].add(workflow.id)
                
                # Load tasks
                for task in tasks:
                    self.data.tasks[task.id] = task
                    self.data.tasks_by_status[task.status.value].add(task.id)
                    self.data.tasks_by_workflow[task.workflow_id].add(task.id)
                    
                    # Load task result if exists
                    result = await self._sql_adapter.get_task_result(task.id)
                    if result:
                        self.data.task_results[task.id] = result
            
            logger.info(f"Restored {len(workflows)} workflows and {len(tasks)} tasks from SQL backup")
            
        except Exception as e:
            logger.warning(f"Failed to restore from SQL backup: {e}")
    
    async def _periodic_backup(self) -> None:
        """Periodic backup to SQL"""
        while True:
            try:
                await asyncio.sleep(self.backup_interval)
                if self._sql_adapter:
                    await self._backup_to_sql()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic backup failed: {e}")
    
    async def _backup_to_sql(self) -> None:
        """Backup current data to SQL"""
        if not self._sql_adapter:
            return
        
        try:
            with self.data._lock:
                # Backup workflows
                for workflow in self.data.workflows.values():
                    await self._sql_adapter.store_workflow(workflow)
                
                # Backup tasks
                for task in self.data.tasks.values():
                    await self._sql_adapter.store_task(task)
                
                # Backup results
                for result in self.data.task_results.values():
                    await self._sql_adapter.store_task_result(result)
            
            logger.debug("Data backed up to SQL")
            
        except Exception as e:
            logger.error(f"SQL backup failed: {e}")
    
    # Core CRUD operations - optimized for speed
    
    async def store_task(self, task: Task) -> None:
        """Store task in memory"""
        with self.data._lock:
            # Check memory limits
            if len(self.data.tasks) >= self.max_tasks:
                await self._cleanup_old_tasks()
            
            # Update indexes if task exists
            if task.id in self.data.tasks:
                old_task = self.data.tasks[task.id]
                old_status_value = old_task.status.value if hasattr(old_task.status, 'value') else old_task.status
                self.data.tasks_by_status[old_status_value].discard(task.id)
                self.data.tasks_by_workflow[old_task.workflow_id].discard(task.id)
            
            # Store task
            self.data.tasks[task.id] = task
            status_value = task.status.value if hasattr(task.status, 'value') else task.status
            self.data.tasks_by_status[status_value].add(task.id)
            self.data.tasks_by_workflow[task.workflow_id].add(task.id)
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task from memory (extremely fast)"""
        with self.data._lock:
            return self.data.tasks.get(task_id)
    
    async def list_tasks(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List tasks using efficient in-memory indexes - returns dict format for abstract method"""
        with self.data._lock:
            if workflow_id:
                task_ids = list(self.data.tasks_by_workflow.get(workflow_id, set()))
            elif status:
                task_ids = list(self.data.tasks_by_status.get(status, set()))
            else:
                task_ids = list(self.data.tasks.keys())
            
            # Apply pagination
            total = len(task_ids)
            task_ids = task_ids[offset:offset + limit]
            
            tasks = [self.data.tasks[task_id] for task_id in task_ids 
                    if task_id in self.data.tasks]
            
            return {
                'tasks': tasks,
                'total': total,
                'offset': offset,
                'limit': limit
            }
    
    async def update_task(self, task: Task) -> None:
        """Update task (same as store for in-memory)"""
        await self.store_task(task)
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete task from memory"""
        with self.data._lock:
            task = self.data.tasks.get(task_id)
            if not task:
                return False
            
            # Remove from all indexes
            del self.data.tasks[task_id]
            status_value = task.status.value if hasattr(task.status, 'value') else task.status
            self.data.tasks_by_status[status_value].discard(task_id)
            self.data.tasks_by_workflow[task.workflow_id].discard(task_id)
            
            # Remove result if exists
            self.data.task_results.pop(task_id, None)
            
            return True
    
    # Workflow operations
    
    async def store_workflow(self, workflow: Workflow) -> None:
        """Store workflow in memory"""
        with self.data._lock:
            # Check memory limits
            if len(self.data.workflows) >= self.max_workflows:
                await self._cleanup_old_workflows()
            
            # Update index if workflow exists
            if workflow.id in self.data.workflows:
                old_workflow = self.data.workflows[workflow.id]
                old_status_value = old_workflow.status.value if hasattr(old_workflow.status, 'value') else old_workflow.status
                self.data.workflows_by_status[old_status_value].discard(workflow.id)
            
            # Store workflow
            self.data.workflows[workflow.id] = workflow
            status_value = workflow.status.value if hasattr(workflow.status, 'value') else workflow.status
            self.data.workflows_by_status[status_value].add(workflow.id)
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow from memory"""
        with self.data._lock:
            return self.data.workflows.get(workflow_id)
    
    async def list_workflows(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List workflows using efficient in-memory indexes - returns dict format for abstract method"""
        with self.data._lock:
            if status:
                workflow_ids = list(self.data.workflows_by_status.get(status, set()))
            else:
                workflow_ids = list(self.data.workflows.keys())
            
            # Apply pagination
            total = len(workflow_ids)
            workflow_ids = workflow_ids[offset:offset + limit]
            
            workflows = [self.data.workflows[workflow_id] for workflow_id in workflow_ids
                        if workflow_id in self.data.workflows]
            
            return {
                'workflows': workflows,
                'total': total,
                'offset': offset,
                'limit': limit
            }
    
    async def update_workflow(self, workflow: Workflow) -> None:
        """Update workflow"""
        await self.store_workflow(workflow)
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow and all its tasks"""
        with self.data._lock:
            workflow = self.data.workflows.get(workflow_id)
            if not workflow:
                return False
            
            # Delete all tasks in this workflow
            task_ids = list(self.data.tasks_by_workflow.get(workflow_id, set()))
            for task_id in task_ids:
                await self.delete_task(task_id)
            
            # Remove workflow
            del self.data.workflows[workflow_id]
            status_value = workflow.status.value if hasattr(workflow.status, 'value') else workflow.status
            self.data.workflows_by_status[status_value].discard(workflow_id)
            self.data.tasks_by_workflow.pop(workflow_id, None)
            
            return True
    
    # Task result operations
    
    async def store_task_result(self, result: TaskResult) -> None:
        """Store task result in memory"""
        with self.data._lock:
            self.data.task_results[result.task_id] = result
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result from memory"""
        with self.data._lock:
            return self.data.task_results.get(task_id)
    
    # Additional required methods for interface compatibility
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Simple in-memory locking (not distributed)"""
        # For single-node deployment, we can use a simple dict-based lock
        if not hasattr(self, '_locks'):
            self._locks = {}
        
        if resource_id in self._locks:
            return False  # Already locked
        
        self._locks[resource_id] = {
            'owner': owner_id,
            'expires_at': datetime.utcnow().timestamp() + timeout
        }
        return True
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release simple lock"""
        if not hasattr(self, '_locks'):
            return
        
        lock_info = self._locks.get(resource_id)
        if lock_info and lock_info['owner'] == owner_id:
            del self._locks[resource_id]
    
    async def _cleanup_old_tasks(self) -> None:
        """Remove oldest completed/failed tasks when memory limit reached"""
        with self.data._lock:
            # Find completed and failed tasks, sorted by creation time
            old_tasks = []
            for task_id, task in self.data.tasks.items():
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    old_tasks.append((task.created_at, task_id))
            
            old_tasks.sort()  # Oldest first
            
            # Remove oldest 10% to make room
            cleanup_count = max(1, len(old_tasks) // 10)
            for _, task_id in old_tasks[:cleanup_count]:
                await self.delete_task(task_id)
            
            logger.info(f"Cleaned up {cleanup_count} old tasks")
    
    async def _cleanup_old_workflows(self) -> None:
        """Remove oldest completed workflows when memory limit reached"""
        with self.data._lock:
            # Find completed workflows, sorted by creation time
            old_workflows = []
            for workflow_id, workflow in self.data.workflows.items():
                if workflow.status == WorkflowStatus.COMPLETED:
                    old_workflows.append((workflow.created_at, workflow_id))
            
            old_workflows.sort()  # Oldest first
            
            # Remove oldest 10% to make room
            cleanup_count = max(1, len(old_workflows) // 10)
            for _, workflow_id in old_workflows[:cleanup_count]:
                await self.delete_workflow(workflow_id)
            
            logger.info(f"Cleaned up {cleanup_count} old workflows")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics"""
        with self.data._lock:
            return {
                'tasks_count': len(self.data.tasks),
                'workflows_count': len(self.data.workflows),
                'results_count': len(self.data.task_results),
                'max_tasks': self.max_tasks,
                'max_workflows': self.max_workflows,
                'task_utilization': len(self.data.tasks) / self.max_tasks,
                'workflow_utilization': len(self.data.workflows) / self.max_workflows,
                'sql_backup_enabled': self.sql_backup_enabled,
                'indexes': {
                    'tasks_by_status': {k: len(v) for k, v in self.data.tasks_by_status.items()},
                    'workflows_by_status': {k: len(v) for k, v in self.data.workflows_by_status.items()},
                    'tasks_by_workflow': len(self.data.tasks_by_workflow)
                }
            }
    
    async def export_data(self, format: str = 'json') -> str:
        """Export all data for backup or migration"""
        with self.data._lock:
            if format.lower() == 'json':
                return json.dumps(self.data.export(), indent=2, default=str)
            else:
                raise ValueError(f"Unsupported format: {format}")
    
    async def import_data(self, data_str: str, format: str = 'json') -> None:
        """Import data from backup or migration"""
        if format.lower() == 'json':
            data = json.loads(data_str)
            self.data.import_data(data)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        result = await self.list_tasks(workflow_id=workflow_id)
        return result['tasks']
    
    # Missing abstract methods implementation
    
    async def save_task(self, task: Task) -> None:
        """Save or update a task - validate workflow_id requirement"""
        if not task.workflow_id:
            error_msg = (
                f"Task {task.id} ({task.name}) cannot be saved without a workflow_id. "
                "Every task must belong to a workflow. "
                "Use ExecutionEngine.submit_task() which auto-creates workflows for single tasks."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        await self.store_task(task)
    
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save or update a workflow"""
        await self.store_workflow(workflow)
    
    async def save_task_result(self, result: TaskResult) -> None:
        """Save a task result"""
        await self.store_task_result(result)
    
    async def save_workflow_execution(self, execution) -> None:
        """Save workflow execution state"""
        # Simple implementation - store as task metadata
        if not hasattr(self.data, 'workflow_executions'):
            self.data.workflow_executions = {}
        with self.data._lock:
            self.data.workflow_executions[execution.id] = execution
    
    async def get_workflow_execution(self, execution_id: str):
        """Get workflow execution by ID"""
        if not hasattr(self.data, 'workflow_executions'):
            return None
        with self.data._lock:
            return self.data.workflow_executions.get(execution_id)
    
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        """Save queue state for recovery"""
        if not hasattr(self.data, 'queue_states'):
            self.data.queue_states = {}
        with self.data._lock:
            self.data.queue_states[queue_name] = state
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Get saved queue state"""
        if not hasattr(self.data, 'queue_states'):
            return None
        with self.data._lock:
            return self.data.queue_states.get(queue_name)
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        """Delete queue state"""
        if not hasattr(self.data, 'queue_states'):
            return False
        with self.data._lock:
            return self.data.queue_states.pop(queue_name, None) is not None
    
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        """Save multiple tasks in a single operation"""
        for task in tasks:
            await self.save_task(task)
    
    async def get_all_queued_tasks(self) -> List[Task]:
        """Get all tasks that should be in queues on startup"""
        return await self.get_tasks_by_status('queued') + await self.get_tasks_by_status('pending')
    
    async def get_task_count_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        with self.data._lock:
            return {status: len(task_ids) for status, task_ids in self.data.tasks_by_status.items()}
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get all tasks with a specific status"""
        result = await self.list_tasks(status=status)
        return result['tasks']
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        result = await self.list_tasks(workflow_id=workflow_id)
        return result['tasks']
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        """Remove old completed tasks and results before cutoff date"""
        with self.data._lock:
            cleaned = 0
            
            # Clean old tasks
            tasks_to_delete = []
            for task_id, task in self.data.tasks.items():
                if (task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] and 
                    task.created_at < cutoff_date):
                    tasks_to_delete.append(task_id)
            
            for task_id in tasks_to_delete:
                await self.delete_task(task_id)
                cleaned += 1
            
            # Clean old workflows
            workflows_to_delete = []
            for workflow_id, workflow in self.data.workflows.items():
                if (workflow.status == WorkflowStatus.COMPLETED and 
                    workflow.created_at < cutoff_date):
                    workflows_to_delete.append(workflow_id)
            
            for workflow_id in workflows_to_delete:
                await self.delete_workflow(workflow_id)
                cleaned += 1
            
            return cleaned
    
    # Hub Resource Operations
    
    async def save_instance(self, hub_id: str, instance) -> None:
        """Persist resource instance state"""
        if not hasattr(self.data, 'instances'):
            self.data.instances = {}
        with self.data._lock:
            key = f"{hub_id}:{instance.id}"
            self.data.instances[key] = {
                'hub_id': hub_id,
                'instance_id': instance.id,
                'data': instance.__dict__
            }
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        if not hasattr(self.data, 'instances'):
            return None
        with self.data._lock:
            for key, instance_data in self.data.instances.items():
                if instance_data['instance_id'] == instance_id:
                    return instance_data['data']
        return None
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        """List all instances for a hub"""
        if not hasattr(self.data, 'instances'):
            return []
        with self.data._lock:
            instances = []
            for key, instance_data in self.data.instances.items():
                if instance_data['hub_id'] == hub_id:
                    instances.append(instance_data['data'])
            return instances
    
    async def delete_instance(self, instance_id: str) -> None:
        """Remove instance from storage"""
        if not hasattr(self.data, 'instances'):
            return
        with self.data._lock:
            keys_to_delete = []
            for key, instance_data in self.data.instances.items():
                if instance_data['instance_id'] == instance_id:
                    keys_to_delete.append(key)
            for key in keys_to_delete:
                del self.data.instances[key]
    
    async def save_metrics(self, instance_id: str, metrics) -> None:
        """Store metrics snapshot"""
        if not hasattr(self.data, 'metrics'):
            self.data.metrics = defaultdict(list)
        with self.data._lock:
            self.data.metrics[instance_id].append({
                'timestamp': datetime.utcnow(),
                'data': metrics.__dict__
            })
    
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Retrieve historical metrics"""
        if not hasattr(self.data, 'metrics'):
            return []
        with self.data._lock:
            metrics_list = self.data.metrics.get(instance_id, [])
            filtered = []
            for metric in metrics_list:
                if start_time <= metric['timestamp'] <= end_time:
                    filtered.append(metric['data'])
            return filtered
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock timeout"""
        if not hasattr(self, '_locks'):
            return False
        
        lock_info = self._locks.get(resource_id)
        if lock_info and lock_info['owner'] == owner_id:
            lock_info['expires_at'] = datetime.utcnow().timestamp() + timeout
            return True
        return False
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get current lock owner"""
        if not hasattr(self, '_locks'):
            return None
        
        lock_info = self._locks.get(resource_id)
        if lock_info:
            # Check if lock is expired
            if lock_info['expires_at'] > datetime.utcnow().timestamp():
                return lock_info['owner']
            else:
                # Clean up expired lock
                del self._locks[resource_id]
        return None
    
