# Workflow Execution Guide

## Overview

Workflows in Gleitzeit v0.0.5 are DAG (Directed Acyclic Graph) based task orchestrations that support parallel execution, dependency management, and parameter substitution. The ExecutionEngine orchestrates workflow execution using providers and resource hubs.

## Workflow Structure

### Basic Workflow YAML

```yaml
name: "My Workflow"
description: "Example workflow showing key features"
version: "1.0.0"
metadata:
  author: "developer@example.com"
  tags: ["example", "llm", "processing"]

# Global parameters available to all tasks
parameters:
  model: "llama3.2"
  temperature: 0.7

# Task definitions
tasks:
  - id: "task1"
    name: "Generate Content"
    protocol: "llm/v1"
    method: "chat"
    parameters:
      model: "${parameters.model}"
      messages:
        - role: "user"
          content: "Generate a story about space"
    
  - id: "task2"
    name: "Analyze Content"
    protocol: "llm/v1"
    method: "chat"
    dependencies: ["task1"]  # Waits for task1
    parameters:
      model: "${parameters.model}"
      messages:
        - role: "user"
          content: "Analyze this story: ${task1.response}"
    
  - id: "task3"
    name: "Create Summary"
    protocol: "llm/v1"
    method: "chat"
    dependencies: ["task1", "task2"]  # Waits for both
    parameters:
      model: "${parameters.model}"
      messages:
        - role: "user"
          content: |
            Based on:
            Story: ${task1.response}
            Analysis: ${task2.response}
            Create a brief summary.
```

## Execution Flow

```
1. Workflow Submission
        ↓
2. Validation & Parsing
        ↓
3. Dependency Resolution
        ↓
4. Task Queue Creation
        ↓
5. Parallel Execution
        ↓
6. Result Collection
        ↓
7. Workflow Completion
```

## ExecutionEngine Architecture

```python
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.registry import ProtocolProviderRegistry
from gleitzeit.persistence import UnifiedPersistenceAdapter

class ExecutionEngine:
    """Core workflow execution engine"""
    
    def __init__(
        self,
        registry: ProtocolProviderRegistry,
        persistence: UnifiedPersistenceAdapter,
        max_parallel_tasks: int = 10,
        task_timeout: int = 300
    ):
        self.registry = registry
        self.persistence = persistence
        self.max_parallel_tasks = max_parallel_tasks
        self.task_timeout = task_timeout
        self.queue_manager = QueueManager()
        self.dependency_resolver = DependencyResolver()
        self.active_workflows = {}
    
    async def submit_workflow(
        self,
        workflow: Dict[str, Any]
    ) -> str:
        """Submit workflow for execution"""
        
        # 1. Validate workflow
        self._validate_workflow(workflow)
        
        # 2. Generate workflow ID
        workflow_id = self._generate_workflow_id()
        workflow['id'] = workflow_id
        
        # 3. Save to persistence
        await self.persistence.save_workflow(workflow)
        
        # 4. Create execution context
        context = WorkflowContext(
            workflow_id=workflow_id,
            workflow=workflow,
            status="pending"
        )
        self.active_workflows[workflow_id] = context
        
        # 5. Start execution
        asyncio.create_task(self._execute_workflow(context))
        
        return workflow_id
```

## Task Execution

### Task Lifecycle

```python
class TaskExecutor:
    """Executes individual tasks"""
    
    async def execute_task(
        self,
        task: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute a single task"""
        
        # 1. Update task status
        task['status'] = 'running'
        await self.persistence.save_task(task)
        
        try:
            # 2. Resolve parameters with substitution
            resolved_params = await self._resolve_parameters(
                task['parameters'],
                context
            )
            
            # 3. Get provider for protocol/method
            provider = await self.registry.get_provider_for_method(
                task['protocol'],
                task['method']
            )
            
            # 4. Execute with timeout
            result = await asyncio.wait_for(
                provider.handle_request(
                    task['method'],
                    resolved_params
                ),
                timeout=self.task_timeout
            )
            
            # 5. Save result
            task['status'] = 'completed'
            task['result'] = result
            await self.persistence.save_result(task['id'], result)
            
            # 6. Update context for parameter substitution
            context.results[task['id']] = result
            
            return result
            
        except asyncio.TimeoutError:
            task['status'] = 'timeout'
            raise TaskTimeout(f"Task {task['id']} timed out")
        
        except Exception as e:
            task['status'] = 'failed'
            task['error'] = str(e)
            raise
        
        finally:
            await self.persistence.save_task(task)
```

