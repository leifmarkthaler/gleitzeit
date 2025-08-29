"""
Base persistence interface for Gleitzeit V4

Defines the abstract interface that all persistence backends must implement
for storing and retrieving tasks, workflows, and queue state.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from collections import deque


class PersistenceBackend(ABC):
    """Abstract base class for persistence backends"""
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the persistence backend"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the persistence backend"""
        pass
    
    # Task operations
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
    
    # Task results
    @abstractmethod
    async def save_task_result(self, task_result: TaskResult) -> None:
        """Save a task result"""
        pass
    
    @abstractmethod
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result by task ID"""
        pass
    
    # Workflow operations
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
    
    # Queue state operations
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
    
    # Bulk operations for efficiency
    @abstractmethod
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        """Save multiple tasks in a single operation"""
        pass
    
    @abstractmethod
    async def get_all_queued_tasks(self) -> List[Task]:
        """Get all tasks that should be in queues on startup"""
        pass
    
    # Statistics and monitoring
    @abstractmethod
    async def get_task_count_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        pass
    
    @abstractmethod
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        """Remove old completed tasks and results before cutoff date"""
        pass


class InMemoryBackend(PersistenceBackend):
    """Simple in-memory backend for testing and development"""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.task_results: Dict[str, TaskResult] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.workflow_executions: Dict[str, WorkflowExecution] = {}
        self.queue_states: Dict[str, Dict[str, Any]] = {}
        # Event storage - using deques with maxlen for automatic trimming
        self.events_global = deque(maxlen=10000)  # Global event stream
        self.events_by_workflow: Dict[str, deque] = {}  # Per-workflow streams
        self.events_by_task: Dict[str, deque] = {}  # Per-task streams
    
    async def initialize(self) -> None:
        """No initialization needed for in-memory"""
        pass
    
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
    
    # Task results
    async def save_task_result(self, task_result: TaskResult) -> None:
        self.task_results[task_result.task_id] = task_result
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        return self.task_results.get(task_id)
    
    # Workflow operations
    async def save_workflow(self, workflow: Workflow) -> None:
        self.workflows[workflow.id] = workflow
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self.workflows.get(workflow_id)
    
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        self.workflow_executions[execution.execution_id] = execution
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        return self.workflow_executions.get(execution_id)
    
    # Queue state operations
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        self.queue_states[queue_name] = state
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        return self.queue_states.get(queue_name)
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        if queue_name in self.queue_states:
            del self.queue_states[queue_name]
            return True
        return False
    
    # Bulk operations
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        for task in tasks:
            self.tasks[task.id] = task
    
    async def get_all_queued_tasks(self) -> List[Task]:
        return [
            task for task in self.tasks.values() 
            if task.status in ["queued", "retry_pending"]
        ]
    
    # Statistics
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
    
    # Event persistence methods
    async def save_event(self, event_data: Dict[str, Any]) -> None:
        """
        Save an event to in-memory storage.
        
        Args:
            event_data: Event dictionary with event_id, event_type, timestamp, etc.
        """
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