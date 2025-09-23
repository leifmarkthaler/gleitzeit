# Workflow Handler Implementation Plan

## Phase 1: Basic Infrastructure (Week 1)

### 1.1 WorkflowHandler Base Implementation
```python
# src/gleitzeit/handlers/workflow.py

@HandlerRegistry.register
class WorkflowHandler(BaseHandler):
    """Execute workflows as tasks"""

    async def validate(self, task: Task) -> None:
        """Validate workflow task parameters"""
        # Check workflow_ref or workflow_definition exists
        # Validate inputs match expected schema
        # Check for circular dependencies

    async def execute(self, task: Task) -> TaskResult:
        """Submit workflow and return WAITING status"""
        # Generate child workflow ID
        # Register parent-child relationship
        # Submit to appropriate shard
        # Return WAITING with monitoring metadata
```

### 1.2 Global Registry Schema
```python
# Redis keys for cross-shard coordination

# Parent-child registry
workflow:registry:{child_id} = {
    "parent_workflow_id": "...",
    "parent_task_id": "...",
    "child_shard": 0,
    "status": "running|completed|failed",
    "result": {...},
    "error": "...",
    "created_at": "...",
    "completed_at": "..."
}

# Reverse lookup for cleanup
workflow:children:{parent_id} = SET of child_ids

# Workflow definitions cache
workflow:definitions:{ref} = {
    "definition": {...},
    "version": "1.0",
    "cached_at": "..."
}
```

## Phase 2: Cross-Shard Monitoring (Week 2)

### 2.1 WorkflowMonitorWorker
```python
# src/gleitzeit/workers/workflow_monitor_worker.py

class WorkflowMonitorWorker(BaseWorker):
    """Monitor cross-shard workflow executions"""

    def get_base_streams(self) -> List[str]:
        return ["workflow:child:status"]  # Global stream

    async def process_message(self, stream: str, message_id: str, data: Dict):
        """Process child workflow status updates"""

        if data['status'] == 'completed':
            await self.propagate_result_to_parent(data)
        elif data['status'] == 'failed':
            await self.handle_child_failure(data)
```

### 2.2 Result Propagation Protocol
```python
# Child workflow completion flow:
# 1. Child updates global registry
# 2. Child emits to global stream
# 3. Monitor worker on parent's shard picks up
# 4. Monitor wakes parent task with result

async def propagate_result_to_parent(self, child_data: Dict):
    parent_shard = get_shard(child_data['parent_workflow_id'])

    if parent_shard == self.shard:
        # We're on the right shard, wake the task
        await self.wake_parent_task(
            child_data['parent_task_id'],
            child_data['result']
        )
```

## Phase 3: Advanced Features (Week 3)

### 3.1 Shard Selection Strategies
```python
class ShardSelector:
    """Smart shard selection for workflow placement"""

    async def select_shard(self, strategy: str, context: Dict) -> int:
        if strategy == "least_loaded":
            return await self.get_least_loaded_shard()
        elif strategy == "affinity":
            return await self.get_affinity_shard(context)
        elif strategy == "round_robin":
            return self.next_round_robin_shard()
        else:  # "any"
            return random.choice(self.available_shards)

    async def get_least_loaded_shard(self) -> int:
        """Query shard metrics and select least loaded"""
        shard_loads = {}
        for shard in self.available_shards:
            load = await self.redis.get(f"shard:{shard}:load")
            shard_loads[shard] = int(load or 0)
        return min(shard_loads, key=shard_loads.get)
```

### 3.2 Workflow Caching
```python
class WorkflowCache:
    """Cache workflow definitions and results"""

    async def get_workflow_definition(self, ref: str) -> Dict:
        # Check cache first
        cached = await self.redis.get(f"workflow:cache:{ref}")
        if cached:
            return json.loads(cached)

        # Load from file/database
        definition = await self.load_workflow(ref)

        # Cache with TTL
        await self.redis.setex(
            f"workflow:cache:{ref}",
            3600,  # 1 hour TTL
            json.dumps(definition)
        )
        return definition

    async def cache_workflow_result(self, workflow_id: str, result: Dict):
        """Cache results for idempotency"""
        cache_key = self.get_cache_key(workflow_id)
        await self.redis.setex(
            cache_key,
            86400,  # 24 hour TTL
            json.dumps(result)
        )
```

## Phase 4: Safety & Reliability (Week 4)

