"""
Workflow Loading and Validation

Handles YAML workflow parsing, validation, and conversion to internal models.
"""

import yaml
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from uuid import uuid4

from gleitzeit.core.models import Task, Workflow, Priority, RetryConfig
from gleitzeit.core.errors import ConfigurationError

logger = logging.getLogger(__name__)


async def load_workflow(workflow_path: Path) -> Workflow:
    """Load workflow from YAML file"""
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
    
    try:
        with open(workflow_path, 'r') as f:
            workflow_data = yaml.safe_load(f)
        
        # Convert YAML to Workflow model
        workflow = _yaml_to_workflow(workflow_data)
        logger.debug(f"Loaded workflow: {workflow.name} with {len(workflow.tasks)} tasks")
        
        return workflow
        
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML format: {e}")
    except Exception as e:
        raise ConfigurationError(f"Failed to load workflow: {e}")


def validate_workflow(workflow: Workflow) -> List[str]:
    """Validate workflow definition and return list of errors"""
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
            errors.append(f"Task {task.id}: protocol is required")
        
        if not task.method:
            errors.append(f"Task {task.id}: method is required")
        
        # Validate dependencies
        if task.dependencies:
            for dep in task.dependencies:
                if dep not in task_ids and dep != task.id:
                    # This might be a forward reference, check all task IDs
                    all_task_ids = {t.id for t in workflow.tasks}
                    if dep not in all_task_ids:
                        errors.append(f"Task {task.id}: unknown dependency '{dep}'")
                
                if dep == task.id:
                    errors.append(f"Task {task.id}: cannot depend on itself")
    
    # Check for circular dependencies
    circular_deps = _find_circular_dependencies(workflow.tasks)
    if circular_deps:
        errors.append(f"Circular dependencies detected: {' -> '.join(circular_deps)}")
    
    return errors


def _yaml_to_workflow(data: Dict[str, Any]) -> Workflow:
    """Convert YAML data to Workflow model"""
    
    # Generate workflow ID if not provided
    workflow_id = data.get('id', f"workflow-{uuid4().hex[:8]}")
    
    # Parse tasks with name-to-ID mapping for dependency resolution
    tasks = []
    name_to_id_map = {}
    
    # First pass: create tasks and build name-to-ID mapping
    for task_data in data.get('tasks', []):
        task = _yaml_to_task(task_data, workflow_id, resolve_dependencies=False)
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
        name=data.get('name', ''),
        description=data.get('description'),
        tasks=tasks,
        metadata=data.get('metadata', {})
    )
    
    # Store provider requirements in metadata
    if 'providers' in data:
        workflow.metadata['required_providers'] = data['providers']
    
    return workflow


def _yaml_to_task(data: Dict[str, Any], workflow_id: str, resolve_dependencies: bool = True) -> Task:
    """Convert YAML task data to Task model"""
    
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
    priority_str = data.get('priority', 'normal')
    try:
        priority = Priority(priority_str)
    except ValueError:
        logger.warning(f"Invalid priority '{priority_str}', using 'normal'")
        priority = Priority.NORMAL
    
    # Handle dependencies - standardize on 'dependencies' key only
    dependencies = []
    if resolve_dependencies:
        # Support both 'dependencies' (preferred) and legacy 'depends_on'
        dependencies = data.get('dependencies', data.get('depends_on', []))
    
    # Create task
    task = Task(
        id=task_id,
        name=data.get('name', task_id),
        protocol=data.get('protocol', ''),
        method=data.get('method', ''),
        params=data.get('params', {}),
        dependencies=dependencies,
        priority=priority,
        timeout=data.get('timeout'),
        workflow_id=workflow_id,
        retry_config=retry_config,
        metadata=data.get('metadata', {})
    )
    
    return task


