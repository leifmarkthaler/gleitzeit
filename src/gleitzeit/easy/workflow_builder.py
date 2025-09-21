"""
WorkflowBuilder - Fluent interface for building Gleitzeit workflows

Combines TaskBuilder instances into complete workflow definitions
and handles event handler registration.
"""

from typing import Dict, Any, List, Optional, Set
import json
from .task_builder import TaskBuilder, EventHandler
from .errors import (
    WorkflowBuilderError,
    DuplicateTaskError,
    CircularDependencyError,
    EmptyWorkflowError,
    InvalidDependencyError
)

class WorkflowBuilder:
    """
    Fluent interface for building Gleitzeit workflows from TaskBuilder instances.
    """
    
    def __init__(self, *tasks: TaskBuilder):
        """
        Initialize WorkflowBuilder with tasks.
        
        Args:
            *tasks: TaskBuilder instances to include in the workflow
        """
        self.tasks = list(tasks)
        self.workflow_metadata = {
            "name": "unnamed_workflow",
            "version": "1.0.0",
            "description": "Workflow created with fluent interface"
        }
        
    def name(self, workflow_name: str) -> 'WorkflowBuilder':
        """
        Set workflow name.
        
        Args:
            workflow_name: Name for the workflow
            
        Returns:
            Self for chaining
        """
        self.workflow_metadata["name"] = workflow_name
        return self
        
    def version(self, version_string: str) -> 'WorkflowBuilder':
        """
        Set workflow version.
        
        Args:
            version_string: Version string (e.g., "1.2.3")
            
        Returns:
            Self for chaining
        """
        self.workflow_metadata["version"] = version_string
        return self
        
    def description(self, desc: str) -> 'WorkflowBuilder':
        """
        Set workflow description.
        
        Args:
            desc: Description of the workflow
            
        Returns:
            Self for chaining
        """
        self.workflow_metadata["description"] = desc
        return self
        
    def add_task(self, task: TaskBuilder) -> 'WorkflowBuilder':
        """
        Add a task to the workflow.
        
        Args:
            task: TaskBuilder instance to add
            
        Returns:
            Self for chaining
        """
        self.tasks.append(task)
        return self
        
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert WorkflowBuilder to dictionary format compatible with Gleitzeit.
        
        Returns:
            Dictionary representation of the workflow
        """
        # Expand all tasks
        expanded_tasks = []
        all_event_handlers = []
        
        for task_builder in self.tasks:
            # Get the main task
            task_dict = task_builder.to_dict()
            expanded_tasks.append(task_dict)
            
            # Collect event handlers
            event_handlers = task_builder.get_event_handlers()
            all_event_handlers.extend(event_handlers)
            
        workflow_dict = {
            **self.workflow_metadata,
            "tasks": expanded_tasks
        }
        
        # Add event handlers if any exist
        if all_event_handlers:
            workflow_dict["event_handlers"] = [
                handler.to_dict() for handler in all_event_handlers
            ]
            
        return workflow_dict
        
    def to_yaml(self) -> str:
        """
        Convert WorkflowBuilder to YAML format.
        
        Returns:
            YAML string representation
        """
        import yaml
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)
        
    def to_json(self, indent: int = 2) -> str:
        """
        Convert WorkflowBuilder to JSON format.
        
        Args:
            indent: Number of spaces for indentation
            
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=indent)
        
    def save_yaml(self, filepath: str) -> None:
        """
        Save workflow as YAML file.
        
        Args:
            filepath: Path to save the YAML file
        """
        with open(filepath, 'w') as f:
            f.write(self.to_yaml())
            
    def save_json(self, filepath: str, indent: int = 2) -> None:
        """
        Save workflow as JSON file.
        
        Args:
            filepath: Path to save the JSON file
            indent: Number of spaces for indentation
        """
        with open(filepath, 'w') as f:
            f.write(self.to_json(indent))
            
    def validate(self) -> List[str]:
        """
        Validate the workflow for common issues.

        Returns:
            List of validation error messages (empty if valid)

        Raises:
            EmptyWorkflowError: If workflow has no tasks
            DuplicateTaskError: If duplicate task IDs are found
            InvalidDependencyError: If dependencies are invalid
            CircularDependencyError: If circular dependencies are detected
        """
        errors = []

        # Check for empty workflow
        if not self.tasks:
            raise EmptyWorkflowError(workflow_name=self.workflow_metadata.get("name"))

        # Check for duplicate task IDs
        task_ids = [task.task_id for task in self.tasks]
        unique_ids = set(task_ids)
        if len(task_ids) != len(unique_ids):
            duplicates = [tid for tid in task_ids if task_ids.count(tid) > 1]
            raise DuplicateTaskError(
                list(set(duplicates)),
                workflow_name=self.workflow_metadata.get("name")
            )

        # Check dependencies exist
        for task in self.tasks:
            for dep in task.task_data.get("dependencies", []):
                if dep not in unique_ids:
                    raise InvalidDependencyError(
                        task.task_id,
                        dep,
                        f"Dependency task '{dep}' does not exist in workflow"
                    )

        # Check for circular dependencies
        self._detect_circular_dependencies()

        return errors  # Return empty list if all validations pass

    def _detect_circular_dependencies(self) -> None:
        """
        Detect circular dependencies in the workflow.

        Raises:
            CircularDependencyError: If circular dependencies are found
        """
        # Build dependency graph
        graph = {}
        for task in self.tasks:
            graph[task.task_id] = set(task.task_data.get("dependencies", []))

        # Check for self-dependencies
        for task_id, deps in graph.items():
            if task_id in deps:
                raise CircularDependencyError(
                    [task_id, task_id],
                    workflow_name=self.workflow_metadata.get("name")
                )

        # Topological sort to detect cycles
        visited = set()
        rec_stack = set()

        def has_cycle(node: str, path: List[str]) -> Optional[List[str]]:
            if node in rec_stack:
                # Found a cycle - return the cycle path
                cycle_start = path.index(node)
                return path[cycle_start:] + [node]

            if node in visited:
                return None

            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for dep in graph.get(node, set()):
                cycle = has_cycle(dep, path.copy())
                if cycle:
                    return cycle

            rec_stack.remove(node)
            return None

        for task_id in graph:
            if task_id not in visited:
                cycle = has_cycle(task_id, [])
                if cycle:
                    raise CircularDependencyError(
                        cycle,
                        workflow_name=self.workflow_metadata.get("name")
                    )
        
    def get_task_count(self) -> int:
        """Get the number of tasks in the workflow."""
        return len(self.tasks)
        
    def get_task_ids(self) -> List[str]:
        """Get list of all task IDs in the workflow."""
        return [task.task_id for task in self.tasks]
        
    def get_event_handler_count(self) -> int:
        """Get the total number of event handlers across all tasks."""
        return sum(len(task.get_event_handlers()) for task in self.tasks)
        
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"WorkflowBuilder(name='{self.workflow_metadata['name']}', tasks={self.get_task_count()}, handlers={self.get_event_handler_count()})"