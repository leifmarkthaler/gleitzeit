# WorkflowHandler Revised Implementation Plan

## Architecture Audit Summary

### Current Gleitzeit Architecture
1. **Redis Cluster with Hash-Tag Based Sharding**
   - All keys use hash tags like `{shard:N}` for routing
   - 16 logical shards mapped to Redis Cluster's 16384 slots
   - Workflow locality enforced - all workflow data on same node

2. **Handler Architecture**
   - Handlers register via `@HandlerRegistry.register` decorator
   - Stateless handlers return metadata, not direct results
   - Workers handle actual execution and state management

3. **Worker Patterns**
   - Workers inherit from `BaseWorker`
   - Use `get_base_streams()` to define monitored streams
   - Process messages via `process_message()`
   - Each worker instance handles specific shards

### Key Constraints for WorkflowHandler
1. **Cross-shard operations are limited** - Can't use multi-key operations across shards
2. **Global registry needs careful design** - Must work within hash-tag routing
3. **Stream-based communication** - Workers monitor streams, not polling
4. **Eventual consistency** - Cross-shard updates are async

## Revised WorkflowHandler Design

### CRITICAL: Stateless Design Pattern

The WorkflowHandler follows the same stateless pattern as SignalHandler:
1. **Handler NEVER accesses Redis or external state**
2. **Handler returns metadata in TaskResult**
3. **Workers handle actual work based on metadata**
4. **Similar to signal/send returning emit_signal flag**

### Phase 1: Core Handler Implementation

```python
# src/gleitzeit/handlers/workflow.py

from typing import Dict, Any, Optional
from ..handlers.base import BaseHandler
from ..handlers.registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.sharding import default_sharding
import uuid
import json

@HandlerRegistry.register
class WorkflowHandler(BaseHandler):
    """
    Handle workflow invocation as tasks.
    
    Enables workflows to call other workflows, potentially on different shards.
    Works within Redis Cluster constraints using hash-tag based routing.
    """
    
    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        return {
            'protocol': 'workflow/v1',
            'task_types': ['workflow', 'subworkflow'],
            'methods': {
                'workflow/execute': {
                    'description': 'Execute a workflow and wait for completion',
                    'required': ['workflow_ref'],
                    'optional': ['inputs', 'timeout', 'shard_preference']
                },
                'workflow/execute_async': {
                    'description': 'Start workflow without waiting',
                    'required': ['workflow_ref'],
                    'optional': ['inputs', 'callback']
                },
                'workflow/status': {
                    'description': 'Check status of child workflow',
                    'required': ['child_workflow_id']
                }
            }
        }
    
    async def execute(self, task: Task) -> TaskResult:
        """Execute workflow task"""
        method = task.method
        
        if method == 'workflow/execute':
            return await self._handle_execute(task)
        elif method == 'workflow/execute_async':
            return await self._handle_execute_async(task)
        elif method == 'workflow/status':
            return await self._handle_status(task)
        else:
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=f"Unknown method: {method}"
            )
    
    async def _handle_execute(self, task: Task) -> TaskResult:
        """Execute and wait for sub-workflow"""
        
        # 1. Generate child workflow ID
        child_workflow_id = f"{task.workflow_id}:child:{uuid.uuid4().hex[:8]}"
        
        # 2. Determine target shard
        shard_preference = task.params.get('shard_preference', 'any')
        target_shard = self._determine_shard(shard_preference, child_workflow_id)
        
        # 3. Return WAITING status with metadata
        # The actual submission happens in the worker based on metadata
        return self.create_result(
            task=task,
            status=TaskStatus.WAITING,
            metadata={
                'waiting_for': 'workflow',
                'child_workflow_id': child_workflow_id,
                'child_shard': target_shard,
                'workflow_ref': task.params.get('workflow_ref'),
                'workflow_definition': task.params.get('workflow_definition'),
                'workflow_inputs': task.params.get('inputs', {}),
                'parent_workflow_id': task.workflow_id,
                'parent_task_id': task.id,
                'submit_workflow': True  # Flag for worker to handle submission
            }
        )
    
    def _determine_shard(self, preference: str, workflow_id: str) -> int:
        """Determine target shard for child workflow"""
        if preference == 'same':
            # Use same shard as parent
            return default_sharding.get_shard(workflow_id)
        elif preference.startswith('specific:'):
            # Use specified shard
            return int(preference.split(':')[1])
        else:
            # Let sharding strategy decide
            return default_sharding.get_shard(workflow_id)
```

