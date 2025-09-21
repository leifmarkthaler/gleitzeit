# Workflow Submission Path Audit - All Paths Through SystemManager

## Objective
Ensure all workflow submission paths (API, Client, CLI) go through SystemManager only.

## Current Architecture Analysis

### 1. API Path (`/api/workflows/`)
**File:** `src/gleitzeit/api/routes/workflows.py:30-60`

**Current Flow:**
```
POST /api/workflows/
├── Check worker_router (if enabled)
├── Check system_manager.workflow_manager (NEW - uses WorkflowManager)
│   └── workflow_manager.submit_workflow()
│       └── Validates and submits to execution_engine
└── Falls back to client execution (PROBLEM!)
```

**Issues:**
- ✅ Now uses WorkflowManager through SystemManager
- ❌ Still has fallback to client execution
- ❌ Worker router bypasses SystemManager

### 2. Client Paths

#### 2a. Client API Adapter
**File:** `src/gleitzeit/client/adapters/api.py:174-184`
```python
async def submit_workflow(self, workflow: Workflow) -> str:
    # Posts to /workflows/ API endpoint
    response = await self._make_request("POST", "/workflows/", ...)
```
**Issue:** Goes through API, but API has fallback paths

#### 2b. Client Native Adapter  
**File:** `src/gleitzeit/client/adapters/native.py:112-122`
```python
async def submit_workflow(self, workflow: Workflow) -> str:
    # Direct persistence save - BYPASSES SystemManager!
    await self.persistence.save_workflow(workflow)
    # Local execution
```
**Issue:** ❌ Completely bypasses SystemManager

#### 2c. Client Mixin
**File:** `src/gleitzeit/client/mixins/workflow.py:15-25`
```python
async def submit_workflow(self, workflow: Workflow) -> str:
    # Delegates to adapter
    return await self.adapter.submit_workflow(workflow)
```

### 3. CLI Paths

#### 3a. Workflow Submit Command
**File:** `src/gleitzeit/cli/commands/workflow.py`
```python
@workflow.command()
async def submit(workflow_file: str):
    client = GleitzeitClient(base_url=...)
    # Uses client.submit_workflow()
```
**Issue:** Uses client, which may bypass SystemManager

#### 3b. Direct Gleitzeit Submit
**File:** `src/gleitzeit/cli/main.py`
```python
gleitzeit submit <workflow>
# Also uses client
```

### 4. SystemManager Components

#### 4a. SystemManager
**File:** `src/gleitzeit/system/system_manager.py`
- Has `workflow_manager` attribute
- Has `execution_engine` attribute
- Properly initialized components

#### 4b. WorkflowManager
**File:** `src/gleitzeit/core/workflow_manager.py:104-249`
```python
async def submit_workflow(self, workflow: Workflow) -> str:
    # Validates dependencies
    # Validates providers/methods
    # Persists workflow
    # Submits to execution_engine
```
**Status:** ✅ Properly implemented with validation

#### 4c. ExecutionEngine
**File:** `src/gleitzeit/core/execution_engine_v2.py:355-387`
```python
async def submit_workflow(self, workflow: Workflow) -> str:
    # Delegates to task_orchestrator
    await self.task_orchestrator.submit_workflow(workflow)
```
**Issue:** Still delegates to TaskOrchestrator (violates separation of concerns)

### 5. TaskOrchestrator
**File:** `src/gleitzeit/core/task_orchestrator.py:565-595`
```python
async def submit_workflow(self, workflow: Workflow) -> str:
    # Validates dependencies only
    # Persists workflow/tasks
    # Emits events
```
**Issue:** Shouldn't handle workflow submission (should only handle task execution)

## Problems Summary

1. **Multiple Entry Points:**
   - API has 3 paths (worker, SystemManager, client fallback)
   - Client Native adapter bypasses everything
   - CLI uses client which may bypass SystemManager

2. **Fallback Paths:**
   - API falls back to client execution
   - Client can use native adapter (direct persistence)

3. **Architectural Violations:**
   - TaskOrchestrator handles workflow submission (should only do tasks)
   - ExecutionEngine just passes through to TaskOrchestrator

## Required Changes