### 4.1 Circular Dependency Detection
```python
class DependencyValidator:
    """Prevent circular workflow dependencies"""

    async def check_circular_dependency(
        self,
        parent_workflow_id: str,
        child_workflow_ref: str
    ) -> bool:
        """Check if child would create a cycle"""

        # Build dependency chain
        chain = await self.get_dependency_chain(parent_workflow_id)

        # Check if child is already in chain
        if child_workflow_ref in chain:
            raise CircularDependencyError(
                f"Workflow {child_workflow_ref} would create circular dependency"
            )

        # Check depth limit
        if len(chain) > self.MAX_DEPTH:
            raise MaxDepthExceededError(
                f"Workflow depth exceeds limit of {self.MAX_DEPTH}"
            )
```

### 4.2 Orphan Cleanup
```python
class OrphanCleaner:
    """Clean up orphaned child workflows"""

    async def cleanup_orphans(self):
        """Periodic cleanup of orphaned workflows"""

        # Get all parent-child relationships
        all_children = await self.redis.keys("workflow:registry:*")

        for child_key in all_children:
            child_data = await self.redis.hgetall(child_key)

            # Check if parent still exists
            parent_exists = await self.redis.exists(
                f"workflow:status:{child_data['parent_workflow_id']}"
            )

            if not parent_exists:
                # Parent is gone, clean up child
                await self.cleanup_orphan(child_data['child_workflow_id'])
```

## Phase 5: Testing & Validation

### 5.1 Unit Tests
```python
# tests/test_workflow_handler.py

async def test_workflow_execution():
    """Test basic workflow execution"""
    handler = WorkflowHandler()

    task = Task(
        id="test-wf-task",
        workflow_id="parent-wf",
        method="workflow/execute",
        params={
            "workflow_ref": "test/simple.yaml",
            "inputs": {"key": "value"}
        }
    )

    result = await handler.execute(task)
    assert result.status == TaskStatus.WAITING
    assert result.metadata['waiting_for'] == 'workflow'

async def test_cross_shard_execution():
    """Test workflow on different shard"""
    # Test shard selection
    # Test result propagation
    # Test failure handling
```

### 5.2 Integration Tests
```python
# tests/test_workflow_integration.py

async def test_nested_workflows():
    """Test workflows calling workflows"""
    # Parent → Child → Grandchild

async def test_parallel_child_workflows():
    """Test multiple child workflows in parallel"""

async def test_workflow_timeout():
    """Test timeout propagation to child"""

async def test_workflow_retry():
    """Test retry of failed child workflow"""
```

## Implementation Timeline

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1 | Basic Infrastructure | WorkflowHandler, Global Registry |
| 2 | Cross-Shard | Monitor Worker, Result Propagation |
| 3 | Advanced Features | Shard Selection, Caching |
| 4 | Safety | Circular Deps, Orphan Cleanup |
| 5 | Testing | Unit & Integration Tests |
| 6 | Documentation | User Guide, API Docs |

## Configuration

```yaml
# gleitzeit.yaml
workflow_handler:
  enabled: true
  max_depth: 10
  default_timeout: 3600
  cache_ttl: 3600
  shard_strategy: "least_loaded"

  # Safety limits
  max_children_per_workflow: 100
  max_concurrent_children: 10

  # Monitoring
  monitor_interval: 5  # seconds
  orphan_cleanup_interval: 300  # 5 minutes
```

## Success Metrics

1. **Functionality**
   - ✅ Execute workflows as tasks
   - ✅ Cross-shard execution
   - ✅ Result propagation
   - ✅ Error handling

2. **Performance**
   - Sub-second workflow submission
   - < 100ms result propagation latency
   - Support 1000+ concurrent child workflows

3. **Reliability**
   - No orphaned workflows
   - Proper timeout handling
   - Graceful failure recovery
   - No circular dependencies

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Circular dependencies | Pre-execution validation with chain tracking |
| Orphaned workflows | Periodic cleanup with parent checking |
| Resource exhaustion | Limits on depth and concurrent children |
| Network partitions | Eventually consistent global registry |
| Shard imbalance | Smart shard selection strategies |

## Next Steps

1. **Immediate**: Review design with team
2. **Week 1**: Implement core WorkflowHandler
3. **Week 2**: Add cross-shard monitoring
4. **Week 3**: Implement advanced features
5. **Week 4**: Add safety mechanisms
6. **Week 5**: Comprehensive testing
7. **Week 6**: Documentation and examples