### Phase 2: Workflow Submission Worker

```python
# src/gleitzeit/workers/workflow_submission_worker.py

from typing import Dict, List
from .base import BaseWorker
from ..core.sharding import default_sharding
from ..core.models import WorkflowSubmission
import json
import logging

logger = logging.getLogger(__name__)

class WorkflowSubmissionWorker(BaseWorker):
    """
    Handle cross-shard workflow submissions.
    
    Monitors for tasks waiting on workflows and submits them to appropriate shards.
    Uses Redis Cluster hash-tag routing for proper key distribution.
    """
    
    def get_base_streams(self) -> List[str]:
        """Monitor workflow submission stream"""
        return ["workflow:submit"]
    
    async def process_message(self, stream: str, message_id: str, data: Dict):
        """Process workflow submission request"""
        
        child_workflow_id = data[b'child_workflow_id'].decode()
        parent_workflow_id = data[b'parent_workflow_id'].decode()
        parent_task_id = data[b'parent_task_id'].decode()
        workflow_ref = data[b'workflow_ref'].decode()
        inputs = json.loads(data.get(b'inputs', b'{}'))
        target_shard = int(data[b'target_shard'])
        
        # 1. Register parent-child relationship in global registry
        # Use shard 0 for global registry (consistent location)
        registry_key = default_sharding.get_global_key(f"workflow:children:{child_workflow_id}")
        
        await self.redis.hset(
            registry_key,
            mapping={
                b'parent_workflow_id': parent_workflow_id.encode(),
                b'parent_task_id': parent_task_id.encode(),
                b'parent_shard': str(default_sharding.get_shard(parent_workflow_id)).encode(),
                b'child_shard': str(target_shard).encode(),
                b'status': b'pending',
                b'created_at': data.get(b'timestamp', b'')
            }
        )
        
        # 2. Add to parent's children set
        parent_children_key = default_sharding.get_workflow_key("children", parent_workflow_id)
        await self.redis.sadd(parent_children_key, child_workflow_id)
        
        # 3. Submit workflow to target shard
        submission_stream = default_sharding.get_stream_key("workflow:loader", shard=target_shard)
        
        await self.redis.xadd(
            submission_stream,
            {
                b'workflow_id': child_workflow_id.encode(),
                b'workflow_ref': workflow_ref.encode(),
                b'inputs': json.dumps(inputs).encode(),
                b'parent_workflow_id': parent_workflow_id.encode(),
                b'parent_task_id': parent_task_id.encode(),
                b'is_child': b'true'
            }
        )
        
        logger.info(
            f"Submitted child workflow {child_workflow_id} to shard {target_shard} "
            f"for parent {parent_workflow_id}"
        )
```

### Phase 3: Workflow Monitor Worker

