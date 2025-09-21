# Workflow Execution Single Pathway Audit

## Current Workflow Submission Paths

### 1. Client Layer Entry Points

#### Primary Client Methods
- `Client.submit_workflow()` (src/gleitzeit/client/client.py)
  - Routes to adapter based on connection type
  
#### Adapter Implementations
1. **NativeAdapter** (src/gleitzeit/client/adapters/native.py)
   - Direct in-process execution
   - Calls `WorkflowManager.execute_workflow()`
   
2. **APIAdapter** (src/gleitzeit/client/adapters/api.py)
   - HTTP API submission
   - Sends to `/workflows/submit` endpoint
   
3. **EventDrivenAdapter** (src/gleitzeit/client/adapters/event_driven.py)
   - Event-based submission
   - Emits WORKFLOW_SUBMITTED event

### 2. Core Execution Components

#### WorkflowManager (Multiple Versions - ISSUE!)
1. **StatelessWorkflowManager** (src/gleitzeit/core/stateless_workflow_manager.py)
   - Used by SystemManager in production
   - Calls `ExecutionEngine.submit_workflow()`
   
2. **WorkflowManager** (src/gleitzeit/core/workflow_manager.py)
   - Legacy version still exists
   - Also calls `ExecutionEngine.submit_workflow()`

#### ExecutionEngine (Multiple Versions - ISSUE!)
1. **ExecutionEngineV2** (src/gleitzeit/core/execution_engine_v2.py)
   - Used by SystemManager
   - Delegates to `TaskOrchestrator.submit_workflow()`
   
2. **Legacy paths still exist in codebase**

#### TaskOrchestrator (Single Implementation ✓)
- src/gleitzeit/core/task_orchestrator.py
- Final workflow submission handler
- Saves workflow and tasks to persistence
- Emits WORKFLOW_SUBMITTED event

### 3. API Routes

#### Multiple Workflow Routes (ISSUE!)
1. **Main API** (src/gleitzeit/api/routes/workflows.py)
   - `/workflows/submit` endpoint
   - Uses WorkflowManager instance
   
2. **UI API** (src/gleitzeit/ui/api/routes/workflows.py)
   - Duplicate workflow submission endpoint
   - May use different workflow manager

## Issues Found

### 🔴 Critical: Multiple Parallel Paths

1. **Two WorkflowManager Implementations**
   - StatelessWorkflowManager (production)
   - WorkflowManager (legacy)
   - Both can be used depending on configuration

2. **Multiple Client Adapters**
   - NativeAdapter → WorkflowManager
   - APIAdapter → API → WorkflowManager
   - EventDrivenAdapter → Events → ?
   
3. **Duplicate API Endpoints**
   - Main API workflows route
   - UI API workflows route

### 🟡 Medium: Inconsistent Flow

The workflow submission can take different paths:

```
Path 1 (Native):
Client → NativeAdapter → WorkflowManager → ExecutionEngine → TaskOrchestrator

Path 2 (API):
Client → APIAdapter → HTTP → API Route → WorkflowManager → ExecutionEngine → TaskOrchestrator

Path 3 (Event):
Client → EventDrivenAdapter → Event Bus → ??? (unclear handler)
```

## Recommended Single Pathway

### Proposed Unified Flow

```
ALL ENTRY POINTS
      ↓
WorkflowManager (single implementation)
      ↓
ExecutionEngine (single implementation)
      ↓
TaskOrchestrator
      ↓
Persistence + Event emission
```

### Implementation Steps

1. **Remove Legacy Components**
   - Delete old WorkflowManager
   - Remove duplicate routes
   - Clean up unused adapters

2. **Standardize on StatelessWorkflowManager**
   - Rename to WorkflowManager (remove "Stateless" prefix)
   - Ensure all paths use this single implementation

3. **Simplify Client Adapters**
   - Keep NativeAdapter for in-process
   - Keep APIAdapter for remote
   - Remove or consolidate EventDrivenAdapter

4. **Single API Route**
   - One `/workflows/submit` endpoint
   - Remove UI duplicate route

## Files to Modify/Remove

### Remove (Legacy)
- [ ] src/gleitzeit/core/workflow_manager.py (old implementation)
- [ ] src/gleitzeit/ui/api/routes/workflows.py (duplicate route)
- [ ] Old execution engine implementations

### Rename/Consolidate
- [ ] StatelessWorkflowManager → WorkflowManager
- [ ] Consolidate client adapters

### Update References
- [ ] SystemManager to use renamed WorkflowManager
- [ ] All imports to use single WorkflowManager
- [ ] API routes to use single endpoint

## Current State Summary

**Multiple parallel paths exist** for workflow submission:
- 2 WorkflowManager implementations
- 3+ client adapter paths
- 2 API route implementations
- Various event-driven paths

This violates the single pathway principle and can lead to:
- Inconsistent behavior
- Maintenance difficulties  
- Debugging challenges
- Race conditions

## Next Steps

1. Confirm which WorkflowManager to keep (recommend StatelessWorkflowManager)
2. Remove all duplicate/legacy implementations
3. Update all references to use single path
4. Test unified workflow submission path