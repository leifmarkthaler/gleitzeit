# Workflow Pathway Cleanup Plan

## Current Situation
- **StatelessWorkflowManager** is used in production (via SystemManager)
- **Old WorkflowManager** exists but is never instantiated
- **WorkflowManagerFactory** always creates StatelessWorkflowManager
- Old WorkflowManager has unimplemented features (templates, scheduling, etc.)

## Action Plan

### 1. Remove Old WorkflowManager
- Delete `src/gleitzeit/core/workflow_manager.py` (not used, features not implemented)

### 2. Rename StatelessWorkflowManager → WorkflowManager
- Rename `src/gleitzeit/core/stateless_workflow_manager.py` → `workflow_manager.py`
- Update class name from `StatelessWorkflowManager` to `WorkflowManager`

### 3. Update All References
- Update imports in:
  - `src/gleitzeit/system/system_manager.py`
  - `src/gleitzeit/core/workflow_manager_factory.py`
  - `src/gleitzeit/core/__init__.py`
  - Any other files importing either manager

### 4. Single Workflow Path
After cleanup, the single path will be:

```
All Entry Points (Client/API/CLI)
           ↓
    WorkflowManager (formerly StatelessWorkflowManager)
           ↓
    ExecutionEngineV2
           ↓
    TaskOrchestrator
           ↓
    Task Execution (via PoolingAdapter)
```

## Benefits
- Single, clear workflow execution path
- No confusion between implementations
- Easier maintenance
- Consistent behavior across all entry points

## Files to Change

### Delete
- `src/gleitzeit/core/workflow_manager.py`

### Rename
- `src/gleitzeit/core/stateless_workflow_manager.py` → `src/gleitzeit/core/workflow_manager.py`

### Update Imports
- All files importing from either workflow manager module