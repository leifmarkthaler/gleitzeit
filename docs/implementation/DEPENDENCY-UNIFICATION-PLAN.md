# Dependency Management Unification Plan

## Current State Analysis

### We Have Two Systems:

1. **DependencyResolver** (`task_queue/dependency_resolver.py`)
   - **Storage**: In-memory (workflows, dependency_graphs) ❌ NOT STATELESS
   - **Used by**: WorkflowManager
   - **Key Methods**:
     - `add_workflow()` - Stores in memory
     - `validate_workflow_dependencies()` - Returns error list
     - `get_ready_tasks()` - Returns task IDs ready to run
     - `get_execution_order()` - Returns grouped execution levels

2. **UnifiedDependencyManager** (`core/dependency_manager.py`)
   - **Storage**: Mixed (in-memory cache + persistence) ⚠️ PARTIALLY STATELESS
   - **Used by**: TaskOrchestrator
   - **Key Methods**:
     - `validate_workflow()` - Returns bool, throws exceptions
     - `get_ready_tasks()` - Returns Task objects
     - `track_submission()` - Idempotency tracking
     - Has persistence backend reference

### Key Differences:

| Feature | DependencyResolver | UnifiedDependencyManager |
|---------|-------------------|-------------------------|
| Storage | Pure in-memory | Memory + Persistence |
| Stateless | ❌ No | ⚠️ Partial |
| Validation | Returns errors list | Throws exceptions |
| Ready tasks | Returns IDs | Returns Task objects |
| Idempotency | ❌ No | ✅ Yes |
| Persistence | ❌ No | ✅ Yes |

## Unified Stateless Solution

### Design Principles:

1. **No in-memory workflow storage** - Always use persistence
2. **Stateless operations** - Each method call is independent
3. **Consistent API** - Single interface for all components
4. **Backward compatible** - Support existing method signatures

### Proposed Architecture:

```python
class StatelessDependencyManager:
    """
    Fully stateless dependency manager using persistence for all state.
    
    Combines functionality from both existing systems while maintaining
    statelessness for horizontal scalability.
    """
    
    def __init__(self, persistence: PersistenceBackend):
        self.persistence = persistence
        # No in-memory state!
    
    async def validate_workflow(self, workflow: Workflow) -> List[str]:
        """
        Validate workflow and return errors (if any).
        Compatible with both validation styles.
        """
        # Build graph on-demand (no storage)
        graph = self._build_dependency_graph(workflow)
        errors = []
        
        # Check circular dependencies
        cycles = self._detect_cycles(graph)
        if cycles:
            errors.append(f"Circular dependency: {' -> '.join(cycles[0])}")
        
        # Check missing dependencies
        for node in graph.values():
            for dep_id in node.dependencies:
                if dep_id not in graph:
                    errors.append(f"Task {node.task_id} depends on non-existent {dep_id}")
        
        return errors  # Empty list means valid
    
    async def get_ready_tasks(
        self, 
        workflow_id: str,
        return_objects: bool = True
    ) -> Union[List[Task], List[str]]:
        """
        Get ready tasks from persistence.
        
        Args:
            workflow_id: Workflow to check
            return_objects: If True, return Task objects; if False, return IDs
        """
        # Load workflow from persistence
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return []
        
        # Load task statuses from persistence
        completed_tasks = await self.persistence.get_completed_task_ids(workflow_id)
        failed_tasks = await self.persistence.get_failed_task_ids(workflow_id)
        
        # Build graph on-demand
        graph = self._build_dependency_graph(workflow)
        
        # Find ready tasks
        ready = []
        for task_id, node in graph.items():
            if task_id in completed_tasks or task_id in failed_tasks:
                continue
            
            # Check if all dependencies are complete
            if all(dep_id in completed_tasks for dep_id in node.dependencies):
                if return_objects:
                    ready.append(node.task)
                else:
                    ready.append(task_id)
        
        return ready
```

## Implementation Plan

### Phase 1: Create Adapter (Immediate)

Create an adapter that makes UnifiedDependencyManager work with both interfaces:

