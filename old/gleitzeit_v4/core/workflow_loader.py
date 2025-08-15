"""
Standalone Workflow Loader

A unified workflow loader that can be used by any component without dependencies
on execution engine or other components. This ensures consistent YAML loading
across CLI, tests, and other parts of the system.
"""

import yaml
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from uuid import uuid4

from core.models import Task, Workflow, Priority, RetryConfig

logger = logging.getLogger(__name__)


def load_workflow_from_file(file_path: str) -> Workflow:
    """
    Load workflow from YAML or JSON file.
    
    This is the single source of truth for loading workflows from files.
    Uses 'params' consistently for task parameters.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {file_path}")
    
    with open(path, 'r') as f:
        if path.suffix.lower() in ['.yaml', '.yml']:
            data = yaml.safe_load(f)
        elif path.suffix.lower() == '.json':
            data = json.load(f)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")
    
    return load_workflow_from_dict(data)


def load_workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    """
    Load workflow from dictionary (parsed YAML/JSON).
    
    Handles:
    - Task creation with auto-generated IDs
    - Dependency resolution (name -> ID mapping)
    - Retry configuration
    - Priority parsing
    """
    # Generate workflow ID if not provided
    workflow_id = data.get('id', f"workflow-{uuid4().hex[:8]}")
    
    # Parse tasks with name-to-ID mapping for dependency resolution
    tasks = []
    name_to_id_map = {}
    
    # First pass: create tasks and build name-to-ID mapping
    for task_data in data.get('tasks', []):
        task = create_task_from_dict(task_data, workflow_id, resolve_dependencies=False)
        tasks.append(task)
        name_to_id_map[task.name] = task.id
    
    # Second pass: resolve dependencies (map task names to task IDs)
    for i, task_data in enumerate(data.get('tasks', [])):
        dependencies = task_data.get('dependencies', [])
        resolved_dependencies = []
        
        for dep_name in dependencies:
            if dep_name in name_to_id_map:
                resolved_dependencies.append(name_to_id_map[dep_name])
            else:
                logger.warning(f"Task '{tasks[i].name}' depends on unknown task '{dep_name}'")
                # Keep original dependency name for error reporting
                resolved_dependencies.append(dep_name)
        
        tasks[i].dependencies = resolved_dependencies
    
    # Create workflow
    workflow = Workflow(
        id=workflow_id,
        name=data.get('name', 'Unnamed Workflow'),
        description=data.get('description', ''),
        tasks=tasks,
        metadata=data.get('metadata', {})
    )
    
    # Store provider requirements in metadata if specified
    if 'providers' in data:
        workflow.metadata['required_providers'] = data['providers']
    
    return workflow


def create_task_from_dict(data: Dict[str, Any], workflow_id: str, 
                          resolve_dependencies: bool = True) -> Task:
    """
    Create a Task from dictionary data.
    
    IMPORTANT: Uses 'params' as the key for task parameters, not 'parameters'.
    """
    # Generate task ID if not provided
    task_id = data.get('id', f"task-{uuid4().hex[:8]}")
    
    # Parse retry configuration
    retry_config = None
    if 'retry' in data:
        retry_data = data['retry']
        retry_config = RetryConfig(
            max_attempts=retry_data.get('max_attempts', 3),
            backoff_strategy=retry_data.get('backoff', 'exponential'),
            base_delay=retry_data.get('base_delay', 1.0),
            max_delay=retry_data.get('max_delay', 300.0),
            jitter=retry_data.get('jitter', True)
        )
    
    # Parse priority
    priority_value = data.get('priority', 'normal')
    # Handle both string and numeric priorities
    if isinstance(priority_value, int):
        # Map numeric priorities to string values
        priority_map = {1: 'high', 2: 'normal', 3: 'low'}
        priority_str = priority_map.get(priority_value, 'normal')
    else:
        priority_str = str(priority_value).lower()
    
    try:
        priority = Priority(priority_str)
    except ValueError:
        logger.warning(f"Invalid priority '{priority_str}', using 'normal'")
        priority = Priority.NORMAL
    
    # Handle dependencies
    dependencies = []
    if resolve_dependencies:
        dependencies = data.get('dependencies', [])
    
    # Create task - using 'params' as the standard key
    task = Task(
        id=task_id,
        name=data.get('name', task_id),
        protocol=data.get('protocol', ''),
        method=data.get('method', ''),
        params=data.get('params', {}),  # Standard: 'params' not 'parameters'
        dependencies=dependencies,
        priority=priority,
        timeout=data.get('timeout'),
        workflow_id=workflow_id,
        retry_config=retry_config,
        metadata=data.get('metadata', {})
    )
    
    return task


def validate_workflow(workflow: Workflow) -> List[str]:
    """
    Validate workflow definition and return list of errors.
    """
    errors = []
    
    # Basic validation
    if not workflow.name:
        errors.append("Workflow name is required")
    
    if not workflow.tasks:
        errors.append("Workflow must contain at least one task")
        return errors
    
    # Task validation
    task_ids = set()
    for task in workflow.tasks:
        # Check for duplicate task IDs
        if task.id in task_ids:
            errors.append(f"Duplicate task ID: {task.id}")
        task_ids.add(task.id)
        
        # Validate task fields
        if not task.protocol:
            errors.append(f"Task {task.name}: protocol is required")
        
        if not task.method:
            errors.append(f"Task {task.name}: method is required")
        
        # Validate dependencies
        if task.dependencies:
            for dep in task.dependencies:
                if dep not in task_ids and dep != task.id:
                    # Check if dependency exists
                    all_task_ids = {t.id for t in workflow.tasks}
                    if dep not in all_task_ids:
                        errors.append(f"Task {task.name}: unknown dependency '{dep}'")
                
                if dep == task.id:
                    errors.append(f"Task {task.name}: cannot depend on itself")
    
    # Check for circular dependencies
    circular = find_circular_dependencies(workflow.tasks)
    if circular:
        errors.append(f"Circular dependencies detected: {' -> '.join(circular)}")
    
    return errors


def find_circular_dependencies(tasks: List[Task]) -> Optional[List[str]]:
    """Find circular dependencies using DFS."""
    # Build adjacency list
    graph = {}
    task_names = {}  # ID to name mapping for better error messages
    for task in tasks:
        graph[task.id] = task.dependencies or []
        task_names[task.id] = task.name
    
    # Track visit states: 0=unvisited, 1=visiting, 2=visited
    state = {task.id: 0 for task in tasks}
    
    def dfs(node: str, path: List[str]) -> Optional[List[str]]:
        if state[node] == 1:  # Back edge found - cycle detected
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            # Convert IDs to names for readability
            return [task_names.get(tid, tid) for tid in cycle]
        
        if state[node] == 2:  # Already visited
            return None
        
        state[node] = 1  # Mark as visiting
        path.append(node)
        
        for neighbor in graph.get(node, []):
            if neighbor in graph:  # Only check valid dependencies
                result = dfs(neighbor, path.copy())
                if result:
                    return result
        
        state[node] = 2  # Mark as visited
        return None
    
    # Check all components
    for task_id in graph:
        if state[task_id] == 0:
            result = dfs(task_id, [])
            if result:
                return result
    
    return None