## Dependency Management

### Dependency Resolution

```python
class DependencyResolver:
    """Resolves task dependencies and determines execution order"""
    
    def resolve_dependencies(
        self,
        tasks: List[Dict[str, Any]]
    ) -> List[List[str]]:
        """
        Returns tasks in execution layers.
        Each layer can be executed in parallel.
        """
        
        # Build dependency graph
        graph = self._build_dependency_graph(tasks)
        
        # Check for cycles
        if self._has_cycles(graph):
            raise ValueError("Workflow contains dependency cycles")
        
        # Topological sort into layers
        layers = []
        completed = set()
        
        while len(completed) < len(tasks):
            layer = []
            
            for task in tasks:
                task_id = task['id']
                
                if task_id in completed:
                    continue
                
                # Check if all dependencies are completed
                deps = task.get('dependencies', [])
                if all(dep in completed for dep in deps):
                    layer.append(task_id)
            
            if not layer:
                raise ValueError("Unresolvable dependencies")
            
            layers.append(layer)
            completed.update(layer)
        
        return layers
```

### Parallel Execution

```python
async def execute_layer(
    self,
    layer: List[str],
    context: WorkflowContext
) -> Dict[str, Any]:
    """Execute all tasks in a layer in parallel"""
    
    # Create semaphore for parallelism control
    semaphore = asyncio.Semaphore(self.max_parallel_tasks)
    
    async def execute_with_limit(task_id: str):
        async with semaphore:
            task = context.get_task(task_id)
            return await self.execute_task(task, context)
    
    # Execute all tasks in parallel
    tasks = [execute_with_limit(task_id) for task_id in layer]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    layer_results = {}
    for task_id, result in zip(layer, results):
        if isinstance(result, Exception):
            # Handle failure
            await self._handle_task_failure(task_id, result, context)
        else:
            layer_results[task_id] = result
    
    return layer_results
```

## Parameter Substitution

### Substitution Syntax

```yaml
# Reference workflow parameters
${parameters.model}

# Reference task results
${task1.response}
${task1.result.data.value}

# Reference environment variables
${env.API_KEY}

# Reference workflow metadata
${workflow.name}
${workflow.id}

# Complex expressions
${task1.response || "default value"}
${task1.count * 2}
```

### Parameter Resolution