```python
# src/gleitzeit/core/dependency_adapter.py
class DependencyAdapter:
    """Adapter to make UnifiedDependencyManager compatible with DependencyResolver interface."""
    
    def __init__(self, unified_manager: UnifiedDependencyManager):
        self.manager = unified_manager
    
    async def validate_workflow_dependencies(self, workflow: Workflow) -> List[str]:
        """Adapt validate_workflow to return error list instead of throwing."""
        try:
            await self.manager.validate_workflow(workflow)
            return []  # No errors
        except CircularDependencyError as e:
            return [str(e)]
        except ValueError as e:
            return [str(e)]
        except Exception as e:
            return [f"Validation error: {e}"]
    
    def add_workflow(self, workflow: Workflow):
        """No-op for compatibility - UnifiedDependencyManager validates on-demand."""
        pass
```

### Phase 2: Wire Everything Together (Immediate)

```python
# In SystemManager._start_core_components()
from ..core.dependency_manager import UnifiedDependencyManager
from ..core.dependency_adapter import DependencyAdapter

# Create unified manager with persistence
unified_dependency_manager = UnifiedDependencyManager(
    persistence=self.persistence
)

# Create adapter for WorkflowManager compatibility
dependency_adapter = DependencyAdapter(unified_dependency_manager)

# Use unified manager for ExecutionEngine
self.execution_engine = ExecutionEngineV2(
    registry=self.registry,
    queue_manager=queue_manager,
    dependency_resolver=unified_dependency_manager,  # Use unified
    persistence=self.persistence,
    event_bus=self.event_bus,
)

# Use adapter for WorkflowManager
self.workflow_manager = await WorkflowManagerFactory.create(
    persistence=self.persistence,
    event_bus=self.event_bus,
    execution_engine=self.execution_engine,
    dependency_resolver=dependency_adapter  # Use adapter
)
```

### Phase 3: Make Fully Stateless (Later)

1. **Update UnifiedDependencyManager**:
   - Remove all in-memory caches
   - Always query persistence
   - Use Redis for distributed locks

2. **Add Persistence Methods**:
   ```python
   # Add to persistence interface
   async def get_completed_task_ids(workflow_id: str) -> Set[str]
   async def get_failed_task_ids(workflow_id: str) -> Set[str]
   async def get_task_statuses(workflow_id: str) -> Dict[str, TaskStatus]
   ```

3. **Update All Components**:
   - Remove references to DependencyResolver
   - Use StatelessDependencyManager everywhere

## Benefits of This Approach

### Immediate Benefits (Adapter Solution):
- ✅ **Works Today** - No breaking changes
- ✅ **Single Dependency System** - UnifiedDependencyManager for all
- ✅ **WorkflowManager Works** - Gets proper dependency resolver
- ✅ **Maintains Compatibility** - All existing code continues working

### Long-term Benefits (Stateless Solution):
- ✅ **Truly Stateless** - Can scale horizontally
- ✅ **Single Source of Truth** - Persistence layer only
- ✅ **No Memory Bloat** - No workflow caching
- ✅ **Distributed Safe** - Multiple instances can coordinate

## Testing Strategy

### Test Cases:
```python
# Test adapter compatibility
async def test_adapter_validation():
    manager = UnifiedDependencyManager(persistence)
    adapter = DependencyAdapter(manager)
    
    workflow = create_test_workflow_with_deps()
    errors = await adapter.validate_workflow_dependencies(workflow)
    assert len(errors) == 0

# Test circular dependency detection
async def test_circular_detection():
    workflow = create_circular_workflow()
    errors = await adapter.validate_workflow_dependencies(workflow)
    assert "Circular dependency" in errors[0]

# Test stateless operation
async def test_stateless_ready_tasks():
    # Create two instances
    manager1 = StatelessDependencyManager(persistence)
    manager2 = StatelessDependencyManager(persistence)
    
    # Complete task via manager1
    await persistence.update_task_status("task-1", TaskStatus.COMPLETED)
    
    # Check ready tasks via manager2
    ready = await manager2.get_ready_tasks("workflow-1")
    assert "task-2" in [t.id for t in ready]
```

## Migration Path

### Step 1: Implement Adapter (Now)
- Create DependencyAdapter class
- Update SystemManager to use it
- Test basic workflows

### Step 2: Update Persistence (Next Sprint)
- Add task status query methods
- Add workflow state methods
- Test with Redis

### Step 3: Full Stateless Migration (Future)
- Replace UnifiedDependencyManager with StatelessDependencyManager
- Remove all in-memory caching
- Update all components

## Conclusion

The adapter pattern provides an immediate solution that:
1. Unifies the dependency systems
2. Makes WorkflowManager functional
3. Maintains backward compatibility
4. Sets foundation for full stateless operation

This approach allows the system to work TODAY while providing a clear path to full stateless operation in the future.