### 1. API Route Changes
```python
# src/gleitzeit/api/routes/workflows.py
@router.post("/", response_model=Dict[str, Any])
async def submit_workflow(
    request: WorkflowSubmissionRequest,
    system_manager = Depends(get_system_manager)
):
    """Submit a workflow for execution - ONLY through SystemManager."""
    if not system_manager:
        raise HTTPException(
            status_code=503,
            detail="SystemManager not available"
        )
    
    if not hasattr(system_manager, 'workflow_manager'):
        raise HTTPException(
            status_code=503, 
            detail="WorkflowManager not initialized"
        )
    
    workflow = Workflow(**request.workflow)
    
    try:
        workflow_id = await system_manager.workflow_manager.submit_workflow(workflow)
        return {"workflow_id": workflow_id, "status": "submitted"}
    except WorkflowValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 2. Client Changes

#### Remove Native Adapter or Make it Use SystemManager
```python
# src/gleitzeit/client/adapters/native.py
class NativeAdapter:
    async def submit_workflow(self, workflow: Workflow) -> str:
        # OPTION 1: Remove this adapter entirely
        raise NotImplementedError("Native execution disabled - use API")
        
        # OPTION 2: Make it use SystemManager
        if not self.system_manager:
            raise RuntimeError("SystemManager required for workflow submission")
        return await self.system_manager.workflow_manager.submit_workflow(workflow)
```

#### Update API Adapter
```python
# src/gleitzeit/client/adapters/api.py
async def submit_workflow(self, workflow: Workflow) -> str:
    # Only use API endpoint, no local fallback
    response = await self._make_request("POST", "/workflows/", ...)
    if response.status_code != 200:
        raise WorkflowSubmissionError(f"API rejected workflow: {response.text}")
    return response.json()["workflow_id"]
```

### 3. CLI Changes
```python
# src/gleitzeit/cli/commands/workflow.py
@workflow.command()
async def submit(workflow_file: str):
    # Ensure client uses API adapter only
    client = GleitzeitClient(
        base_url=config.get("api_url"),
        adapter_type="api"  # Force API adapter
    )
    result = await client.submit_workflow(workflow)
```

### 4. Remove Worker Router Path
```python
# src/gleitzeit/api/routes/workflows.py
# Remove this section:
# worker_router = get_worker_router()
# if worker_router.enabled:
#     result = await worker_router.route_workflow(workflow)
```

### 5. Clean Up TaskOrchestrator
```python
# src/gleitzeit/core/task_orchestrator.py
# Remove submit_workflow() method entirely
# TaskOrchestrator should only handle task execution
```

### 6. Update ExecutionEngine
```python
# src/gleitzeit/core/execution_engine_v2.py
async def submit_workflow(self, workflow: Workflow) -> str:
    """
    Queue workflow tasks for execution.
    Note: Validation already done by WorkflowManager.
    """
    # Queue tasks for execution
    for task in workflow.tasks:
        await self.task_orchestrator.queue_task(task)
    
    return workflow.id
```

## Recommended Flow

```
All Entry Points (API, CLI, Client)
    ↓
API Endpoint (/api/workflows/)
    ↓
SystemManager.workflow_manager.submit_workflow()
    ├── Validate dependencies
    ├── Validate providers/methods
    ├── Persist workflow
    └── Submit to execution_engine
        └── Queue tasks for execution
```

## Implementation Priority

1. **HIGH:** Remove all fallback paths in API
2. **HIGH:** Disable or fix Native adapter
3. **MEDIUM:** Force CLI to use API adapter
4. **MEDIUM:** Remove worker router bypass
5. **LOW:** Clean up TaskOrchestrator/ExecutionEngine separation

## Testing Requirements

1. Test that API rejects workflows when SystemManager unavailable
2. Test that client can't bypass SystemManager
3. Test that CLI properly uses API path
4. Test that validation happens at submission time
5. Test that invalid methods fail at submission, not execution

## Conclusion

The system currently has multiple bypass paths that allow workflow submission without going through SystemManager. The main issues are:

1. API fallback to client execution
2. Native adapter direct persistence
3. Worker router bypass
4. Architectural confusion between WorkflowManager and TaskOrchestrator

All paths must be consolidated to go through:
`API → SystemManager → WorkflowManager → ValidationExecution`