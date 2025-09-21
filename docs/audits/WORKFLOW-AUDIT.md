# Workflow Submission Path Audit

## Overview
This document audits all workflow submission paths in the Gleitzeit codebase to identify duplicates and consolidation opportunities.

## Architecture Intent
- **WorkflowManager**: Manages workflow lifecycle, tracks status, handles dependencies
- **TaskOrchestrator**: Handles task execution, queuing, and coordination
- These should work together, not be alternative paths

## Workflow Submission Paths

### 1. Primary API Route (`/api/workflows/`)
**File:** `src/gleitzeit/api/routes/workflows.py:31-59`

**Flow:**
```
API POST /workflows/
├── submit_workflow()
├── Checks for SystemManager.execution_engine
│   ├── YES: system_manager.execution_engine.submit_workflow()
│   └── NO: workflow_routes.handle_client_call("submit_workflow")
```

**Issues:**
- Dual path based on SystemManager availability
- Falls back to client execution if SystemManager fails

### 2. ExecutionEngine V2 Path
**File:** `src/gleitzeit/core/execution_engine_v2.py:355-385`

**Flow:**
```
ExecutionEngineV2.submit_workflow()
└── task_orchestrator.submit_workflow()
```

**Features:**
- Logs operations
- Delegates to TaskOrchestrator
- No validation

### 3. TaskOrchestrator Path
**File:** `src/gleitzeit/core/task_orchestrator.py:565-595`

**Flow:**
```
TaskOrchestrator.submit_workflow()
├── dependency_manager.validate_workflow() [dependency validation only]
├── persistence.save_workflow()
├── persistence.save_task() [for each task]
└── event_bus.emit(WORKFLOW_SUBMITTED)
```

**Features:**
- Validates dependencies only
- NO provider/method validation
- Persists workflow and tasks
- Emits events

### 4. WorkflowManager Path (OLD)
**File:** `src/gleitzeit/core/workflow_manager.py`

**Flow:**
```
WorkflowManager.execute_workflow()
├── dependency_manager.validate_workflow()
├── pooling_adapter.validate_provider_availability() [ADDED but not in submission path]
├── persistence operations
└── task execution
```

**Issues:**
- This is execute_workflow, not submit_workflow
- Validation happens during execution, not submission
- My changes added method validation here but it's the wrong place

### 5. Client Paths

#### 5a. Client API Adapter
**File:** `src/gleitzeit/client/adapters/api.py:174-184`
- Posts to `/workflows/` API endpoint
- Sets up event tracking

#### 5b. Client Native Adapter
**File:** `src/gleitzeit/client/adapters/native.py:112-122`
- Direct persistence save
- Local execution

#### 5c. Client Mixin
**File:** `src/gleitzeit/client/mixins/workflow.py:15-25`
- Delegates to adapter's submit_workflow

## Problems Identified

### 1. Multiple Submission Paths
- **API → SystemManager → ExecutionEngine → TaskOrchestrator**
- **API → Client → API (circular!)**
- **Client → Native → Local execution**
- **WorkflowManager.execute_workflow (separate from submission)**

### 2. Inconsistent Validation
- **TaskOrchestrator:** Only validates dependencies
- **WorkflowManager:** Only validates during execution (not submission)
- **No provider/method validation at submission time anywhere**

### 3. Naming Confusion
- `submit_workflow()` vs `execute_workflow()`
- Some paths submit for later execution
- Others execute immediately

### 4. Circular Dependencies
- API can fall back to client
- Client posts back to API
- Potential infinite loop

## Revised Understanding

The architecture SHOULD have clear separation:
- **WorkflowManager**: Workflow lifecycle management (status tracking, dependency resolution, workflow-level operations)
- **TaskOrchestrator**: Task execution and queuing (individual task operations)

However, the current implementation shows TaskOrchestrator doing both workflow submission AND task execution, while WorkflowManager has an execute_workflow method that seems redundant.

## Recommendations (Revised)

### 1. Proper Separation of Concerns