```python
class ParameterResolver:
    """Resolves parameter substitutions"""
    
    async def resolve_parameters(
        self,
        params: Any,
        context: WorkflowContext
    ) -> Any:
        """Recursively resolve all parameter substitutions"""
        
        if isinstance(params, str):
            return await self._resolve_string(params, context)
        
        elif isinstance(params, dict):
            resolved = {}
            for key, value in params.items():
                resolved[key] = await self.resolve_parameters(value, context)
            return resolved
        
        elif isinstance(params, list):
            return [
                await self.resolve_parameters(item, context)
                for item in params
            ]
        
        return params
    
    async def _resolve_string(
        self,
        value: str,
        context: WorkflowContext
    ) -> Any:
        """Resolve substitutions in a string"""
        
        # Find all substitution patterns
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, value)
        
        if not matches:
            return value
        
        # Single substitution - return actual type
        if len(matches) == 1 and value == f"${{{matches[0]}}}":
            return await self._resolve_reference(matches[0], context)
        
        # Multiple substitutions - string interpolation
        result = value
        for match in matches:
            resolved = await self._resolve_reference(match, context)
            result = result.replace(f"${{{match}}}", str(resolved))
        
        return result
    
    async def _resolve_reference(
        self,
        reference: str,
        context: WorkflowContext
    ) -> Any:
        """Resolve a single reference"""
        
        parts = reference.split('.')
        
        # Task result reference
        if parts[0] in context.results:
            return self._navigate_path(
                context.results[parts[0]],
                parts[1:]
            )
        
        # Workflow parameters
        elif parts[0] == 'parameters':
            return self._navigate_path(
                context.workflow.get('parameters', {}),
                parts[1:]
            )
        
        # Environment variables
        elif parts[0] == 'env':
            return os.environ.get(parts[1]) if len(parts) > 1 else None
        
        # Workflow metadata
        elif parts[0] == 'workflow':
            return self._navigate_path(
                context.workflow,
                parts[1:]
            )
        
        raise ValueError(f"Cannot resolve reference: {reference}")
```

## Workflow Types

### 1. Sequential Workflow

```yaml
name: "Sequential Processing"
tasks:
  - id: "step1"
    method: "process"
    
  - id: "step2"
    method: "transform"
    dependencies: ["step1"]
    
  - id: "step3"
    method: "finalize"
    dependencies: ["step2"]
```

### 2. Parallel Workflow

```yaml
name: "Parallel Processing"
tasks:
  - id: "parallel1"
    method: "process_a"
    
  - id: "parallel2"
    method: "process_b"
    
  - id: "parallel3"
    method: "process_c"
    
  - id: "combine"
    method: "merge"
    dependencies: ["parallel1", "parallel2", "parallel3"]
```

### 3. Batch Workflow

```yaml
name: "Batch Processing"
type: "batch"

batch:
  directory: "./data"
  pattern: "*.txt"
  max_parallel: 5

template:
  protocol: "llm/v1"
  method: "chat"
  parameters:
    model: "llama3.2"
    messages:
      - role: "user"
        content: "Summarize: ${file.content}"
```

### 4. Conditional Workflow

```yaml
name: "Conditional Processing"
tasks:
  - id: "check"
    method: "evaluate"
    
  - id: "path_a"
    method: "process_a"
    condition: "${check.result.score > 0.8}"
    dependencies: ["check"]
    
  - id: "path_b"
    method: "process_b"
    condition: "${check.result.score <= 0.8}"
    dependencies: ["check"]
```

## Error Handling

### Task Retry Strategy

```python
class RetryStrategy:
    """Configurable retry strategy for failed tasks"""
    
    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        max_backoff: int = 60
    ):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
    
    async def execute_with_retry(
        self,
        task_executor: Callable,
        task: Dict,
        context: WorkflowContext
    ) -> Any:
        """Execute task with retry logic"""
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return await task_executor(task, context)
            
            except (TaskTimeout, ProviderError) as e:
                last_error = e
                
                if attempt < self.max_retries - 1:
                    # Calculate backoff
                    wait_time = min(
                        self.backoff_factor ** attempt,
                        self.max_backoff
                    )
                    
                    logger.info(
                        f"Task {task['id']} failed (attempt {attempt + 1}), "
                        f"retrying in {wait_time}s"
                    )
                    
                    await asyncio.sleep(wait_time)
        
        # All retries exhausted
        raise TaskRetryExhausted(
            f"Task {task['id']} failed after {self.max_retries} attempts",
            last_error
        )
```

### Workflow Error Policies

```yaml
name: "Workflow with Error Handling"
error_policy: "continue"  # continue, fail_fast, retry

tasks:
  - id: "task1"
    method: "process"
    on_error: "skip"  # skip, retry, fail
    max_retries: 5
    
  - id: "task2"
    method: "transform"
    dependencies: ["task1"]
    on_error: "retry"
    retry_config:
      max_attempts: 3
      backoff: "exponential"
```