```python
# src/gleitzeit/workers/workflow_monitor_worker.py

from typing import Dict, List
from .base import BaseWorker
from ..core.sharding import default_sharding
from ..core.models import TaskStatus
import json
import logging

logger = logging.getLogger(__name__)

class WorkflowMonitorWorker(BaseWorker):
    """
    Monitor cross-shard workflow completions.
    
    Uses global registry on shard 0 and stream-based notifications.
    """
    
    def get_base_streams(self) -> List[str]:
        """Monitor workflow completion notifications"""
        # Monitor both local and global completion streams
        return [
            "workflow:completed",  # Local completions
            "workflow:child:completed"  # Cross-shard notifications
        ]
    
    async def process_message(self, stream: str, message_id: str, data: Dict):
        """Process workflow completion notification"""
        
        if stream.endswith("workflow:completed"):
            # Local workflow completion
            await self._handle_local_completion(data)
        else:
            # Cross-shard child completion
            await self._handle_child_completion(data)
    
    async def _handle_local_completion(self, data: Dict):
        """Handle completion of workflow on this shard"""
        
        workflow_id = data[b'workflow_id'].decode()
        result = json.loads(data.get(b'result', b'{}'))
        status = data.get(b'status', b'completed').decode()
        
        # Check if this is a child workflow
        registry_key = default_sharding.get_global_key(f"workflow:children:{workflow_id}")
        child_info = await self.redis.hgetall(registry_key)
        
        if child_info:
            # This is a child workflow - notify parent
            parent_workflow_id = child_info[b'parent_workflow_id'].decode()
            parent_task_id = child_info[b'parent_task_id'].decode()
            parent_shard = int(child_info[b'parent_shard'])
            
            # Update registry
            await self.redis.hset(
                registry_key,
                mapping={
                    b'status': status.encode(),
                    b'result': json.dumps(result).encode(),
                    b'completed_at': data.get(b'timestamp', b'')
                }
            )
            
            if parent_shard == self.shard:
                # Parent is on this shard - wake it directly
                await self._wake_parent_task(parent_workflow_id, parent_task_id, result)
            else:
                # Parent is on different shard - send notification
                notification_stream = default_sharding.get_stream_key(
                    "workflow:child:completed",
                    shard=parent_shard
                )
                
                await self.redis.xadd(
                    notification_stream,
                    {
                        b'child_workflow_id': workflow_id.encode(),
                        b'parent_workflow_id': parent_workflow_id.encode(),
                        b'parent_task_id': parent_task_id.encode(),
                        b'result': json.dumps(result).encode(),
                        b'status': status.encode()
                    }
                )
    
    async def _handle_child_completion(self, data: Dict):
        """Handle notification of child workflow completion"""
        
        parent_workflow_id = data[b'parent_workflow_id'].decode()
        parent_task_id = data[b'parent_task_id'].decode()
        result = json.loads(data.get(b'result', b'{}'))
        
        # Wake parent task with result
        await self._wake_parent_task(parent_workflow_id, parent_task_id, result)
    
    async def _wake_parent_task(self, workflow_id: str, task_id: str, result: Dict):
        """Wake a waiting parent task with child result"""
        
        # Update task status
        task_key = default_sharding.get_task_key(task_id, workflow_id)
        
        await self.redis.hset(
            task_key,
            mapping={
                b'status': TaskStatus.READY.value.encode(),
                b'result': json.dumps(result).encode(),
                b'waiting_cleared': b'true'
            }
        )
        
        # Add to ready queue
        ready_stream = default_sharding.get_stream_key("task:ready", workflow_id)
        await self.redis.xadd(
            ready_stream,
            {
                b'task_id': task_id.encode(),
                b'workflow_id': workflow_id.encode(),
                b'priority': b'0',
                b'resumed_from': b'workflow_wait'
            }
        )
        
        logger.info(f"Woke parent task {task_id} with child workflow result")
```

### Phase 4: Integration with TaskExecutionWorker

The TaskExecutionWorker handles the metadata flags similar to how it handles signal emissions:

```python
# Modification to TaskExecutionWorker to handle workflow waiting

class TaskExecutionWorker(BaseWorker):

    async def _handle_task_result(self, task: Task, result: TaskResult):
        """Handle task result based on status and metadata"""

        # Check for workflow submission flag (like emit_signal)
        if result.metadata and result.metadata.get('submit_workflow'):
            await self._submit_child_workflow(task, result.metadata)

        # Check for signal emission flag (existing)
        if result.metadata and result.metadata.get('emit_signal'):
            await self._emit_signal(task, result.metadata)

        # Handle WAITING status
        if result.status == TaskStatus.WAITING:
            await self._handle_waiting_task(task, result)
    
    async def _submit_child_workflow(self, task: Task, metadata: Dict):
        """Submit child workflow for execution"""
        
        submission_stream = default_sharding.get_stream_key(
            "workflow:submit",
            task.workflow_id
        )
        
        await self.redis.xadd(
            submission_stream,
            {
                b'child_workflow_id': metadata['child_workflow_id'].encode(),
                b'parent_workflow_id': metadata['parent_workflow_id'].encode(),
                b'parent_task_id': task.id.encode(),
                b'workflow_ref': metadata['workflow_ref'].encode(),
                b'inputs': json.dumps(metadata.get('workflow_inputs', {})).encode(),
                b'target_shard': str(metadata['child_shard']).encode(),
                b'timestamp': datetime.utcnow().isoformat().encode()
            }
        )
```

