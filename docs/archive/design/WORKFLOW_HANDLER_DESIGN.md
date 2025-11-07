# Workflow Handler Design Document

## Overview

The WorkflowHandler enables workflows to invoke other workflows as tasks, creating composable, reusable workflow patterns. Unlike regular tasks, sub-workflows can run on different shards, enabling true distributed execution.

## Core Concepts

### 1. Workflow as a Task
A workflow task represents an entire workflow execution that:
- Can run on any shard (not restricted to parent's shard)
- Has its own workflow ID and execution context
- Returns a result like any other task
- Can be awaited, retried, and timed out

### 2. Cross-Shard Coordination
Since sub-workflows may run on different shards, we need:
- Global workflow registry
- Cross-shard result propagation
- Status monitoring across shards
- Proper cleanup on failure

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Parent Workflow (Shard A)               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │   workflow_task_1 → WorkflowHandler                  │  │
│  │     ↓                                                │  │
│  │   Submits child workflow to appropriate shard        │  │
│  │     ↓                                                │  │
│  │   Monitors via global registry                       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │        Global Workflow Registry         │
         │   (Redis keys not shard-specific)       │
         │                                         │
         │  workflow:registry:{child_id}           │
         │    - parent_workflow_id                 │
         │    - parent_task_id                     │
         │    - status                             │
         │    - result                             │
         │    - shard                              │
         └────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   Child Workflow (Shard B)                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │   Executes independently                             │  │
│  │   Updates global registry on completion              │  │
│  │   Publishes result to parent's result stream         │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Design

### WorkflowHandler Class

```python
from gleitzeit.handlers.base import BaseHandler
from gleitzeit.handlers.registry import HandlerRegistry
from gleitzeit.core.models import Task, TaskResult, TaskStatus
import uuid
import json

@HandlerRegistry.register
class WorkflowHandler(BaseHandler):
    """
    Handle workflow invocation as tasks.

    Enables workflows to call other workflows, potentially on different shards.
    """

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        return {
            'protocol': 'workflow/v1',
            'task_types': ['workflow', 'subworkflow', 'nested'],
            'methods': {
                'workflow/execute': {
                    'description': 'Execute a workflow',
                    'required': ['workflow_ref'],  # or workflow_definition
                    'optional': ['inputs', 'timeout', 'shard_preference']
                },
                'workflow/execute_async': {
                    'description': 'Start workflow without waiting',
                    'required': ['workflow_ref'],
                    'optional': ['inputs', 'callback']
                },
                'workflow/wait': {
                    'description': 'Wait for external workflow',
                    'required': ['workflow_id'],
                    'optional': ['timeout']
                }
            }
        }

    async def execute(self, task: Task) -> TaskResult:
        """Execute workflow task"""
        if task.method == 'workflow/execute':
            return await self._handle_execute(task)
        elif task.method == 'workflow/execute_async':
            return await self._handle_execute_async(task)
        elif task.method == 'workflow/wait':
            return await self._handle_wait(task)

    async def _handle_execute(self, task: Task) -> TaskResult:
        """Execute and wait for sub-workflow"""

        # 1. Generate child workflow ID
        child_workflow_id = f"{task.workflow_id}:child:{task.id}:{uuid.uuid4().hex[:8]}"

        # 2. Prepare workflow
        workflow = await self._prepare_workflow(task)

        # 3. Determine target shard
        shard = self._determine_shard(task, child_workflow_id)

        # 4. Register parent-child relationship
        await self._register_relationship(
            parent_workflow_id=task.workflow_id,
            parent_task_id=task.id,
            child_workflow_id=child_workflow_id,
            shard=shard
        )

        # 5. Submit workflow to target shard
        await self._submit_workflow(child_workflow_id, workflow, shard)

        # 6. Return WAITING status with monitoring info
        return self.create_result(
            task=task,
            status=TaskStatus.WAITING,
            metadata={
                'waiting_for': 'workflow',
                'child_workflow_id': child_workflow_id,
                'child_shard': shard,
                'monitor_type': 'cross_shard'
            }
        )
```

### Cross-Shard Monitoring (WorkflowMonitorWorker)

```python
class WorkflowMonitorWorker(BaseWorker):
    """
    Monitor cross-shard workflow executions.

    Runs on all shards and monitors workflows that have children on other shards.
    """

    async def monitor_child_workflows(self):
        """Monitor child workflows across shards"""

        # Get all waiting workflow tasks on this shard
        waiting_tasks = await self.get_waiting_workflow_tasks()

        for task_info in waiting_tasks:
            child_workflow_id = task_info['child_workflow_id']

            # Check global registry (not shard-specific)
            status = await self.redis.hget(
                f"workflow:registry:{child_workflow_id}",
                "status"
            )

            if status == b"completed":
                # Get result from global registry
                result = await self.redis.hget(
                    f"workflow:registry:{child_workflow_id}",
                    "result"
                )

                # Wake up parent task
                await self._wake_parent_task(
                    task_info['parent_task_id'],
                    task_info['parent_workflow_id'],
                    json.loads(result)
                )

            elif status == b"failed":
                # Handle failure
                error = await self.redis.hget(
                    f"workflow:registry:{child_workflow_id}",
                    "error"
                )

                await self._fail_parent_task(
                    task_info['parent_task_id'],
                    task_info['parent_workflow_id'],
                    error.decode()
                )
```

## Workflow Task Definition

### YAML Format

```yaml
tasks:
  # Execute another workflow and wait for result
  - id: run_etl
    type: workflow
    method: workflow/execute
    params:
      workflow_ref: "etl/data-pipeline.yaml"  # File reference
      inputs:
        source: "database"
        date: "2024-01-01"
      timeout: 3600
      shard_preference: "any"  # or "same", "specific:2"

  # Use result from sub-workflow
  - id: process_etl_result
    type: python
    code: |
      etl_result = inputs.get('run_etl')
      print(f"ETL processed {etl_result['records']} records")
    dependencies: [run_etl]

  # Execute inline workflow
  - id: run_inline
    type: workflow
    method: workflow/execute
    params:
      workflow_definition:
        name: "inline-processor"
        tasks:
          - id: step1
            type: python
            code: "result = {'done': True}"
      inputs:
        param1: "value1"

  # Fire-and-forget workflow
  - id: async_job
    type: workflow
    method: workflow/execute_async
    params:
      workflow_ref: "jobs/background-job.yaml"
      inputs:
        job_type: "cleanup"
      callback:  # Optional callback when done
        signal: "job-complete"
```

## Key Features

### 1. Shard Distribution Strategies

```python
class ShardStrategy(Enum):
    ANY = "any"              # Let system choose optimal shard
    SAME = "same"            # Run on same shard as parent
    SPECIFIC = "specific"    # Run on specific shard
    LEAST_LOADED = "least"   # Run on least loaded shard
    HASH = "hash"            # Hash-based shard selection
```

### 2. Result Propagation

```python
# Child workflow completion handler
async def on_workflow_complete(child_workflow_id: str, result: Dict):
    # 1. Update global registry
    await redis.hset(
        f"workflow:registry:{child_workflow_id}",
        mapping={
            "status": "completed",
            "result": json.dumps(result),
            "completed_at": datetime.utcnow().isoformat()
        }
    )

    # 2. Get parent info
    parent_info = await redis.hgetall(f"workflow:registry:{child_workflow_id}")

    if parent_info.get(b"parent_workflow_id"):
        # 3. Emit to parent's shard
        parent_shard = get_shard(parent_info[b"parent_workflow_id"])

        await redis.xadd(
            f"{{shard:{parent_shard}}}:workflow:child:completed",
            {
                b"parent_workflow_id": parent_info[b"parent_workflow_id"],
                b"parent_task_id": parent_info[b"parent_task_id"],
                b"child_workflow_id": child_workflow_id.encode(),
                b"result": json.dumps(result).encode()
            }
        )
```

### 3. Failure Handling

```python
class WorkflowTaskFailureHandler:
    """Handle failures in workflow tasks"""

    async def handle_child_failure(self, child_workflow_id: str, error: str):
        # Options for parent workflow:

        # 1. Fail parent task (default)
        await self.fail_parent_task(error)

        # 2. Retry with different parameters
        if self.should_retry():
            await self.retry_with_backoff()

        # 3. Fallback to alternative workflow
        if self.has_fallback():
            await self.execute_fallback_workflow()

        # 4. Partial success (if multiple children)
        if self.allows_partial_success():
            await self.continue_with_partial_results()
```

## Advanced Patterns

### 1. Workflow Composition

```yaml
# Master workflow that orchestrates multiple sub-workflows
tasks:
  # Parallel workflow execution
  - id: ingest_workflow
    type: workflow
    method: workflow/execute
    params:
      workflow_ref: "pipelines/ingest.yaml"
      shard_preference: "specific:1"

  - id: validate_workflow
    type: workflow
    method: workflow/execute
    params:
      workflow_ref: "pipelines/validate.yaml"
      shard_preference: "specific:2"

  # Wait for both
  - id: combine_results
    type: python
    dependencies: [ingest_workflow, validate_workflow]
```

### 2. Dynamic Workflow Generation

```yaml
tasks:
  - id: generate_workflows
    type: python
    code: |
      # Generate multiple workflow definitions based on data
      workflows = []
      for region in ['us', 'eu', 'asia']:
          workflows.append({
              'name': f'process-{region}',
              'tasks': [...]
          })
      result = {'workflows': workflows}

  - id: execute_generated
    type: workflow
    method: workflow/execute
    params:
      workflow_definition: "{{ inputs.generate_workflows.workflows[0] }}"
    dependencies: [generate_workflows]
```

### 3. Recursive Workflows

```yaml
tasks:
  - id: recursive_processor
    type: workflow
    method: workflow/execute
    params:
      workflow_ref: "self"  # Reference to same workflow
      inputs:
        depth: "{{ inputs.depth - 1 }}"
      when: "{{ inputs.depth > 0 }}"  # Conditional execution
```

## Implementation Considerations

### 1. Security
- Workflow access control (who can execute which workflows)
- Input/output sanitization
- Resource limits per workflow
- Prevent infinite recursion

### 2. Performance
- Workflow result caching
- Shard load balancing
- Connection pooling for cross-shard communication
- Lazy loading of workflow definitions

### 3. Monitoring
- Parent-child workflow tracing
- Cross-shard execution visualization
- Performance metrics aggregation
- Dependency graph generation

### 4. Error Recovery
- Orphaned workflow cleanup
- Timeout propagation
- Cascading failure prevention
- State reconciliation after network partitions

## Benefits

1. **Modularity**: Break complex workflows into reusable components
2. **Scalability**: Distribute workflow execution across shards
3. **Maintainability**: Update sub-workflows without changing parents
4. **Testing**: Test workflows in isolation
5. **Versioning**: Version workflows independently
6. **Resource Isolation**: Run heavy workflows on dedicated shards

## Migration Path

```python
# Phase 1: Basic workflow execution (same shard)
# Phase 2: Cross-shard execution with monitoring
# Phase 3: Advanced features (caching, optimization)
# Phase 4: Full workflow composition framework
```

## Example Use Cases

1. **ETL Pipelines**: Compose extraction, transformation, and loading workflows
2. **CI/CD**: Orchestrate build, test, and deployment workflows
3. **Data Processing**: Chain data processing workflows with different resource requirements
4. **Microservice Orchestration**: Coordinate workflows across service boundaries
5. **Batch Processing**: Distribute batch jobs across shards for parallel processing