## Workflow Monitoring

### Real-time Status

```python
class WorkflowMonitor:
    """Monitor workflow execution in real-time"""
    
    async def get_workflow_status(
        self,
        workflow_id: str
    ) -> Dict[str, Any]:
        """Get current workflow status"""
        
        workflow = await self.persistence.get_workflow(workflow_id)
        tasks = await self.persistence.list_tasks(workflow_id)
        
        return {
            "workflow_id": workflow_id,
            "status": workflow['status'],
            "progress": {
                "total": len(tasks),
                "completed": len([t for t in tasks if t['status'] == 'completed']),
                "running": len([t for t in tasks if t['status'] == 'running']),
                "failed": len([t for t in tasks if t['status'] == 'failed'])
            },
            "tasks": [
                {
                    "id": task['id'],
                    "status": task['status'],
                    "duration": task.get('duration'),
                    "error": task.get('error')
                }
                for task in tasks
            ],
            "started_at": workflow.get('started_at'),
            "completed_at": workflow.get('completed_at'),
            "duration": workflow.get('duration')
        }
```

### Event Streaming

```python
class WorkflowEventStream:
    """Stream workflow events in real-time"""
    
    async def stream_events(
        self,
        workflow_id: str,
        callback: Callable
    ):
        """Stream events for a workflow"""
        
        # Subscribe to workflow events
        async for event in self.event_bus.subscribe(f"workflow:{workflow_id}"):
            await callback({
                "timestamp": datetime.now().isoformat(),
                "workflow_id": workflow_id,
                "event_type": event['type'],
                "data": event['data']
            })

# Usage
async def print_event(event):
    print(f"[{event['timestamp']}] {event['event_type']}: {event['data']}")

await stream.stream_events("wf-123", print_event)
```

## Advanced Features

### 1. Dynamic Task Generation

```python
class DynamicWorkflow:
    """Generate tasks dynamically during execution"""
    
    async def generate_tasks(
        self,
        config: Dict
    ) -> List[Dict]:
        """Generate tasks based on runtime conditions"""
        
        # Query data source
        items = await self.fetch_items(config['source'])
        
        # Generate task for each item
        tasks = []
        for i, item in enumerate(items):
            tasks.append({
                "id": f"process_{i}",
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {
                    "model": config['model'],
                    "messages": [
                        {"role": "user", "content": f"Process: {item}"}
                    ]
                }
            })
        
        # Add aggregation task
        tasks.append({
            "id": "aggregate",
            "protocol": "llm/v1",
            "method": "chat",
            "dependencies": [f"process_{i}" for i in range(len(items))],
            "parameters": {
                "model": config['model'],
                "messages": [
                    {"role": "user", "content": "Aggregate all results"}
                ]
            }
        })
        
        return tasks
```

### 2. Workflow Composition

```yaml
# Parent workflow
name: "Parent Workflow"
tasks:
  - id: "prepare"
    method: "setup"
    
  - id: "child_workflow"
    type: "workflow"
    workflow: "./child_workflow.yaml"
    dependencies: ["prepare"]
    parameters:
      input: "${prepare.result}"
    
  - id: "finalize"
    method: "cleanup"
    dependencies: ["child_workflow"]
```

### 3. Checkpointing

```python
class CheckpointManager:
    """Save and restore workflow state"""
    
    async def save_checkpoint(
        self,
        workflow_id: str,
        context: WorkflowContext
    ):
        """Save workflow checkpoint"""
        
        checkpoint = {
            "workflow_id": workflow_id,
            "timestamp": datetime.now().isoformat(),
            "completed_tasks": list(context.completed_tasks),
            "results": context.results,
            "state": context.state
        }
        
        await self.persistence.save_checkpoint(workflow_id, checkpoint)
    
    async def restore_from_checkpoint(
        self,
        workflow_id: str
    ) -> WorkflowContext:
        """Restore workflow from checkpoint"""
        
        checkpoint = await self.persistence.get_checkpoint(workflow_id)
        
        context = WorkflowContext(workflow_id=workflow_id)
        context.completed_tasks = set(checkpoint['completed_tasks'])
        context.results = checkpoint['results']
        context.state = checkpoint['state']
        
        return context
```