## Key Design Changes from Original

### 0. Stateless Handler Pattern (MOST IMPORTANT)
- **Handler NEVER touches Redis** - only returns metadata
- **Workers do all the work** - based on metadata flags
- **Similar to SignalHandler** - returns emit_signal flag
- **Maintains handler purity** - handlers are computation only

### 1. Redis Cluster Compatibility
- **All keys use hash tags** for proper routing
- **Global registry on shard 0** using `get_global_key()`
- **Stream-based communication** instead of direct key access

### 2. Worker-Based Architecture
- **WorkflowSubmissionWorker** handles cross-shard submissions
- **WorkflowMonitorWorker** monitors completions
- **Stream processing** instead of polling

### 3. Eventual Consistency
- **Async notifications** for cross-shard updates
- **Registry updates** are eventually consistent
- **Parent waking** via streams

### 4. Simplified Handler
- **Handler returns metadata** not results
- **Workers do the actual work** based on metadata
- **Stateless design** aligns with existing handlers

## Implementation Timeline

| Week | Phase | Tasks |
|------|-------|-------|
| 1 | Handler & Registry | Implement WorkflowHandler, global registry design |
| 2 | Submission Worker | Create WorkflowSubmissionWorker for cross-shard submission |
| 3 | Monitor Worker | Create WorkflowMonitorWorker for completion tracking |
| 4 | Integration | Integrate with TaskExecutionWorker, test cross-shard |
| 5 | Testing | Comprehensive testing, edge cases |
| 6 | Documentation | Examples, best practices, performance tuning |

## Testing Strategy

### Unit Tests
```python
# tests/test_workflow_handler.py

async def test_workflow_handler_metadata():
    """Test handler returns correct metadata"""
    handler = WorkflowHandler()
    task = Task(
        id="test-task",
        workflow_id="parent-wf",
        method="workflow/execute",
        params={"workflow_ref": "test.yaml"}
    )
    
    result = await handler.execute(task)
    assert result.status == TaskStatus.WAITING
    assert result.metadata['waiting_for'] == 'workflow'

async def test_shard_determination():
    """Test shard selection strategies"""
    # Test 'same', 'any', 'specific:N' preferences

async def test_cross_shard_submission():
    """Test workflow submission to different shard"""
    # Mock Redis operations
    # Verify correct streams and keys used
```

### Integration Tests
```python
# tests/test_workflow_integration.py

async def test_parent_child_workflow():
    """Test full parent-child workflow execution"""
    # Submit parent workflow
    # Verify child submission
    # Simulate child completion
    # Verify parent wakes with result

async def test_multi_shard_workflow():
    """Test workflows across multiple shards"""
    # Force different shards
    # Verify cross-shard communication
```

## Configuration

```yaml
# gleitzeit.yaml
workflow_handler:
  enabled: true
  max_depth: 10
  default_timeout: 3600
  
workers:
  workflow_submission:
    enabled: true
    batch_size: 10
    
  workflow_monitor:
    enabled: true
    check_interval: 5
```

## Benefits of Revised Design

1. **Redis Cluster Native**: Works perfectly with hash-tag routing
2. **Stream-Based**: Aligns with existing worker patterns
3. **Scalable**: Can handle thousands of concurrent workflows
4. **Fault-Tolerant**: Registry persists across restarts
5. **Observable**: Clear event streams for monitoring
6. **Simple**: Follows existing Gleitzeit patterns

## Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| Registry on shard 0 bottleneck | Use batching, consider sharded registry |
| Stream message loss | Use consumer groups with ACK |
| Orphaned workflows | Periodic cleanup worker |
| Circular dependencies | Pre-execution validation |