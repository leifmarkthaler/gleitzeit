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

    # DAG Pattern Helpers

    def pipeline(self, *tasks: TaskBuilder) -> 'WorkflowBuilder':
        """
        Create a sequential pipeline where each task depends on the previous.

        This is an alias for sequential() with clearer semantics.

        Example:
            workflow = w().pipeline(
                t("fetch", "http/v1:request"),
                t("process", "python/v1:execute"),
                t("analyze", "ollama/v1:generate"),
                t("save", "python/v1:execute")
            )
            # Creates: fetch → process → analyze → save

        Args:
            *tasks: Tasks to chain sequentially

        Returns:
            Self for chaining
        """
        return self.sequential(*tasks)

    def fan_out(self, source: Union[str, TaskBuilder], *consumers: TaskBuilder) -> 'WorkflowBuilder':
        """
        Create a fan-out pattern: one producer feeds multiple consumers.

        All consumer tasks will depend on the source task and can run in parallel.

        Example:
            workflow = w(
                t("fetch", "http/v1:request").with_(url="...")
            ).fan_out("fetch",
                t("process1", "python/v1:execute"),
                t("process2", "python/v1:execute"),
                t("process3", "python/v1:execute")
            )
            # Creates: fetch → [process1, process2, process3] (parallel)

        Args:
            source: Source task ID or TaskBuilder
            *consumers: Consumer tasks that depend on source

        Returns:
            Self for chaining

        Raises:
            WorkflowBuilderError: If source task not found
        """
        # Get source task ID
        if isinstance(source, TaskBuilder):
            source_id = source.task_id
            # Make sure source is in the workflow
            if source not in self.tasks:
                self.add_task(source)
        else:
            source_id = source
            # Verify source exists
            if not any(t.task_id == source_id for t in self.tasks):
                raise WorkflowBuilderError(f"Source task '{source_id}' not found in workflow")

        # Add consumers with dependency on source
        for consumer in consumers:
            if source_id not in consumer.dependencies:
                consumer.needs(source_id)
            self.add_task(consumer)

        return self

    def fan_in(self, *sources: Union[str, TaskBuilder], aggregator: TaskBuilder) -> 'WorkflowBuilder':
        """
        Create a fan-in pattern: multiple producers feed one consumer.

        The aggregator task will depend on all source tasks.

        Example:
            workflow = w(
                t("fetch1", "http/v1:request"),
                t("fetch2", "http/v1:request"),
                t("fetch3", "http/v1:request")
            ).fan_in("fetch1", "fetch2", "fetch3",
                aggregator=t("merge", "python/v1:execute")
            )
            # Creates: [fetch1, fetch2, fetch3] → merge

        Args:
            *sources: Source task IDs or TaskBuilders
            aggregator: Consumer task that depends on all sources

        Returns:
            Self for chaining

        Raises:
            WorkflowBuilderError: If source tasks not found
        """
        source_ids = []

        for source in sources:
            if isinstance(source, TaskBuilder):
                source_id = source.task_id
                # Make sure source is in the workflow
                if source not in self.tasks:
                    self.add_task(source)
            else:
                source_id = source
                # Verify source exists
                if not any(t.task_id == source_id for t in self.tasks):
                    raise WorkflowBuilderError(f"Source task '{source_id}' not found in workflow")

            source_ids.append(source_id)

        # Add all sources as dependencies for aggregator
        for source_id in source_ids:
            if source_id not in aggregator.dependencies:
                aggregator.needs(source_id)

        self.add_task(aggregator)
        return self

    def diamond(
        self,
        source: Union[str, TaskBuilder],
        *middle_tasks: TaskBuilder,
        aggregator: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Create a diamond pattern: fan-out then fan-in.

        One source task feeds multiple middle tasks, which all feed into one aggregator.

        Example:
            workflow = w(
                t("fetch", "http/v1:request")
            ).diamond("fetch",
                t("process1", "python/v1:execute"),
                t("process2", "python/v1:execute"),
                t("process3", "python/v1:execute"),
                aggregator=t("merge", "python/v1:execute")
            )
            # Creates:
            #        process1
            #       /         \\
            # fetch - process2 - merge
            #       \\         /
            #        process3

        Args:
            source: Source task ID or TaskBuilder
            *middle_tasks: Tasks that depend on source
            aggregator: Final task that depends on all middle tasks

        Returns:
            Self for chaining

        Raises:
            WorkflowBuilderError: If pattern cannot be created
        """
        # Fan out from source to middle tasks
        self.fan_out(source, *middle_tasks)

        # Fan in from middle tasks to aggregator
        middle_ids = [task.task_id for task in middle_tasks]
        self.fan_in(*middle_ids, aggregator=aggregator)

        return self

    def broadcast(
        self,
        source: Union[str, TaskBuilder],
        *consumers: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Broadcast pattern: alias for fan_out with clearer semantics.

        One task broadcasts its output to multiple consumers.

        Example:
            workflow = w(
                t("load_config", "python/v1:execute")
            ).broadcast("load_config",
                t("service1", "python/v1:execute"),
                t("service2", "python/v1:execute"),
                t("service3", "python/v1:execute")
            )

        Args:
            source: Source task
            *consumers: Consumer tasks

        Returns:
            Self for chaining
        """
        return self.fan_out(source, *consumers)

    def aggregate(
        self,
        *sources: Union[str, TaskBuilder],
        aggregator: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Aggregation pattern: alias for fan_in with clearer semantics.

        Multiple tasks feed their outputs into one aggregator.

        Example:
            workflow = w(
                t("query1", "http/v1:request"),
                t("query2", "http/v1:request"),
                t("query3", "http/v1:request")
            ).aggregate("query1", "query2", "query3",
                aggregator=t("combine", "python/v1:execute")
            )

        Args:
            *sources: Source tasks
            aggregator: Aggregator task

        Returns:
            Self for chaining
        """
        return self.fan_in(*sources, aggregator=aggregator)

    def print_dag(self):
        """
        Print a visual representation of the workflow DAG.

        Shows task dependencies in an ASCII tree structure.

        Example output:
            Workflow DAG: Data Pipeline

            fetch (no dependencies)
              └─> process1
                    └─> analyze
                          └─> save
              └─> process2
                    └─> analyze
        """
        print(f"Workflow DAG: {self.workflow_name or 'Unnamed'}")
        print()

        # Build dependency map
        dependents = {}  # task_id -> list of tasks that depend on it
        for task in self.tasks:
            for dep in task.dependencies:
                if dep not in dependents:
                    dependents[dep] = []
                dependents[dep].append(task.task_id)

        # Find root tasks (no dependencies)
        roots = [task.task_id for task in self.tasks if not task.dependencies]

        # Print tree recursively
        def print_tree(task_id: str, prefix: str = "", is_last: bool = True):
            # Get task info
            task = self.get_task(task_id)
            if not task:
                return

            # Print current task
            connector = "└─> " if is_last else "├─> "
            dep_info = f" (depends on: {', '.join(task.dependencies)})" if task.dependencies else " (no dependencies)"
            print(f"{prefix}{connector if prefix else ''}{task_id}{dep_info if not prefix else ''}")

            # Print dependents
            children = dependents.get(task_id, [])
            for i, child_id in enumerate(children):
                is_last_child = (i == len(children) - 1)
                extension = "    " if is_last else "│   "
                print_tree(child_id, prefix + extension, is_last_child)

        # Print all root tasks
        for i, root_id in enumerate(roots):
            print_tree(root_id, "", i == len(roots) - 1)
            if i < len(roots) - 1:
                print()