"""
WorkflowBuilder - Fluent interface for building and submitting Gleitzeit workflows.

Provides a chainable API for composing tasks into workflows and submitting them.
"""

import json
import asyncio
import uuid
from typing import Dict, Any, List, Optional, Union
from .task_builder import TaskBuilder
from .errors import (
    WorkflowBuilderError,
    EmptyWorkflowError,
    DuplicateTaskError,
    InvalidDependencyError,
    CircularDependencyError
)


class WorkflowBuilder:
    """
    Fluent builder for creating and submitting workflows.

    Adapted for 0.0.7's workflow structure and can directly submit to the API.
    """

    def __init__(self, *tasks: TaskBuilder):
        """
        Initialize workflow builder with tasks.

        Args:
            *tasks: TaskBuilder instances to include

        Raises:
            EmptyWorkflowError: If no tasks provided
            DuplicateTaskError: If duplicate task IDs found
        """
        if not tasks:
            raise EmptyWorkflowError()

        self.tasks: List[TaskBuilder] = list(tasks)
        self.workflow_name: Optional[str] = None
        self.workflow_id: Optional[str] = None
        self.workflow_version: str = "1.0.0"
        self.workflow_description: Optional[str] = None
        self.workflow_metadata: Dict[str, Any] = {}

        # Validate no duplicate task IDs
        self._validate_unique_tasks()

    def _validate_unique_tasks(self):
        """Check for duplicate task IDs."""
        task_ids = [task.task_id for task in self.tasks]
        seen = set()
        for task_id in task_ids:
            if task_id in seen:
                raise DuplicateTaskError(task_id)
            seen.add(task_id)

    def _validate_dependencies(self):
        """Validate all dependencies exist."""
        task_ids = {task.task_id for task in self.tasks}

        for task in self.tasks:
            for dep in task.dependencies:
                if dep not in task_ids:
                    raise InvalidDependencyError(
                        task.task_id,
                        dep,
                        list(task_ids)
                    )

    def _detect_circular_dependencies(self):
        """Detect circular dependencies in the workflow."""
        # Build adjacency list
        graph = {}
        for task in self.tasks:
            graph[task.task_id] = task.dependencies.copy()

        def has_cycle_from(node: str, visited: set, rec_stack: set, path: list) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    result = has_cycle_from(neighbor, visited, rec_stack, path.copy())
                    if result:
                        return result
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]

            rec_stack.remove(node)
            return None

        visited = set()
        for task_id in graph:
            if task_id not in visited:
                rec_stack = set()
                result = has_cycle_from(task_id, visited, rec_stack, [])
                if result:
                    raise CircularDependencyError(result)

    def add_task(self, task: TaskBuilder) -> 'WorkflowBuilder':
        """
        Add a task to the workflow.

        Args:
            task: TaskBuilder instance

        Returns:
            Self for chaining
        """
        # Check for duplicate
        for existing in self.tasks:
            if existing.task_id == task.task_id:
                raise DuplicateTaskError(task.task_id)

        self.tasks.append(task)
        return self

    def name(self, name: str) -> 'WorkflowBuilder':
        """
        Set workflow name.

        Args:
            name: Workflow name

        Returns:
            Self for chaining
        """
        self.workflow_name = name
        return self

    def id(self, workflow_id: str) -> 'WorkflowBuilder':
        """
        Set workflow ID.

        Args:
            workflow_id: Unique workflow identifier

        Returns:
            Self for chaining
        """
        self.workflow_id = workflow_id
        return self

    def version(self, version: str) -> 'WorkflowBuilder':
        """
        Set workflow version.

        Args:
            version: Version string

        Returns:
            Self for chaining
        """
        self.workflow_version = version
        return self

    def description(self, desc: str) -> 'WorkflowBuilder':
        """
        Set workflow description.

        Args:
            desc: Description text

        Returns:
            Self for chaining
        """
        self.workflow_description = desc
        return self

    def metadata(self, **metadata) -> 'WorkflowBuilder':
        """
        Set workflow metadata.

        Args:
            **metadata: Metadata key-value pairs

        Returns:
            Self for chaining
        """
        self.workflow_metadata.update(metadata)
        return self

    def validate(self) -> List[str]:
        """
        Validate the workflow structure.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        try:
            self._validate_unique_tasks()
        except DuplicateTaskError as e:
            errors.append(str(e))

        try:
            self._validate_dependencies()
        except InvalidDependencyError as e:
            errors.append(str(e))

        try:
            self._detect_circular_dependencies()
        except CircularDependencyError as e:
            errors.append(str(e))

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to 0.0.7 workflow dictionary format.

        Returns:
            Workflow dictionary ready for submission
        """
        # Validate before building
        errors = self.validate()
        if errors:
            raise WorkflowBuilderError(
                f"Workflow validation failed: {'; '.join(errors)}"
            )

        # Build workflow structure
        workflow = {
            "workflow": {
                "name": self.workflow_name or "Easy Workflow",
                "tasks": [task.to_dict() for task in self.tasks]
            }
        }

        # Add optional workflow ID
        if self.workflow_id:
            workflow["workflow_id"] = self.workflow_id
        else:
            # Generate one if not provided
            workflow["workflow_id"] = f"easy-workflow-{uuid.uuid4().hex[:8]}"

        # Add metadata if any
        if self.workflow_metadata:
            workflow["metadata"] = self.workflow_metadata

        return workflow

    def to_json(self, indent: int = 2) -> str:
        """
        Convert to JSON string.

        Args:
            indent: JSON indentation

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=indent)

    def to_yaml(self) -> str:
        """
        Convert to YAML string.

        Returns:
            YAML string representation

        Raises:
            ImportError: If PyYAML not installed
        """
        try:
            import yaml
            return yaml.dump(self.to_dict(), default_flow_style=False)
        except ImportError:
            raise ImportError("PyYAML required for YAML output: pip install pyyaml")

    def submit(self, api_url: str = "http://localhost:8000") -> Dict[str, Any]:
        """
        Submit workflow to Gleitzeit API synchronously.

        Args:
            api_url: API base URL

        Returns:
            Submission response

        Raises:
            WorkflowBuilderError: If submission fails
        """
        return asyncio.run(self.submit_async(api_url))

    async def submit_async(self, api_url: str = "http://localhost:8000") -> Dict[str, Any]:
        """
        Submit workflow to Gleitzeit API asynchronously.

        Args:
            api_url: API base URL

        Returns:
            Submission response

        Raises:
            WorkflowBuilderError: If submission fails
        """
        # Import here to avoid circular dependency
        from ..client import GleitzeitClient

        try:
            async with GleitzeitClient(api_url) as client:
                workflow_dict = self.to_dict()
                response = await client.submit_workflow(
                    workflow_dict["workflow"],
                    workflow_id=workflow_dict.get("workflow_id")
                )
                return {
                    "workflow_id": response.workflow_id,
                    "status": response.status,
                    "submitted_at": response.submitted_at
                }
        except Exception as e:
            raise WorkflowBuilderError(f"Failed to submit workflow: {e}")

    def get_task_count(self) -> int:
        """Get number of tasks in workflow."""
        return len(self.tasks)

    def get_task_ids(self) -> List[str]:
        """Get list of task IDs."""
        return [task.task_id for task in self.tasks]

    def get_task(self, task_id: str) -> Optional[TaskBuilder]:
        """Get task by ID."""
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def __repr__(self) -> str:
        """String representation of the workflow."""
        name = self.workflow_name or "Unnamed"
        return f"WorkflowBuilder('{name}', tasks={len(self.tasks)})"

    # Convenience methods for common operations

    def parallel(self, *tasks: TaskBuilder) -> 'WorkflowBuilder':
        """
        Add tasks that run in parallel (no dependencies between them).

        Args:
            *tasks: Tasks to run in parallel

        Returns:
            Self for chaining
        """
        for task in tasks:
            self.add_task(task)
        return self

    def sequential(self, *tasks: TaskBuilder) -> 'WorkflowBuilder':
        """
        Add tasks that run sequentially (each depends on the previous).

        Args:
            *tasks: Tasks to run sequentially

        Returns:
            Self for chaining
        """
        prev_task_id = None

        for i, task in enumerate(tasks):
            if prev_task_id and prev_task_id not in task.dependencies:
                task.dependencies.append(prev_task_id)
            self.add_task(task)
            prev_task_id = task.task_id

        return self

    def print_structure(self):
        """Print workflow structure for debugging."""
        print(f"Workflow: {self.workflow_name or 'Unnamed'}")
        print(f"Tasks: {len(self.tasks)}")

        for task in self.tasks:
            deps = f" <- {task.dependencies}" if task.dependencies else ""
            print(f"  - {task.task_id}{deps}")

    def submit_and_wait(
        self,
        api_url: str = "http://localhost:8000",
        timeout: int = 300,
        poll_interval: int = 2
    ) -> Dict[str, Any]:
        """
        Submit workflow and wait for completion.

        Args:
            api_url: API base URL
            timeout: Maximum wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Final workflow status

        Raises:
            WorkflowBuilderError: If submission fails
            TimeoutError: If workflow doesn't complete in time
        """
        return asyncio.run(
            self.submit_and_wait_async(api_url, timeout, poll_interval)
        )

    async def submit_and_wait_async(
        self,
        api_url: str = "http://localhost:8000",
        timeout: int = 300,
        poll_interval: int = 2
    ) -> Dict[str, Any]:
        """
        Submit workflow and wait for completion asynchronously.

        Args:
            api_url: API base URL
            timeout: Maximum wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Final workflow status

        Raises:
            WorkflowBuilderError: If submission fails
            TimeoutError: If workflow doesn't complete in time
        """
        from ..client import GleitzeitClient

        async with GleitzeitClient(api_url) as client:
            # Submit workflow
            workflow_dict = self.to_dict()
            response = await client.submit_workflow(
                workflow_dict["workflow"],
                workflow_id=workflow_dict.get("workflow_id")
            )

            # Wait for completion
            final_status = await client.wait_for_workflow(
                response.workflow_id,
                timeout=timeout,
                poll_interval=poll_interval
            )

            return {
                "workflow_id": final_status.workflow_id,
                "status": final_status.status,
                "created_at": final_status.created_at,
                "completed_at": final_status.completed_at,
                "error": final_status.error
            }