## Performance Optimization

### 1. Task Batching
```python
# Batch similar tasks for efficient execution
async def batch_execute_tasks(tasks: List[Dict]) -> List[Any]:
    # Group by provider
    grouped = {}
    for task in tasks:
        provider_id = task['protocol']
        if provider_id not in grouped:
            grouped[provider_id] = []
        grouped[provider_id].append(task)
    
    # Execute batches
    results = []
    for provider_id, batch in grouped.items():
        provider = await registry.get_provider(provider_id)
        batch_results = await provider.batch_execute(batch)
        results.extend(batch_results)
    
    return results
```

### 2. Resource Pre-allocation
```python
# Pre-allocate resources for workflow
async def preallocate_resources(workflow: Dict):
    # Analyze workflow requirements
    required_resources = analyze_resource_requirements(workflow)
    
    # Pre-allocate from hubs
    for resource_type, count in required_resources.items():
        hub = resource_manager.get_hub(resource_type)
        await hub.preallocate(count)
```

### 3. Result Caching
```python
# Cache task results for reuse
class ResultCache:
    async def get_or_execute(self, task: Dict, executor: Callable):
        cache_key = self.generate_cache_key(task)
        
        # Check cache
        cached = await self.persistence.get_cached_result(cache_key)
        if cached and not self.is_expired(cached):
            return cached['result']
        
        # Execute and cache
        result = await executor(task)
        await self.persistence.cache_result(cache_key, result, ttl=3600)
        return result
```

## CLI Usage

### Submit Workflow
```bash
# Submit workflow from file
gleitzeit workflow submit workflow.yaml

# Submit with parameters
gleitzeit workflow submit workflow.yaml \
  --param model=llama3.2 \
  --param temperature=0.8

# Submit and wait for completion
gleitzeit workflow submit workflow.yaml --wait
```

### Monitor Workflow
```bash
# Get workflow status
gleitzeit workflow status wf-123

# Watch workflow progress
gleitzeit workflow watch wf-123

# Get workflow logs
gleitzeit workflow logs wf-123

# Get task details
gleitzeit task status task-456
```

### Manage Workflows
```bash
# List workflows
gleitzeit workflow list
gleitzeit workflow list --status running

# Cancel workflow
gleitzeit workflow cancel wf-123

# Retry failed workflow
gleitzeit workflow retry wf-123

# Export workflow results
gleitzeit workflow export wf-123 --format json > results.json
```

## Python API Usage

```python
from gleitzeit import GleitzeitClient

async def run_workflow_example():
    # Create client
    async with GleitzeitClient() as client:
        
        # Submit workflow
        workflow_id = await client.submit_workflow("workflow.yaml")
        
        # Monitor progress
        while True:
            status = await client.get_workflow_status(workflow_id)
            print(f"Progress: {status['progress']}")
            
            if status['status'] in ['completed', 'failed']:
                break
            
            await asyncio.sleep(5)
        
        # Get results
        if status['status'] == 'completed':
            results = await client.get_workflow_results(workflow_id)
            print("Results:", results)
        else:
            errors = await client.get_workflow_errors(workflow_id)
            print("Errors:", errors)

# Run
asyncio.run(run_workflow_example())
```

## Summary

Workflow execution in Gleitzeit v0.0.5 provides:
- **DAG-based orchestration** with dependency management
- **Parallel execution** for independent tasks
- **Parameter substitution** for result chaining
- **Comprehensive error handling** with retry strategies
- **Real-time monitoring** and event streaming
- **Performance optimization** through batching and caching

The system is designed to handle complex workflows efficiently while maintaining simplicity for basic use cases.