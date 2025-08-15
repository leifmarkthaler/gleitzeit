"""
Dependency resolution for Gleitzeit V4

Handles task dependency analysis, circular dependency detection,
and workflow ordering with topological sorting.
"""

import logging
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict, deque
from dataclasses import dataclass

from gleitzeit.core.models import Task, Workflow, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class DependencyNode:
    """Node in the dependency graph"""
    task_id: str
    task: Task
    dependencies: Set[str]  # Tasks this depends on
    dependents: Set[str]    # Tasks that depend on this
    depth: int = 0          # Depth in dependency tree (0 = no dependencies)


class CircularDependencyError(Exception):
    """Raised when circular dependencies are detected"""
    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle + [cycle[0]])}")


class DependencyResolver:
    """
    Analyzes and resolves task dependencies within workflows
    
    Features:
    - Circular dependency detection
    - Topological sorting for execution order
    - Dependency depth calculation
    - Parameter substitution analysis
    """
    
    def __init__(self):
        self.workflows: Dict[str, Workflow] = {}
        self.dependency_graphs: Dict[str, Dict[str, DependencyNode]] = {}
        
        logger.info("Initialized DependencyResolver")
    
    def add_workflow(self, workflow: Workflow) -> None:
        """
        Add a workflow and build its dependency graph
        
        Args:
            workflow: Workflow to analyze
            
        Raises:
            CircularDependencyError: If circular dependencies are found
        """
        self.workflows[workflow.id] = workflow
        
        # Build dependency graph
        graph = self._build_dependency_graph(workflow)
        
        # Detect circular dependencies
        cycles = self._detect_cycles(graph)
        if cycles:
            raise CircularDependencyError(cycles[0])
        
        # Calculate depths
        self._calculate_depths(graph)
        
        self.dependency_graphs[workflow.id] = graph
        
        logger.info(f"Added workflow {workflow.id} with {len(graph)} tasks")
    
    def remove_workflow(self, workflow_id: str) -> None:
        """Remove a workflow from analysis"""
        self.workflows.pop(workflow_id, None)
        self.dependency_graphs.pop(workflow_id, None)
        
        logger.info(f"Removed workflow {workflow_id}")
    
    def _build_dependency_graph(self, workflow: Workflow) -> Dict[str, DependencyNode]:
        """Build dependency graph for a workflow"""
        graph = {}
        
        # Create nodes for all tasks
        for task in workflow.tasks:
            graph[task.id] = DependencyNode(
                task_id=task.id,
                task=task,
                dependencies=set(task.dependencies),
                dependents=set()
            )
        
        # Build reverse dependencies (dependents)
        for task in workflow.tasks:
            for dep_id in task.dependencies:
                if dep_id in graph:
                    graph[dep_id].dependents.add(task.id)
                else:
                    logger.warning(f"Task {task.id} depends on non-existent task {dep_id}")
        
        return graph
    
    def _detect_cycles(self, graph: Dict[str, DependencyNode]) -> List[List[str]]:
        """
        Detect circular dependencies using DFS
        
        Returns:
            List of cycles found (each cycle is a list of task IDs)
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        colors = {task_id: WHITE for task_id in graph}
        cycles = []
        
        def dfs(task_id: str, path: List[str]) -> None:
            if colors[task_id] == GRAY:
                # Found a cycle
                cycle_start = path.index(task_id)
                cycle = path[cycle_start:] + [task_id]
                cycles.append(cycle)
                return
            
            if colors[task_id] == BLACK:
                return
            
            colors[task_id] = GRAY
            path.append(task_id)
            
            for dep_id in graph[task_id].dependencies:
                if dep_id in graph:  # Only check existing tasks
                    dfs(dep_id, path)
            
            path.pop()
            colors[task_id] = BLACK
        
        for task_id in graph:
            if colors[task_id] == WHITE:
                dfs(task_id, [])
        
        return cycles
    
    def _calculate_depths(self, graph: Dict[str, DependencyNode]) -> None:
        """Calculate dependency depth for each task (topological levels)"""
        # Find tasks with no dependencies (depth 0)
        queue = deque([
            task_id for task_id, node in graph.items() 
            if not node.dependencies
        ])
        
        depths = {task_id: 0 for task_id in queue}
        
        # BFS to calculate depths
        while queue:
            current_id = queue.popleft()
            current_depth = depths[current_id]
            
            # Update depth for dependent tasks
            for dependent_id in graph[current_id].dependents:
                if dependent_id in graph:
                    new_depth = max(depths.get(dependent_id, 0), current_depth + 1)
                    
                    if dependent_id not in depths or depths[dependent_id] < new_depth:
                        depths[dependent_id] = new_depth
                        
                        # Check if all dependencies are processed
                        deps_processed = all(
                            dep_id in depths 
                            for dep_id in graph[dependent_id].dependencies
                            if dep_id in graph
                        )
                        
                        if deps_processed and dependent_id not in queue:
                            queue.append(dependent_id)
        
        # Set calculated depths
        for task_id, depth in depths.items():
            graph[task_id].depth = depth
    
    def get_execution_order(self, workflow_id: str) -> List[List[str]]:
        """
        Get execution order for workflow tasks grouped by dependency level
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            List of task ID lists, where each inner list contains tasks
            that can execute in parallel (same dependency depth)
        """
        if workflow_id not in self.dependency_graphs:
            return []
        
        graph = self.dependency_graphs[workflow_id]
        
        # Group tasks by depth
        depth_groups = defaultdict(list)
        for task_id, node in graph.items():
            depth_groups[node.depth].append(task_id)
        
        # Return sorted by depth
        result = []
        for depth in sorted(depth_groups.keys()):
            result.append(sorted(depth_groups[depth]))
        
        return result
    
    def get_ready_tasks(
        self, 
        workflow_id: str, 
        completed_tasks: Set[str],
        failed_tasks: Optional[Set[str]] = None
    ) -> List[str]:
        """
        Get tasks that are ready to execute (all dependencies satisfied)
        
        Args:
            workflow_id: Workflow ID
            completed_tasks: Set of completed task IDs
            failed_tasks: Set of failed task IDs (optional)
            
        Returns:
            List of task IDs ready for execution
        """
        if workflow_id not in self.dependency_graphs:
            return []
        
        failed_tasks = failed_tasks or set()
        graph = self.dependency_graphs[workflow_id]
        ready = []
        
        for task_id, node in graph.items():
            # Skip if already completed or failed
            if task_id in completed_tasks or task_id in failed_tasks:
                continue
            
            # Check if task is currently running
            if node.task.status in [TaskStatus.EXECUTING, TaskStatus.ROUTED]:
                continue
            
            # Check if all dependencies are satisfied
            dependencies_satisfied = all(
                dep_id in completed_tasks
                for dep_id in node.dependencies
                if dep_id in graph  # Only check existing dependencies
            )
            
            if dependencies_satisfied:
                ready.append(task_id)
        
        return ready
    
    def get_blocked_tasks(
        self, 
        workflow_id: str, 
        completed_tasks: Set[str],
        failed_tasks: Set[str]
    ) -> List[Tuple[str, List[str]]]:
        """
        Get tasks that are blocked by failed dependencies
        
        Args:
            workflow_id: Workflow ID
            completed_tasks: Set of completed task IDs
            failed_tasks: Set of failed task IDs
            
        Returns:
            List of tuples (task_id, list_of_failed_dependencies)
        """
        if workflow_id not in self.dependency_graphs:
            return []
        
        graph = self.dependency_graphs[workflow_id]
        blocked = []
        
        for task_id, node in graph.items():
            if task_id in completed_tasks or task_id in failed_tasks:
                continue
            
            # Check for failed dependencies
            failed_deps = [
                dep_id for dep_id in node.dependencies
                if dep_id in failed_tasks
            ]
            
            if failed_deps:
                blocked.append((task_id, failed_deps))
        
        return blocked
    
    def validate_workflow_dependencies(self, workflow: Workflow) -> List[str]:
        """
        Validate workflow dependencies and return error messages
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        task_ids = {task.id for task in workflow.tasks}
        
        # Check for non-existent dependencies
        for task in workflow.tasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    errors.append(f"Task '{task.id}' depends on non-existent task '{dep_id}'")
                elif dep_id == task.id:
                    errors.append(f"Task '{task.id}' cannot depend on itself")
        
        # Check for circular dependencies
        try:
            temp_graph = self._build_dependency_graph(workflow)
            cycles = self._detect_cycles(temp_graph)
            
            for cycle in cycles:
                errors.append(f"Circular dependency: {' -> '.join(cycle + [cycle[0]])}")
                
        except Exception as e:
            errors.append(f"Dependency analysis error: {str(e)}")
        
        return errors
    
    def analyze_parameter_dependencies(self, workflow: Workflow) -> Dict[str, List[str]]:
        """
        Analyze parameter substitution patterns to infer dependencies
        
        Args:
            workflow: Workflow to analyze
            
        Returns:
            Dictionary mapping task IDs to lists of task IDs they reference in parameters
        """
        import re
        
        param_dependencies = {}
        pattern = r'\$\{([^}]+)\}'  # Match ${...} patterns
        
        for task in workflow.tasks:
            referenced_tasks = set()
            
            # Check all parameters for references
            def find_references(obj):
                if isinstance(obj, str):
                    matches = re.findall(pattern, obj)
                    for match in matches:
                        # Parse reference like "task-id.result" or "task-id"
                        parts = match.split('.')
                        if parts[0] and parts[0] != task.id:  # Don't self-reference
                            referenced_tasks.add(parts[0])
                elif isinstance(obj, dict):
                    for value in obj.values():
                        find_references(value)
                elif isinstance(obj, list):
                    for item in obj:
                        find_references(item)
            
            find_references(task.params)
            
            if referenced_tasks:
                param_dependencies[task.id] = list(referenced_tasks)
        
        return param_dependencies
    
    def suggest_missing_dependencies(self, workflow: Workflow) -> Dict[str, List[str]]:
        """
        Suggest missing dependencies based on parameter references
        
        Args:
            workflow: Workflow to analyze
            
        Returns:
            Dictionary mapping task IDs to suggested additional dependencies
        """
        param_deps = self.analyze_parameter_dependencies(workflow)
        suggestions = {}
        
        for task in workflow.tasks:
            declared_deps = set(task.dependencies)
            param_refs = set(param_deps.get(task.id, []))
            
            # Find parameter references not in declared dependencies
            missing_deps = param_refs - declared_deps
            
            # Filter to only include tasks that exist in the workflow
            task_ids = {t.id for t in workflow.tasks}
            missing_deps = missing_deps.intersection(task_ids)
            
            if missing_deps:
                suggestions[task.id] = list(missing_deps)
        
        return suggestions
    
    def get_dependency_stats(self, workflow_id: str) -> Dict[str, Any]:
        """Get dependency statistics for a workflow"""
        if workflow_id not in self.dependency_graphs:
            return {}
        
        graph = self.dependency_graphs[workflow_id]
        
        # Calculate statistics
        max_depth = max((node.depth for node in graph.values()), default=0)
        avg_dependencies = sum(len(node.dependencies) for node in graph.values()) / len(graph)
        
        # Find root tasks (no dependencies) and leaf tasks (no dependents)
        root_tasks = [task_id for task_id, node in graph.items() if not node.dependencies]
        leaf_tasks = [task_id for task_id, node in graph.items() if not node.dependents]
        
        # Complexity metrics
        total_edges = sum(len(node.dependencies) for node in graph.values())
        complexity_ratio = total_edges / len(graph) if graph else 0
        
        return {
            "workflow_id": workflow_id,
            "total_tasks": len(graph),
            "max_dependency_depth": max_depth,
            "average_dependencies_per_task": round(avg_dependencies, 2),
            "total_dependency_edges": total_edges,
            "complexity_ratio": round(complexity_ratio, 2),
            "root_tasks": root_tasks,
            "leaf_tasks": leaf_tasks,
            "parallelizable_levels": max_depth + 1
        }