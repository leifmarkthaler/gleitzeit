"""
Stateless Dependency Manager for Gleitzeit.

This manager provides dependency resolution without any in-memory state,
using persistence for all storage needs with atomic operations to prevent
race conditions. Designed for horizontal scaling.
"""

import logging
from typing import Dict, List, Set, Optional, Union, Any
from collections import defaultdict, deque
from dataclasses import dataclass
from uuid import uuid4

from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.persistence.atomic_operations import AtomicPersistenceOperations

logger = logging.getLogger(__name__)


@dataclass
class DependencyNode:
    """Temporary node for dependency graph calculations (not stored)."""
    task_id: str
    task: Task
    dependencies: Set[str]
    dependents: Set[str]
    depth: int = 0


class CircularDependencyError(Exception):
    """Raised when circular dependencies are detected."""
    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle + [cycle[0]])}")


class StatelessDependencyManager:
    """
    Fully stateless dependency manager using persistence for all state.
    
    Key Features:
    - No in-memory workflow or graph storage
    - All operations fetch fresh data from persistence
    - Atomic operations to prevent race conditions
    - Distributed locking for critical sections
    - Supports horizontal scaling (multiple instances)
    - Thread-safe and concurrent-operation safe
    
    This manager can be instantiated anywhere, anytime, and will always
    work with the current state in persistence.
    """
    
    def __init__(self, persistence: PersistenceBackend, redis_client=None):
        """
        Initialize with persistence backend and optional Redis for atomic ops.
        
        Args:
            persistence: Backend for all state storage
            redis_client: Optional Redis client for atomic operations
        """
        self.persistence = persistence
        
        # Initialize atomic operations if Redis available
        if redis_client:
            self.atomic_ops = AtomicPersistenceOperations(redis_client, persistence)
            logger.info("Initialized StatelessDependencyManager with atomic operations")
        else:
            self.atomic_ops = None
            logger.warning("StatelessDependencyManager initialized without atomic operations - race conditions possible!")
        
        self.worker_id = f"worker-{uuid4().hex[:8]}"  # Unique worker identifier
    
    # Core validation methods
    
    async def validate_workflow(self, workflow: Workflow) -> List[str]:
        """
        Validate workflow dependencies and return any errors.
        
        This method builds the dependency graph on-demand without storing it.
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        try:
            # Build graph temporarily (not stored)
            graph = self._build_dependency_graph(workflow)
            
            # Check for circular dependencies
            cycles = self._detect_cycles(graph)
            if cycles:
                for cycle in cycles:
                    errors.append(f"Circular dependency: {' -> '.join(cycle + [cycle[0]])}")
            
            # Check for missing task references
            task_ids = set(graph.keys())
            for node in graph.values():
                for dep_id in node.dependencies:
                    if dep_id not in task_ids:
                        errors.append(
                            f"Task '{node.task_id}' depends on non-existent task '{dep_id}'"
                        )
            
            # Don't store workflow here - that's the caller's responsibility
            if not errors:
                logger.info(f"Workflow {workflow.id} validated successfully")
            
        except Exception as e:
            logger.error(f"Error validating workflow: {e}")
            errors.append(f"Validation error: {str(e)}")
        
        return errors
    
    async def validate_workflow_dependencies(self, workflow: Workflow) -> List[str]:
        """
        Alias for validate_workflow to match DependencyResolver interface.
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            List of error messages (empty if valid)
        """
        return await self.validate_workflow(workflow)
    
    # Task readiness and claiming methods (atomic)
    
    async def claim_next_ready_task(
        self,
        workflow_id: str,
        worker_id: Optional[str] = None
    ) -> Optional[Task]:
        """
        Atomically claim the next ready task for execution.
        
        This prevents race conditions where multiple workers might
        try to execute the same task.
        
        Args:
            workflow_id: Workflow to get task from
            worker_id: Optional worker ID (uses instance ID if not provided)
            
        Returns:
            The claimed task or None if no tasks available
        """
        if not self.atomic_ops:
            logger.error("Cannot claim tasks without atomic operations!")
            return None
        
        worker_id = worker_id or self.worker_id
        
        # Get ready tasks
        ready_task_ids = await self.get_ready_tasks(workflow_id, return_objects=False)
        
        # Try to claim one atomically
        for task_id in ready_task_ids:
            if await self.atomic_ops.claim_task(task_id, worker_id):
                # Successfully claimed, get the task object
                task_data = await self.persistence.get_task(task_id)
                if task_data:
                    if isinstance(task_data, dict):
                        return Task(**task_data)
                    return task_data
        
        return None  # No tasks available or all already claimed
    
    async def get_ready_tasks(
        self, 
        workflow_id: str,
        return_objects: bool = True
    ) -> Union[List[Task], List[str]]:
        """
        Get tasks that are ready to execute (all dependencies met).
        
        Fetches fresh data from persistence to determine readiness.
        
        Args:
            workflow_id: Workflow to check
            return_objects: If True, return Task objects; if False, return IDs
            
        Returns:
            List of ready tasks (objects or IDs based on return_objects)
        """
        try:
            # Fetch workflow from persistence
            workflow_data = await self.persistence.get_workflow(workflow_id)
            if not workflow_data:
                logger.warning(f"Workflow {workflow_id} not found")
                return []
            
            # Convert to Workflow object if needed
            if isinstance(workflow_data, dict):
                workflow = Workflow(**workflow_data)
            else:
                workflow = workflow_data
            
            # Fetch task statuses from persistence
            task_statuses = await self._get_task_statuses(workflow_id)
            
            # Build dependency graph temporarily
            graph = self._build_dependency_graph(workflow)
            
            # Find ready tasks
            ready = []
            for task_id, node in graph.items():
                # Skip if already processed
                status = task_statuses.get(task_id)
                if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, 
                             TaskStatus.EXECUTING, TaskStatus.CANCELLED]:
                    continue
                
                # Check if all dependencies are complete
                deps_complete = all(
                    task_statuses.get(dep_id) == TaskStatus.COMPLETED
                    for dep_id in node.dependencies
                )
                
                if deps_complete:
                    if return_objects:
                        ready.append(node.task)
                    else:
                        ready.append(task_id)
            
            logger.debug(f"Found {len(ready)} ready tasks for workflow {workflow_id}")
            return ready
            
        except Exception as e:
            logger.error(f"Error getting ready tasks: {e}")
            return []
    
    async def get_execution_order(self, workflow_id: str) -> List[List[str]]:
        """
        Get execution order grouped by dependency levels.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            List of task ID groups that can run in parallel
        """
        try:
            # Fetch workflow from persistence
            workflow_data = await self.persistence.get_workflow(workflow_id)
            if not workflow_data:
                return []
            
            # Convert to Workflow object
            if isinstance(workflow_data, dict):
                workflow = Workflow(**workflow_data)
            else:
                workflow = workflow_data
            
            # Build graph and calculate depths
            graph = self._build_dependency_graph(workflow)
            self._calculate_depths(graph)
            
            # Group by depth
            depth_groups = defaultdict(list)
            for task_id, node in graph.items():
                depth_groups[node.depth].append(task_id)
            
            # Return sorted by depth
            result = []
            for depth in sorted(depth_groups.keys()):
                result.append(sorted(depth_groups[depth]))
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting execution order: {e}")
            return []
    
    async def check_dependencies_met(
        self,
        task_id: str,
        workflow_id: str
    ) -> bool:
        """
        Check if all dependencies for a task are met.
        
        Args:
            task_id: Task to check
            workflow_id: Workflow containing the task
            
        Returns:
            True if all dependencies are satisfied
        """
        try:
            # Get workflow to find dependencies
            workflow_data = await self.persistence.get_workflow(workflow_id)
            if not workflow_data:
                return False
            
            # Find the task
            if isinstance(workflow_data, dict):
                workflow = Workflow(**workflow_data)
            else:
                workflow = workflow_data
            
            task = next((t for t in workflow.tasks if t.id == task_id), None)
            if not task:
                return False
            
            # No dependencies means ready
            if not task.dependencies:
                return True
            
            # Check each dependency status
            task_statuses = await self._get_task_statuses(workflow_id)
            return all(
                task_statuses.get(dep_id) == TaskStatus.COMPLETED
                for dep_id in task.dependencies
            )
            
        except Exception as e:
            logger.error(f"Error checking dependencies: {e}")
            return False
    
    # Workflow state tracking methods (atomic)
    
    async def mark_task_ready(self, workflow_id: str, task_id: str) -> bool:
        """Mark a task as ready for execution."""
        if self.atomic_ops:
            # Use atomic transition
            return await self.atomic_ops.atomic_task_status_transition(
                task_id, TaskStatus.FAILED, TaskStatus.PENDING
            )
        else:
            # Get task, update status, and save
            task = await self.persistence.get_task(task_id)
            if task:
                task.status = TaskStatus.PENDING
                await self.persistence.save_task(task)
            return True
    
    async def mark_task_running(
        self, 
        workflow_id: str, 
        task_id: str,
        worker_id: Optional[str] = None
    ) -> bool:
        """
        Mark a task as currently running.
        
        Args:
            workflow_id: Workflow ID
            task_id: Task ID
            worker_id: Optional worker ID for ownership validation
            
        Returns:
            True if successfully marked, False otherwise
        """
        if self.atomic_ops:
            return await self.atomic_ops.atomic_task_status_transition(
                task_id, 
                TaskStatus.PENDING, 
                TaskStatus.EXECUTING,
                worker_id or self.worker_id
            )
        else:
            # Get task, update status, and save
            task = await self.persistence.get_task(task_id)
            if task:
                task.status = TaskStatus.EXECUTING
                await self.persistence.save_task(task)
            return True
    
    async def mark_task_completed(
        self, 
        workflow_id: str, 
        task_id: str,
        worker_id: Optional[str] = None
    ) -> bool:
        """
        Mark a task as completed with atomic workflow completion check.
        
        Args:
            workflow_id: Workflow ID
            task_id: Task ID
            worker_id: Optional worker ID for ownership validation
            
        Returns:
            True if successfully marked, False otherwise
        """
        if self.atomic_ops:
            # Atomic task completion
            success = await self.atomic_ops.atomic_task_status_transition(
                task_id,
                TaskStatus.EXECUTING,
                TaskStatus.COMPLETED,
                worker_id or self.worker_id
            )
            
            if success:
                # Atomic workflow completion check
                await self.atomic_ops.check_and_complete_workflow(workflow_id)
            
            return success
        else:
            # Get task, update status, and save
            task = await self.persistence.get_task(task_id)
            if task:
                task.status = TaskStatus.COMPLETED
                await self.persistence.save_task(task)
            await self._check_workflow_completion(workflow_id)
            return True
    
    async def mark_task_failed(
        self,
        workflow_id: str,
        task_id: str,
        worker_id: Optional[str] = None
    ) -> bool:
        """
        Mark a task as failed with atomic operations.
        
        Args:
            workflow_id: Workflow ID
            task_id: Task ID  
            worker_id: Optional worker ID for ownership validation
            
        Returns:
            True if successfully marked, False otherwise
        """
        if self.atomic_ops:
            # Use distributed lock for workflow status update
            lock_id = uuid4().hex
            lock_acquired = await self.atomic_ops.acquire_lock(
                f"workflow:{workflow_id}",
                lock_id,
                ttl=30
            )
            
            if not lock_acquired:
                logger.warning(f"Could not acquire lock for workflow {workflow_id}")
                return False
            
            try:
                # Atomic task failure
                success = await self.atomic_ops.atomic_task_status_transition(
                    task_id,
                    TaskStatus.EXECUTING,
                    TaskStatus.FAILED,
                    worker_id or self.worker_id
                )
                
                if success:
                    # Update workflow status within lock
                    workflow = await self.persistence.get_workflow(workflow_id)
                    if workflow:
                        workflow.status = WorkflowStatus.FAILED
                        await self.persistence.save_workflow(workflow)
                
                return success
                
            finally:
                await self.atomic_ops.release_lock(f"workflow:{workflow_id}", lock_id)
        else:
            # Update task status
            task = await self.persistence.get_task(task_id)
            if task:
                task.status = TaskStatus.FAILED
                await self.persistence.save_task(task)
            
            # Update workflow status
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.FAILED
                await self.persistence.save_workflow(workflow)
            return True
    
    # Private helper methods
    
    def _build_dependency_graph(self, workflow: Workflow) -> Dict[str, DependencyNode]:
        """
        Build dependency graph for a workflow (temporary, not stored).
        
        Args:
            workflow: Workflow to analyze
            
        Returns:
            Dictionary of task IDs to dependency nodes
        """
        graph = {}
        
        # Create nodes for all tasks
        for task in workflow.tasks:
            graph[task.id] = DependencyNode(
                task_id=task.id,
                task=task,
                dependencies=set(task.dependencies) if task.dependencies else set(),
                dependents=set()
            )
        
        # Build reverse dependencies
        for task in workflow.tasks:
            if task.dependencies:
                for dep_id in task.dependencies:
                    if dep_id in graph:
                        graph[dep_id].dependents.add(task.id)
        
        return graph
    
    def _detect_cycles(self, graph: Dict[str, DependencyNode]) -> List[List[str]]:
        """
        Detect circular dependencies using DFS.
        
        Args:
            graph: Dependency graph
            
        Returns:
            List of cycles found (empty if none)
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        colors = {task_id: WHITE for task_id in graph}
        cycles = []
        
        def dfs(task_id: str, path: List[str]) -> None:
            colors[task_id] = GRAY
            path.append(task_id)
            
            for dep_id in graph[task_id].dependencies:
                if dep_id not in graph:
                    continue
                    
                if colors[dep_id] == GRAY:
                    # Found cycle
                    cycle_start = path.index(dep_id)
                    cycles.append(path[cycle_start:])
                elif colors[dep_id] == WHITE:
                    dfs(dep_id, path.copy())
            
            colors[task_id] = BLACK
        
        for task_id in graph:
            if colors[task_id] == WHITE:
                dfs(task_id, [])
        
        return cycles
    
    def _calculate_depths(self, graph: Dict[str, DependencyNode]) -> None:
        """
        Calculate dependency depths for topological sorting.
        
        Modifies the graph nodes in-place to set depth values.
        
        Args:
            graph: Dependency graph to process
        """
        # Find tasks with no dependencies
        queue = deque([
            task_id for task_id, node in graph.items()
            if not node.dependencies
        ])
        
        # Set initial depths
        for task_id in queue:
            graph[task_id].depth = 0
        
        # BFS to calculate depths
        processed = set(queue)
        while queue:
            current_id = queue.popleft()
            current_depth = graph[current_id].depth
            
            # Update dependent tasks
            for dependent_id in graph[current_id].dependents:
                # Calculate new depth
                max_dep_depth = max(
                    graph[dep_id].depth
                    for dep_id in graph[dependent_id].dependencies
                    if dep_id in processed
                )
                graph[dependent_id].depth = max_dep_depth + 1
                
                # Check if all dependencies processed
                if all(dep_id in processed for dep_id in graph[dependent_id].dependencies):
                    if dependent_id not in processed:
                        queue.append(dependent_id)
                        processed.add(dependent_id)
    
    async def _get_task_statuses(self, workflow_id: str) -> Dict[str, TaskStatus]:
        """
        Get all task statuses for a workflow from persistence.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Dictionary mapping task IDs to their current status
        """
        try:
            # Get all tasks for workflow
            tasks = await self.persistence.list_tasks(workflow_id=workflow_id)
            
            statuses = {}
            for task in tasks:
                if isinstance(task, dict):
                    statuses[task['id']] = TaskStatus(task.get('status', 'pending'))
                else:
                    statuses[task.id] = task.status
            
            return statuses
            
        except Exception as e:
            logger.error(f"Error getting task statuses: {e}")
            return {}
    
    async def _check_workflow_completion(self, workflow_id: str) -> None:
        """
        Check if workflow is complete and update status if needed.
        
        Args:
            workflow_id: Workflow to check
        """
        try:
            # Get all task statuses
            statuses = await self._get_task_statuses(workflow_id)
            
            # Check if all tasks are complete
            all_complete = all(
                status == TaskStatus.COMPLETED
                for status in statuses.values()
            )
            
            if all_complete:
                workflow = await self.persistence.get_workflow(workflow_id)
                if workflow:
                    workflow.status = WorkflowStatus.COMPLETED
                    await self.persistence.save_workflow(workflow)
                logger.info(f"Workflow {workflow_id} marked as completed")
                
        except Exception as e:
            logger.error(f"Error checking workflow completion: {e}")
    
    # Compatibility methods (no-ops for stateless operation)
    
    def add_workflow(self, workflow: Workflow) -> None:
        """No-op for compatibility - validation happens on-demand."""
        logger.debug(f"add_workflow called for {workflow.id} (no-op in stateless)")
    
    def remove_workflow(self, workflow_id: str) -> None:
        """No-op for compatibility - no in-memory state to clean."""
        logger.debug(f"remove_workflow called for {workflow_id} (no-op in stateless)")