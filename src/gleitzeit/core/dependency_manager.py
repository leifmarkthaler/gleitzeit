"""
Unified Dependency Management for Gleitzeit

Merges functionality from DependencyResolver and DependencyTracker into a 
single, cohesive service for dependency analysis and resolution tracking.
"""

import asyncio
import logging
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gleitzeit.core.models import Task, Workflow, TaskStatus
from gleitzeit.persistence.base import PersistenceBackend
from .errors import TaskValidationError

logger = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Raised when circular dependencies are detected"""
    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle + [cycle[0]])}")


@dataclass
class DependencyNode:
    """Node in the dependency graph"""
    task_id: str
    task: Task
    dependencies: Set[str]  # Tasks this depends on
    dependents: Set[str]    # Tasks that depend on this
    depth: int = 0          # Depth in dependency tree (0 = no dependencies)
    status: TaskStatus = TaskStatus.PENDING
    

@dataclass
class ResolutionAttempt:
    """Track resolution attempts for a workflow"""
    workflow_id: str
    attempt_count: int = 0
    last_attempt: Optional[datetime] = None
    submitted_tasks: Set[str] = field(default_factory=set)
    failed_attempts: List[str] = field(default_factory=list)


class UnifiedDependencyManager:
    """
    Unified dependency management service combining analysis and tracking.
    
    Consolidates functionality from:
    - DependencyResolver: Graph analysis, circular detection, topological sorting
    - DependencyTracker: Submission tracking, idempotency, attempt management
    
    Features:
    - Single source of truth for dependencies
    - Unified caching strategy
    - Consistent validation across the system
    - Simplified API for dependency operations
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        max_attempts: int = 3,
        attempt_timeout: int = 300
    ):
        """
        Initialize the unified dependency manager.
        
        Args:
            persistence: Backend for persistence operations
            max_attempts: Maximum resolution attempts per workflow
            attempt_timeout: Timeout in seconds before allowing retry
        """
        self.persistence = persistence
        self.max_attempts = max_attempts
        self.attempt_timeout = attempt_timeout
        
        # Unified cache for workflows and dependency graphs
        self._workflow_cache: Dict[str, Workflow] = {}
        self._dependency_graphs: Dict[str, Dict[str, DependencyNode]] = {}
        
        # Tracking for idempotency
        self._submitted_tasks: Set[str] = set()
        self._resolution_attempts: Dict[str, ResolutionAttempt] = {}
        self._pending_resolutions: Set[str] = set()
        self._resolution_locks: Dict[str, asyncio.Lock] = {}
        
        logger.info("Initialized UnifiedDependencyManager")
        
    async def validate_workflow(self, workflow: Workflow) -> bool:
        """
        Validate a workflow for dependency issues.
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            True if valid, raises exception if not
            
        Raises:
            CircularDependencyError: If circular dependencies detected
        """
        # Build dependency graph
        graph = self._build_dependency_graph(workflow)
        
        # Check for circular dependencies
        self._detect_circular_dependencies(graph)
        
        # Validate all task references exist
        for node in graph.values():
            for dep_id in node.dependencies:
                if dep_id not in graph:
                    raise TaskValidationError(node.task_id, [f"depends on non-existent task {dep_id}"])
                    
        # Cache the validated workflow and graph
        self._workflow_cache[workflow.id] = workflow
        self._dependency_graphs[workflow.id] = graph
        
        logger.info(f"Workflow {workflow.id} validated successfully")
        return True

    async def check_dependencies(self, task: Task) -> bool:
        """
        Check if all task dependencies are satisfied.

        Args:
            task: Task to check dependencies for

        Returns:
            True if all dependencies are satisfied, False otherwise
        """
        if not task.dependencies:
            return True

        # Check each dependency
        for dep_task_id in task.dependencies:
            dep_task = await self.persistence.get_task(dep_task_id)
            if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                return False

        return True

    async def resolve_dependencies(self, task: Task, workflow_id: str) -> List[str]:
        """
        Resolve dependencies for a task.
        
        Args:
            task: Task to resolve dependencies for
            workflow_id: ID of the workflow containing the task
            
        Returns:
            List of task IDs that must complete before this task
        """
        # Get cached graph or load from persistence
        graph = await self._get_or_load_graph(workflow_id)
        
        if not graph or task.id not in graph:
            return []
            
        node = graph[task.id]
        return list(node.dependencies)
        
    async def get_ready_tasks(self, workflow_id: str, completed_tasks: Set[str] = None) -> List[Task]:
        """
        Get tasks that are ready to execute (all dependencies met).

        Args:
            workflow_id: Workflow to check
            completed_tasks: Set of completed task IDs

        Returns:
            List of tasks ready for execution
        """
        completed_tasks = completed_tasks or set()
        graph = await self._get_or_load_graph(workflow_id)

        if not graph:
            return []

        ready_tasks = []

        for node in graph.values():
            # Skip if already completed or in progress
            if node.task_id in completed_tasks:
                continue

            # Check if all dependencies are completed
            if node.dependencies.issubset(completed_tasks):
                ready_tasks.append(node.task)

        return ready_tasks

    async def get_dependent_tasks(self, completed_task_id: str) -> List[str]:
        """
        Get tasks that depend on the completed task and check if they're now ready to run.

        Args:
            completed_task_id: ID of the task that just completed

        Returns:
            List of task IDs that are now ready to execute
        """
        # Find the workflow containing this task
        workflow_id = None
        for wf_id, graph in self._dependency_graphs.items():
            if completed_task_id in graph:
                workflow_id = wf_id
                break

        if not workflow_id:
            # Task not in any cached graph, try to find it from persistence
            task = await self.persistence.get_task(completed_task_id)
            if task and task.workflow_id:
                workflow_id = task.workflow_id
                graph = await self._get_or_load_graph(workflow_id)
            else:
                logger.debug(f"Task {completed_task_id} not found in any workflow")
                return []
        else:
            graph = self._dependency_graphs[workflow_id]

        if not graph or completed_task_id not in graph:
            return []

        completed_node = graph[completed_task_id]
        newly_ready = []

        # Check each dependent task
        for dependent_id in completed_node.dependents:
            if dependent_id not in graph:
                continue

            dependent_node = graph[dependent_id]

            # Check if all dependencies of this dependent are now satisfied
            all_deps_complete = True
            for dep_id in dependent_node.dependencies:
                if dep_id == completed_task_id:
                    # The just-completed task is satisfied
                    continue

                # Check if other dependencies are completed
                dep_task = await self.persistence.get_task(dep_id)
                if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                    all_deps_complete = False
                    break

            if all_deps_complete:
                # This dependent task is now ready to run
                newly_ready.append(dependent_id)
                logger.debug(f"Task {dependent_id} is now ready after {completed_task_id} completed")

        return newly_ready

    async def get_dependent_tasks(self, task_id: str) -> List[str]:
        """
        Get all tasks that depend on the given task.

        Args:
            task_id: The completed task ID

        Returns:
            List of task IDs that depend on this task
        """
        # First get the workflow ID for this task
        task = await self.persistence.get_task(task_id)
        if not task or not task.workflow_id:
            return []

        workflow = await self.persistence.get_workflow(task.workflow_id)
        if not workflow:
            return []

        dependent_tasks = []
        for other_task in workflow.tasks:
            if other_task.id != task_id and task_id in other_task.dependencies:
                dependent_tasks.append(other_task.id)

        logger.debug(f"Found {len(dependent_tasks)} tasks depending on {task_id}")
        return dependent_tasks

    async def track_submission(self, task_id: str, workflow_id: str) -> bool:
        """
        Track task submission for idempotency.
        
        Args:
            task_id: Task being submitted
            workflow_id: Workflow containing the task
            
        Returns:
            True if submission should proceed, False if duplicate
        """
        # Check if already submitted
        if task_id in self._submitted_tasks:
            logger.debug(f"Task {task_id} already submitted, skipping")
            return False
            
        # Track submission
        self._submitted_tasks.add(task_id)
        
        # Update resolution attempt
        if workflow_id not in self._resolution_attempts:
            self._resolution_attempts[workflow_id] = ResolutionAttempt(workflow_id)
            
        attempt = self._resolution_attempts[workflow_id]
        attempt.submitted_tasks.add(task_id)
        attempt.last_attempt = datetime.utcnow()
        
        logger.debug(f"Tracked submission of task {task_id} for workflow {workflow_id}")
        return True
        
    async def start_resolution(self, workflow_id: str) -> bool:
        """
        Start dependency resolution for a workflow.
        
        Args:
            workflow_id: Workflow to resolve
            
        Returns:
            True if resolution should proceed, False if already in progress
        """
        # Get or create lock for this workflow
        if workflow_id not in self._resolution_locks:
            self._resolution_locks[workflow_id] = asyncio.Lock()
            
        # Try to acquire lock without blocking
        if self._resolution_locks[workflow_id].locked():
            logger.debug(f"Resolution already in progress for workflow {workflow_id}")
            return False
            
        # Check if already pending
        if workflow_id in self._pending_resolutions:
            logger.debug(f"Resolution already pending for workflow {workflow_id}")
            return False
            
        # Check attempt limits
        if workflow_id in self._resolution_attempts:
            attempt = self._resolution_attempts[workflow_id]
            if attempt.attempt_count >= self.max_attempts:
                # Check timeout
                if attempt.last_attempt:
                    elapsed = (datetime.utcnow() - attempt.last_attempt).total_seconds()
                    if elapsed < self.attempt_timeout:
                        logger.warning(
                            f"Max attempts reached for workflow {workflow_id}, "
                            f"retry after {self.attempt_timeout - elapsed:.0f}s"
                        )
                        return False
                        
        # Mark as pending
        self._pending_resolutions.add(workflow_id)
        
        # Update attempt count
        if workflow_id not in self._resolution_attempts:
            self._resolution_attempts[workflow_id] = ResolutionAttempt(workflow_id)
        self._resolution_attempts[workflow_id].attempt_count += 1
        
        return True
        
    async def complete_resolution(self, workflow_id: str, success: bool = True):
        """
        Mark resolution as complete.
        
        Args:
            workflow_id: Workflow that was resolved
            success: Whether resolution succeeded
        """
        # Remove from pending
        self._pending_resolutions.discard(workflow_id)
        
        # Update attempt record
        if workflow_id in self._resolution_attempts:
            attempt = self._resolution_attempts[workflow_id]
            attempt.last_attempt = datetime.utcnow()
            if not success:
                attempt.failed_attempts.append(datetime.utcnow().isoformat())
                
        logger.debug(f"Completed resolution for workflow {workflow_id} (success={success})")
        
    def get_topological_order(self, workflow_id: str) -> List[str]:
        """
        Get topological ordering of tasks for execution.
        
        Args:
            workflow_id: Workflow to order
            
        Returns:
            List of task IDs in execution order
        """
        graph = self._dependency_graphs.get(workflow_id)
        if not graph:
            return []
            
        # Kahn's algorithm for topological sort
        in_degree = {task_id: len(node.dependencies) for task_id, node in graph.items()}
        queue = deque([task_id for task_id, degree in in_degree.items() if degree == 0])
        result = []
        
        while queue:
            task_id = queue.popleft()
            result.append(task_id)
            
            node = graph[task_id]
            for dependent_id in node.dependents:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)
                    
        if len(result) != len(graph):
            # Should not happen if validation passed
            raise CircularDependencyError(["<cycle detected in topological sort>"])
            
        return result
        
    def get_dependency_depth(self, workflow_id: str) -> Dict[str, int]:
        """
        Get the dependency depth for all tasks.
        
        Args:
            workflow_id: Workflow to analyze
            
        Returns:
            Dictionary mapping task IDs to their depth
        """
        graph = self._dependency_graphs.get(workflow_id)
        if not graph:
            return {}
            
        return {task_id: node.depth for task_id, node in graph.items()}
        
    def clear_workflow_cache(self, workflow_id: str):
        """
        Clear cached data for a workflow.
        
        Args:
            workflow_id: Workflow to clear
        """
        self._workflow_cache.pop(workflow_id, None)
        self._dependency_graphs.pop(workflow_id, None)
        
        # Clear submitted tasks for this workflow
        if workflow_id in self._resolution_attempts:
            attempt = self._resolution_attempts[workflow_id]
            self._submitted_tasks -= attempt.submitted_tasks
            del self._resolution_attempts[workflow_id]
            
        self._pending_resolutions.discard(workflow_id)
        self._resolution_locks.pop(workflow_id, None)
        
        logger.debug(f"Cleared cache for workflow {workflow_id}")
        
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get dependency manager statistics.
        
        Returns:
            Dictionary of statistics
        """
        return {
            "cached_workflows": len(self._workflow_cache),
            "dependency_graphs": len(self._dependency_graphs),
            "submitted_tasks": len(self._submitted_tasks),
            "pending_resolutions": len(self._pending_resolutions),
            "resolution_attempts": {
                wf_id: {
                    "attempts": attempt.attempt_count,
                    "submitted_tasks": len(attempt.submitted_tasks),
                    "failed_attempts": len(attempt.failed_attempts)
                }
                for wf_id, attempt in self._resolution_attempts.items()
            }
        }
        
    # Private helper methods
    
    def _build_dependency_graph(self, workflow: Workflow) -> Dict[str, DependencyNode]:
        """Build dependency graph from workflow"""
        graph = {}
        
        # Create nodes
        for task in workflow.tasks:
            graph[task.id] = DependencyNode(
                task_id=task.id,
                task=task,
                dependencies=set(task.dependencies) if task.dependencies else set(),
                dependents=set()
            )
            
        # Build reverse dependencies (dependents)
        for task in workflow.tasks:
            if task.dependencies:
                for dep_id in task.dependencies:
                    if dep_id in graph:
                        graph[dep_id].dependents.add(task.id)
                        
        # Calculate depths
        self._calculate_depths(graph)
        
        return graph
        
    def _calculate_depths(self, graph: Dict[str, DependencyNode]):
        """Calculate dependency depths for all nodes"""
        # Start with nodes that have no dependencies
        queue = deque([node for node in graph.values() if not node.dependencies])
        
        while queue:
            node = queue.popleft()
            
            # Update dependents' depths
            for dependent_id in node.dependents:
                dependent = graph[dependent_id]
                dependent.depth = max(dependent.depth, node.depth + 1)
                
                # Check if all dependencies have been processed
                deps_processed = all(
                    graph[dep_id].depth >= 0 
                    for dep_id in dependent.dependencies
                )
                
                if deps_processed and dependent not in queue:
                    queue.append(dependent)
                    
    def _detect_circular_dependencies(self, graph: Dict[str, DependencyNode]):
        """Detect circular dependencies using DFS"""
        visited = set()
        rec_stack = set()
        
        def visit(node_id: str, path: List[str]) -> bool:
            if node_id in rec_stack:
                # Found cycle
                cycle_start = path.index(node_id)
                raise CircularDependencyError(path[cycle_start:])
                
            if node_id in visited:
                return False
                
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            
            node = graph[node_id]
            for dep_id in node.dependencies:
                if dep_id in graph:
                    visit(dep_id, path.copy())
                    
            rec_stack.remove(node_id)
            return False
            
        # Check all nodes
        for node_id in graph:
            if node_id not in visited:
                visit(node_id, [])
                
    async def _get_or_load_graph(self, workflow_id: str) -> Optional[Dict[str, DependencyNode]]:
        """Get dependency graph from cache or load from persistence"""
        if workflow_id in self._dependency_graphs:
            return self._dependency_graphs[workflow_id]
            
        # Try to load workflow from persistence
        workflow = await self.persistence.get_workflow(workflow_id)
        if workflow:
            await self.validate_workflow(workflow)
            return self._dependency_graphs.get(workflow_id)
            
        return None