```
API/Client
└── SystemManager
    └── ExecutionEngine
        └── WorkflowManager (workflow lifecycle)
            ├── submit_workflow() - validates and accepts workflows
            │   ├── Validate dependencies
            │   ├── Validate providers/methods [ADD HERE]
            │   ├── Track workflow status
            │   └── Persist workflow
            └── Uses TaskOrchestrator for task execution
                └── execute_task() - runs individual tasks
```

### 2. Where to Add Validation

Given the proper architecture, validation should be in **WorkflowManager**, not TaskOrchestrator:

1. **Create/enhance WorkflowManager.submit_workflow()** to include:
   - Dependency validation (already exists)
   - Provider/method validation (needs to be added)
   - Workflow status tracking

2. **Keep TaskOrchestrator focused on task execution**:
   - Should not handle workflow submission
   - Should focus on task queuing and execution

### 3. Fix the Current Confusion

Currently, TaskOrchestrator has `submit_workflow()` which violates separation of concerns. This should be:
- Either moved to WorkflowManager
- Or renamed to clarify it's just queuing tasks for execution

### 4. Consolidate Paths

The ideal flow should be:
```
API → ExecutionEngine → WorkflowManager.submit_workflow() → validation → persistence → TaskOrchestrator.queue_tasks()
```

Not the current multiple paths that bypass WorkflowManager entirely.

## Current State vs Desired State

### Current State
```
Multiple entry points → Inconsistent validation → Various execution paths
```

### Desired State
```
Single entry point → Consistent validation → Unified execution path
```

## Action Items (Revised)

1. **Immediate Fix:** Since WorkflowManager lacks submit_workflow(), the validation must go in TaskOrchestrator.submit_workflow() for now
2. **Short Term:** Create WorkflowManager.submit_workflow() and move workflow submission logic there
3. **Medium Term:** Refactor TaskOrchestrator to only handle task execution, not workflow submission
4. **Long Term:** Ensure clear separation:
   - WorkflowManager: Workflow lifecycle (submission, validation, status tracking)
   - TaskOrchestrator: Task execution only

## Parameter Substitution System

### Status: ✅ FULLY FUNCTIONAL AND STATELESS

The parameter substitution system enables workflows to pass results between dependent tasks using template syntax.

### Key Features

1. **Template Syntax**: `${task_id.field.path}`
   - Supports nested field navigation
   - Works with both user-defined and system-generated task IDs

2. **Stateless Operation**:
   - Task name mappings fetched from persistence at resolution time
   - No pre-built mappings held in memory
   - Each resolution is independent

3. **ID Management**:
   - WorkflowLoaderV2 stores original user-defined IDs in task metadata
   - ParameterResolver maps user IDs to system IDs dynamically
   - Preserves user-friendly references while using system IDs internally

### Verified Working Examples

1. **LLM Workflows**:
   ```yaml
   - task: analyze
     dependencies: [summarize]
     parameters:
       content: "Analyze: ${summarize.result.response}"
   ```

2. **Python Workflows**:
   ```yaml
   - task: process
     dependencies: [calculate]
     parameters:
       context:
         previous_result: "${calculate.result}"
   ```

### Implementation Components

- **ParameterResolver** (`core/parameter_resolver.py`): Handles all substitution logic
- **WorkflowLoaderV2** (`core/workflow_loader_v2.py`): Stores original IDs in metadata
- **TaskExecutor** (`core/task_executor.py`): Calls resolver for dependent tasks

## Summary

The audit reveals architectural confusion where:
- **TaskOrchestrator** is doing both workflow submission AND task execution (violates single responsibility)
- **WorkflowManager** only has execute_workflow() but no submit_workflow()
- Multiple paths bypass the WorkflowManager entirely
- The system lacks a clear, single workflow submission path with proper validation

However, the parameter substitution system is working correctly:
- ✅ Fully stateless operation with persistence-based resolution
- ✅ Supports complex nested field paths
- ✅ Works with both LLM and Python workflows
- ✅ Maintains user-friendly task ID references

The immediate need is to add validation where workflows are currently submitted (TaskOrchestrator), but the long-term solution requires proper architectural separation with WorkflowManager handling workflow lifecycle and TaskOrchestrator focusing solely on task execution.