def _find_circular_dependencies(tasks: List[Task]) -> Optional[List[str]]:
    """Find circular dependencies using DFS"""
    # Build adjacency list
    graph = {}
    for task in tasks:
        graph[task.id] = task.dependencies or []
    
    # Track visit states: 0=unvisited, 1=visiting, 2=visited
    state = {task.id: 0 for task in tasks}
    
    def dfs(node: str, path: List[str]) -> Optional[List[str]]:
        if state[node] == 1:  # Back edge found - cycle detected
            cycle_start = path.index(node)
            return path[cycle_start:] + [node]
        
        if state[node] == 2:  # Already processed
            return None
        
        state[node] = 1  # Mark as visiting
        path.append(node)
        
        for neighbor in graph.get(node, []):
            if neighbor in graph:  # Only check valid dependencies
                cycle = dfs(neighbor, path)
                if cycle:
                    return cycle
        
        path.pop()
        state[node] = 2  # Mark as visited
        return None
    
    # Check each unvisited node
    for task_id in graph:
        if state[task_id] == 0:
            cycle = dfs(task_id, [])
            if cycle:
                return cycle
    
    return None


def create_workflow_template(name: str, template_type: str) -> Dict[str, Any]:
    """Create workflow template"""
    
    if template_type == "data-pipeline":
        return {
            'name': name,
            'version': '1.0',
            'description': 'Data processing pipeline',
            'providers': [
                'mcp://filesystem'
            ],
            'tasks': [
                {
                    'id': 'fetch-data',
                    'name': 'Fetch Input Data',
                    'protocol': 'mcp/filesystem',
                    'method': 'file.read',
                    'params': {
                        'path': '/path/to/input.json'
                    }
                },
                {
                    'id': 'process-data',
                    'name': 'Process Data',
                    'protocol': 'custom/processor',
                    'method': 'transform',
                    'params': {
                        'input': '${fetch-data.result}'
                    },
                    'dependencies': ['fetch-data'],
                    'retry': {
                        'max_attempts': 3,
                        'backoff': 'exponential'
                    }
                },
                {
                    'id': 'save-results',
                    'name': 'Save Results',
                    'protocol': 'mcp/filesystem',
                    'method': 'file.write',
                    'params': {
                        'path': '/path/to/output.json',
                        'content': '${process-data.result}'
                    },
                    'dependencies': ['process-data']
                }
            ]
        }
    
    elif template_type == "api-workflow":
        return {
            'name': name,
            'version': '1.0', 
            'description': 'HTTP API workflow',
            'providers': [
                'http://api-client'
            ],
            'tasks': [
                {
                    'id': 'api-call',
                    'name': 'API Request',
                    'protocol': 'http/client',
                    'method': 'get',
                    'params': {
                        'url': 'https://api.example.com/data',
                        'headers': {
                            'Authorization': 'Bearer ${env.API_TOKEN}'
                        }
                    },
                    'retry': {
                        'max_attempts': 3,
                        'backoff': 'exponential',
                        'base_delay': 2.0
                    }
                }
            ]
        }
    
    elif template_type == "mcp-integration":
        return {
            'name': name,
            'version': '1.0',
            'description': 'MCP server integration example',
            'providers': [
                'mcp://filesystem',
                'mcp://brave-search'
            ],
            'tasks': [
                {
                    'id': 'echo-test',
                    'name': 'Echo Test',
                    'protocol': 'mcp/v1',
                    'method': 'mcp/tool.echo',
                    'params': {
                        'message': 'Advanced workflow with MCP'
                    },
                    'retry': {
                        'max_attempts': 2
                    }
                },
                {
                    'id': 'process-result',
                    'name': 'Process Echo Result',
                    'protocol': 'python/v1',
                    'method': 'python/execute',
                    'params': {
                        'code': 'result = f"Processed: ${echo-test.response}"'
                    },
                    'dependencies': ['echo-test']
                }
            ]
        }
    
    else:
        # Basic template
        return {
            'name': name,
            'version': '1.0',
            'description': f'Generated workflow: {name}',
            'tasks': [
                {
                    'id': 'example-task',
                    'name': 'Example Task',
                    'protocol': 'custom/example',
                    'method': 'execute',
                    'params': {
                        'message': 'Hello, Gleitzeit!'
                    }
                }
            ]
        }