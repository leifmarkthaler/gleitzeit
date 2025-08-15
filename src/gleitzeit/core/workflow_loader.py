"""
Standalone Workflow Loader

A unified workflow loader that can be used by any component without dependencies
on execution engine or other components. This ensures consistent YAML loading
across CLI, tests, and other parts of the system.
"""

import yaml
import json
import logging
import glob
from pathlib import Path
from typing import Dict, Any, List, Optional
from uuid import uuid4

from gleitzeit.core.models import Task, Workflow, Priority, RetryConfig
from gleitzeit.core.errors import WorkflowValidationError, ConfigurationError

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
            raise ConfigurationError(f"Unsupported file format: {path.suffix}")
    
    return load_workflow_from_dict(data)


def load_workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    """
    Load workflow from dictionary (parsed YAML/JSON).
    
    Handles:
    - Task creation with auto-generated IDs
    - Dependency resolution (name -> ID mapping)
    - Retry configuration
    - Priority parsing
    - Batch workflows with dynamic file discovery
    """
    # Check if this is a batch workflow
    if data.get('type') == 'batch' or 'batch' in data:
        return create_batch_workflow_from_dict(data)
    
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
    
    # Extract protocol from method if not provided
    method = data.get('method', '')
    protocol = data.get('protocol', '')
    if not protocol and method:
        if '/' in method:
            # Extract protocol from method like "llm/chat" -> "llm/v1"
            protocol = method.split('/')[0] + '/v1'
        else:
            protocol = 'python/v1'
    
    # Handle both 'params' and 'parameters' for backwards compatibility
    params = data.get('params', data.get('parameters', {}))
    
    # Create task
    task = Task(
        id=task_id,
        name=data.get('name', task_id),
        protocol=protocol,
        method=method,
        params=params,
        dependencies=dependencies,
        priority=priority,
        timeout=data.get('timeout'),
        workflow_id=workflow_id,
        retry_config=retry_config,
        metadata=data.get('metadata', {})
    )
    
    return task


def create_batch_workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    """
    Create a batch workflow with dynamic file discovery.
    
    Batch workflows have:
    - A 'batch' section with directory and pattern
    - A 'template' section defining the task to apply to each file
    """
    batch_config = data.get('batch', {})
    template = data.get('template', {})
    
    # Get batch configuration
    directory = batch_config.get('directory')
    pattern = batch_config.get('pattern', '*')
    
    if not directory:
        raise WorkflowValidationError(
            workflow_id="batch_workflow",
            validation_errors=["Batch workflow requires 'batch.directory' to be specified"]
        )
    
    if not template:
        raise WorkflowValidationError(
            workflow_id="batch_workflow",
            validation_errors=["Batch workflow requires 'template' section to define task parameters"]
        )
    
    # Discover files
    dir_path = Path(directory)
    if not dir_path.exists():
        raise ConfigurationError(f"Directory not found: {directory}")
    
    if not dir_path.is_dir():
        raise ConfigurationError(f"Not a directory: {directory}")
    
    # Use glob to find matching files
    file_pattern = str(dir_path / pattern)
    files = glob.glob(file_pattern)
    
    # Filter out directories
    files = [f for f in files if Path(f).is_file()]
    
    if not files:
        logger.warning(f"No files found matching '{pattern}' in {directory}")
    
    logger.info(f"Found {len(files)} files matching '{pattern}' in {directory}")
    
    # Generate workflow ID
    workflow_id = data.get('id', f"batch-{uuid4().hex[:8]}")
    workflow_name = data.get('name', f"Batch Processing ({len(files)} files)")
    
    # Create tasks for each file
    tasks = []
    for i, file_path in enumerate(files):
        file_name = Path(file_path).name
        task_id = f"process-{file_name.replace('.', '-')}-{i}"
        
        # Determine if this is an image file
        is_image = Path(file_path).suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']
        
        # Build task parameters from template
        params = {}
        
        # Copy template parameters
        for key, value in template.items():
            if key != 'method':
                params[key] = value
        
        # Add file path based on protocol/method
        protocol = data.get('protocol', 'llm/v1')
        if protocol == 'python/v1':
            # For Python, file path goes in context
            if 'context' not in params:
                params['context'] = {}
            params['context']['file_path'] = file_path
        elif is_image and template.get('method') == 'llm/vision':
            params['image_path'] = file_path
        else:
            params['file_path'] = file_path
        
        # Create task
        task_data = {
            'id': task_id,
            'name': f"Process {file_name}",
            'protocol': data.get('protocol', 'llm/v1'),
            'method': template.get('method', 'llm/chat'),
            'params': params,
            'priority': template.get('priority', 'normal')
        }
        
        task = create_task_from_dict(task_data, workflow_id, resolve_dependencies=False)
        tasks.append(task)
    
    # Create workflow
    workflow = Workflow(
        id=workflow_id,
        name=workflow_name,
        description=data.get('description', f"Batch processing of {len(files)} files"),
        tasks=tasks,
        metadata={
            'batch': True,
            'file_count': len(files),
            'directory': directory,
            'pattern': pattern,
            'template': template
        }
    )
    
    return workflow


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