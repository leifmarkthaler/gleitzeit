"""
Dependency Adapter for bridging dependency management systems.

This adapter makes UnifiedDependencyManager compatible with the DependencyResolver
interface, allowing us to use a single dependency system throughout Gleitzeit.
"""

import logging
from typing import List, Set, Optional, Dict, Any
import asyncio

from gleitzeit.core.models import Task, Workflow, TaskStatus
from gleitzeit.core.dependency_manager import UnifiedDependencyManager, CircularDependencyError

logger = logging.getLogger(__name__)


class DependencyAdapter:
    """
    Adapter to make UnifiedDependencyManager compatible with DependencyResolver interface.
    
    This allows WorkflowManager to use UnifiedDependencyManager while maintaining
    backward compatibility with the DependencyResolver API.
    """
    
    def __init__(self, unified_manager: UnifiedDependencyManager):
        """
        Initialize the adapter with a UnifiedDependencyManager.
        
        Args:
            unified_manager: The unified dependency manager to adapt
        """
        self.manager = unified_manager
        logger.info("Initialized DependencyAdapter")
    
    async def validate_workflow_dependencies(self, workflow: Workflow) -> List[str]:
        """
        Validate workflow dependencies and return error messages.
        
        Adapts UnifiedDependencyManager.validate_workflow() to return an error list
        instead of throwing exceptions, matching DependencyResolver interface.
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            List of error messages (empty if valid)
        """
        try:
            # UnifiedDependencyManager.validate_workflow throws exceptions
            await self.manager.validate_workflow(workflow)
            return []  # No errors
            
        except CircularDependencyError as e:
            return [str(e)]
            
        except ValueError as e:
            return [str(e)]
            
        except Exception as e:
            logger.error(f"Unexpected error during validation: {e}")
            return [f"Validation error: {e}"]
    
    def validate_workflow_dependencies_sync(self, workflow: Workflow) -> List[str]:
        """
        Synchronous version of validate_workflow_dependencies.
        
        Some code paths may expect synchronous validation.
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            List of error messages (empty if valid)
        """
        try:
            # Create event loop if needed
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run async validation
            return loop.run_until_complete(
                self.validate_workflow_dependencies(workflow)
            )
            
        except Exception as e:
            logger.error(f"Error in sync validation: {e}")
            return [f"Validation error: {e}"]
    
    def add_workflow(self, workflow: Workflow) -> None:
        """
        Add a workflow for dependency tracking.
        
        This is a no-op for compatibility as UnifiedDependencyManager
        validates and caches on-demand rather than requiring pre-registration.
        
        Args:
            workflow: Workflow to add
        """
        # No-op - UnifiedDependencyManager handles this internally
        logger.debug(f"add_workflow called for {workflow.id} (no-op in adapter)")
    
    def remove_workflow(self, workflow_id: str) -> None:
        """
        Remove a workflow from tracking.
        
        This is a no-op for compatibility as UnifiedDependencyManager
        doesn't require explicit removal.
        
        Args:
            workflow_id: ID of workflow to remove
        """
        # No-op - UnifiedDependencyManager handles this internally
        logger.debug(f"remove_workflow called for {workflow_id} (no-op in adapter)")
    
    async def get_ready_tasks(
        self, 
        workflow_id: str,
        completed_tasks: Optional[Set[str]] = None,
        failed_tasks: Optional[Set[str]] = None
    ) -> List[str]:
        """
        Get task IDs that are ready to execute.
        
        Adapts UnifiedDependencyManager.get_ready_tasks() to return task IDs
        instead of Task objects, matching DependencyResolver interface.
        
        Args:
            workflow_id: Workflow ID
            completed_tasks: Set of completed task IDs
            failed_tasks: Set of failed task IDs
            
        Returns:
            List of task IDs ready for execution
        """
        try:
            # UnifiedDependencyManager returns Task objects
            ready_tasks = await self.manager.get_ready_tasks(
                workflow_id, 
                completed_tasks or set()
            )
            
            # Extract just the IDs
            return [task.id for task in ready_tasks]
            
        except Exception as e:
            logger.error(f"Error getting ready tasks: {e}")
            return []
    
    async def get_execution_order(self, workflow_id: str) -> List[List[str]]:
        """
        Get execution order for workflow tasks grouped by dependency level.
        
        This provides compatibility with DependencyResolver.get_execution_order().
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            List of task ID lists, where each inner list contains tasks
            that can execute in parallel (same dependency depth)
        """
        try:
            # Load workflow to build execution order
            workflow = self.manager._workflow_cache.get(workflow_id)
            if not workflow and self.manager.persistence:
                # Try loading from persistence
                workflow = await self.manager.persistence.get_workflow(workflow_id)
            
            if not workflow:
                return []
            
            # Build dependency graph
            graph = self.manager._build_dependency_graph(workflow)
            
            # Calculate depths (similar to DependencyResolver)
            from collections import defaultdict, deque
            
            # Find tasks with no dependencies (depth 0)
            depth_map = {}
            queue = deque()
            
            for task_id, node in graph.items():
                if not node.dependencies:
                    depth_map[task_id] = 0
                    queue.append(task_id)
            
            # BFS to calculate depths
            while queue:
                current_id = queue.popleft()
                current_depth = depth_map[current_id]
                
                for dependent_id in graph[current_id].dependents:
                    if dependent_id not in depth_map:
                        # Check if all dependencies have been processed
                        deps_ready = all(
                            dep_id in depth_map 
                            for dep_id in graph[dependent_id].dependencies
                        )
                        if deps_ready:
                            max_dep_depth = max(
                                depth_map[dep_id] 
                                for dep_id in graph[dependent_id].dependencies
                            ) if graph[dependent_id].dependencies else -1
                            depth_map[dependent_id] = max_dep_depth + 1
                            queue.append(dependent_id)
            
            # Group by depth
            depth_groups = defaultdict(list)
            for task_id, depth in depth_map.items():
                depth_groups[depth].append(task_id)
            
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
        task: Task,
        workflow_id: str,
        completed_tasks: Set[str]
    ) -> bool:
        """
        Check if all dependencies for a task are met.
        
        Args:
            task: Task to check
            workflow_id: Workflow ID
            completed_tasks: Set of completed task IDs
            
        Returns:
            True if all dependencies are satisfied
        """
        dependencies = await self.manager.resolve_dependencies(task, workflow_id)
        return all(dep_id in completed_tasks for dep_id in dependencies)